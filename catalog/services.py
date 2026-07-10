"""ingestion logic for the etl loading endpoint

kept out of the view on purpose, a view's job is to translate http in
and out, the actual upsert/parsing rules belong here so they can be
unit tested without touching request/response objects at all
"""

import csv
import io

from django.db import transaction
from django.db.models import Count

from catalog.models import Etl, Schema, TableName

REQUIRED_FIELDS = {"name", "schema_name", "etl_name"}

SUPPORTED_ENGINES = {"postgres", "oracle"}


POSTGRES_METADATA_QUERY = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_type = 'BASE TABLE'
      AND table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY table_schema, table_name
"""


ORACLE_METADATA_QUERY = """
    SELECT owner, table_name
    FROM all_tables
    ORDER BY owner, table_name
"""


class PayloadFormatError(Exception):
    """raised when the request body can't be parsed as csv or json"""


class ExternalConnectionError(Exception):
    """raised when connecting to or querying an external database fails

    covers everything from a bad host/port to an authentication
    failure to a query timing out, the view layer only needs to know
    that the external side failed, not which driver-specific
    exception caused it
    """


def _validate_row(row, index):
    """raise if a row is missing a field or has one that is blank
    """

    missing = REQUIRED_FIELDS - set(row)
    if missing:
        raise PayloadFormatError(f"row {index} is missing fields: {sorted(missing)}")

    blank = {
        field for field in REQUIRED_FIELDS if row[field] is None or not str(row[field]).strip()
    }
    if blank:
        raise PayloadFormatError(f"row {index} has blank fields: {sorted(blank)}")


def parse_csv_rows(raw_bytes):
    """turn an uploaded csv file into a list of row dicts
    """

    text = raw_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    if reader.fieldnames is None:
        raise PayloadFormatError("csv file has no header row")

    missing_columns = REQUIRED_FIELDS - set(reader.fieldnames)
    if missing_columns:
        raise PayloadFormatError(f"csv is missing columns: {sorted(missing_columns)}")

    rows = list(reader)
    for index, row in enumerate(rows):
        _validate_row(row, index)

    return rows


def normalize_json_rows(payload):
    """turn a parsed json body into the same row shape the csv path
    """

    if isinstance(payload, dict):
        rows = payload.get("tables")
        if rows is None:
            raise PayloadFormatError("json body must contain a 'tables' list")
    elif isinstance(payload, list):
        rows = payload
    else:
        raise PayloadFormatError("json body must be a list or an object with 'tables'")

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise PayloadFormatError(f"row {index} must be an object")
        _validate_row(row, index)

    return rows


@transaction.atomic
def ingest_rows(rows):
    """create any missing schema/etl rows and register the tables
    """

    created_tables = []
    touched_etl_names = set()

    for row in rows:
        schema_name = row["schema_name"].strip()
        schema, _ = Schema.objects.get_or_create(
            name__iexact=schema_name, defaults={"name": schema_name}
        )

        etl_name = row["etl_name"].strip()
        etl, _ = Etl.objects.get_or_create(name__iexact=etl_name, defaults={"name": etl_name})

        table_name = row["name"].strip()
        table, was_created = (
            TableName.objects.filter(schema=schema, name__iexact=table_name).first(),
            False,
        )
        if table is None:
            table = TableName.objects.create(schema=schema, name=table_name, etl=etl)
            was_created = True
        else:
            table.etl = etl
            table.save(update_fields=["etl", "updated_at"])

        touched_etl_names.add(etl.name)
        created_tables.append((table, was_created))

    return {
        "processed": len(created_tables),
        "created": sum(1 for _, was_created in created_tables if was_created),
        "updated": sum(1 for _, was_created in created_tables if not was_created),
        "etl_names": sorted(touched_etl_names),
        "tables": [table for table, _ in created_tables],
    }


def _connect_postgres(connection_info):
    """open a connection to an external postgres database
    """

    import psycopg2

    try:
        return psycopg2.connect(
            host=connection_info["host"],
            port=connection_info["port"],
            dbname=connection_info["database"],
            user=connection_info["user"],
            password=connection_info["password"],
            connect_timeout=5,
        )
    except psycopg2.Error as exc:
        raise ExternalConnectionError(f"could not connect to postgres database: {exc}") from exc


def _connect_oracle(connection_info):
    """open a connection to an external oracle database
    """

    import oracledb

    dsn = oracledb.makedsn(
        connection_info["host"], connection_info["port"], service_name=connection_info["database"]
    )
    try:
        return oracledb.connect(
            user=connection_info["user"], password=connection_info["password"], dsn=dsn
        )
    except oracledb.Error as exc:
        raise ExternalConnectionError(f"could not connect to oracle database: {exc}") from exc


def discover_external_tables(connection_info):
    """connect to an external database and list its schema/table pairs    """

    engine = connection_info["engine"]

    if engine == "postgres":
        connect, query = _connect_postgres, POSTGRES_METADATA_QUERY
    elif engine == "oracle":
        connect, query = _connect_oracle, ORACLE_METADATA_QUERY
    else:
        raise ExternalConnectionError(f"unsupported engine: {engine}")

    connection = connect(connection_info)
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            return [(schema_name, table_name) for schema_name, table_name in cursor.fetchall()]
    except Exception as exc:
        raise ExternalConnectionError(f"failed reading table metadata: {exc}") from exc
    finally:
        connection.close()


def rows_from_external_tables(discovered_tables, etl_name):
    """turn (schema_name, table_name) pairs into ingest_rows() input
    """

    return [
        {"name": table_name, "schema_name": schema_name, "etl_name": etl_name}
        for schema_name, table_name in discovered_tables
    ]


def schema_summary_queryset():
    """per-schema rollup of table count and distinct etl jobs used
    """

    return Schema.objects.annotate(
        table_count=Count("tables", distinct=True),
        etl_count=Count("tables__etl", distinct=True),
    ).order_by("name")
