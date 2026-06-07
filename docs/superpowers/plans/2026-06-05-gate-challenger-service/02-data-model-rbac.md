# Data Model and RBAC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the database schema and access-control rules that make analyses, etalons, and benchmarks reproducible.

**Architecture:** Use SQLAlchemy models and Alembic migrations. Authorization is enforced in backend services with explicit ownership and role checks before returning rows or file handles.

**Tech Stack:** PostgreSQL, SQLAlchemy 2, Alembic, Pydantic, pytest.

---

## Files

- Create: `apps/api/app/models/user.py`
- Create: `apps/api/app/models/document.py`
- Create: `apps/api/app/models/skill.py`
- Create: `apps/api/app/models/analysis.py`
- Create: `apps/api/app/models/etalon.py`
- Create: `apps/api/app/models/benchmark.py`
- Create: `apps/api/app/models/feedback.py`
- Create: `apps/api/app/models/provider_key.py`
- Create: `apps/api/app/models/audit_log.py`
- Create: `apps/api/app/authz/policies.py`
- Create: `apps/api/app/schemas/enums.py`
- Modify: `apps/api/app/db/base.py`
- Create: `apps/api/tests/test_authz_policies.py`

## Core Enums

Use these enum values exactly so UI, API, worker, and benchmark code remain aligned:

```text
Role: user, annotator, admin
UserStatus: active, blocked
DocumentType: gate_1, gate_2, gate_3, progress_review, stream_review, strategy_review, unknown
DocumentParseStatus: queued, running, completed, failed
EntityStatus: active, archived, deleted
SkillType: main_analysis, predicted_comments, benchmark_judge, parser_helper, document_classifier
SkillSourceType: inline_prompt, local_skill_repo, local_knowledge_base
RunStatus: queued, running, completed, failed, cancelled
Provider: openai_compatible, anthropic_compatible, hermes
Verdict: approve, approve_with_conditions, need_evidence, reject, unknown
CheckStatus: pass, partial, fail, not_applicable
Severity: low, medium, high, critical
EtalonSource: manual, ai_post_annotation, imported_defense
EtalonStatus: draft, active, archived
FeedbackUsefulness: useful, partially_useful, useless
```

## Tables

### users

Fields:

- `id uuid primary key`
- `login text unique not null`
- `display_name text not null`
- `password_hash text not null`
- `role text not null`
- `status text not null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

### documents

Fields:

- `id uuid primary key`
- `owner_id uuid references users(id)`
- `title text not null`
- `original_filename text not null`
- `mime_type text not null`
- `file_size_bytes bigint not null`
- `file_hash_sha256 text not null`
- `storage_path text not null`
- `parse_status text not null`
- `detected_document_type text not null`
- `document_type_confidence numeric`
- `document_type_explanation text`
- `manual_document_type text`
- `parsed_text text`
- `status text not null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

Index:

- `(owner_id, created_at desc)`
- `(file_hash_sha256)`
- `(detected_document_type)`

### skills

Fields:

- `id uuid primary key`
- `name text not null`
- `description text not null`
- `version text not null`
- `skill_type text not null`
- `supported_document_types jsonb not null`
- `source_type text not null`
- `source_uri text`
- `source_entrypoint text`
- `source_revision text`
- `source_fingerprint text`
- `source_metadata jsonb not null`
- `prompt_text text not null`
- `result_schema_path text not null`
- `status text not null`
- `author_id uuid references users(id)`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

Unique:

- `(name, version, skill_type)`

### analyses

Fields:

- `id uuid primary key`
- `document_id uuid references documents(id)`
- `user_id uuid references users(id)`
- `skill_id uuid references skills(id)`
- `skill_version text not null`
- `provider text not null`
- `model text not null`
- `status text not null`
- `started_at timestamptz`
- `completed_at timestamptz`
- `error_message text`
- `verdict text`
- `summary text`
- `structured_output jsonb`
- `raw_output text`
- `latency_ms integer`
- `input_tokens integer`
- `output_tokens integer`
- `estimated_cost numeric`
- `run_parameters jsonb not null`
- `created_at timestamptz not null`

Index:

- `(document_id, created_at desc)`
- `(user_id, created_at desc)`
- `(provider, model)`
- `(skill_id, skill_version)`

### predicted_comment_runs

Fields:

- `id uuid primary key`
- `analysis_id uuid references analyses(id)`
- `skill_id uuid references skills(id)`
- `skill_version text not null`
- `provider text not null`
- `model text not null`
- `status text not null`
- `structured_output jsonb`
- `raw_output text`
- `error_message text`
- `created_at timestamptz not null`
- `completed_at timestamptz`

### etalons

Fields:

- `id uuid primary key`
- `document_id uuid references documents(id)`
- `author_id uuid references users(id)`
- `source text not null`
- `document_type text not null`
- `real_defense_status text`
- `defense_comments text`
- `expected_verdict text not null`
- `layer_1 jsonb not null`
- `layer_2 jsonb not null`
- `key_findings jsonb not null`
- `forbidden_false_findings jsonb not null`
- `status text not null`
- `version integer not null`
- `raw_file_visible_to_all boolean not null default false`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

### benchmarks

Fields:

- `id uuid primary key`
- `name text not null`
- `description text not null`
- `etalon_ids jsonb not null`
- `skill_id uuid references skills(id)`
- `skill_version text not null`
- `judge_skill_id uuid references skills(id)`
- `provider text not null`
- `model text not null`
- `status text not null`
- `started_by_id uuid references users(id)`
- `started_at timestamptz`
- `completed_at timestamptz`
- `overall_score numeric`
- `layer_1_score numeric`
- `layer_2_score numeric`
- `precision numeric`
- `recall numeric`
- `f1 numeric`
- `missed_findings jsonb`
- `false_positives jsonb`
- `partial_matches jsonb`
- `judge_output jsonb`
- `run_parameters jsonb not null`
- `error_message text`

### feedback

Fields:

- `id uuid primary key`
- `user_id uuid references users(id)`
- `document_id uuid references documents(id)`
- `analysis_id uuid references analyses(id)`
- `provider text not null`
- `model text not null`
- `skill_id uuid references skills(id)`
- `skill_version text not null`
- `usefulness text not null`
- `verdict_correct boolean`
- `has_false_findings boolean`
- `has_missed_findings boolean`
- `comment text`
- `can_use_for_benchmark boolean not null`
- `processed_at timestamptz`
- `created_at timestamptz not null`

### provider_keys

Fields:

- `id uuid primary key`
- `owner_id uuid references users(id)`
- `provider text not null`
- `base_url text`
- `default_model text not null`
- `encrypted_api_key bytea not null`
- `api_key_fingerprint text not null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

Unique:

- `(owner_id, provider)`

### audit_logs

Fields:

- `id uuid primary key`
- `actor_id uuid references users(id)`
- `action text not null`
- `entity_type text not null`
- `entity_id uuid`
- `metadata jsonb not null`
- `created_at timestamptz not null`

## Authorization Policy Matrix

| Action | user | annotator | admin |
|---|---|---|---|
| Read own raw document | yes | yes | yes |
| Read another user's raw document | no | no | yes |
| Read public etalon raw document | yes | yes | yes |
| Read own analysis | yes | yes | yes |
| Read another user's raw model output | no | no | yes |
| Create etalon draft from own analysis | yes | yes | yes |
| Publish etalon active | no | yes | yes |
| Run benchmark with own provider key | yes | yes | yes |
| Manage users | no | no | yes |
| Manage skills | no | no | yes |
| Read provider keys | masked only | masked only | masked metadata only |

## Tasks

### Task 1: Create Models and Migration

- [ ] Add SQLAlchemy models for every table above.
- [ ] Add enum constants in `apps/api/app/schemas/enums.py`.
- [ ] Generate Alembic migration named `initial_schema`.
- [ ] Verify migration creates all indexes and unique constraints.

Acceptance:

- `alembic upgrade head` creates all tables;
- `alembic downgrade base` removes all tables cleanly in local dev database.

### Task 2: Implement Authorization Helpers

- [ ] Create `apps/api/app/authz/policies.py`.
- [ ] Implement functions:

```python
def can_read_document(actor, document) -> bool
def can_read_document_raw(actor, document, etalon=None) -> bool
def can_read_analysis(actor, analysis) -> bool
def can_read_raw_output(actor, analysis) -> bool
def can_publish_etalon(actor) -> bool
def can_manage_users(actor) -> bool
def can_manage_skills(actor) -> bool
def can_manage_benchmarks(actor) -> bool
```

- [ ] Add tests for every row in the Authorization Policy Matrix.

Acceptance:

- policy tests pass;
- every route added later uses a policy helper rather than inline role checks.

### Task 3: Seed Baseline Skills

- [ ] Add seed script `apps/api/app/seeds/skills.py`.
- [ ] Seed five skills:
  - `gate2_challenger_main_analysis` from `/Users/iseremenko/Projects/Gate2-challenger/skills/gate2-challenger/SKILL.md`;
  - `devils_advocate_predefense` from `/Users/iseremenko/Documents/Common GPTs/devils-advocate/ic-voting-prompt.md` plus `/Users/iseremenko/Documents/Common GPTs/devils-advocate/wiki-ic`;
  - generic predicted comments fallback;
  - benchmark judge;
  - document classifier.
- [ ] Store result schema path for each seeded skill.
- [ ] Store source type, source URI, entrypoint, git revision when available, and source fingerprint for each seeded skill.

Acceptance:

- fresh database has active baseline skills;
- seeded Gate 2 analysis defaults to `gate2_challenger_main_analysis`;
- seeded pre-defense simulation defaults to `devils_advocate_predefense`;
- seed script is idempotent.

## Verification

Run:

```bash
pytest apps/api/tests/test_authz_policies.py -q
alembic upgrade head
alembic downgrade base
```

Expected:

- authorization tests pass;
- migrations apply and roll back cleanly.
