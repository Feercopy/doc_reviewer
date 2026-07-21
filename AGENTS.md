# Agent Instructions

These instructions apply to the whole repository.

## Project Context

Gate Challenger Service is an MVP platform for reproducible analysis of
investment and product defense documents. The product is not a document chat.
Every verdict, finding, benchmark score, and feedback item must be traceable to
the input document, parsed text, skill version, provider/model, run parameters,
structured output, raw model output, and benchmark or etalon evidence when
available.

The canonical implementation plan lives in:

- `docs/superpowers/plans/2026-06-05-gate-challenger-service/00-plan-index.md`

Before implementing a module, read the matching plan file in that directory and
keep the implementation scoped to that file's acceptance criteria.

## Development Context

Use repository files as the source of development context. Before architecture,
planning, schema, prompt, or implementation decisions, read the relevant local
context: `AGENTS.md`, `TASKS.md`, matching files under `docs/superpowers/plans/`,
recent git history when useful, and nearby code/tests.

After meaningful decisions, implementation milestones, debugging findings,
benchmark conclusions, or prompt/skill changes, update `TASKS.md` or the
relevant plan/handoff file with a concise note.

## Architecture Commitments

Target stack:

- `apps/web`: Next.js and TypeScript frontend.
- `apps/api`: FastAPI backend, SQLAlchemy, Alembic, Pydantic.
- `apps/worker`: Python worker for parsing, analysis, predicted comments, and
  benchmarks.
- `contracts/schemas`: JSON schemas shared by API, worker, UI assumptions, and
  benchmark validation.
- `infra`: Docker Compose, PostgreSQL, Redis, and local runtime support.

Boundary rules:

- The frontend never calls model providers directly.
- The frontend never constructs trusted raw file paths.
- Authorization decisions live in the backend, not in the UI.
- Long-running parsing, provider, and benchmark work runs in workers.
- PostgreSQL is the source of truth for persisted business state.
- Local filesystem storage is acceptable for MVP artifacts, but database
  ownership checks must guard every file access.
- Provider-specific logic must stay behind adapters returning one normalized
  result contract.
- External skill sources are snapshotted per run; historical results must not
  depend on mutable files at display time.

Canonical external skill sources:

- Gate 2 main analysis:
  `/Users/iseremenko/Projects/Gate2-challenger/skills/gate2-challenger/SKILL.md`
- Devil's Advocate / pre-defense critique:
  `/Users/iseremenko/Documents/Common GPTs/devils-advocate`

## Security And Privacy

- Never commit `.env`, API keys, passwords, private certificates, raw provider
  outputs containing sensitive document text, or local storage artifacts.
- Provider keys must be encrypted before storage and must never be returned to
  the frontend.
- Logs, audit metadata, tests, and fixtures must not contain plaintext secrets.
- Do not send raw user documents, provider outputs, or secrets to external
  tools.
- Use `.env.example` for non-secret configuration templates only.

## Infrastructure Access

- When root access is required for `178.250.159.250`, use the SSH identity
  `~/.ssh/my-server-codex` (the codex key) with `IdentitiesOnly`; the default
  SSH identities are not accepted. Never store or commit private key material.

## Workflow For Agents

1. Read `AGENTS.md`, `TASKS.md`, and the relevant implementation plan before
   editing.
2. Check git status before edits and do not overwrite unrelated user changes.
3. Prefer `rg` and `rg --files` for discovery.
4. Keep edits small and aligned with the existing plan boundaries.
5. Update `TASKS.md` when task state, scope, or verification status changes.
6. Add or update tests for behavior that can regress.
7. Run the narrowest useful verification first, then broader checks when the
   touched surface warrants it.
8. After frontend changes that the user should inspect at `localhost:3000`,
   rebuild and restart the local web container with
   `docker compose -f infra/docker-compose.yml up -d --build web`; otherwise
   the browser may keep showing the previous image.
9. Record meaningful decisions or milestones in `TASKS.md` or the relevant
   project handoff document.
10. Do not create commits unless the user explicitly asks.

## Coding Standards

Python:

- Target Python 3.12.
- Use typed Pydantic models for API and worker contracts.
- Keep SQLAlchemy models, schemas, services, and routers separated.
- Use Alembic migrations for database changes.
- Keep worker jobs idempotent where practical and safe to retry.

TypeScript:

- Use TypeScript for all frontend code.
- Keep API access behind a small typed client layer.
- Do not duplicate authorization logic as security logic in the frontend.
- Keep UI rendering driven by structured result contracts, not raw model text.

Contracts:

- JSON schemas in `contracts/schemas/` are shared contracts, not UI-only
  helpers.
- Validate provider output before persisting completed structured results.
- Preserve raw provider output for reproducibility and debugging when allowed by
  the data handling rules.

## Verification Commands

Use the commands that exist for the current implementation stage:

```bash
pytest apps/api/tests -q
pytest apps/worker/tests -q
npm --prefix apps/web run test
npm --prefix apps/web run e2e
docker compose -f infra/docker-compose.yml config
docker compose -f infra/docker-compose.yml up -d --build web
```

When a command cannot run because the scaffold is not implemented yet, state
that explicitly in the handoff instead of implying verification passed.
