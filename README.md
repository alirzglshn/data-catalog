# Mini data catalog

A small metadata catalog service. it tracks which database schemas
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
│   ├── services.py              # csv/json parsing + upsert logic
│   ├── views.py                 # IngestTablesView, EtlTablesView
│   ├── exceptions.py            # shared drf error shape
│   ├── admin.py                 # django admin registration
│   ├── management/commands/
│   │   └── seed_etl_names.py    # loads etl_names.csv
│   ├── migrations/
│   └── tests/
│       ├── test_models.py       # fk/constraint behaviour
│       ├── test_services.py     # parsing + upsert logic, incl. blank-field validation
│       └── test_views.py        # http-level, including auth
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
problem.

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

### `GET /api/v1/catalog/etl-tables/?etl_name=etl1`
returns the tables that a given etl job populates. a name that does
not exist in the catalog returns `404`, not an empty list, since those
are different situations for the caller (the job has no tables yet
vs. the job was never registered). a name that exists but has no
tables pointing at it yet correctly returns `200` with an empty list.

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

the ingestion endpoint sends a summary email after every successful
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
- **catalog / tables for an etl job** — the lookup endpoint
- **catalog / tables for an unknown etl job (expect 404)** — the
  not-found case

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

37 tests cover three layers independently:

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

