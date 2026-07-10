"""
data catalog models

the original source (a legacy dump plus a csv of etl names) only had
flat, unrelated tables: a schema list, a table list carrying
schema_name/etl_name as plain text, and a csv of etl names. this
module normalizes that into three related tables so schema_name and
etl_name become real foreign keys instead of free text that could
silently drift out of sync

Schema      -- one row per database schema in the organisation
Etl         -- one row per etl job that can populate tables
TableName   -- one row per catalogued table, fk to both of the above
"""

from django.db import models


class TimeStampedModel(models.Model):
    """abstract base that adds created/updated timestamps

    every catalog table benefits from knowing when a row was first
    registered and last touched, so this is shared rather than
    repeated on each model
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Schema(TimeStampedModel):
    """a database schema known to the catalog, e.g. 'sales' or 'hr'"""

    name = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = "schemas"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Etl(TimeStampedModel):
    """an etl job that is allowed to populate catalogued tables

    seeded from etl_names.csv (etl1..etl5) and extended at runtime
    whenever the ingestion endpoint sees a new etl name
    """

    name = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = "etl"
        ordering = ["name"]

    def __str__(self):
        return self.name


class TableName(TimeStampedModel):
    """a catalogued table, tied to the schema it lives in and the etl

    job that loads it. the (schema, name) pair is unique per schema,
    enforced case-insensitively so "orders" and "Orders" in the same
    schema are treated as the same table. that uniqueness is enforced
    by a raw sql functional unique index (see migration 0003), not by
    a Meta.constraints entry, since UniqueConstraint has no way to
    express an index over lower(name)
    """

    name = models.CharField(max_length=255)
    schema = models.ForeignKey(Schema, related_name="tables", on_delete=models.CASCADE)
    etl = models.ForeignKey(Etl, related_name="tables", on_delete=models.PROTECT)

    class Meta:
        db_table = "tables_name"
        ordering = ["schema__name", "name"]

    def __str__(self):
        return f"{self.schema.name}.{self.name}"
