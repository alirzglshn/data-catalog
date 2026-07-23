# mini data catalog

A  metadata catalog service that tracks which database schemas
exist, which tables live in each schema, and which etl job is
responsible for loading each table. tables, schemas and etl jobs are
related through real foreign keys rather than free-text columns.


## project structure

```
.
├── Dockerfile                   # django app image (gunicorn)
├── docker-compose.yml           # web + postgres + postfix
├── requirements.txt             # production dependencies
├── requirements-dev.txt         # + pytest, black, flake8
├── .env.example                 # documents every required env var
├── .gitignore
├── pytest.ini
├── pyproject.toml               # black config
├── setup.cfg                    # flake8 config
├── etl_names.csv                # seed data for the Etl table
│
├── config/                      # django project package
│   ├── settings.py              # env-driven settings, drf, jwt, smtp
│   ├── urls.py                  # /api/v1/auth/, /api/v1/catalog/
│   ├── wsgi.py / asgi.py
│
├── accounts/                    # authentication
│   └── urls.py                  # jwt obtain/refresh (simplejwt views)
│
├── catalog/                     # the actual data catalog app
│   ├── models.py                # Schema, Etl, TableName
│   ├── serializers.py
│   ├── services.py              # csv/json parsing, external-db metadata
│   │                             reads, and the schema summary query
│   ├── views.py                 # IngestTablesView, DirectDatabaseIngestView,
│   │                             EtlTablesView, SchemaSummaryView
│   ├── exceptions.py            # shared drf error shape
│   ├── admin.py                 # django admin registration
│   ├── management/commands/
│   │   └── seed_etl_names.py    # loads etl_names.csv
│   ├── migrations/
│   │   ├── 0001_initial.py
│   │   ├── 0002_case_insensitive_unique_names.py
│   │   ├── 0003_case_insensitive_table_uniqueness.py
│   │   └── 0004_table_created_at_index.py
│   └── tests/
│       ├── test_models.py               # fk/constraint behaviour
│       ├── test_services.py             # parsing + upsert logic, incl. blank-field validation
│       ├── test_views.py                # http-level, including auth
│       ├── test_direct_database_ingest.py  # external-db ingestion, mocked connection
│       └── test_schema_summary.py          # join/aggregation endpoint
│
├── postfix/                     # minimal internal mail relay
│   ├── Dockerfile
│   └── main.cf
│
└── postman/
    └── mini-data-catalog.postman_collection.json
```

## data model and foreign key design

```
Schema (1) ──< TableName >── (1) Etl
```

- `Schema.name` is unique. one row per schema (`sales`, `hr`, ...).
- `Etl.name` is unique. one row per etl job (`etl1`, `etl2`, ...),
  seeded from `etl_names.csv` and extended automatically whenever the
  ingestion endpoint sees a new name.
- `TableName` is the join point: it has a foreign key to `Schema` and
  a foreign key to `Etl`, plus its own `name`. the pair
  `(schema, name)` is unique, so the same table name can exist in two
  different schemas, but not twice within the same schema.

two different `on_delete` behaviours were chosen on purpose:

- `TableName.schema` uses `CASCADE`: a table cannot exist without its
  schema, so removing a schema removes the tables catalogued under it.
- `TableName.etl` uses `PROTECT`: an etl job is a piece of lineage
  history, deleting it while tables still point to it would silently
  orphan that lineage, so the delete is refused until the referencing
  tables are reassigned or removed first. this is enforced by django
  itself (`django.db.models.PROTECT`), not by a database-level
  constraint, so it holds regardless of which database backend is
  used.

ingestion also rejects rows where `name`, `schema_name`, or
`etl_name` is present but blank, rather than silently creating a
`Schema` or `Etl` row named `""`. a value that is entirely missing
from a row and one that is an empty string are treated as the same
problem, this applies identically whether the rows came from an
uploaded csv/json body or were discovered by reading an external
database's own metadata (see [direct-database
ingestion](#post-apiv1catalogingestdatabase) below), both paths
converge on the same `ingest_rows` upsert.

## indexes and constraints

three indexing decisions were made deliberately after the initial
migration, each shipped as its own raw sql migration
(`migrations.RunSQL`) rather than an orm field change, since all
three rely on a postgres functional expression (`LOWER(name)`) that
django's `UniqueConstraint` cannot express directly:

- **`0002_case_insensitive_unique_names`** — replaces the plain
  case-sensitive `unique=True` btree index on `Schema.name` and
  `Etl.name` with a unique index over `LOWER(name)`. without this,
  `"sales"` and `"Sales"` could exist as two different schema rows,
  which is a data-quality bug for a catalog table, not just a missing
  performance index.
- **`0003_case_insensitive_table_uniqueness`** — replaces the
  original `unique_table_per_schema` constraint from `0001` (plain,
  case-sensitive, over `(schema_id, name)`) with a case-insensitive
  equivalent, `CREATE UNIQUE INDEX ... ON tables_name (schema_id,
  LOWER(name))`. the old constraint is dropped rather than kept
  alongside the new one, two overlapping unique indexes over almost
  the same columns would only add write overhead with no additional
  guarantee. the drop and the model's `Meta.constraints` entry are
  kept in sync via `SeparateDatabaseAndState`, so `makemigrations`
  does not see `models.py` and the recorded migration state as
  disagreeing after this change.
- **`0004_table_created_at_index`** — a plain (non-unique) btree
  index on `TableName.created_at`, added for "which tables were
  loaded in the last N days" style queries, which had no index
  backing them at all before this.

not added, and left to the automatic ones django already creates: a
non-unique index on each foreign key column (`schema_id`, `etl_id` on
`TableName`) is created automatically for every `ForeignKey`, and a
unique index backs every primary key. no additional indexing was
needed on top of those for the query patterns this project's
endpoints actually use, including the new per-schema summary
endpoint below, which relies entirely on those existing foreign-key
indexes plus `Count(..., distinct=True)`, not a new index.

because `ingest_rows` now upserts against database-level
case-insensitive uniqueness, the lookup logic in
`catalog/services.py` uses `name__iexact` rather than a plain
`get_or_create(name=...)`, a case-only variant of an existing schema
or etl name (e.g. re-ingesting `"Sales"` after `"sales"` already
exists) is treated as the same row and reuses it, rather than
raising `IntegrityError` against the new index.

## api

all endpoints below are versioned under `/api/v1/` and require a
bearer token except the auth endpoints themselves. url path
versioning was chosen over header-based versioning so the version is
visible directly in the request url, no extra postman configuration
needed.

### `POST /api/v1/auth/token/`
obtain an access/refresh token pair.

```json
{ "username": "admin", "password": "changeme" }
```

### `POST /api/v1/auth/token/refresh/`
exchange a refresh token for a new access token.

```json
{ "refresh": "<refresh token>" }
```

### `POST /api/v1/catalog/ingest/`
registers tables in the catalog, creating any missing schema/etl rows
along the way. accepts **either** a csv file upload **or** a json
body, auto-detected:

- csv upload: multipart form field named `file`, with header
  `name,schema_name,etl_name`
- json body: either a bare list or `{"tables": [...]}`, each item
  shaped `{"name": ..., "schema_name": ..., "etl_name": ...}`

every row must have all three fields present and non-blank, a row
missing a field or containing an empty string for one returns `400`
before anything is written to the database.

on success, sends a summary email (see [email setup](#email-setup)
below) and returns:

```json
{
  "processed": 2,
  "created": 2,
  "updated": 0,
  "etl_names": ["etl1", "etl2"],
  "tables": [
    { "id": 1, "name": "customers", "schema_name": "sales", "etl_name": "etl1", ... },
    { "id": 2, "name": "orders", "schema_name": "sales", "etl_name": "etl2", ... }
  ]
}
```

### `POST /api/v1/catalog/ingest/database/`

registers tables by reading them straight out of an **external**
postgres or oracle database's own metadata, rather than from an
uploaded csv/json body. this is the counterpart to
`POST /api/v1/catalog/ingest/` for the "read the data directly from
postgres or oracle" case: the caller supplies connection details for
a database it wants scanned, and every table that connection can see
is registered under a single etl job supplied in the same request.

request body:

```json
{
  "engine": "postgres",
  "host": "warehouse.internal",
  "port": 5432,
  "database": "sales_db",
  "user": "readonly",
  "password": "secret",
  "etl_name": "etl9"
}
```

`engine` is either `"postgres"` or `"oracle"`. behind the scenes:

- **postgres** — connects with `psycopg2` and reads
  `information_schema.tables`, filtered to `table_type = 'BASE
  TABLE'` and excluding the `pg_catalog`/`information_schema` system
  schemas, so only application tables are discovered.
- **oracle** — connects with `python-oracledb` (thin mode, no oracle
  instant client install required) and reads `all_tables`, which is
  already scoped to whatever the connecting user has visibility into.

every `(schema_name, table_name)` pair found is fed through the exact
same `ingest_rows` upsert that the csv/json endpoint uses, so
case-insensitive matching, idempotent re-ingestion, and the
create-vs-update counts all behave identically regardless of which
endpoint populated the catalog. the response shape is the same
`IngestionResultSerializer` summary shown above.

connection failures (bad host, refused connection, authentication
failure, unreachable network) are caught and returned as a `502`
with a `detail` message, not a raw `500`, since the failure is on the
external database's side, not the catalog's own database or request
handling. a database with no tables visible to the connecting user
returns `400`.

**why this needed to be its own endpoint** rather than reusing
`POST /api/v1/catalog/ingest/`: the existing ingest endpoint's
contract is "the caller already knows the schema/table/etl names and
is handing them over as rows" (csv or json). this endpoint's contract
is the opposite: the caller does *not* know the table names ahead of
time, it hands over *connection credentials* instead, and the names
are discovered at request time by querying the target database's own
catalog view. that's a different input shape, a different failure
mode (an external network/auth failure vs. a malformed payload), and
a different response code for that failure (`502` vs `400`), so it
gets a dedicated `ExternalConnectionSerializer` and view rather than
being folded into the existing one.

### `GET /api/v1/catalog/etl-tables/?etl_name=etl1`
returns the tables that a given etl job populates. a name that does
not exist in the catalog returns `404`, not an empty list, since those
are different situations for the caller (the job has no tables yet
vs. the job was never registered). a name that exists but has no
tables pointing at it yet correctly returns `200` with an empty list.

### `GET /api/v1/catalog/schema-summary/`

**deliberate multi-table join example.** returns a per-schema rollup
of how many tables exist in that schema and how many *distinct* etl
jobs populate them, computed in a single query across `Schema`,
`TableName`, and `Etl`:

```json
[
  { "id": 1, "name": "hr", "table_count": 1, "etl_count": 1 },
  { "id": 2, "name": "sales", "table_count": 3, "etl_count": 2 }
]
```

implemented as one annotated queryset
(`catalog/services.py::schema_summary_queryset`):

```python
Schema.objects.annotate(
    table_count=Count("tables", distinct=True),
    etl_count=Count("tables__etl", distinct=True),
).order_by("name")
```

`Count("tables", ...)` walks the `Schema -> TableName` reverse
foreign key, and `Count("tables__etl", ...)` walks
`Schema -> TableName -> Etl` in the same query, so postgres performs
the join and the counting server-side in one round trip. this is
intentionally not implemented as "fetch all schemas, then loop and
count tables/etl per schema in python" (which would be n+1 queries),
and `distinct=True` on the etl count is what makes a schema with five
tables all loaded by the same etl job correctly report `1` distinct
etl job rather than `5`.

## running it

### with docker (recommended)

1. copy the env file and adjust values, in particular
   `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD`:

   ```bash
   cp .env.example .env
   ```

2. build and start everything:

   ```bash
   docker compose up --build
   ```

   this brings up three containers: `db` (postgres 16), `postfix`
   (mail relay), and `web` (the django app). the `web` container runs
   migrations and seeds `etl_names.csv` automatically before starting
   gunicorn, so the api is ready to use as soon as the logs show
   gunicorn listening on port 8000.

3. create a user to authenticate with:

   ```bash
   docker compose exec web python manage.py createsuperuser
   ```

4. the api is now reachable at `http://localhost:8000/api/v1/...`

## email setup

the ingestion endpoints (both the csv/json upload and the
direct-database endpoint) send a summary email after every successful
load. two delivery options are supported through `.env`, both use the
same `EMAIL_*` settings so no code changes are needed to switch:

**option a — the bundled postfix container (default).** no external
account required, works immediately after `docker compose up`. mail
sent this way can be inspected with `docker compose logs postfix` or
by exec-ing into the container, it will not reach a real inbox.

**option b — a real gmail account**, so the notification lands in an
actual inbox instead of just container logs. this is the setup used
while building and demoing this project. set these four values in
`.env`:

```dotenv
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-address@gmail.com
EMAIL_HOST_PASSWORD=your-16-character-app-password
```

gmail rejects a normal account password over smtp, an **app
password** is required: enable 2-step verification on the google
account, then generate one at
[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords),
and use that 16-character value as `EMAIL_HOST_PASSWORD`.
`NOTIFY_EMAIL_RECIPIENT` can be the same gmail address, or any other
address you want the notification delivered to. the `postfix`
container still builds and starts either way, django just talks
straight to gmail instead of routing through it when option b is
configured.

## testing with postman

import `postman/mini-data-catalog.postman_collection.json`. it
already contains:

- **auth / obtain token** — posts credentials, and automatically
  stores the returned `access`/`refresh` tokens as collection
  variables via a small test script
- **auth / refresh token** — exchanges the stored refresh token for a
  new access token
- **catalog / ingest tables (json)** — a ready-to-send example body
- **catalog / ingest tables (csv upload)** — attach a csv file to the
  `file` form field before sending, the request will otherwise send
  with no file attached
- **catalog / ingest from external database** — a ready-to-send
  example body pointing at a postgres connection; swap `engine` to
  `"oracle"` and adjust `port`/credentials to test against an oracle
  instance instead
- **catalog / tables for an etl job** — the lookup endpoint
- **catalog / tables for an unknown etl job (expect 404)** — the
  not-found case
- **catalog / schema summary** — the join/aggregation endpoint

run "obtain token" first, the access token is then reused
automatically by the other requests through the `{{access_token}}`
collection variable.

## running the automated test suite

```bash
pip install -r requirements-dev.txt
pytest
```

pytest is configured through `pytest.ini` to use `--reuse-db`, so
after the first run it reuses the same test database instead of
rebuilding it from migrations every time, pass `--create-db` once if
migrations have changed and the cached test database is stale.

49 tests cover five layers independently:

- `test_models.py` (7 tests) — fk/uniqueness constraints at the
  database level, including that deleting a schema cascades and that
  deleting a referenced etl is blocked
- `test_services.py` (17 tests) — the parsing and upsert functions
  directly, including the blank/missing field validation and the
  re-ingest-is-idempotent behaviour
- `test_views.py` (13 tests) — full http request/response cycle,
  including authentication required, token rejection, the 404 vs
  empty-list distinction, and that a successful ingest actually sends
  an email (checked against django's in-memory test mailbox, no real
  smtp call happens during the test run)
- `test_direct_database_ingest.py` (8 tests) — the external-db
  ingestion endpoint, with `discover_external_tables` mocked so no
  real postgres/oracle connection is made during the test run: covers
  successful discovery-and-registration for both engines, idempotent
  re-scanning, an unsupported engine being rejected before any
  connection attempt, a missing required field, authentication being
  required, and (critically) a connection failure returning `502`
  rather than raising an unhandled exception
- `test_schema_summary.py` (4 tests) — the join/aggregation endpoint,
  confirming `table_count` and `etl_count` are correct per schema,
  that a schema with zero tables reports zero rather than erroring,
  and specifically that many tables sharing one etl job report
  `etl_count == 1` rather than the row count

## code style

the project follows pep8 and is checked with black and flake8:

```bash
black --check catalog accounts config
flake8 catalog accounts config
```

black is configured in `pyproject.toml` (100 character line length,
migrations excluded), flake8 is configured in `setup.cfg` with a
matching line length and `E203`/`W503` ignored, since both conflict
with choices black itself makes around slices and line breaks before
binary operators.

