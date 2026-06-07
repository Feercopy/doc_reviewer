# Admin, Observability, and Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete admin operations, audit logs, reproducibility checks, operational visibility, and MVP acceptance testing.

**Architecture:** Admin features use the same backend services and authorization policies as user features. Audit logs record sensitive actions. Tests cover unit, API, worker, and end-to-end flows.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, Playwright, Docker Compose, structured logging.

---

## Files

- Create: `apps/api/app/routers/admin_documents.py`
- Create: `apps/api/app/routers/admin_analyses.py`
- Create: `apps/api/app/routers/admin_skills.py`
- Create: `apps/api/app/routers/admin_etalons.py`
- Create: `apps/api/app/routers/admin_benchmarks.py`
- Create: `apps/api/app/routers/admin_feedback.py`
- Create: `apps/api/app/services/audit.py`
- Create: `apps/api/app/logging.py`
- Create: `apps/api/tests/test_admin_sections.py`
- Create: `apps/api/tests/test_audit_logs.py`
- Create: `apps/worker/tests/test_reproducibility_contract.py`
- Create: `docs/acceptance/mvp-checklist.md`

## Admin Sections

### Users

Implemented by auth module:

- list;
- create;
- change role;
- reset password;
- block/unblock.

### Documents

Admin can:

- list all documents;
- filter by user, type, date;
- open raw file;
- open parsed text;
- see all analyses for a document;
- archive document.

### Analyses

Admin can:

- list all analyses;
- filter by provider/model;
- filter by skill;
- filter by status;
- inspect structured output;
- inspect raw output;
- inspect errors.

### Skills

Admin can:

- list skills;
- create new version;
- archive version;
- view version history;
- set default skill by type and document type.

### Etalons

Admin can:

- list all etalons;
- change status;
- archive;
- view metadata and history.

### Benchmarks

Admin can:

- list all benchmark runs;
- launch benchmark;
- inspect report;
- compare benchmark parameters.

### Feedback

Admin can:

- list feedback;
- filter by model, skill, user, verdict;
- mark as processed.

## Audit Log Actions

Record these actions:

```text
user.created
user.role_changed
user.status_changed
user.password_reset
document.uploaded
document.parsed
document.parse_failed
document.type_overridden
analysis.created
analysis.completed
analysis.failed
provider_key.saved
provider_key.deleted
skill.created
skill.archived
skill.source_refreshed
etalon.created
etalon.updated
etalon.published
etalon.archived
benchmark.created
benchmark.completed
benchmark.failed
feedback.created
feedback.processed
```

## Reproducibility Contract

Every completed analysis must have:

- document ID;
- raw file path;
- parsed text snapshot or document parsed text version reference;
- provider;
- model;
- API mode;
- skill ID;
- skill version;
- skill source path;
- skill source entrypoint;
- skill source revision;
- skill source fingerprint;
- run parameters;
- timestamp;
- structured output;
- raw output;
- token counts when provider returns them;
- estimated cost when calculable.

Every benchmark must have:

- etalon IDs;
- skill ID;
- skill version;
- judge skill ID;
- analysis skill source snapshot;
- judge skill source snapshot;
- provider;
- model;
- run parameters;
- per-document judge output;
- aggregate score fields;
- status and timestamps.

## Tasks

### Task 1: Admin Routers

- [ ] Implement admin document router.
- [ ] Implement admin analysis router.
- [ ] Implement admin skill router.
- [ ] Implement admin etalon router.
- [ ] Implement admin benchmark router.
- [ ] Implement admin feedback router.
- [ ] Reuse existing service functions where possible.

Acceptance:

- every admin route requires admin role;
- admin filters work for documents, analyses, and feedback.

### Task 2: Audit Service

- [ ] Implement `record_audit(actor_id, action, entity_type, entity_id, metadata)`.
- [ ] Add audit calls for every action listed above.
- [ ] Ensure metadata never stores plaintext API keys or passwords.
- [ ] Add tests for audit creation and secret exclusion.

Acceptance:

- sensitive actions create audit rows;
- audit metadata does not include secret values.

### Task 3: Structured Logging

- [ ] Add request ID middleware.
- [ ] Log request method, path, actor ID when available, status, latency.
- [ ] Worker logs job ID, job type, entity ID, status, latency.
- [ ] Provider logs include provider, model, latency, token counts, and error class without API key.

Acceptance:

- logs can trace a document upload through parse job and analysis job;
- logs never expose provider keys.

### Task 4: Reproducibility Tests

- [ ] Add tests that completed analysis contains every field in the reproducibility contract.
- [ ] Add tests that completed benchmark contains every field in the benchmark contract.
- [ ] Add tests that Gate2-challenger and Devil's Advocate runs persist source path, entrypoint, revision, and fingerprint.
- [ ] Add tests that failed analysis preserves raw output if provider returned one.

Acceptance:

- reproducibility tests pass;
- missing required metadata fails tests.

### Task 5: MVP Acceptance Checklist

- [ ] Create `docs/acceptance/mvp-checklist.md`.
- [ ] Include every criterion from section 18 of the source spec.
- [ ] Add a verification method for each criterion:
  - unit test;
  - API test;
  - worker test;
  - Playwright test;
  - manual check.

Acceptance:

- checklist maps every MVP criterion to a verification method;
- no MVP criterion is left unmapped.

### Task 6: Full Test Suite Command

- [ ] Add root-level test script or Makefile target named `test`.
- [ ] It runs backend tests, worker tests, frontend tests, and Playwright MVP flow.

Acceptance:

- one command verifies the MVP locally;
- command fails on missing environment variables with clear message.

## Verification

Run:

```bash
pytest apps/api/tests apps/worker/tests -q
npm --prefix apps/web run test
npm --prefix apps/web run e2e
```

Expected:

- admin route tests pass;
- audit tests pass;
- reproducibility contract tests pass;
- frontend and e2e tests pass.
