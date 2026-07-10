"""serializers for the catalog api

TableNameSerializer is the read shape used everywhere a table needs
to come back to the client, schema and etl are nested by name rather
than by id since the id is an internal detail the caller never needs
"""

from rest_framework import serializers

from catalog.models import Etl, Schema, TableName


class SchemaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Schema
        fields = ["id", "name", "created_at"]


class EtlSerializer(serializers.ModelSerializer):
    class Meta:
        model = Etl
        fields = ["id", "name", "created_at"]


class TableNameSerializer(serializers.ModelSerializer):
    schema_name = serializers.CharField(source="schema.name", read_only=True)
    etl_name = serializers.CharField(source="etl.name", read_only=True)

    class Meta:
        model = TableName
        fields = ["id", "name", "schema_name", "etl_name", "created_at", "updated_at"]


class IngestionResultSerializer(serializers.Serializer):
    """shapes the summary returned by catalog.services.ingest_rows

    this is a plain Serializer rather than a ModelSerializer since the
    payload is a summary dict, not a single model instance
    """

    processed = serializers.IntegerField()
    created = serializers.IntegerField()
    updated = serializers.IntegerField()
    etl_names = serializers.ListField(child=serializers.CharField())
    tables = TableNameSerializer(many=True)
