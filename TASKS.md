# Project Tasks

This file is the living execution tracker for Gate Challenger Service. Keep it
short enough to scan, and use the detailed Superpowers plan files for module
implementation steps.

Primary plan index:

- `docs/superpowers/plans/2026-06-05-gate-challenger-service/00-plan-index.md`

## Task Rules

- Use checkbox status: `[ ]` not started, `[~]` in progress, `[x]` done,
  `[!]` blocked.
- Keep active work near the top of the relevant phase.
- Link detailed work to the matching plan file instead of duplicating every
  subtask here.
- Update this file when scope, status, or verification changes.
- Before decisions, search GBrain with the `gate-challenger-service` prefix.
- After meaningful milestones, save a concise GBrain note if GBrain is
  available.

## Current Focus

- [x] Create root `AGENTS.md` with project, workflow, security, and GBrain
  instructions.
- [x] Create root `TASKS.md` aligned with the MVP phase plan.
- [x] Document the GBrain/PGLite sandbox rule: use GBrain MCP when available or
  run GBrain CLI with escalated filesystem access from Codex; do not delete lock
  files before verifying the lock holder.
- [x] Finish full Phase 1 Docker Compose runtime verification using verified
  public mirror image defaults.
- [x] Verify frontend package install, tests, production build, and critical
  npm audit threshold.
- [x] Verify Phase 1 API login/admin/ownership smoke and Alembic
  upgrade/downgrade in a local backend venv.
- [x] Implement Phase 2 backend document upload slice: supported file upload,
  local raw storage, queued document rows, and user/admin ownership visibility.
- [x] Implement Phase 2 backend parser/job slice: `.txt`, `.md`, `.docx`, and
  `.pdf` parsers, parsed artifact storage, deterministic type detection, parse
  status updates, and upload enqueue wiring.
- [x] Implement document detail API/UI slice plus Phase 3 main-analysis MVP:
  parsed/raw/reparse endpoints, manual type override, provider key settings,
  skill list, analysis launch/detail, worker main-analysis job, provider
  adapters, and feedback capture.
- [x] Complete Phase 3 second-stage runtime: Gate2/Devil's Advocate prompt
  renderers, Devil's Advocate predicted-comments worker job, reproducible
  second-stage run metadata, API detail embedding, and result UI block.
- [x] Close Phase 3 skill admin/runtime hardening: admin skill create, archive,
  patch, source refresh, schema/source validation, provider key test endpoint,
  and worker skill-source availability checks.

## Phase 1: Skeleton And Data Foundation

Source plans:

- `docs/superpowers/plans/2026-06-05-gate-challenger-service/01-bootstrap-architecture.md`
- `docs/superpowers/plans/2026-06-05-gate-challenger-service/02-data-model-rbac.md`
- `docs/superpowers/plans/2026-06-05-gate-challenger-service/03-auth-admin-users.md`

Tasks:

- [x] Create monorepo skeleton: `apps/web`, `apps/api`, `apps/worker`,
  `contracts/schemas`, and `infra`.
- [x] Add `.gitignore`, `.env.example`, and root `README.md`.
- [x] Scaffold FastAPI `/health`, settings, DB session, and health test.
- [x] Scaffold worker queues and worker health job.
- [x] Scaffold Next.js TypeScript app and initial authenticated route structure.
- [x] Add initial shared JSON schema contracts.
- [x] Implement database schema, enums, migrations, and RBAC ownership rules.
- [x] Implement auth, sessions, and admin-created users.

Exit criteria:

- [x] Local Docker Compose config renders.
- [x] Database migrations run cleanly in local SQLite smoke verification.
- [x] Admin can create a user in local API smoke verification.
- [x] User can log in and access authenticated API state in local smoke
  verification.
- [x] Tests cover auth and role checks.
- [x] Frontend `/login`, `/documents`, `/admin/users`, and `/health` build and
  test successfully.
- [x] Ownership policy assertions pass in a direct Python check independent of
  unavailable backend dependencies.
- [x] Full Docker Compose stack starts with PostgreSQL, Redis, API, worker, and
  web containers.

## Phase 2: Document Workflow

Source plans:

- `docs/superpowers/plans/2026-06-05-gate-challenger-service/04-documents-parsing-storage.md`
- Document workflow portions of
  `docs/superpowers/plans/2026-06-05-gate-challenger-service/09-frontend-ui.md`

Tasks:

- [x] Implement document upload for `.docx`, `.pdf`, `.md`, and `.txt`.
- [x] Store raw files under local MVP storage with database ownership checks.
- [x] Parse and persist document text.
- [x] Detect document type and support manual override.
- [x] Show document history and document detail pages.
- [x] Enforce user/admin document visibility.

Exit criteria:

- [x] Authenticated user uploads supported files.
- [x] Raw file and parsed text are persisted.
- [x] Document type can be manually overridden.
- [x] User sees own documents; admin sees all documents.

## Phase 3: AI Analysis Runtime

Source plans:

- `docs/superpowers/plans/2026-06-05-gate-challenger-service/05-skills-providers-secrets.md`
- `docs/superpowers/plans/2026-06-05-gate-challenger-service/06-analysis-worker-results-feedback.md`
- Analysis UI portions of
  `docs/superpowers/plans/2026-06-05-gate-challenger-service/09-frontend-ui.md`

Tasks:

- [x] Implement encrypted provider key storage and masked settings API.
- [x] Implement provider adapters for OpenAI-compatible, Anthropic-compatible,
  and Hermes modes.
- [x] Implement versioned skill registry and source snapshotting.
- [x] Render Gate2-challenger and Devil's Advocate prompts into normalized
  schema contracts.
- [x] Enqueue and execute analysis jobs in workers.
- [x] Persist structured output, raw output, run parameters, cost/token metadata,
  and errors.
- [x] Add analysis result UI and feedback flow.

Exit criteria:

- [x] User can save an encrypted provider key.
- [x] User can launch an analysis.
- [x] Worker persists structured and raw outputs.
- [x] Predicted-comments or Devil's Advocate second stage runs after main
  analysis.
- [x] User can leave feedback.

## Phase 4: Etalons And Benchmarks

Source plans:

- `docs/superpowers/plans/2026-06-05-gate-challenger-service/07-etalons-annotation.md`
- `docs/superpowers/plans/2026-06-05-gate-challenger-service/08-benchmark-engine.md`
- Etalon and benchmark UI portions of
  `docs/superpowers/plans/2026-06-05-gate-challenger-service/09-frontend-ui.md`

Tasks:

- [ ] Create etalon drafts from analysis results.
- [ ] Implement admin etalon review and activation.
- [ ] Implement benchmark runs over active etalons.
- [ ] Persist judge output, aggregate metrics, misses, false positives, and
  partial matches.
- [ ] Add etalon and benchmark UI.

Exit criteria:

- [ ] User creates etalon draft from analysis.
- [ ] Admin can activate etalon.
- [ ] Benchmark runs over active etalons.
- [ ] Benchmark persists precision, recall, F1, missed findings, false
  positives, and partial matches.

## Phase 5: Admin, Audit, Hardening

Source plans:

- `docs/superpowers/plans/2026-06-05-gate-challenger-service/10-admin-observability-testing.md`
- Remaining admin portions of
  `docs/superpowers/plans/2026-06-05-gate-challenger-service/09-frontend-ui.md`

Tasks:

- [ ] Implement admin views for users, documents, analyses, skills, etalons,
  benchmarks, and feedback.
- [ ] Add audit log service and required audit events.
- [ ] Add structured API and worker logging with request/job IDs.
- [ ] Add reproducibility contract tests for analyses and benchmarks.
- [ ] Create `docs/acceptance/mvp-checklist.md`.
- [ ] Add one root-level `test` command or Makefile target.
- [ ] Run the full MVP acceptance suite.

Exit criteria:

- [ ] Admin sections cover all MVP operational entities.
- [ ] Audit log records sensitive actions without secrets.
- [ ] Reproducibility metadata is covered by automated tests.
- [ ] MVP checklist maps each acceptance criterion to a verification method.

## Out Of MVP

- Full annotator queue automation.
- Scheduled and bulk benchmarks.
- PPTX and Google Docs/Slides import.
- Organization-level shared provider keys.
- Complex team workspaces.
- UI comments inside documents.
- Etalon version diff UI.

## Decision Log

- 2026-06-07: Added root agent and task workflow documents. GBrain is treated as
  development memory only and must not become an application dependency.
- 2026-06-07: Confirmed GBrain itself works when run with escalated filesystem
  access. The earlier `Timed out waiting for PGLite lock` from Codex sandbox was
  a misleading symptom of restricted access to `~/.gbrain/brain.pglite`, with
  live `gbrain serve` as a normal lock holder.
- 2026-06-07: Implemented Phase 1 scaffold, initial schema migration, RBAC
  ownership helpers, cookie session auth, admin user management, bootstrap admin
  seed, baseline skill seed helper, and minimal Next.js authenticated routes.
  Runtime verification is blocked by DNS failures to PyPI, GitHub release
  assets, and npm package installation; Docker daemon setup also depends on
  Colima image download.
- 2026-06-07: Frontend dependencies installed using project-local npm cache.
  `npm --prefix apps/web run test`, `npm --prefix apps/web run build`, and
  `npm --prefix apps/web audit --audit-level=critical` pass after updating
  Vitest to 4.1.8. Two moderate Next/PostCSS advisories remain with only a
  breaking `npm audit fix --force` path reported by npm audit.
- 2026-06-07: Reconfirmed backend runtime blockers. `curl` resolves
  `registry.npmjs.org`, but resolving `files.pythonhosted.org` and
  `release-assets.githubusercontent.com` times out; `pip` and `uv pip` cannot
  install backend dependencies, and Colima cannot download its VM image.
- 2026-06-07: Built a local `.venv-backend` using system-site packages,
  cached FastAPI/Starlette, and GitHub source installs for SQLAlchemy, Mako,
  and Alembic. Verified backend imports, password hashing fallback, Alembic
  `upgrade head` and `downgrade base` against SQLite, and a FastAPI TestClient
  smoke covering `/health`, admin login, `/auth/me`, admin user creation/list,
  non-admin 403, blocked user login denial, ownership policies, and worker
  health job. Docker daemon remains unavailable, so full Compose stack with
  PostgreSQL/Redis is still not verified.
- 2026-06-07: Retried Docker Desktop after the daemon became available.
  `docker ps` succeeds and Compose config renders. Full Compose startup remains
  blocked by external DNS failures to Docker Hub (`registry-1.docker.io`) for
  `postgres:16-alpine`/`redis:7-alpine`. Cached-image fallbacks were checked:
  Supabase PostgreSQL and Studio/Node images are present, but no Redis image is
  available, and the cached Python image lacks `pydantic-settings`, `psycopg`,
  `redis`, `rq`, and `passlib`. Installing those or Redis from PyPI/Alpine is
  also blocked by DNS failures to `files.pythonhosted.org` and Alpine package
  repositories.
- 2026-06-07: Found a working registry path through `mirror.gcr.io` for official
  PostgreSQL, Redis, Python, and Node images. Updated Compose defaults and
  `.env.example` to use that public mirror while preserving env overrides.
  Regenerated the web `package-lock.json` in a Linux Node container so Docker
  `npm ci` includes Linux optional dependency entries. Verified full Compose
  stack startup, PostgreSQL Alembic `upgrade head`, bootstrap admin seed, API
  `/health`, admin login with HTTP-only cookie, `/auth/me`, admin user create
  and list, non-admin `403` on admin users, blocked-user login denial,
  ownership policy assertions inside the API image, RQ worker health job
  execution through Redis, and web `/login` plus `/health` routes on port 3000.
- 2026-06-07: Browser-level login smoke found a loopback host mismatch:
  opening the web app at `127.0.0.1:3000` while the API client targeted
  `localhost:8000` caused failed browser auth. Added a CORS regression for both
  `localhost` and `127.0.0.1`, allowed both frontend origins in the API, and made
  the web API client align local API hostname with the current browser hostname.
  Verified browser login reaches `/documents` and the admin users UI creates and
  lists a user.
- 2026-06-07: Completed the document detail and main-analysis MVP slice. The API
  exposes parsed text, raw download, manual document type override, reparse,
  provider key settings, skills, analyses, and feedback. The worker now has
  OpenAI-compatible, Anthropic-compatible, Hermes, and mock provider adapters,
  validates structured output against shared schemas, and persists raw output,
  token/cost metadata, verdict, summary, status, and errors. Predicted-comments
  and specialized Gate2/Devil's Advocate renderers remain open Phase 3 work.
- 2026-06-07: Closed the Phase 3 second-stage runtime slice. Added
  Gate2-challenger and Devil's Advocate prompt renderers, `run_predicted_comments`
  worker job, second-stage reproducibility metadata on `predicted_comment_runs`,
  automatic enqueue after successful main analysis, enqueue-failure handling that
  preserves the completed main analysis, API embedding of the latest predicted
  comment run, and a Devil's Advocate result UI block.
- 2026-06-08: Closed the remaining Phase 3 skill/provider gaps. Added admin
  skill create, patch, archive, and source-refresh endpoints; result schema and
  local source validation; deterministic source fingerprint refresh; provider
  key configuration test endpoint without plaintext key exposure; provider-key
  and skill audit events; and worker failures for unavailable or changed
  external skill sources before provider calls.
