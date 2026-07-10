"""tests for model level constraints and foreign key behaviour.

these exercise the database itself, confirming cascade/protect and
the uniqueness rules actually hold, not just that the orm calls
succeed.
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
