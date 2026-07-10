from django.contrib import admin

from catalog.models import Etl, Schema, TableName


@admin.register(Schema)
class SchemaAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(Etl)
class EtlAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(TableName)
class TableNameAdmin(admin.ModelAdmin):
    list_display = ("name", "schema", "etl", "created_at")
    list_filter = ("schema", "etl")
    search_fields = ("name",)
