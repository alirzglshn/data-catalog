"""adds case-insensitive uniqueness on Schema.name and Etl.name.

the plain unique=True index from 0001 is a case-sensitive btree index,
it happily allows "Sales" and "sales" to exist as two different rows.
that is a real data-quality bug for a catalog table, not just a
missing performance index, so it is fixed here with a functional
unique index over lower(name) instead.

written as raw sql (RunSQL) rather than an orm field change, since
django's UniqueConstraint has no direct way to express an index over
an expression like lower(name), only over plain columns.
"""

from django.db import migrations

CREATE_SCHEMA_INDEX = """
    CREATE UNIQUE INDEX schema_name_lower_uniq
    ON schemas (LOWER(name));
"""

DROP_SCHEMA_INDEX = """
    DROP INDEX IF EXISTS schema_name_lower_uniq;
"""

CREATE_ETL_INDEX = """
    CREATE UNIQUE INDEX etl_name_lower_uniq
    ON etl (LOWER(name));
"""

DROP_ETL_INDEX = """
    DROP INDEX IF EXISTS etl_name_lower_uniq;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SCHEMA_INDEX, reverse_sql=DROP_SCHEMA_INDEX),
        migrations.RunSQL(sql=CREATE_ETL_INDEX, reverse_sql=DROP_ETL_INDEX),
    ]
