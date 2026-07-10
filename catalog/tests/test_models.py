"""tests for model level constraints and foreign key behaviour.
"""

import pytest
from django.db import IntegrityError
from django.db.models import ProtectedError

from catalog.models import Etl, Schema, TableName

pytestmark = pytest.mark.django_db


def test_schema_name_must_be_unique():
    Schema.objects.create(name="sales")
    with pytest.raises(IntegrityError):
        Schema.objects.create(name="sales")


def test_etl_name_must_be_unique():
    Etl.objects.create(name="etl1")
    with pytest.raises(IntegrityError):
        Etl.objects.create(name="etl1")


def test_same_table_name_allowed_in_different_schemas():
    sales = Schema.objects.create(name="sales")
    hr = Schema.objects.create(name="hr")
    etl = Etl.objects.create(name="etl1")

    TableName.objects.create(name="employees", schema=sales, etl=etl)
    # should not raise, "employees" in a different schema is a
    # different table entirely
    TableName.objects.create(name="employees", schema=hr, etl=etl)

    assert TableName.objects.filter(name="employees").count() == 2


def test_duplicate_table_name_within_same_schema_is_rejected():
    schema = Schema.objects.create(name="sales")
    etl = Etl.objects.create(name="etl1")
    TableName.objects.create(name="orders", schema=schema, etl=etl)

    with pytest.raises(IntegrityError):
        TableName.objects.create(name="orders", schema=schema, etl=etl)


def test_schema_name_uniqueness_is_case_insensitive():
    # enforced by the functional unique index added in migration 0002
    # (CREATE UNIQUE INDEX ... ON schemas (LOWER(name))), a postgres
    # only construct, this test therefore only passes when the test
    # suite runs against postgres, which is what pytest.ini/settings
    # point at by default
    Schema.objects.create(name="sales")
    with pytest.raises(IntegrityError):
        Schema.objects.create(name="Sales")


def test_etl_name_uniqueness_is_case_insensitive():
    # same as above, backed by migration 0002's functional index on
    # etl (LOWER(name))
    Etl.objects.create(name="etl1")
    with pytest.raises(IntegrityError):
        Etl.objects.create(name="ETL1")


def test_table_name_uniqueness_is_case_insensitive_within_schema():
    # backed by migration 0003's functional index on
    # tables_name (schema_id, LOWER(name)), which replaced the plain
    # case-sensitive UniqueConstraint from 0001
    schema = Schema.objects.create(name="sales")
    etl = Etl.objects.create(name="etl1")
    TableName.objects.create(name="orders", schema=schema, etl=etl)

    with pytest.raises(IntegrityError):
        TableName.objects.create(name="Orders", schema=schema, etl=etl)


def test_deleting_schema_cascades_to_its_tables():
    schema = Schema.objects.create(name="sales")
    etl = Etl.objects.create(name="etl1")
    table = TableName.objects.create(name="orders", schema=schema, etl=etl)

    schema.delete()

    assert not TableName.objects.filter(pk=table.pk).exists()


def test_deleting_referenced_etl_is_blocked():
    schema = Schema.objects.create(name="sales")
    etl = Etl.objects.create(name="etl1")
    TableName.objects.create(name="orders", schema=schema, etl=etl)

    with pytest.raises(ProtectedError):
        etl.delete()

    # the table must still exist, the delete was refused, not
    # partially applied
    assert TableName.objects.filter(name="orders").exists()


def test_deleting_unreferenced_etl_succeeds():
    etl = Etl.objects.create(name="etl1")
    etl.delete()
    assert not Etl.objects.filter(name="etl1").exists()
