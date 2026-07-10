"""adds an index on tables_name.created_at.
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
