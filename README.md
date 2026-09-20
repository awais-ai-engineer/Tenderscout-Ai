# TenderScout AI

TenderScout AI is intended to help teams discover and evaluate public tenders.
This first increment contains only the backend foundation: FastAPI, environment
configuration, PostgreSQL engine setup, and Redis connection settings.

## Structure

- `backend/app/api`: HTTP routes.
- `backend/app/core`: environment configuration.
- `backend/app/db`: SQLAlchemy engine setup using psycopg.
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

## Current limitations

No tender sources are supported yet. There are no database tables or migrations,
scrapers, AI/RAG features, workers, frontend, or tender matching. Alembic migrations
will accompany the first database schema change.
