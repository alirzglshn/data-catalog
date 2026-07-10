"""replaces the case-sensitive composite unique constraint on
TableName with a case-insensitive one.

the unique_table_per_schema constraint from 0001 is a plain btree
unique index over (schema_id, name), it allows "orders" and "Orders"
to both be registered under the same schema as two distinct rows,
which is the same class of bug fixed for Schema/Etl in 0002.

the old constraint is dropped and replaced rather than kept alongside
the new one, keeping both would mean two overlapping unique indexes
enforcing almost the same thing, which only adds write overhead
without adding any additional guarantee.

written as raw sql since a functional expression, lower(name), is not
something django's ORM-level UniqueConstraint can express directly.
"""

from django.db import migrations

DROP_OLD_CONSTRAINT = """
    ALTER TABLE tables_name
    DROP CONSTRAINT IF EXISTS unique_table_per_schema;
"""

RESTORE_OLD_CONSTRAINT = """
    ALTER TABLE tables_name
    ADD CONSTRAINT unique_table_per_schema UNIQUE (schema_id, name);
"""

CREATE_CASE_INSENSITIVE_INDEX = """
    CREATE UNIQUE INDEX table_schema_name_lower_uniq
    ON tables_name (schema_id, LOWER(name));
"""

DROP_CASE_INSENSITIVE_INDEX = """
    DROP INDEX IF EXISTS table_schema_name_lower_uniq;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0002_case_insensitive_unique_names"),
    ]

    operations = [
        # SeparateDatabaseAndState is used for the constraint removal
        # so django's migration state (what makemigrations compares
        # models.py against) drops unique_table_per_schema at the same
        # point the real database constraint is dropped, without this
        # the next makemigrations run would see models.py (no
        # constraint) out of sync with the recorded state (constraint
        # still present) and generate a spurious migration
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="tablename",
                    name="unique_table_per_schema",
                ),
            ],
            database_operations=[
                migrations.RunSQL(sql=DROP_OLD_CONSTRAINT, reverse_sql=RESTORE_OLD_CONSTRAINT),
            ],
        ),
        migrations.RunSQL(
            sql=CREATE_CASE_INSENSITIVE_INDEX, reverse_sql=DROP_CASE_INSENSITIVE_INDEX
        ),
    ]
