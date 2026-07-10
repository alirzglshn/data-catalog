"""tests for the per-schema summary (join/aggregation) endpoint

these confirm the annotated counts coming back from
catalog.services.schema_summary_queryset are correct, in particular
that etl_count reflects distinct etl jobs rather than the number of
joined table rows
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from catalog.models import Etl, Schema, TableName

pytestmark = pytest.mark.django_db


@pytest.fixture
def authenticated_client():
    user = get_user_model().objects.create_user(username="tester", password="pw")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def catalog_data():
    sales = Schema.objects.create(name="sales")
    hr = Schema.objects.create(name="hr")
    empty = Schema.objects.create(name="empty")

    etl1 = Etl.objects.create(name="etl1")
    etl2 = Etl.objects.create(name="etl2")

    # sales: three tables, two distinct etl jobs
    TableName.objects.create(schema=sales, name="customers", etl=etl1)
    TableName.objects.create(schema=sales, name="orders", etl=etl1)
    TableName.objects.create(schema=sales, name="coupons", etl=etl2)

    # hr: one table, one etl job
    TableName.objects.create(schema=hr, name="employees", etl=etl2)

    # empty: no tables at all
    return {"sales": sales, "hr": hr, "empty": empty}


class TestSchemaSummary:
    def test_table_and_etl_counts_are_correct(self, authenticated_client, catalog_data):
        response = authenticated_client.get(reverse("catalog:schema-summary"))

        assert response.status_code == 200
        by_name = {row["name"]: row for row in response.json()}

        assert by_name["sales"]["table_count"] == 3
        assert by_name["sales"]["etl_count"] == 2

        assert by_name["hr"]["table_count"] == 1
        assert by_name["hr"]["etl_count"] == 1

    def test_schema_with_no_tables_reports_zero_counts(self, authenticated_client, catalog_data):
        response = authenticated_client.get(reverse("catalog:schema-summary"))

        by_name = {row["name"]: row for row in response.json()}
        assert by_name["empty"]["table_count"] == 0
        assert by_name["empty"]["etl_count"] == 0

    def test_same_etl_across_many_tables_counts_once(self, authenticated_client):
        schema = Schema.objects.create(name="reporting")
        etl = Etl.objects.create(name="shared-etl")
        for table_name in ("a", "b", "c", "d", "e"):
            TableName.objects.create(schema=schema, name=table_name, etl=etl)

        response = authenticated_client.get(reverse("catalog:schema-summary"))

        row = next(r for r in response.json() if r["name"] == "reporting")
        assert row["table_count"] == 5
        assert row["etl_count"] == 1

    def test_requires_authentication(self, catalog_data):
        client = APIClient()
        response = client.get(reverse("catalog:schema-summary"))
        assert response.status_code == 401
