# TenderScout AI

TenderScout AI is intended to help teams discover and evaluate public tenders.
The backend currently includes FastAPI, environment configuration, PostgreSQL
models and migrations for sources, tenders, documents and analyses, and Redis settings.

## Structure

- `backend/app/api`: HTTP routes.
- `backend/app/core`: environment configuration.
- `backend/app/db`: SQLAlchemy engine setup using psycopg.
- `backend/app/models`: source, tender, document, version and analysis ORM entities.
- `backend/app/ai`: structured output schemas, versioned prompt and OpenAI client.
- `backend/app/schemas`: Pydantic create/read data contracts.
- `backend/app/scrapers`: public listing fetching and source-specific parsing.
- `backend/app/services`: tender ingestion, document storage and PDF extraction.
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
base deletes all five tables and their records:

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
at most 20 releases; cursor/next links are not followed. Tender ingestion makes no
record, detail, or document requests. HTTPX uses a 30-second timeout per operation and no
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

## Tender documents

Document discovery currently supports **Contracts Finder only**, using
`tender.documents[]` in the same bounded 20-release search response. It reuses the
notice UUID for parent identity and skips the canonical HTML notice. There are no
Find a Tender detail requests. Apply migration `0002` and ingest tenders first:

```text
python -m alembic -c backend/alembic.ini upgrade head
python -m app.ingest --source contracts-finder
python -m app.documents --source contracts-finder
```

Set `PYTHONPATH=backend` as above. Missing parents or inactive sources are skipped;
the command never creates placeholder tenders. The two commands fetch independently,
so a moving recent batch may contain notices not ingested by the previous command.
Metadata-only discovery needs no PostgreSQL configuration, downloads no PDF bodies,
and writes no files:

```text
python -m app.documents --source contracts-finder --fetch-only
```

Revision `0002` adds `tender_documents` (source ID, URL, optional title/type/media
type and observation timestamps) and `document_versions` (SHA-256, size, relative
path, download time and extraction result). Document identity prefers the source
document ID within a tender, with URL fallback; both are uniquely constrained.
Conflicting identities fail without merging. Rediscovery advances `last_seen_at`,
preserves `first_seen_at`, and updates provided fields without clearing omitted ones.
Deleting a tender with documents is restricted. Deleting a logical document cascades
to its versions, in both the ORM and database; it does not remove stored files.

Only metadata explicitly marked `application/pdf` on the observed exact hostname
`www.contractsfinder.service.gov.uk` is automatically downloaded. HTTPS, no URL
credentials, and the default port or port 443 are required. All redirects are
rejected, including same-host redirects. External links and other formats remain
metadata only. Requests use HTTPX streaming, an identifiable user agent, a 10-second
connect/30-second operation timeout, no authentication, no environment proxies,
no retries, and no automatic decompression. Responses must have PDF magic bytes and
either `application/pdf` or `application/octet-stream` content type.

Configuration defaults:

| Setting | Default |
| --- | --- |
| `DOCUMENT_STORAGE_DIR` | `.data/documents`, relative to the repository root |
| `DOCUMENT_MAX_BYTES` | `26214400` (25 MiB), checked against headers and streamed bytes |
| `DOCUMENT_MAX_PAGES` | `500`, checked before text extraction |

Files are SHA-256 hashed while streaming to temporary files. After validation they
are atomically placed at `<first-two-hash-characters>/<sha256>.pdf`; source filenames
are never used. Failed downloads clean up partial files. `.data/` is ignored by Git;
if changing the storage directory, keep that location outside tracked source files.
The storage directory is a trusted local application directory, not shared with
untrusted writers.

Metadata commits before network I/O. A short read detects an existing hash; pypdf
extracts only new versions outside transactions. A final short transaction locks
the logical document and rechecks `(document_id, content_hash)` before inserting.
Content A, A, B therefore retains one logical document and two immutable versions;
the service never updates older version rows. Downloads are repeated to detect
changed bytes; HTTP validators and automatic re-extraction are not implemented.
File storage and the database are not one atomic transaction: a later database
failure can leave an unreferenced, complete hash file. There is no automatic cleanup
of complete files because content can be shared by multiple documents.

pypdf extracts page text separated by blank lines and removes NUL characters.
Statuses are `extracted`, `empty` (valid but no extractable text), and `failed`
(malformed/encrypted PDF, page limit or extraction error). Extraction failure
retains the raw file and version with a concise error. Scanned PDFs may be empty;
OCR is not implemented. Byte/page limits do not provide CPU or memory isolation
against every pathological PDF; extraction currently runs in the CLI process.

The summary separates committed metadata outcomes, new versions, unchanged hashes,
extracted/empty results, failures and skips. These counters describe different
stages and should not all be summed. `discovered` counts valid normalized attachment
observations (including repeated releases); malformed release/attachment metadata
adds to `failed`. Skips include missing parents and unsupported download candidates.
Failures return exit code 1; valid work already committed remains committed.

The document JSON fixture preserves real API attachment metadata captured on
2026-09-20 under OGL v3.0, without contacts. These attachments provide no title;
tests separately inject a clearly synthetic title to check optional-field handling.
`tiny_text.pdf` is a locally generated 973-byte, two-page text fixture, not a
downloaded tender. Unit tests use MockTransport and SQLite for domain behavior,
including A/A/B history, deletion, failure retention and transaction boundaries.
Offline PostgreSQL SQL is checked against all model metadata. Live PostgreSQL
migration, processing, locking and concurrent idempotency remain pending while
Docker/PostgreSQL is unavailable.

## Current limitations

Only Find a Tender and Contracts Finder are integrated. There are no CRUD endpoints,
RAG features, workers or frontend. Document processing is manual,
Contracts Finder PDF-only, and bounded to one recent API batch. There is no OCR,
DOCX/Excel/ZIP extraction, scheduling, or cloud document storage.

## Structured tender analysis

Analysis runs manually on a single `DocumentVersion` with `extraction_status=extracted`
and nonblank text. Empty/failed extractions are skipped; missing IDs are errors.
Apply migration `0003`, then set `OPENAI_API_KEY` and `AI_MODEL` in the root `.env`
or environment. The key is a redacted `SecretStr`. AI settings are optional for
normal backend startup and document processing. There is no default model: choose
an account-accessible model supporting Responses structured outputs, preferably
a pinned model snapshot when reproducibility matters.

With `PYTHONPATH=backend`:

```text
python -m alembic -c backend/alembic.ini upgrade head
python -m app.analyze --document-version-id 12 --prepare-only
python -m app.analyze --document-version-id 12
```

Replace `12` with an existing extracted version ID. Prepare-only requires database
access but no AI credentials; it reports character count, hash and truncation,
without provider calls, analysis writes or printing document text. Processing
reports document version ID, status, analysis ID, model and `reused`. Failures return
exit code 1; ineligible extractions return `skipped` with exit code 0.

The small `StructuredLLMClient` protocol has one implementation, using the official
OpenAI Python SDK's [Responses structured parsing](https://developers.openai.com/api/docs/guides/structured-outputs).
It sends only the prepared text and versioned extraction instructions, requests
`store=false`, disables SDK retries and provider-side input truncation, uses a
60-second request timeout and an 8,000-output-token ceiling. No tools are supplied.
The API endpoint is fixed to OpenAI; environment proxies and redirects are disabled.
The SDK's HTTP dependency is separate from the existing source download client.

Prompt version **v1** treats document contents as untrusted data, forbids invented
requirements, qualifications, dates or weights, and preserves uncertainty. Analysis
schema version **v1** rejects extra fields and type coercions. Output fields are:

- `summary`: nullable text, with `summary_evidence` quotations when present.
- `eligibility_requirements`, `required_documents`, `technical_requirements`,
  `financial_requirements`, `submission_instructions`, `risks_or_ambiguities`:
  lists of `{value, evidence}`.
- `evaluation_criteria`: `{criterion, weighting, notes, evidence}` items.
- `important_dates`: `{label, date, notes, evidence}` items; dates retain source wording.
- `contact_information`: `{name, organization, email, phone, role, evidence}` items.

Absent facts use null/empty lists. Evidence is limited to 400 characters per item,
and each quote must occur in a retained input section after whitespace normalization.
Quotes from omitted text or across the truncation gap are rejected. Summary evidence
is limited to ten snippets; other lists to 100 items each. Matching a quote does
**not** verify that it supports the claim or that the extraction is complete.
This is structured extraction, not legal advice. Results require human review;
no model-quality benchmark or accuracy claim is provided.

Input preparation converts CRLF/CR to LF, removes NULs and strips outer whitespace,
preserving internal paragraphs and Unicode. `AI_MAX_INPUT_CHARS` defaults to 60,000
(minimum 128). Longer input keeps equal beginning/end portions, giving the beginning
the extra character when needed, with `\n\n... [TRUNCATED BY TENDERSCOUT] ...\n\n`
between them. The marker counts toward the limit. SHA-256 covers the exact UTF-8
prepared text sent as the user message, including the marker, not the binary hash,
IDs, timestamps or system prompt. This is a character bound, not a token estimate;
model context limits may still reject a request. There is no chunking or retrieval.

`tender_analyses` stores the document-version FK, schema/provider/model/prompt/input
identity, status, raw response, validated fields, optional failure reason and an
aware creation timestamp. Lists use PostgreSQL JSONB with SQLAlchemy JSON for SQLite
domain tests. The six identity fields have one unique constraint, including failed
results. Exact repeats reuse the row without a provider call. Different prompt,
schema, provider, model, prepared text or document version creates a new row; the
service never updates existing analyses. Model aliases may change upstream behavior;
alias drift is not detected when reusing an existing result.

Failures preserve a concise reason without transport messages, headers or secrets.
Structured columns remain SQL NULL on failure. Successful OpenAI responses retain
the normalized parsed JSON separately from structured columns. Invalid output is
retained when returned to the service, bounded to 100,000 characters; SDK-level
parsing errors, refusals and transport failures retain a reason without the provider
body. Failed results are deliberately reused too: no retry/force mode is implemented.
Changing a version label solely to retry is discouraged because labels describe
actual prompt/schema changes. A future retry policy must preserve prior failures.
NULs and invalid Unicode are rejected in validated fields and escaped in raw audit
text so a malformed response cannot break PostgreSQL text/JSONB storage. Bump the
prompt or schema version whenever its instructions or output contract change.

All reads close before the provider call. A short final transaction locks the
document version, rechecks identity and inserts the result. Concurrent callers can
both incur a provider call, but reuse the first committed result; PostgreSQL locking
still needs live verification. Analysis history restricts deleting its document
version, including deletion through a logical document's version cascade.

Tests use a synthetic source/output fixture, a test-only fake client, and the real
SDK with mocked HTTP transport. Prepare-only is exercised against a SQLite fixture;
this does not verify live PostgreSQL. Live PostgreSQL migration/analysis and a real
LLM call remain pending until a database, extracted version and API credentials are
available. No RAG, embeddings or proposal generation is implemented.
Company matching is described below.

## Company profiles and deterministic matching

Apply revision `0004` with `alembic -c backend/alembic.ini upgrade head` from
the repository root. Run these commands with `backend` on `PYTHONPATH`, as above:

```powershell
python -m app.company create --file company.json
python -m app.company show --company-id 1
python -m app.match --company-id 1 --analysis-id 5
```

Import JSON uses the structure in
[`backend/tests/fixtures/company_profile.json`](backend/tests/fixtures/company_profile.json),
which is synthetic test data and is never seeded automatically. `name` is required;
optional business fields default to `null`. Monetary amounts are decimal strings,
currencies are three uppercase letters, dates are ISO `YYYY-MM-DD`, and website
URLs must use HTTP(S) without credentials. Unknown fields, negative quantities,
reversed dates and duplicate capability names (casefolded, normalized whitespace)
are rejected. Imports are bounded to 2 MB and commit the parent and children together.
`show` explicitly prints the profile; `match` prints only IDs, status, score,
coverage, result counts and whether the match was reused. Errors omit input bodies
and database/transport messages.

All four completeness flags default to false: `capabilities_complete`,
`certifications_complete`, `experience_complete`, `financials_complete`.
True means the company asserts that collection/data is complete enough for matching;
it is not independent verification. Missing certification, capability or experience
rows otherwise mean **unknown**, not failure. A missing financial amount or currency
remains unknown even when `financials_complete` is true.

Revision `0004` adds only these tables; revisions `0001`–`0003` remain unchanged:

| Model | Stored fields |
| --- | --- |
| CompanyProfile | ID, name, description, country, website, employee count, annual revenue (`Numeric(18,2)`), currency, years in business, four completeness flags, created/updated timestamps |
| CompanyCapability | ID, company FK, name, normalized name key, optional description, creation timestamp; unique company/name key |
| CompanyCertification | ID, company FK, name, optional issuer/identifier/valid-from/valid-until dates, creation timestamp |
| CompanyExperience | ID, company FK, optional title/client/description/country/contract value/currency/start/end dates, creation timestamp; import requires some identifying text |
| TenderMatch | ID, company/analysis FKs, matcher version, eligibility status, nullable integer score, coverage, company snapshot, blocker/matched/unmatched/unknown/capability/certification/experience/risk JSONB lists, creation timestamp |

Company child collections cascade on deletion. Matches restrict deletion of both
their company and analysis to retain audit history. PostgreSQL timestamp columns
are timezone-aware. JSONB has a JSON variant for SQLite tests. Matches have no
`updated_at`; the service never updates prior matches or analyses. This is service
append-only behavior, not a database trigger preventing privileged manual edits.

The unique match identity is `(company_id, tender_analysis_id, matcher_version)`.
`MATCHER_VERSION = "v1"`; result-affecting rule changes must bump it. An exact repeat
reuses its result; another company, analysis or matcher version creates a new row.
Profiles have a create/show workflow, with no update command: import a new profile
for changed assertions. Direct database edits do not invalidate existing matches.
Each result stores its full company snapshot so old comparisons remain interpretable.
The service closes its read session before comparison, then opens a short insert
transaction, rechecks identity and handles uniqueness conflicts. PostgreSQL race
behavior still needs live verification.

The matcher requires a completed, supported-schema analysis and performs no network
calls. It needs no OpenAI API key and adds no LLM explanation layer. Rules use the
existing tender evidence quotations, preserving them verbatim in every result:

- Certification matching recognizes only obvious ISO numeric families (for example,
  ISO 9001, ISO-9001 and ISO 9001:2015). Explicit mandatory holding requirements can
  match an asserted holding. Missing dates never establish validity. Explicit
  `valid`/`current` requirements need both dates covering the **UTC analysis creation
  date**, not today's date. Expired/not-yet-valid records establish a blocker only
  when the certification inventory is complete. Recheck validity before acting.
- Years compare only simple minimum/at-least experience or in-business clauses
  against known years in business; specialist experience clauses remain unknown.
- Country compares only explicit supplier-establishment clauses. The small v1
  parser recognizes UK/United Kingdom/GB and Pakistan/PK company countries;
  other company-country names remain unknown. Delivery location is never used
  as supplier eligibility. Other country clauses need review.
- Financial rules compare obvious minimum annual turnover with asserted annual
  revenue only in the same currency (GBP/£, USD or EUR). Complex clauses, ambiguous
  currency symbols and missing/different currencies remain unknown. No FX lookup.
- Capability and experience alignment uses lowercase ASCII word tokens, removes
  a small explicit stop-word list and requires at least two remaining requirement
  tokens. At least **60%** must occur in one capability's name/description or one
  experience record's title/description/country/client. Experience is selected by
  the word `experience` in the evidence. This is lexical alignment, not semantic
  equivalence, project quality, successful delivery or proof of compliance.
  Numeric, negative and explicit mandatory technical clauses need stronger rules
  or human review. Unsupported clauses remain unknown.
- Required documents remain unknown because there is no document inventory.
  Holding ISO certification does not prove a certificate file exists. Submission
  instructions and evaluation criteria require manual review; they are not
  inferred from company facts. Analysis ambiguities retain their original evidence.

**Eligibility:** `ineligible` means at least one safely parsed hard requirement
contradicts the asserted company facts (including complete certification absence).
`eligible` means at least one hard requirement exists and every identified hard
requirement matched. Otherwise it is `uncertain`. Unparsed eligibility/financial
clauses, document requirements, submission instructions and unsupported mandatory
technical constraints remain unresolved hard requirements, preventing `eligible`.
This is an assessment against supplied data, not independently verified legal status.
`unmatched` means a supported contradiction or a lexical gap in an asserted complete
list; `unknown` means missing data or an unsupported comparison. Lexical gaps never
become hard blockers.

**Score:** an optional integer heuristic alignment score, **not win probability,
AI confidence or legal eligibility certainty**. Each comparable non-hard item has
equal weight: `round_half_up(100 * matched_non_hard / comparable_non_hard)`.
Unknowns and hard requirements do not enter that denominator; no comparable soft
items means `null`. A blocker can coexist with a score of 100.

**Coverage:** `(matched + unmatched) / all considered requirements`, rounded to
six decimal places, or zero when none exist. Considered items are eligibility,
financial, technical, required-document, submission and evaluation requirements;
summary, dates, contacts and ambiguity notes are excluded. Unknowns lower coverage
without counting as score failures. A sparse profile can score 100 with low coverage;
always inspect coverage, blockers and unknowns together.

Tests exercise strict imports, rules, evidence retention, scores, SQLite CLI flows,
transactions, uniqueness, snapshots and deletion, plus offline PostgreSQL migration
rendering. SQLite is not live PostgreSQL verification. Live migration, matching
idempotency and concurrent insertion verification remain pending when PostgreSQL
is unavailable. Human review is required; matching makes no bid/no-bid decision.
There is no RAG, automatic proposal generation or automated bidding.
