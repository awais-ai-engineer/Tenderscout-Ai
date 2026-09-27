# Task 12 validation report

Baseline: `696d14bee5f5d3b2d4b5cc57f9c74d1d5ce239ae`
(`fix: finalize task 11 product review`). The working tree was clean on entry.
Validation date: 2026-09-27, Windows, Python 3.12, Node 24.

Statuses: **VERIFIED** means the stated check actually ran; **FAILED** means an
executed check failed its expectation; **BLOCKED** identifies an unavailable
dependency; **NOT RUN** means no execution is claimed. A skipped test is not passed.

## Changes

- Created `.github/workflows/ci.yml`: separate backend, frontend and PostgreSQL
  jobs on main pushes/PRs and manual dispatch; read-only permissions, pinned
  actions, Python 3.12/Node 24 and simple dependency caches. No provider secrets or
  public-source scraping in CI.
- Created `backend/integration/test_postgresql.py`: five opt-in PostgreSQL checks
  using an explicitly named disposable test database. Normal fixtures roll back;
  the row-lock check removes only the test row it committed. No schema drops.
- Modified `.dockerignore`: exclude integration tests from the backend image and
  explicitly exclude nested backend dotenv files as well as the already excluded
  root secrets. No actual leaked build credential was found.
- Modified `README.md`: current capabilities/stack and links, actual architecture,
  integration/CI commands, concise deployment responsibilities, and the confirmed
  ten-field metadata wording correction.
- Created this report. No application runtime code, dependency versions, visual
  design, storage identity or migration changed.
- Local only: created the missing ignored root `.env` from the example with a
  cryptographically generated development PostgreSQL password. No provider key or
  live-provider opt-in was added. It is not a tracked deliverable.

## Baseline and final automated evidence

Before editing, the existing **353 backend tests passed**; Ruff check and format
check passed (124 files); `pip check` found no broken requirements; Alembic heads
reported `0007`. Frontend lint, typecheck/type generation and production build
passed; all **15 SSR smoke checks passed**.

Final automated results are recorded below. GitHub Actions run #1 on commit
`10c4e0748d2da1b182d1711a4a60557819f13d98` completed with overall success;
backend, frontend and PostgreSQL jobs each succeeded. Hosted PostgreSQL results
are separate from the blocked local PostgreSQL/Docker checks.

| Required report item | Status and evidence |
| --- | --- |
| 1. Baseline commit | **VERIFIED** — full hash above; clean entry state. |
| 2. Files created | **VERIFIED** — CI workflow, PostgreSQL integration module, this report. |
| 3. Files modified | **VERIFIED** — README and root Docker ignore rules only. |
| 4. Bugs discovered | **VERIFIED** — README said eleven business fields; `BUSINESS_FIELDS` contains ten. Nested backend dotenv exclusions were not explicit. No runtime regression demonstrated. |
| 5. Bugs fixed | **VERIFIED** — corrected the field count; tightened build context exclusions. Existing Task 11 fixes remain intact. |
| 6. Migration head | **VERIFIED** — repository head `0007`; hosted CI upgraded its PostgreSQL service to `0007` (head). Local database head remains **BLOCKED**. |
| 7. Migration files changed? | **VERIFIED** — all seven migration files compared with baseline, unchanged. No 0008. |
| 8. Backend unit tests | **VERIFIED** ? final full suite: **353 passed**, no skips (99.526 seconds). |
| 9. PostgreSQL integration tests | **VERIFIED in GitHub CI** — all **5 passed** against `pgvector/pgvector:pg17`. **BLOCKED locally** — PostgreSQL unavailable; local discovery explicitly skipped all five without opt-in. |
| 10. Ruff | **VERIFIED** ? full backend lint passed; all **125** Python files passed format checking. |
| 11. pip check | **VERIFIED** ? no broken requirements found. |
| 12. Frontend lint | **VERIFIED** ? `npm ci` followed by `npm run lint` passed. |
| 13. Frontend typecheck | **VERIFIED** ? `npm run typecheck`, including `next typegen`, passed. |
| 14. Frontend production build | **VERIFIED** ? `npm run build` completed with Next.js 16.3.5. |
| 15. SSR smoke | **VERIFIED** ? final **15 passed**, production Next server with isolated synthetic HTTP API; not browser interaction. |
| 16. Docker daemon | **BLOCKED** — `docker info` could not connect: `dockerDesktopLinuxEngine` named pipe does not exist (system cannot find the file specified). |
| 17. PostgreSQL live validation | **VERIFIED in GitHub CI** — Alembic upgrade to `0007` and all five integration tests passed on the pgvector PostgreSQL service. **BLOCKED locally** — localhost:5432 not reachable; no local migration or database execution claimed. |
| 18. Redis live validation | **BLOCKED** — localhost:6379 not reachable; no PING or broker delivery claimed. |
| 19. Celery worker live result | **BLOCKED** — no Redis/PostgreSQL; no worker started or durable transitions observed. |
| 20. Beat live result | **BLOCKED** — no broker; no scheduler started. |
| 21. API live result | **VERIFIED, limited** — actual Uvicorn server on loopback: health/docs schema, CORS, errors and request limits checked below. Database-backed reads return 503, so successful product reads remain **BLOCKED**. |
| 22. Frontend live result | **VERIFIED** only for the production server in synthetic SSR smoke. **BLOCKED** for a separate real-API SSR run: automatic approval review rejected starting Next on loopback port 3000 with ?blocked by policy.? No successful database-backed view claimed. |
| 23. Browser interactions | **BLOCKED** — browser inventory failed to start `codex app-server`: required path missing, OS error 3. No browser tab, hydration, forms, console, narrow-layout or keyboard check claimed; no screenshot fabricated. |
| 24. Find a Tender live result | **VERIFIED, fetch-only** — robots 404, listing 200; discovered **20**, valid **3**, failed **0**, skipped **17**. No persistence. |
| 25. Contracts Finder live result | **VERIFIED, fetch-only** — existing OCDS endpoint returned 200 with bounded limit 20; discovered **20**, valid **20**, failed **0**, skipped **0**. No persistence. |
| 26. Document download live result | **BLOCKED** — no actually ingested PostgreSQL tender to process. No new live PDF download attempted; previous 403 reports are not presented as a new observation. Existing controlled PDF tests ran in the unit suite. |
| 27. Real provider test | **NOT RUN** — no configured key and no `TENDERSCOUT_RUN_LIVE_PROVIDER_TESTS=1`. |
| 28. Real structured analysis | **NOT RUN** — provider opt-in absent. |
| 29. Real embeddings | **NOT RUN** — provider opt-in absent. Synthetic vectors in tests do not validate a provider. |
| 30. Real Ask Tender | **NOT RUN** — provider opt-in absent. Unit tests exercise exact citation validation with fake clients. |
| 31. GitHub Actions files | **VERIFIED** — `.github/workflows/ci.yml` added with backend/frontend/PostgreSQL jobs; pgvector-capable PostgreSQL 17 service, test-only credentials and migrations from base. |
| 32. Local CI-equivalent validation | **VERIFIED** ? backend/frontend commands above and workflow syntax via **actionlint v1.7.12** (shellcheck integration disabled; unavailable). Action SHAs were resolved from official action repositories. PostgreSQL job remains **BLOCKED** locally. |
| 33. GitHub-hosted CI | **VERIFIED** — run #1 on commit `10c4e0748d2da1b182d1711a4a60557819f13d98` concluded success. Backend, frontend and PostgreSQL jobs succeeded: 353 backend tests, Ruff check/format, pip check, Alembic upgrade to `0007`, five PostgreSQL integration tests, and frontend lint/typecheck/build/smoke. No badge added. |
| 34. Security/privacy audit | **VERIFIED, scoped** — findings below. No real credential found; no history rewrite needed. This is not an independent security certification. |
| 35. Benchmarks | **NOT RUN — not measured.** No working PostgreSQL dataset; no performance numbers invented. |
| 36. Docker image builds | **BLOCKED** — daemon unavailable. Dockerfile inspection confirms non-root users, but is not an image-build result. |
| 37. Compose runtime | **BLOCKED** — daemon unavailable. `docker compose --profile product --profile pipeline config --quiet` succeeded; that validates configuration only. |
| 38. End-to-end walkthrough | **BLOCKED** — no PostgreSQL/Redis and no browser runtime. Source fetches, API failure handling and synthetic SSR checks do not establish an end-to-end pipeline. |
| 39. Remaining unverified | Local PostgreSQL/Docker/Compose execution, persistent source/document idempotency, Redis delivery/worker/Beat, successful real-data API/UI flows, browser interactions, project Docker image builds/volumes and opted-in AI execution. Hosted migrations and the five PostgreSQL integration tests are verified separately. |
| 40. Known limitations | No auth/multi-tenancy; CORS is not access control. Synchronous Q&A, non-transactional DB-to-broker publication, no exactly-once claim, provider/source availability restrictions, heuristic matching and company assertions remain documented. |

## Actual API checks

With Uvicorn running against the configured but unavailable PostgreSQL endpoint:

| Request | Observed result |
| --- | --- |
| `/health` | 200 |
| `/openapi.json` | 200 |
| `/api/v1/dashboard/summary`, `/tenders`, `/companies`, `/pipeline/runs` | Each returned 503 `database_unavailable` (all product paths prefixed `/api/v1`). |
| `/api/v1/tenders?limit=101` | 422 `invalid_request` |
| Unknown product route | 404 `not_found` |
| Configured-origin POST preflight | 200 and matching allow-origin header |
| Untrusted-origin POST preflight | 400, no allow-origin header |
| 262,145-byte invalid company body | 422 `invalid_request`, reached validation |
| 8,388,609-byte body | 413 `request_too_large` |

These checks establish transport/error behavior, not successful PostgreSQL reads.
The existing API tests cover bounded payloads and omission of storage paths, PDF
text, vectors and raw provider bodies from SQLite-backed product responses.

Source commands were the existing `python -m app.ingest --source <slug> --fetch-only`
for each supported slug. Fetches used existing adapters, timeouts, bounds and access
rules; no bypass was used. Created/changed/unchanged counts are **NOT RUN**, not zero,
because no database ingestion took place. No real source history was created or deleted.

## Security and operational audit

- Scanned **253 unique reachable history blobs** for provider/GitHub token, private
  key and credential-bearing database/broker URL patterns: no matches. Inspected
  tracked env/config files; examples use placeholders, tests use explicit test
  values. No non-example `.env` is tracked. This pattern scan cannot prove absence
  of every possible secret.
- Settings repr and JSON serialization were checked against the configured secret
  without printing it. The local `.env` is ignored. No private absolute filesystem
  path pattern was found in tracked code/docs. Public Next variables contain only
  a browser-visible local API URL, not credentials.
- Backend build context excludes root secrets by allowlist; nested backend dotenv
  files and new integration tests are now excluded explicitly. Frontend context
  excludes `.env*` except the placeholder example. Actual Docker context/build
  behavior still needs a working daemon.
- Reviewed response projections and domain wording: user-provided company facts,
  heuristic alignment (with explicit denial of win probability), source evidence,
  and non-materiality change descriptions remain intact. No chain-of-thought,
  embeddings or raw provider response is added to the public contract.
- Tests use fake providers and mocked source transports; the new integration suite
  accesses only its configured PostgreSQL instance. Live source CLI checks were
  separate from tests. No real provider call or automatic pipeline trigger occurred.
- Hosted CI success is recorded for run #1 only. No hosted deployment, accuracy
  improvement, win-rate improvement, production performance or uptime claim is made.

The changes are suitable for final human code/documentation review, with the blocked
integration items as explicit release gates. They do not establish a fully validated
deployment or completed live product walkthrough.
