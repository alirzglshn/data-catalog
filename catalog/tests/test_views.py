"""http-level tests for the catalog endpoints, including authentication.

these go through the full request/response cycle via drf's APIClient,
so they also catch url wiring, versioning, and permission mistakes
that the service-level tests in test_services.py cannot see.
"""

import io

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework.test import APIClient

from catalog.models import Etl, Schema, TableName

pytestmark = pytest.mark.django_db

INGEST_URL = "/api/v1/catalog/ingest/"
ETL_TABLES_URL = "/api/v1/catalog/etl-tables/"
TOKEN_URL = "/api/v1/auth/token/"


@pytest.fixture
def user():
    return get_user_model().objects.create_user(username="tester", password="s3cret-pass")


@pytest.fixture
def auth_client(user):
    client = APIClient()
    response = client.post(TOKEN_URL, {"username": "tester", "password": "s3cret-pass"})
    assert response.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return client


class TestAuthentication:
    def test_obtaining_a_token_requires_valid_credentials(self, user):
        client = APIClient()
        response = client.post(TOKEN_URL, {"username": "tester", "password": "wrong"})
        assert response.status_code == 401

    def test_endpoints_reject_requests_without_a_token(self):
        client = APIClient()
        response = client.get(ETL_TABLES_URL, {"etl_name": "etl1"})
        assert response.status_code == 401

    def test_valid_token_is_accepted(self, auth_client):
        response = auth_client.get(ETL_TABLES_URL, {"etl_name": "etl1"})
        # the etl does not exist yet in this test, so 404 is expected,
        # the point here is that auth itself did not block the request
        assert response.status_code == 404


class TestIngestEndpoint:
    def test_ingest_via_json_body(self, auth_client):
        payload = {
            "tables": [
                {"name": "orders", "schema_name": "sales", "etl_name": "etl1"},
                {"name": "customers", "schema_name": "sales", "etl_name": "etl1"},
            ]
        }
        response = auth_client.post(INGEST_URL, payload, format="json")

        assert response.status_code == 201
        assert response.data["processed"] == 2
        assert response.data["created"] == 2
        assert TableName.objects.count() == 2

    def test_ingest_via_csv_upload(self, auth_client):
        csv_content = b"name,schema_name,etl_name\norders,sales,etl1\n"
        upload = io.BytesIO(csv_content)
        upload.name = "tables.csv"

        response = auth_client.post(INGEST_URL, {"file": upload}, format="multipart")

        assert response.status_code == 201
        assert response.data["processed"] == 1
        assert TableName.objects.filter(name="orders").exists()

    def test_ingest_sends_a_notification_email(self, auth_client):
        payload = {"tables": [{"name": "orders", "schema_name": "sales", "etl_name": "etl1"}]}
        auth_client.post(INGEST_URL, payload, format="json")

        assert len(mail.outbox) == 1
        assert "ingestion completed" in mail.outbox[0].subject

    def test_ingest_rejects_malformed_json_body(self, auth_client):
        response = auth_client.post(INGEST_URL, {"tables": "not-a-list"}, format="json")
        assert response.status_code == 400
        assert "detail" in response.data

    def test_ingest_rejects_row_with_blank_field(self, auth_client):
        payload = {"tables": [{"name": "orders", "schema_name": "", "etl_name": "etl1"}]}
        response = auth_client.post(INGEST_URL, payload, format="json")
        assert response.status_code == 400

    def test_ingest_requires_authentication(self):
        client = APIClient()
        payload = {"tables": [{"name": "orders", "schema_name": "sales", "etl_name": "etl1"}]}
        response = client.post(INGEST_URL, payload, format="json")
        assert response.status_code == 401


class TestEtlTablesEndpoint:
    def test_returns_tables_for_a_known_etl(self, auth_client):
        schema = Schema.objects.create(name="sales")
        etl = Etl.objects.create(name="etl1")
        TableName.objects.create(name="orders", schema=schema, etl=etl)

        response = auth_client.get(ETL_TABLES_URL, {"etl_name": "etl1"})

        assert response.status_code == 200
        names = [row["name"] for row in response.data]
        assert names == ["orders"]

    def test_unknown_etl_name_returns_404_not_empty_list(self, auth_client):
        response = auth_client.get(ETL_TABLES_URL, {"etl_name": "does-not-exist"})
        assert response.status_code == 404

    def test_missing_etl_name_param_returns_404(self, auth_client):
        response = auth_client.get(ETL_TABLES_URL)
        assert response.status_code == 404

    def test_known_etl_with_no_tables_yet_returns_empty_list_not_404(self, auth_client):
        # this is the case the etl exists but nothing points at it,
        # distinct from an etl name that was never registered at all
        Etl.objects.create(name="etl1")

        response = auth_client.get(ETL_TABLES_URL, {"etl_name": "etl1"})

        assert response.status_code == 200
        assert response.data == []
