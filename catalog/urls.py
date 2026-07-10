from django.urls import path

from catalog.views import (
    DirectDatabaseIngestView,
    EtlTablesView,
    IngestTablesView,
    SchemaSummaryView,
)

app_name = "catalog"

urlpatterns = [
    path("ingest/", IngestTablesView.as_view(), name="ingest-tables"),
    path("ingest/database/", DirectDatabaseIngestView.as_view(), name="ingest-database"),
    path("etl-tables/", EtlTablesView.as_view(), name="etl-tables"),
    path("schema-summary/", SchemaSummaryView.as_view(), name="schema-summary"),
]
