"""tests for the direct-database ingestion endpoint
"""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from catalog.models import Etl, Schema, TableName
from catalog.services import ExternalConnectionError

pytestmark = pytest.mark.django_db


@pytest.fixture
def authenticated_client():
    user = get_user_model().objects.create_user(username="tester", password="pw")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


VALID_PAYLOAD = {
    "engine": "postgres",
    "host": "warehouse.internal",
    "port": 5432,
    "database": "sales_db",
    "user": "readonly",
    "password": "secret",
    "etl_name": "etl9",
}


class TestDirectDatabaseIngestSuccess:
    def test_discovered_tables_are_registered(self, authenticated_client):
        discovered = [("sales", "customers"), ("sales", "orders"), ("hr", "employees")]

        with patch("catalog.views.discover_external_tables", return_value=discovered) as mocked:
            response = authenticated_client.post(
                reverse("catalog:ingest-database"), VALID_PAYLOAD, format="json"
            )

        assert response.status_code == 201
        assert mocked.call_count == 1

        body = response.json()
        assert body["processed"] == 3
        assert body["created"] == 3
        assert body["etl_names"] == ["etl9"]

        assert TableName.objects.filter(name__iexact="customers", schema__name="sales").exists()
        assert TableName.objects.filter(name__iexact="orders", schema__name="sales").exists()
        assert TableName.objects.filter(name__iexact="employees", schema__name="hr").exists()
        assert Schema.objects.filter(name="sales").exists()
        assert Schema.objects.filter(name="hr").exists()
        assert Etl.objects.filter(name="etl9").exists()

    def test_reingesting_the_same_database_is_idempotent(self, authenticated_client):
        discovered = [("sales", "customers")]

        with patch("catalog.views.discover_external_tables", return_value=discovered):
            first = authenticated_client.post(
                reverse("catalog:ingest-database"), VALID_PAYLOAD, format="json"
            )
            second = authenticated_client.post(
                reverse("catalog:ingest-database"), VALID_PAYLOAD, format="json"
            )

        assert first.json()["created"] == 1
        assert second.json()["created"] == 0
        assert second.json()["updated"] == 1
        assert TableName.objects.filter(name__iexact="customers").count() == 1

    def test_oracle_engine_is_accepted(self, authenticated_client):
        payload = {**VALID_PAYLOAD, "engine": "oracle", "port": 1521}

        with patch("catalog.views.discover_external_tables", return_value=[("FIN", "LEDGER")]):
            response = authenticated_client.post(
                reverse("catalog:ingest-database"), payload, format="json"
            )

        assert response.status_code == 201
        assert TableName.objects.filter(name__iexact="LEDGER", schema__name="FIN").exists()


class TestDirectDatabaseIngestFailure:
    def test_connection_failure_returns_502_not_500(self, authenticated_client):
        with patch(
            "catalog.views.discover_external_tables",
            side_effect=ExternalConnectionError("could not connect to postgres database: timeout"),
        ):
            response = authenticated_client.post(
                reverse("catalog:ingest-database"), VALID_PAYLOAD, format="json"
            )

        assert response.status_code == 502
        assert "detail" in response.json()
        assert TableName.objects.count() == 0

    def test_empty_external_database_returns_400(self, authenticated_client):
        with patch("catalog.views.discover_external_tables", return_value=[]):
            response = authenticated_client.post(
                reverse("catalog:ingest-database"), VALID_PAYLOAD, format="json"
            )

        assert response.status_code == 400

    def test_unsupported_engine_is_rejected_before_connecting(self, authenticated_client):
        payload = {**VALID_PAYLOAD, "engine": "mysql"}

        with patch("catalog.views.discover_external_tables") as mocked:
            response = authenticated_client.post(
                reverse("catalog:ingest-database"), payload, format="json"
            )

        assert response.status_code == 400
        mocked.assert_not_called()

    def test_missing_field_is_rejected(self, authenticated_client):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "host"}

        response = authenticated_client.post(
            reverse("catalog:ingest-database"), payload, format="json"
        )

        assert response.status_code == 400

    def test_requires_authentication(self):
        client = APIClient()
        response = client.post(reverse("catalog:ingest-database"), VALID_PAYLOAD, format="json")
        assert response.status_code == 401
