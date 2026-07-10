"""adds an index on tables_name.created_at.

a catalog/lineage service is a realistic candidate for "which tables
were loaded in the last N days" style queries, created_at had no
index at all before this, a plain btree index is enough since the
expected filters are equality/range comparisons on a timestamp, not
pattern matching.

added as raw sql via RunSQL rather than field(db_index=True) plus
makemigrations, to keep this change alongside the other two raw index
migrations and keep all three index decisions reviewable in one place
"""

from django.db import migrations

CREATE_INDEX = """
    CREATE INDEX table_created_at_idx
    ON tables_name (created_at);
"""

DROP_INDEX = """
    DROP INDEX IF EXISTS table_created_at_idx;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0003_case_insensitive_table_uniqueness"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_INDEX, reverse_sql=DROP_INDEX),
    ]
