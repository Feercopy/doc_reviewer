# Gate Challenger Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MVP web platform for reproducible analysis of investment and product defense documents.

**Architecture:** The service is split into a Next.js frontend, FastAPI backend, Python worker, PostgreSQL database, Redis queue, and local file storage. Runtime AI integrations are isolated behind provider adapters so GPT, Claude, and Hermes return the same structured result contracts.

**Tech Stack:** Next.js, TypeScript, FastAPI, Python, SQLAlchemy, Alembic, PostgreSQL, Redis, RQ, Pydantic, OpenAPI, Playwright, pytest.

---

## Source Spec

Primary source: `ТЗ- сайт-анализатор документов инвестиционных защит.docx`.

The product is not a chat with a document. It is a reproducible platform where every verdict, finding, benchmark score, and feedback item is tied to:

- raw document;
- parsed text;
- skill and skill version;
- provider and model;
- run parameters;
- structured output;
- raw model output;
- benchmark or etalon evidence when available.

## Proposed MVP Boundaries

MVP includes:

- login and admin-created users;
- roles `user` and `admin`, with `annotator` modeled in the database for future use;
- upload `.docx`, `.pdf`, `.md`, `.txt`;
- local raw file storage;
- parsed text extraction;
- document type detection with manual override;
- encrypted user API keys for OpenAI-compatible GPT and Anthropic-compatible Claude;
- optional Hermes provider adapter with explicit disabled state if endpoint is not configured;
- `Projects/Gate2-challenger` as the canonical main analysis skill source for Gate 2 documents;
- `Documents/Common GPTs/devils-advocate` as the canonical adversarial / pre-defense comments skill source;
- skill-source snapshots so every analysis can be reproduced even if the external skill repository changes later;
- analysis history and result UI;
- feedback;
- etalon draft creation from analysis result;
- basic benchmark over active etalons;
- admin views for users, documents, analyses, skills, etalons, benchmarks, and feedback.

Out of MVP:

- full annotator queue automation;
- scheduled benchmark;
- bulk benchmark;
- PPTX and Google Docs/Slides import;
- organization-level shared provider keys;
- complex team workspaces;
- UI comments inside documents;
- etalon version diff UI.

## Module Files

1. [01-bootstrap-architecture.md](./01-bootstrap-architecture.md) - repository scaffold, dev environment, service boundaries, contracts.
2. [02-data-model-rbac.md](./02-data-model-rbac.md) - database schema, enums, ownership rules, migrations.
3. [03-auth-admin-users.md](./03-auth-admin-users.md) - login, sessions, admin user management.
4. [04-documents-parsing-storage.md](./04-documents-parsing-storage.md) - upload, raw storage, parsing, type detection.
5. [05-skills-providers-secrets.md](./05-skills-providers-secrets.md) - skill registry, JSON schemas, provider adapters, encrypted API keys, Hermes.
6. [06-analysis-worker-results-feedback.md](./06-analysis-worker-results-feedback.md) - async analysis pipeline, result persistence, feedback.
7. [07-etalons-annotation.md](./07-etalons-annotation.md) - etalon drafts, annotation workspace, publishing rules.
8. [08-benchmark-engine.md](./08-benchmark-engine.md) - benchmark runs, judge skill, scoring, reports.
9. [09-frontend-ui.md](./09-frontend-ui.md) - frontend pages and workflows.
10. [10-admin-observability-testing.md](./10-admin-observability-testing.md) - admin sections, audit logs, operational testing.

## Delivery Sequence

### Phase 1: Skeleton and Data Foundation

- [ ] Implement `01-bootstrap-architecture.md`.
- [ ] Implement `02-data-model-rbac.md`.
- [ ] Implement `03-auth-admin-users.md`.

Exit criteria:

- local stack starts with Docker Compose;
- database migrations run cleanly;
- admin can create a user;
- user can log in and access an authenticated route;
- tests cover auth and role checks.

### Phase 2: Document Workflow

- [ ] Implement `04-documents-parsing-storage.md`.
- [ ] Implement the document parts of `09-frontend-ui.md`.

Exit criteria:

- authenticated user uploads supported file types;
- raw file is stored;
- parsed text is saved;
- detected document type can be manually overridden;
- user sees only own documents;
- admin sees all documents.

### Phase 3: AI Analysis Runtime

- [ ] Implement `05-skills-providers-secrets.md`.
- [ ] Implement `06-analysis-worker-results-feedback.md`.
- [ ] Implement analysis screens from `09-frontend-ui.md`.

Exit criteria:

- user saves encrypted provider key;
- user launches analysis;
- worker persists structured output and raw output;
- second predicted-comments skill runs after the main analysis;
- user can leave feedback.

### Phase 4: Etalons and Benchmarks

- [ ] Implement `07-etalons-annotation.md`.
- [ ] Implement `08-benchmark-engine.md`.
- [ ] Implement etalon and benchmark screens from `09-frontend-ui.md`.

Exit criteria:

- user creates etalon draft from analysis;
- admin can activate etalon;
- benchmark runs over active etalons;
- benchmark persists precision, recall, F1, missed findings, false positives, partial matches.

### Phase 5: Admin, Audit, Hardening

- [ ] Complete `10-admin-observability-testing.md`.
- [ ] Run end-to-end MVP acceptance suite.

Exit criteria:

- admin views cover users, documents, analyses, skills, etalons, benchmarks, feedback;
- audit log records sensitive actions;
- all MVP acceptance criteria from the source spec are covered by automated or manual checks.

## Cross-Module Decisions

- PostgreSQL is the source of truth for users, documents, analyses, etalons, benchmarks, feedback, skill versions, provider settings, and audit logs.
- Local filesystem storage is used for MVP raw files and large artifacts; file paths are never trusted without database ownership checks.
- Redis plus RQ is used for async jobs because analyses and benchmarks must not block HTTP requests.
- Provider adapters normalize GPT, Claude, and Hermes into one `AnalysisProviderResult` contract.
- JSON schemas live in `contracts/schemas/` and are used by API validation, worker validation, UI rendering assumptions, and benchmark judge prompts.
- Baseline skill sources are external local repositories: `/Users/iseremenko/Projects/Gate2-challenger` for Gate 2 stage-gate review and `/Users/iseremenko/Documents/Common GPTs/devils-advocate` for Avito InvCo adversarial critique. The app must snapshot prompt text, source path, source revision, and source fingerprint into each run instead of depending on mutable files at read time.
- GBrain is used only as development memory for this project, not as runtime memory inside the product.
