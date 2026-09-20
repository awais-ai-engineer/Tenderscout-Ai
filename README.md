# TenderScout AI

TenderScout AI is intended to help teams discover and evaluate public tenders.
The backend currently includes FastAPI, environment configuration, PostgreSQL
models and migrations for sources and tenders, and Redis connection settings.

## Structure

- `backend/app/api`: HTTP routes.
- `backend/app/core`: environment configuration.
- `backend/app/db`: SQLAlchemy engine setup using psycopg.
- `backend/app/models`: Source and Tender ORM entities.
- `backend/app/schemas`: Pydantic create/read data contracts.
- `backend/app/scrapers`: public listing fetching and source-specific parsing.
- `backend/app/services`: transactional tender ingestion.
- `backend/alembic`: versioned database migrations.
- `backend/app/main.py`: application and resource lifecycle.
- `compose.yaml`: local PostgreSQL and Redis services.

## Development setup

Use Python 3.12 or newer and Docker Compose. Run from the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements-dev.txt
Copy-Item .env.example .env
```

On Linux/macOS, activate with `source .venv/bin/activate` and copy with
`cp .env.example .env`. For runtime-only installation, use
`backend/requirements.txt` instead.

Replace the example PostgreSQL password in `.env`, then start:

```text
docker compose up -d --wait
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn app.main:app --app-dir backend --reload
```

The application reads the repository-root `.env` regardless of working directory;
environment variables take precedence. PostgreSQL credentials are required at
startup. Passwords are redacted in settings representations and JSON serialization;
do not log raw environment variables, explicit secret values, or validation error
input dictionaries.

`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, and
`POSTGRES_PASSWORD` configure PostgreSQL. `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`,
and optional `REDIS_PASSWORD` configure Redis. Redis has no client or workload yet.

Compose binds both services to loopback for local development. Its Redis service
is unauthenticated and disposable; `REDIS_PASSWORD` is for a separately configured
authenticated deployment. PostgreSQL data uses a named volume. Changing `.env`
credentials does not change credentials in an already initialized database.
This Compose file is not a production deployment configuration.

## API

```text
GET http://127.0.0.1:8000/health
200 OK
{"status":"ok"}
```

Interactive API documentation is at `/docs`. `/health` reports application
liveness only, not PostgreSQL or Redis readiness. Engine creation is lazy:
startup validates configuration but does not open a database connection.
Connections have a five-second connection timeout, pool checks, and are disposed
at shutdown.

## Verification

```text
python -m unittest discover -s backend/tests
python -m ruff check backend
python -m ruff format --check backend
docker compose config --quiet
```

For the unittest command, set `PYTHONPATH=backend` in your environment first
(`$env:PYTHONPATH = "backend"` in PowerShell, `export PYTHONPATH=backend` on POSIX).
Tests do not require running PostgreSQL or Redis.

## Database migrations

Alembic uses the existing application settings and synchronous SQLAlchemy/psycopg
engine. No credentials are stored in `alembic.ini`, and application startup never
creates tables. Run commands from the repository root:

```text
python -m alembic -c backend/alembic.ini current
python -m alembic -c backend/alembic.ini upgrade head
```

Revision `0001` creates `sources` and `tenders`. Source slugs are unique; tender
external IDs and source URLs are unique within each source. Multiple null
external IDs are allowed. Indexes cover `source_id` and `deadline`.

The source foreign key uses `ON DELETE RESTRICT`, with no ORM delete cascade.
A source with tender history cannot be deleted; deactivate it with `is_active`
instead. All timestamps use PostgreSQL `TIMESTAMP WITH TIME ZONE` and database
`now()` defaults where required. PostgreSQL stores instants independently of the
session timezone. Inputs reject naive datetimes. `updated_at` advances on
SQLAlchemy updates; direct SQL writers must set it themselves. `last_seen_at`
must be set explicitly when an opportunity is observed again.

On a disposable database, test reversal with the commands below. Downgrading to
base deletes both tables and their records:

```text
python -m alembic -c backend/alembic.ini downgrade base
python -m alembic -c backend/alembic.ini upgrade head
```

Without PostgreSQL, append `--sql` to `upgrade head` or use
`downgrade head:base --sql` to render PostgreSQL SQL only. Settings still require
a password; use a dummy environment value for offline checks. SQL rendering does
not verify live migration execution. The migration tests check generated SQL
against model metadata without a database.

## Supported sources

| Source | Ingestion |
| --- | --- |
| Find a Tender | Public HTML listing, UK4 notices |
| Contracts Finder | Official public OCDS JSON search API, active tender releases |

Both source-specific parsers produce `ScrapedTender` records for the same
transactional ingestion service and PostgreSQL models.

### Find a Tender

The adapter reads the first public [Find a Tender listing page](https://www.find-tender.service.gov.uk/Search/Results)
and selects **UK4: Tender notice** records. It uses HTTPX and Beautiful Soup;
JavaScript rendering, login, and detail requests are not needed for listing data.
The service's [terms](https://www.find-tender.service.gov.uk/Home/TermsAndConditions)
permit reuse of licensed content. The HTML fixture contains public sector
information licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

After configuring PostgreSQL and applying migrations, run from the repository root
with `PYTHONPATH=backend` set as described above:

```text
python -m app.ingest --source find-a-tender
```

To fetch and validate the real listing without database configuration or writes:

```text
python -m app.ingest --source find-a-tender --fetch-only
```

Collected fields are the notice ID, title, buyer/organization, description excerpt,
canonical notice URL, location, publication time, and submission deadline when
present. Category is not supplied by this listing and remains unset. Displayed
English dates are interpreted as `Europe/London` local time and converted to UTC;
unrecognized dates and ambiguous/nonexistent daylight-saving times are rejected.

Each run requests `robots.txt` and one listing page, with an identifiable user agent
and a 20-second HTTPX timeout per network operation. A missing robots file (404) is
allowed; an explicit denial or HTTP failure stops the run. There are no retries,
redirect following, detail requests, or access-control workarounds. A sampled
detail URL returned HTTP 403 during development; only listing access was verified.

Ingestion commits a page in one transaction. A source-row lock serializes concurrent
runs for that source, and source creation handles slug uniqueness with `ON CONFLICT`.
Tenders match by source plus external ID, with source plus canonical URL as fallback.
Conflicting identities are logged and skipped rather than merged. Other database
errors roll back the whole transaction and propagate. Inactive sources are not
reactivated. Existing records keep `first_seen_at` and receive a new `last_seen_at`;
provided mutable values are updated, while missing optional values preserve known
data. Content hashes remain unset because direct field comparison is sufficient.

For either source, the summary reports records discovered, created, changed,
unchanged, failed, and skipped. `changed` means at least one provided normalized
source field changed; `unchanged` means the record was merely seen again. Both
advance `last_seen_at`, which does not itself count as a content change. Missing
optional values preserve known data. Repeated records count as separate observations.
Partial failures return exit code 1 after committing valid records. Source-level
fetch/parse failures and database failures also return 1, without success counts.
Operational logs go to stderr. `--fetch-only` reports valid records, not insert counts.

Coverage is intentionally limited to the first page and UK4 notices. Descriptions
may be truncated; there is no pagination, full detail collection, or category/CPV
extraction. Missing result structure raises an error; a valid zero notice count or
a page containing only other notice types is reported separately. Selectors and
date labels may change. Parser tests use saved HTML and mocked HTTP; ingestion
tests use in-memory SQLite with unchanged production models. They verify business
behavior, not PostgreSQL row locking, concurrency, or live migration execution.

### Contracts Finder

The adapter uses the [documented OCDS search API](https://www.contractsfinder.service.gov.uk/apidocumentation/Notices/1/GET-Published-Notice-OCDS-Search):

```text
GET https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search?stages=tender&limit=20
python -m app.ingest --source contracts-finder
python -m app.ingest --source contracts-finder --fetch-only
```

This public endpoint was verified without login or an API key. One request fetches
at most 20 releases; cursor/next links are not followed. There are no record, detail,
or document requests. HTTPX uses a 30-second timeout per network operation and no
retries or redirects. The API documents a five-minute pause after HTTP 403;
the command stops on that response rather than retrying.

Mapping uses fields observed in the public response:

| Normalized field | OCDS field |
| --- | --- |
| `external_id` | Notice UUID from the official HTML `tender.documents[].url` |
| `source_url` | That same URL, for `documentType=tenderNotice`, `format=text/html` |
| `title`, `description` | `tender.title`, `tender.description` |
| `organization` | `buyer.name`; otherwise matching buyer party or sorted buyer-role names |
| `category` | `tender.mainProcurementCategory` |
| `location` | Distinct sorted `tender.items[].deliveryAddresses[].countryName` values |
| `published_at` | `tender.datePublished`, not the release/package modification date |
| `deadline` | `tender.tenderPeriod.endDate` |

The notice UUID identifies the published notice across release versions. The API's
`ocid` identifies a procurement process; release `id` includes a version suffix,
and `tender.id` is a buyer reference. None replaces notice identity in this adapter.
Each source retains its own identity namespace.

Only active releases tagged `tender`, `tenderUpdate`, or `tenderAmendment` are ingested;
other stages and inactive tenders are skipped. This is a bounded recent batch, not
complete coverage or a guarantee of an unexpired deadline. Countries are delivery
locations, not buyer addresses. Missing optional fields remain absent; malformed
required data or datetimes reject that record. ISO datetimes must carry an offset
and are converted to UTC. An invalid package or wholly malformed batch fails loudly.

The JSON fixture contains two real public releases captured on 2026-09-20, with
contact details, buyer addresses, attachment links, and pagination removed. Its
original OGL license field is retained. Tests never require either live source.
Omitting `--source` keeps the previous Find a Tender default; unknown names are errors.

## Current limitations

Only Find a Tender and Contracts Finder are integrated. There are no CRUD endpoints,
AI/RAG features, workers, frontend, or tender matching. No documents are downloaded,
and content hashing is not implemented.
