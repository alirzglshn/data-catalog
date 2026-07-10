from django.urls import path

from catalog.views import EtlTablesView, IngestTablesView

app_name = "catalog"

urlpatterns = [
    path("ingest/", IngestTablesView.as_view(), name="ingest-tables"),
    path("etl-tables/", EtlTablesView.as_view(), name="etl-tables"),
]
