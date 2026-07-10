"""
data catalog models
"""

from django.db import models


class TimeStampedModel(models.Model):
    """abstract base that adds created/updated timestamps
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
    """

    name = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = "etl"
        ordering = ["name"]

    def __str__(self):
        return self.name


class TableName(TimeStampedModel):
    """a catalogued table, tied to the schema it lives in and the etl
    """

    name = models.CharField(max_length=255)
    schema = models.ForeignKey(Schema, related_name="tables", on_delete=models.CASCADE)
    etl = models.ForeignKey(Etl, related_name="tables", on_delete=models.PROTECT)

    class Meta:
        db_table = "tables_name"
        ordering = ["schema__name", "name"]

    def __str__(self):
        return f"{self.schema.name}.{self.name}"
