"""tests for the parsing and upsert logic in catalog.services.
"""

import pytest

from catalog.models import Etl, Schema, TableName
from catalog.services import (
    PayloadFormatError,
    ingest_rows,
    normalize_json_rows,
    parse_csv_rows,
)

pytestmark = pytest.mark.django_db


class TestParseCsvRows:
    def test_parses_valid_csv(self):
        raw = b"name,schema_name,etl_name\norders,sales,etl1\n"
        rows = parse_csv_rows(raw)
        assert rows == [{"name": "orders", "schema_name": "sales", "etl_name": "etl1"}]

    def test_handles_utf8_bom(self):
        raw = "name,schema_name,etl_name\norders,sales,etl1\n".encode("utf-8-sig")
        rows = parse_csv_rows(raw)
        assert rows[0]["name"] == "orders"

    def test_rejects_missing_header_row(self):
        with pytest.raises(PayloadFormatError, match="no header row"):
            parse_csv_rows(b"")

    def test_rejects_missing_required_column(self):
        raw = b"name,schema_name\norders,sales\n"
        with pytest.raises(PayloadFormatError, match="missing columns"):
            parse_csv_rows(raw)

    def test_rejects_blank_schema_name(self):
        # header present, but the schema_name value on the data row
        # is an empty string, this must not be treated as valid
        raw = b"name,schema_name,etl_name\norders,,etl1\n"
        with pytest.raises(PayloadFormatError, match="blank fields"):
            parse_csv_rows(raw)

    def test_rejects_short_row_with_missing_trailing_value(self):
        # csv.DictReader fills a missing trailing column with None
        # rather than an empty string, this must be caught too
        raw = b"name,schema_name,etl_name\norders,sales\n"
        with pytest.raises(PayloadFormatError, match="blank fields"):
            parse_csv_rows(raw)


class TestNormalizeJsonRows:
    def test_accepts_bare_list(self):
        payload = [{"name": "orders", "schema_name": "sales", "etl_name": "etl1"}]
        assert normalize_json_rows(payload) == payload

    def test_accepts_tables_wrapper(self):
        payload = {"tables": [{"name": "orders", "schema_name": "sales", "etl_name": "etl1"}]}
        assert normalize_json_rows(payload) == payload["tables"]

    def test_rejects_dict_without_tables_key(self):
        with pytest.raises(PayloadFormatError, match="'tables' list"):
            normalize_json_rows({"foo": "bar"})

    def test_rejects_non_list_non_dict_payload(self):
        with pytest.raises(PayloadFormatError):
            normalize_json_rows("not a list or dict")

    def test_rejects_row_missing_field(self):
        payload = [{"name": "orders", "schema_name": "sales"}]
        with pytest.raises(PayloadFormatError, match="missing fields"):
            normalize_json_rows(payload)

    def test_rejects_row_with_blank_etl_name(self):
        payload = [{"name": "orders", "schema_name": "sales", "etl_name": "  "}]
        with pytest.raises(PayloadFormatError, match="blank fields"):
            normalize_json_rows(payload)

    def test_rejects_row_that_is_not_an_object(self):
        payload = ["not-a-dict"]
        with pytest.raises(PayloadFormatError, match="must be an object"):
            normalize_json_rows(payload)


class TestIngestRows:
    def test_creates_schema_etl_and_table(self):
        rows = [{"name": "orders", "schema_name": "sales", "etl_name": "etl1"}]
        result = ingest_rows(rows)

        assert result["processed"] == 1
        assert result["created"] == 1
        assert result["updated"] == 0
        assert result["etl_names"] == ["etl1"]
        assert Schema.objects.filter(name="sales").exists()
        assert Etl.objects.filter(name="etl1").exists()
        assert TableName.objects.filter(name="orders", schema__name="sales").exists()

    def test_reuses_existing_schema_and_etl(self):
        Schema.objects.create(name="sales")
        Etl.objects.create(name="etl1")

        rows = [{"name": "orders", "schema_name": "sales", "etl_name": "etl1"}]
        ingest_rows(rows)

        assert Schema.objects.filter(name="sales").count() == 1
        assert Etl.objects.filter(name="etl1").count() == 1

    def test_reingesting_same_table_updates_rather_than_duplicates(self):
        rows = [{"name": "orders", "schema_name": "sales", "etl_name": "etl1"}]
        ingest_rows(rows)

        rows_again = [{"name": "orders", "schema_name": "sales", "etl_name": "etl2"}]
        result = ingest_rows(rows_again)

        assert result["created"] == 0
        assert result["updated"] == 1
        assert TableName.objects.filter(name="orders", schema__name="sales").count() == 1
        table = TableName.objects.get(name="orders", schema__name="sales")
        assert table.etl.name == "etl2"

    def test_strips_whitespace_from_values(self):
        rows = [{"name": " orders ", "schema_name": " sales ", "etl_name": " etl1 "}]
        ingest_rows(rows)

        assert Schema.objects.filter(name="sales").exists()
        assert TableName.objects.filter(name="orders").exists()

    def test_reuses_existing_rows_on_case_only_difference(self):
        # schemas/tables_name/etl all enforce case-insensitive
        # uniqueness at the database level (migrations 0002, 0003),
        # ingest_rows has to look rows up the same way or a
        # case-variant re-ingest would raise IntegrityError instead
        # of being treated as the same row
        Schema.objects.create(name="sales")
        Etl.objects.create(name="etl1")

        rows = [{"name": "orders", "schema_name": "Sales", "etl_name": "ETL1"}]
        result = ingest_rows(rows)

        assert result["created"] == 1
        assert Schema.objects.count() == 1
        assert Etl.objects.count() == 1
        # the original casing is preserved, not overwritten by the
        # differently-cased value from the second ingest
        assert Schema.objects.get().name == "sales"
        assert Etl.objects.get().name == "etl1"
