"""serializers for the catalog api

TableNameSerializer is the read shape used everywhere a table needs
to come back to the client, schema and etl are nested by name rather
than by id since the id is an internal detail the caller never needs
"""

from rest_framework import serializers

from catalog.models import Etl, Schema, TableName
from catalog.services import SUPPORTED_ENGINES


class SchemaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Schema
        fields = ["id", "name", "created_at"]


class EtlSerializer(serializers.ModelSerializer):
    class Meta:
        model = Etl
        fields = ["id", "name", "created_at"]


class TableNameSerializer(serializers.ModelSerializer):
    schema_name = serializers.CharField(source="schema.name", read_only=True)
    etl_name = serializers.CharField(source="etl.name", read_only=True)

    class Meta:
        model = TableName
        fields = ["id", "name", "schema_name", "etl_name", "created_at", "updated_at"]


class IngestionResultSerializer(serializers.Serializer):
    """shapes the summary returned by catalog.services.ingest_rows

    this is a plain Serializer rather than a ModelSerializer since the
    payload is a summary dict, not a single model instance
    """

    processed = serializers.IntegerField()
    created = serializers.IntegerField()
    updated = serializers.IntegerField()
    etl_names = serializers.ListField(child=serializers.CharField())
    tables = TableNameSerializer(many=True)


class ExternalConnectionSerializer(serializers.Serializer):
    """validates the request body for the direct-database ingestion

    endpoint. this only validates shape and type, not reachability,
    whether the host/credentials actually work is only known once
    catalog.services.discover_external_tables attempts the connection
    at request time
    """

    engine = serializers.ChoiceField(choices=sorted(SUPPORTED_ENGINES))
    host = serializers.CharField(max_length=255)
    port = serializers.IntegerField(min_value=1, max_value=65535)
    database = serializers.CharField(max_length=255)
    user = serializers.CharField(max_length=255)
    password = serializers.CharField(max_length=255, trim_whitespace=False)
    etl_name = serializers.CharField(max_length=255)

    def validate_etl_name(self, value):
        etl_name = value.strip()
        if not etl_name:
            raise serializers.ValidationError("etl_name must not be blank")
        return etl_name


class SchemaSummarySerializer(serializers.ModelSerializer):
    """per-schema rollup produced by catalog.services.schema_summary_queryset

    table_count and etl_count are annotated onto the queryset by
    schema_summary_queryset, not real model fields, so ModelSerializer
    needs them declared explicitly here, listing them in Meta.fields
    alone is not enough, it only auto-resolves actual model fields
    """

    table_count = serializers.IntegerField(read_only=True)
    etl_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Schema
        fields = ["id", "name", "table_count", "etl_count"]
