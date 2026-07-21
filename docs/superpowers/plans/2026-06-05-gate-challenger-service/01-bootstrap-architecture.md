# Bootstrap and Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the repository skeleton, local runtime, shared contracts, and service boundaries for the MVP.

**Architecture:** Use a small monorepo with separate frontend, backend, worker, contracts, and infrastructure folders. Keep business logic in the backend and worker; the frontend consumes typed API contracts and never talks directly to providers or storage.

**Tech Stack:** Next.js, TypeScript, FastAPI, Python 3.12, PostgreSQL, Redis, Docker Compose, Alembic, pytest.

---

## Files

- Create: `apps/web/` - Next.js frontend.
- Create: `apps/api/` - FastAPI backend.
- Create: `apps/worker/` - background worker entrypoint and job handlers.
- Create: `apps/api/app/` - backend application package.
- Create: `apps/api/app/core/config.py` - environment settings.
- Create: `apps/api/app/main.py` - FastAPI app factory.
- Create: `apps/api/app/db/session.py` - database session.
- Create: `apps/api/app/db/base.py` - model metadata import surface.
- Create: `apps/api/alembic/` - migrations.
- Create: `contracts/schemas/` - JSON schemas for AI outputs and benchmark judge outputs.
- Create: `infra/docker-compose.yml` - local PostgreSQL, Redis, API, worker, web.
- Create: `.env.example` - non-secret configuration template.
- Create: `README.md` - local setup and MVP overview.

## Service Boundaries

### Frontend

Responsibilities:

- login flow;
- document upload and document history;
- result rendering;
- etalon and benchmark pages;
- settings and admin pages.

Non-responsibilities:

- provider API calls;
- raw file path construction;
- authorization decisions;
- benchmark scoring.

### Backend API

Responsibilities:

- auth and sessions;
- role and ownership authorization;
- CRUD for users, documents, analyses, skills, etalons, benchmarks, feedback;
- file upload orchestration;
- job enqueueing;
- API key encryption and provider test endpoints.

Non-responsibilities:

- long-running AI calls;
- benchmark execution loops;
- parsing large files inside request handlers.

### Worker

Responsibilities:

- document parsing jobs;
- main analysis jobs;
- predicted-comments jobs;
- benchmark jobs;
- JSON repair and schema validation;
- token/cost metadata capture.

Non-responsibilities:

- serving HTTP routes;
- UI formatting;
- direct user session handling.

## Environment Variables

Use these in `.env.example`:

```dotenv
APP_ENV=development
APP_SECRET_KEY=replace-with-32-byte-random-value
DATABASE_URL=postgresql+psycopg://gate:gate@postgres:5432/gate
REDIS_URL=redis://redis:6379/0
STORAGE_ROOT=/var/lib/gate-challenger/storage
PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
HERMES_ENABLED=false
HERMES_MODE=http
HERMES_HTTP_URL=http://127.0.0.1:8787
```

`APP_SECRET_KEY` is mandatory. It is used for session signing and encryption key derivation. The value must not be committed.

## Tasks

### Task 1: Create Monorepo Skeleton

- [ ] Create the folders listed in the Files section.
- [ ] Add `.gitignore` entries for `.env`, Python caches, Node build outputs, local storage, and test artifacts.
- [ ] Add `.env.example` with the variables above.
- [ ] Add `README.md` with local setup commands:

```bash
docker compose -f infra/docker-compose.yml up --build
```

Acceptance:

- repository has stable module folders;
- no runtime secret is committed;
- a new engineer can identify where web, API, worker, contracts, and infra live.

### Task 2: Scaffold Backend API

- [ ] Create `apps/api/pyproject.toml` with dependencies:

```toml
[project]
name = "gate-challenger-api"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi",
  "uvicorn[standard]",
  "pydantic-settings",
  "sqlalchemy",
  "psycopg[binary]",
  "alembic",
  "passlib[argon2]",
  "python-multipart",
  "cryptography",
  "redis",
  "rq",
  "python-docx",
  "pypdf",
  "anthropic",
  "openai",
]
```

- [ ] Create `apps/api/app/main.py` with `/health` route returning `{"status": "ok"}`.
- [ ] Create `apps/api/app/core/config.py` using Pydantic settings and the environment variables above.
- [ ] Create `apps/api/app/db/session.py` with SQLAlchemy engine and session factory.
- [ ] Add pytest test `apps/api/tests/test_health.py` that calls `/health`.

Acceptance:

- `pytest apps/api/tests/test_health.py` passes;
- `uvicorn app.main:app` starts from `apps/api`.

### Task 3: Scaffold Worker

- [ ] Create `apps/worker/pyproject.toml` reusing backend dependencies through the API package path.
- [ ] Create `apps/worker/worker.py` that starts an RQ worker for queues `documents`, `analysis`, `benchmark`.
- [ ] Create `apps/worker/jobs/health.py` with a job returning `{"status": "ok"}`.
- [ ] Add a smoke test that enqueues the health job against local Redis in integration test mode.

Acceptance:

- worker starts without importing frontend code;
- worker can execute a simple job.

### Task 4: Scaffold Frontend

- [ ] Create `apps/web` as a Next.js TypeScript app.
- [ ] Add routes for `/login`, `/documents`, `/documents/upload`, `/benchmarks`, `/etalons`, `/settings`, `/admin`.
- [ ] Add an API client wrapper reading `NEXT_PUBLIC_API_BASE_URL`.
- [ ] Add a simple unauthenticated health check page that displays API `/health`.

Acceptance:

- `npm run dev` starts the frontend;
- health page confirms backend connectivity in local dev.

### Task 5: Add Shared Contracts

- [ ] Create `contracts/schemas/main-analysis-result.schema.json`.
- [ ] Create `contracts/schemas/predicted-comments-result.schema.json`.
- [ ] Create `contracts/schemas/devils-advocate-result.schema.json`.
- [ ] Create `contracts/schemas/devils-advocate-query-result.schema.json`.
- [ ] Create `contracts/schemas/benchmark-judge-result.schema.json`.
- [ ] Add schema validation tests in the backend using representative valid and invalid examples.

Acceptance:

- schemas encode the result structures from sections 8 and 9 of the source spec;
- `devils-advocate-result.schema.json` encodes the default full `ic-voting-prompt.md` run: run mode, anchored comment records, four-section trailer, IC decision block, predicted committee questions, consulted wiki pages, and source citations;
- `devils-advocate-query-result.schema.json` encodes the optional `/ic:query` grounded query / pattern-check output for lightweight diagnostics, not the default product result;
- worker and API tests use the same schema files.

## Verification

Run:

```bash
pytest apps/api/tests -q
docker compose -f infra/docker-compose.yml config
```

Expected:

- tests pass;
- Docker Compose config renders without missing variables.
