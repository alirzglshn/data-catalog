"""api views for the data catalog

four endpoints live here:

* IngestTablesView       -- POST, accepts csv or json, registers tables
* DirectDatabaseIngestView -- POST, reads an external db's own table
                               metadata and registers it
* EtlTablesView          -- GET,  given an etl name, lists tables using it
* SchemaSummaryView      -- GET,  per-schema table/etl rollup (join example)
"""

import logging
import smtplib

from django.core.mail import send_mail
from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Etl, TableName
from catalog.serializers import (
    ExternalConnectionSerializer,
    IngestionResultSerializer,
    SchemaSummarySerializer,
    TableNameSerializer,
)
from catalog.services import (
    ExternalConnectionError,
    PayloadFormatError,
    discover_external_tables,
    ingest_rows,
    normalize_json_rows,
    parse_csv_rows,
    rows_from_external_tables,
    schema_summary_queryset,
)

logger = logging.getLogger(__name__)


class IngestTablesView(APIView):
    """loads table/schema/etl metadata from an uploaded csv or json body
    """

    parser_classes = [MultiPartParser, JSONParser]

    def post(self, request, *args, **kwargs):
        uploaded_file = request.FILES.get("file")

        try:
            if uploaded_file is not None:
                rows = parse_csv_rows(uploaded_file.read())
            else:
                rows = normalize_json_rows(request.data)
        except PayloadFormatError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not rows:
            return Response(
                {"detail": "no rows found in payload"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = ingest_rows(rows)
        self._notify_by_email(result)

        serializer = IngestionResultSerializer(result)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _notify_by_email(result):
        """sends a short summary email after a successful load

        only smtp/socket-level failures are swallowed here, a broken
        or unreachable mail relay should not turn a successful
        ingestion into a 500, but the failure is still logged so it
        stays visible to whoever watches the logs, unlike a bare
        except that would hide it completely
        """

        try:
            send_mail(
                subject="data catalog: table ingestion completed",
                message=(
                    f"processed {result['processed']} rows "
                    f"({result['created']} created, {result['updated']} updated) "
                    f"for etl jobs: {', '.join(result['etl_names'])}"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[settings.NOTIFY_EMAIL_RECIPIENT],
                fail_silently=False,
            )
        except (smtplib.SMTPException, OSError):
            logger.exception("failed to send ingestion notification email")


class DirectDatabaseIngestView(APIView):
    """reads schema/table metadata straight from an external database
    """

    def post(self, request, *args, **kwargs):
        connection_serializer = ExternalConnectionSerializer(data=request.data)
        connection_serializer.is_valid(raise_exception=True)
        connection_info = connection_serializer.validated_data

        try:
            discovered_tables = discover_external_tables(connection_info)
        except ExternalConnectionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        if not discovered_tables:
            return Response(
                {"detail": "no tables found in the external database"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rows = rows_from_external_tables(discovered_tables, connection_info["etl_name"])
        result = ingest_rows(rows)
        IngestTablesView._notify_by_email(result)

        serializer = IngestionResultSerializer(result)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class EtlTablesView(ListAPIView):
    """given ?etl_name=..., returns the tables that etl job populates
    """

    serializer_class = TableNameSerializer

    def get_queryset(self):
        etl_name = self.request.query_params.get("etl_name")

        if not etl_name:
            raise NotFound("etl_name query parameter is required")

        etl = Etl.objects.filter(name=etl_name).first()
        if etl is None:
            raise NotFound(f"no etl job named '{etl_name}' in the catalog")

        return TableName.objects.filter(etl=etl).select_related("schema", "etl")


class SchemaSummaryView(ListAPIView):
    """per-schema rollup of table count and distinct etl jobs used
    """

    serializer_class = SchemaSummarySerializer

    def get_queryset(self):
        return schema_summary_queryset()
