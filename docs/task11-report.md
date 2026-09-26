# Task 11 completion report

Validated on 2026-09-26. This change adds the product API and dashboard without
rewriting the existing domain services or changing the database schema.

## Files and purpose

New backend files:

| File | Purpose |
| --- | --- |
| `backend/app/api/product_support.py` | Shared dependencies, sanitized errors, explicit CORS and 256 KiB request boundary. |
| `backend/app/api/v1/__init__.py` | Versioned API package. |
| `backend/app/api/v1/router.py` | `/api/v1` composition and documented error responses. |
| `backend/app/api/v1/tenders.py` | Tender, document, analysis, revision, change and dashboard read adapters. |
| `backend/app/api/v1/actions.py` | Company, matching and Ask Tender adapters. |
| `backend/app/api/v1/pipeline.py` | Pipeline enqueue and operational read adapters. |
| `backend/app/schemas/product.py` | Explicit bounded request, summary, detail, page and error schemas. |
| `backend/app/services/queries.py` | Column projections, filters, aggregate counts and cursor reads. |
| `backend/app/services/product_actions.py` | Adapt existing action services and domain failures to product outcomes. |
| `backend/tests/test_product_api.py` | 19 API tests using SQLite, ASGI and fake external clients. |

Existing files modified:

| File | Purpose |
| --- | --- |
| `backend/app/main.py` | Register the API, error boundary and OpenAPI metadata; retain health/lifespan. |
| `backend/app/core/config.py` | Validated environment-configured CORS allowlist. |
| `.env.example` | Document JSON CORS origins. |
| `.gitignore` | Exclude Node dependencies, Next build output and TypeScript build cache. |
| `compose.yaml` | Optional product API/frontend services; loopback ports and PostgreSQL dependency. |
| `README.md` | Startup, routes, response policies, UI use, Compose, tests and limitations. |

All frontend files are new:

| Files under `frontend/` | Purpose |
| --- | --- |
| `package.json`, `package-lock.json` | Modest dependency set, repeatable install and validation scripts. |
| `tsconfig.json`, `next-env.d.ts`, `next.config.ts`, `eslint.config.mjs` | Strict TypeScript, App Router, standalone build and Next lint rules. |
| `.env.example`, `.dockerignore`, `Dockerfile` | Browser/server URL separation and non-root container build. |
| `app/layout.tsx`, `app/globals.css` | Professional shared navigation, typography, responsive layout and focus styling. |
| `app/loading.tsx`, `app/error.tsx`, `app/not-found.tsx` | Route loading, retry and missing-resource states. |
| `app/page.tsx` | Actual dashboard counts, deadlines, changes and runs. |
| `app/tenders/page.tsx`, `app/tenders/[id]/page.tsx` | Filtered list and six lazily loaded detail tabs. |
| `app/companies/page.tsx`, `app/companies/new/page.tsx`, `app/companies/[id]/page.tsx` | Profile discovery, creation and recorded company facts. |
| `app/matches/[id]/page.tsx` | Saved deterministic match explanation. |
| `app/changes/[kind]/[id]/page.tsx` | Stored metadata/document comparison and old/new evidence. |
| `app/pipeline/page.tsx`, `app/pipeline/[id]/page.tsx` | Manual trigger, run history and operational detail. |
| `components/ui.tsx`, `components/navigation.tsx` | Shared semantic tables, facts, badges, states, links and navigation. |
| `components/analysis-view.tsx`, `components/document-list.tsx` | Structured facts/provenance and paginated versions. |
| `components/company-form.tsx`, `components/match-form.tsx`, `components/match-view.tsx` | Company input, comparison action and explanation display. |
| `components/ask-form.tsx` | Synchronous version-scoped questions, citations and insufficient-evidence state. |
| `components/pipeline-trigger.tsx`, `components/pipeline-live.tsx` | Enqueue action and five-second polling until terminal. |
| `lib/api.ts`, `lib/types.ts`, `lib/format.ts` | Central typed API client, focused response types and UTC date formatting. |
| `scripts/smoke.mjs` | Production SSR smoke checks against a synthetic test-only HTTP API. |

This report is the only additional documentation file. Existing migrations,
scrapers, provider clients, matching, RAG and pipeline orchestration are unchanged.

## API and UI completion checklist

| Requested item | Result |
| --- | --- |
| 1. Backend files created | Listed above: versioned adapters, schemas, queries, action bridge and tests. |
| 2. Backend files modified | Only `main.py` and `core/config.py`; root configuration/documentation changes listed above. |
| 3. API routes | 20 versioned path templates, including GET/POST companies and pipeline runs. Complete method/path table in the [README](../README.md#routes-and-contracts); `/health` retained. |
| 4. Schemas | Explicit summary/detail models with `extra="forbid"`, bounded lists, nullable unknown facts, validated analysis output and documented error envelope. Company input is the existing strict schema. |
| 5. Pagination | Descending ID, default 20/max 100, `{items,next_cursor}`. Stages preserve ascending `after_stage_id`, max 100. Nested document versions initially return five and have a continuation route. |
| 6. Errors | `{error:{code,message}}`; deliberate 400/404/409/413/422/500/502/503 mapping. No SQL/provider details in errors. Insufficient evidence is HTTP 200. |
| 7. Read architecture | Focused SQL projections and aggregates; grouped document-version query. No heavy repository framework. No PDF text, vectors or raw provider bodies in normal reads. Tender-list test confirms one SQL statement. |
| 8. CORS | Exact JSON-array origins, no wildcards or credentials; default localhost:3000. Rejected preflights also use the error envelope. |
| 9. Tenders | Source/search/organization/category/deadline API filters; UI search/source/deadline filter. Detail includes current metadata and bounded related summaries; tabs fetch their own larger contents. |
| 10. Analysis | Validated structured facts and preserved evidence. Latest supported completed analysis returns 404 if absent; failed/unsupported direct reads have null facts. |
| 11. Companies | List/create/detail; strict decimal/date JSON behavior reused from CLI. UI covers nested facts and completeness declarations, labeled company-provided. |
| 12. Matches | POST reuses deterministic service. GET reads persisted explanation. Heuristic alignment, coverage, blockers, matched/unmatched/unknown requirements and source evidence remain separate. |
| 13. Ask Tender | Existing synchronous Q&A; complete current index required. Exact version/chunk citations preserved. Configuration, index, provider, validation and insufficient-evidence outcomes distinguished. |
| 14. Revisions/changes | Bounded histories and saved metadata/document changes. Comparison IDs, category counts, old/new values and evidence retained. No recomputation/materiality score. |
| 15. Pipeline | POST returns 202, accepts only the two known sources, never performs eager scraping inline. Bounded run/stage reads; no maintenance endpoint. |
| 16. Dashboard summary | SQL counts and up to five upcoming deadlines, changes and runs. Upcoming means a known deadline has not passed, not verified open status. |
| 17. Frontend stack | Next.js 16.3.5 App Router, React 19.3.0, TypeScript, ESLint; no UI framework or extra runtime dependency. |
| 18. Pages | `/`, `/tenders`, `/tenders/[id]`, `/companies`, `/companies/new`, `/companies/[id]`, `/matches/[id]`, `/changes/[kind]/[id]`, `/pipeline`, `/pipeline/[id]`. |
| 19. Components | Listed above: tables/states, evidence, forms, versions and polling. Read pages are Server Components; actions use Client Components. |
| 20. API client | Central base URL and structured errors; public browser URL with optional server-only internal URL. No scattered fetch endpoints. |
| 21. UI states | Shared route loading/error/missing states; per-page empty/API errors; pending actions; insufficient evidence displayed as a valid result. No fallback fake data. |
| 22. Accessibility | Labels, semantic tables/headings, skip link, visible focus, text statuses and reduced-motion CSS. Responsive breakpoints and deliberate table scrolling. Full browser/assistive-technology audit pending. |
| 23. Compose | Optional `product` API/frontend. API depends on healthy PostgreSQL only; worker/Beat remain independent. Explicit migrations; non-root frontend image. Configuration validated; containers not built/run. |
| 24. Migration status | Head **0007**. All seven migration files compared against HEAD and unchanged. No new migration. |
| 25. Backend tests added | 19 tests cover reads, filters, pagination, errors, sanitized projections, strict company creation, matching, Q&A outcomes/reuse/citations, changes, pipeline, CORS, health and OpenAPI. |
| 26. Backend results | **352 tests passed**. Ruff check passed; all 124 Python files formatted; `pip check` reports no broken requirements. App import, `/health` and API requests pass in ASGI tests. |
| 27. Frontend results | Installation completed; ESLint, TypeScript and production build passed. **15 production SSR smoke checks passed** for main pages, tender tabs and API error states. |
| 28. PostgreSQL live-tested? | **No.** Local port 5432 unavailable. SQLite tests do not establish PostgreSQL execution, locking or query performance. |
| 29. API ran live? | **No external FastAPI server.** Actual app exercised in-process through TestClient/ASGI with SQLite. The frontend smoke API is synthetic, not a live backend substitute. |
| 30. Frontend ran live? | **Yes, a production Next server on loopback during smoke testing**, then stopped. No browser interaction/hydration test or real-backend end-to-end claim. |
| 31. Real provider calls? | **None.** Tests use fake providers; no real source fetch, embedding, answer or Redis delivery was triggered. Package/documentation access is separate. |
| 32. Unverified | Live PostgreSQL/API integration, Redis/worker/Beat, Docker image startup, provider calls, browser forms/hydration, mobile visual behavior and full end-to-end product flow. Docker daemon and Redis localhost:6379 unavailable. |
| 33. Limitations | No auth/tenant boundaries. Substring search only. Bounded previews and cursor navigation. Synchronous Q&A may time out without cancelling server work. Current embedding configuration determines readiness. Company facts are assertions; matching is heuristic; exact citations do not establish semantic correctness. |

See the [startup and operating instructions](../README.md#product-api-and-dashboard-task-11)
for environment variables, commands and the 150-second Ask Tender timeout expectation.
