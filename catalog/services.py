"""ingestion logic for the etl loading endpoint

kept out of the view on purpose, a view's job is to translate http in
and out, the actual upsert/parsing rules belong here so they can be
unit tested without touching request/response objects at all
"""

import csv
import io

from django.db import transaction

from catalog.models import Etl, Schema, TableName

REQUIRED_FIELDS = {"name", "schema_name", "etl_name"}


class PayloadFormatError(Exception):
    """raised when the request body can't be parsed as csv or json"""


def _validate_row(row, index):
    """raise if a row is missing a field or has one that is blank

    a present-but-empty schema_name/etl_name/name is just as broken
    as a missing key, both would otherwise sail through
    get_or_create and leave an Etl or Schema row named "" sitting in
    the database, so both cases are rejected here up front
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

    the expected header is name, schema_name, etl_name, matching the
    shape tables_name had in the original dump. rows are decoded as
    utf-8 with a bom-safe codec since exports from windows tools
    often carry one
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

    produces, accepting either a bare list or a {"tables": [...]}
    wrapper so callers have some flexibility in how they post data
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

    returns a summary dict rather than model instances directly, so
    the view layer can serialize it without an extra translation step

    every row reaching this point has already passed _validate_row,
    so schema_name/etl_name/name are guaranteed present and non-blank
    """

    created_tables = []
    touched_etl_names = set()

    for row in rows:
        schema, _ = Schema.objects.get_or_create(name=row["schema_name"].strip())
        etl, _ = Etl.objects.get_or_create(name=row["etl_name"].strip())

        table, was_created = TableName.objects.update_or_create(
            schema=schema,
            name=row["name"].strip(),
            defaults={"etl": etl},
        )

        touched_etl_names.add(etl.name)
        created_tables.append((table, was_created))

    return {
        "processed": len(created_tables),
        "created": sum(1 for _, was_created in created_tables if was_created),
        "updated": sum(1 for _, was_created in created_tables if not was_created),
        "etl_names": sorted(touched_etl_names),
        "tables": [table for table, _ in created_tables],
    }
