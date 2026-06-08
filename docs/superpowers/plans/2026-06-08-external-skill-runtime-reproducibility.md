# External Skill Runtime Reproducibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Gate Challenger and Devil's Advocate run in the service with the same source richness as Codex skills while preserving reproducibility, auditability, benchmarkability, and UI-friendly structured outputs.

**Architecture:** External skill repositories remain development-owned sources, not application dependencies at display time. Before each run, the API resolves and validates the configured external source, builds an immutable source/context snapshot, and stores that snapshot as DB metadata plus artifact files. Workers render prompts from the stored snapshot only; they do not silently fall back to stale inline prompts or live-read mutable external paths.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, RQ, Redis, PostgreSQL, local artifact storage, Python `subprocess` for controlled git checks, deterministic text/BM25-style retrieval for MVP, optional future pgvector embeddings.

---

## Non-Negotiable Product Requirements

- The service must not become a thin wrapper around live Codex skill execution.
- External skill sources may be mounted or mirrored, but historical analysis display must never depend on mutable external files.
- Every completed analysis must be traceable to:
  - input document hash and parsed text hash;
  - source repository path or URL;
  - source commit/ref and dirty-state policy;
  - selected source files and their hashes;
  - rendered prompt and retrieval dossier;
  - provider/model/run parameters;
  - raw provider output and validated structured output.
- No silent fallback to stub prompts for Gate Challenger or Devil's Advocate.
- Local dirty skill runs are allowed only when explicitly marked as `intentional_local_run`.
- Devil's Advocate wiki/case retrieval must snapshot selected pages/chunks/questions, not just the repo commit.

## Current Failure To Fix

The `TRX_SE` service run used the same document as the Gate Challenger benchmark file, but did not use the same skill context:

- `gate2_challenger_main_analysis.prompt_text` in DB was a 48-character stub.
- `devils_advocate_predefense.prompt_text` in DB was a 45-character stub.
- `source_revision` and `source_fingerprint` were empty.
- API/worker containers did not mount `/Users/iseremenko/Projects/Gate2-challenger` or `/Users/iseremenko/Documents/Common GPTs/devils-advocate`.
- The worker rendered prompts from DB `skill.prompt_text`, so missing external sources degraded quality without a hard failure.
- Current schemas compress output into generic JSON and do not preserve full Gate stage routing, Layer 3, approval scope, DA retrieval, or narrative summary.

## Phased Delivery

Implement in six increments. Each increment should leave the app runnable and testable.

1. **Source Registry And Freshness**: configure external skill sources and fail fast when unavailable or stale.
2. **Immutable Snapshot Runtime**: store source files, prompt context, and hashes per run.
3. **Gate Challenger Parity**: render current `gate-challenger` source and references with stage-aware output.
4. **Devil's Advocate RAG Dossier**: deterministic retrieval over `wiki-ic` cases/patterns/personas/questions with snapshot.
5. **Run UI And Admin Observability**: expose source version, retrieval, and run mode to users/admins.
6. **Regression Benchmarks**: compare service output against existing Gate Challenger and DA benchmark expectations.

## Data Model Changes

### New Tables

#### `skill_sources`

Purpose: canonical configuration for an external source independent of individual skill versions.

Columns:

- `id uuid primary key`
- `slug text unique not null`
- `display_name text not null`
- `source_kind text not null`
  - values: `local_git_repo`, `local_directory`, `inline`
- `local_path text null`
- `repo_url text null`
- `default_ref text null`
- `entrypoint text not null`
- `required_paths jsonb not null default []`
- `update_policy text not null`
  - values: `require_latest`, `allow_pinned`, `allow_local_dirty`
- `status text not null`
  - values: `active`, `archived`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

Initial rows:

- `gate-challenger`: `/Users/iseremenko/Projects/Gate2-challenger`, entrypoint `skills/gate-challenger/SKILL.md`, required references under `skills/gate-challenger/references/`.
- `devils-advocate`: `/Users/iseremenko/Documents/Common GPTs/devils-advocate`, entrypoint `ic-voting-prompt.md`, required paths `workflow-ic-cases.md`, `wiki-ic/schema.md`, `wiki-ic/meta/output-format.md`, `wiki-ic/CLAUDE.md`, `wiki-ic/cases`, `wiki-ic/patterns`, `wiki-ic/heuristics`, `wiki-ic/domains`, `wiki-ic/personas`, `wiki-ic/eval`.

#### `skill_source_snapshots`

Purpose: immutable source material snapshot for a specific run.

Columns:

- `id uuid primary key`
- `skill_source_id uuid references skill_sources(id)`
- `analysis_id uuid null references analyses(id)`
- `predicted_comment_run_id uuid null references predicted_comment_runs(id)`
- `source_slug text not null`
- `source_kind text not null`
- `source_path text null`
- `repo_url text null`
- `requested_ref text null`
- `resolved_revision text null`
- `is_dirty boolean not null default false`
- `dirty_details jsonb not null default {}`
- `snapshot_mode text not null`
  - values: `production_latest`, `pinned_revision`, `intentional_local_run`
- `source_fingerprint text not null`
- `file_manifest jsonb not null`
- `artifact_path text not null`
- `created_at timestamptz not null`

Constraint:

- exactly one of `analysis_id` or `predicted_comment_run_id` must be non-null.

#### `retrieval_snapshots`

Purpose: immutable Devil's Advocate retrieval dossier for a predicted-comments run.

Columns:

- `id uuid primary key`
- `predicted_comment_run_id uuid references predicted_comment_runs(id) not null`
- `retrieval_mode text not null`
  - values: `none`, `deterministic_topk`, `hybrid_rag`
- `retrieval_version text not null`
- `corpus_fingerprint text not null`
- `query_fingerprint text not null`
- `selected_items jsonb not null`
- `artifact_path text not null`
- `created_at timestamptz not null`

### Existing Table Changes

Modify `skills`:

- Add `skill_source_id uuid null references skill_sources(id)`.
- Keep `source_uri`, `source_revision`, `source_fingerprint`, and `prompt_text` temporarily for backward compatibility.
- Add `runtime_mode text not null default 'snapshot_required'`.

Modify `analyses.run_parameters` contract:

- Keep `skill_source_snapshot` but make it point to `skill_source_snapshots.id`.
- Include `rendered_prompt_artifact_path`.
- Include `prompt_fingerprint`.
- Include `source_snapshot_id`.

Modify `predicted_comment_runs.run_parameters` contract:

- Include `main_analysis_source_snapshot_id`.
- Include `skill_source_snapshot_id`.
- Include `retrieval_snapshot_id`.
- Include `rendered_prompt_artifact_path`.
- Include `prompt_fingerprint`.

## File Structure

### API

- Modify: `apps/api/app/models/skill.py`
  - Add relationships/columns for `skill_source_id` and runtime mode.
- Create: `apps/api/app/models/skill_source.py`
  - Define `SkillSource`, `SkillSourceSnapshot`, `RetrievalSnapshot`.
- Modify: `apps/api/app/models/__init__.py`
  - Export new models.
- Create: `apps/api/alembic/versions/202606080002_external_skill_snapshots.py`
  - Add tables and columns.
- Create: `apps/api/app/services/external_sources.py`
  - Resolve local paths, run freshness checks, collect manifests, write source snapshot artifacts.
- Create: `apps/api/app/services/skill_snapshots.py`
  - Create source snapshots for analyses and predicted-comment runs.
- Create: `apps/api/app/services/devils_retrieval.py`
  - Build deterministic DA retrieval dossier from `wiki-ic`.
- Modify: `apps/api/app/services/skills.py`
  - Bind skills to `skill_sources`.
  - Remove reliance on stub `prompt_text` for external runtime.
- Modify: `apps/api/app/services/analyses.py`
  - Create Gate source snapshot before enqueue.
  - Fail analysis creation if source is unavailable or stale.
- Modify: `apps/api/app/services/benchmarks.py`
  - Snapshot source/retrieval when benchmarks create analysis jobs.
- Modify: `apps/api/app/seeds/skills.py`
  - Seed current `gate-challenger` path, not old `gate2-challenger` path.
  - Seed DA source registry and required paths.
- Modify: `apps/api/app/schemas/skills.py`
  - Include source health, snapshot policy, and current revision.
- Modify: `apps/api/app/schemas/analyses.py`
  - Include source snapshot summary and DA retrieval summary in read models.
- Modify: `apps/api/app/routers/skills.py`
  - Add admin health/refresh endpoints.
- Modify: `infra/docker-compose.yml`
  - Add optional read-only mounts for local source repos.

### Worker

- Create: `apps/worker/skills/snapshot_loader.py`
  - Load source snapshot artifacts and retrieval artifacts by path.
- Modify: `apps/worker/skills/gate2_challenger_renderer.py`
  - Render from snapshot files, not DB prompt stub.
- Modify: `apps/worker/skills/devils_advocate_renderer.py`
  - Render from DA source snapshot plus retrieval dossier.
- Modify: `apps/worker/skills/prompt_renderer.py`
  - Route Gate Challenger through snapshot-aware renderer.
- Modify: `apps/worker/jobs/run_analysis.py`
  - Require source snapshot id and prompt artifact.
  - Persist prompt fingerprint and rendered prompt artifact.
- Modify: `apps/worker/jobs/run_predicted_comments.py`
  - Require DA source snapshot and retrieval snapshot for DA mode.
- Modify: `apps/worker/results/schema_validation.py`
  - Support richer result schemas.

### Contracts

- Modify: `contracts/schemas/main-analysis-result.schema.json`
  - Add stage routing, narrative summary, approval scope, Layer 3, merged blockers.
- Modify: `contracts/schemas/devils-advocate-result.schema.json`
  - Align with DA trailer sections: brutal truth, contradictions/missing proofs, tough questions, actionable JTBDs, IC decision.
- Create: `contracts/schemas/skill-source-snapshot.schema.json`
  - Validate source snapshot metadata.
- Create: `contracts/schemas/devils-retrieval-snapshot.schema.json`
  - Validate retrieval dossier metadata.

### Web

- Modify: `apps/web/src/lib/api/types.ts`
  - Add source snapshot/retrieval types.
- Modify: `apps/web/src/app/analyses/[analysisId]/page.tsx`
  - Show skill source revision, snapshot mode, prompt/retrieval fingerprints, DA consulted cases.
- Modify: `apps/web/src/app/admin/skills/page.tsx`
  - Show source health and refresh/freshness status.
- Modify: `apps/web/src/app/admin/analyses/page.tsx`
  - Add source revision and snapshot mode columns.

### Tests

- Modify/Create:
  - `apps/api/tests/test_skill_sources.py`
  - `apps/api/tests/test_analyses_api.py`
  - `apps/api/tests/test_skills_api.py`
  - `apps/worker/tests/test_skill_renderers.py`
  - `apps/worker/tests/test_run_analysis_job.py`
  - `apps/worker/tests/test_run_predicted_comments_job.py`
  - `apps/worker/tests/test_reproducibility_contract.py`
  - `apps/api/tests/test_contract_schemas.py`
  - `apps/web/src/lib/api/skills.test.ts`
  - `apps/web/src/lib/api/documents.test.ts`

## Implementation Tasks

### Task 1: Add Source Registry And Snapshot Tables

**Files:**

- Create: `apps/api/app/models/skill_source.py`
- Modify: `apps/api/app/models/__init__.py`
- Modify: `apps/api/app/models/skill.py`
- Create: `apps/api/alembic/versions/202606080002_external_skill_snapshots.py`
- Test: `apps/api/tests/test_skill_sources.py`

Steps:

- [ ] Add failing model/migration smoke test that creates a `SkillSource`, `SkillSourceSnapshot`, and `RetrievalSnapshot`.
- [ ] Add SQLAlchemy models with the columns listed above.
- [ ] Add Alembic migration.
- [ ] Run `pytest apps/api/tests/test_skill_sources.py -q`.
- [ ] Run `pytest apps/api/tests/test_contract_schemas.py -q`.

Acceptance:

- New tables exist after migration.
- Snapshot rows can be linked to either an analysis or a predicted-comments run.
- Existing tests still create baseline `Skill` rows.

### Task 2: Seed Current External Source Registry

**Files:**

- Modify: `apps/api/app/seeds/skills.py`
- Modify: `apps/api/tests/test_seeds.py`
- Modify: `infra/docker-compose.yml`
- Modify: `.env.example`

Steps:

- [ ] Update seed tests to expect `skills/gate-challenger/SKILL.md`.
- [ ] Add `GATE_CHALLENGER_SOURCE_PATH` and `DEVILS_ADVOCATE_SOURCE_PATH` env vars with safe defaults.
- [ ] Seed `skill_sources` rows for Gate Challenger and DA.
- [ ] Link `gate2_challenger_main_analysis` and `devils_advocate_predefense` skills to those sources.
- [ ] Add read-only Compose mounts controlled by env vars:
  - `${GATE_CHALLENGER_HOST_PATH:-/Users/iseremenko/Projects/Gate2-challenger}:/external/gate-challenger:ro`
  - `${DEVILS_ADVOCATE_HOST_PATH:-/Users/iseremenko/Documents/Common GPTs/devils-advocate}:/external/devils-advocate:ro`
- [ ] Use container paths in seeded source rows when running under Compose:
  - `/external/gate-challenger`
  - `/external/devils-advocate`
- [ ] Run `pytest apps/api/tests/test_seeds.py -q`.
- [ ] Run `docker compose -f infra/docker-compose.yml config`.

Acceptance:

- Fresh seed no longer stores old `skills/gate2-challenger` path.
- Compose config includes read-only external mounts.
- If mount env vars are missing on another machine, health check should report source unavailable rather than silently using stub prompts.

### Task 3: Implement Source Freshness And Manifest Collection

**Files:**

- Create: `apps/api/app/services/external_sources.py`
- Test: `apps/api/tests/test_skill_sources.py`

Core functions:

- `resolve_external_source(source: SkillSource) -> ResolvedSource`
- `check_git_freshness(source: SkillSource, mode: SnapshotMode) -> SourceHealth`
- `collect_source_manifest(source: SkillSource) -> SourceManifest`
- `fingerprint_manifest(manifest: SourceManifest) -> str`

Rules:

- `production_latest`:
  - source path must exist;
  - git repo must be clean;
  - `git fetch` must succeed when remote is configured;
  - local HEAD must not be behind configured upstream;
  - revision must be non-null.
- `pinned_revision`:
  - source path must exist;
  - current HEAD must match requested revision or ref resolution.
- `intentional_local_run`:
  - dirty tree allowed;
  - dirty file list captured in snapshot;
  - UI must show local-run warning.

Steps:

- [ ] Write tests for missing source path returning `source_unavailable`.
- [ ] Write tests for clean temporary git repo returning revision and manifest.
- [ ] Write tests for dirty repo failing in `production_latest`.
- [ ] Write tests for dirty repo allowed in `intentional_local_run`.
- [ ] Implement source resolution and git checks.
- [ ] Implement manifest collection for required files/directories.
- [ ] Run `pytest apps/api/tests/test_skill_sources.py -q`.

Acceptance:

- Freshness failures are explicit and typed.
- Manifest includes path, sha256, size, and relative source path for every included file.
- No source check deletes, mutates, or commits external repo files.

### Task 4: Create Immutable Source Snapshot Artifacts

**Files:**

- Create: `apps/api/app/services/skill_snapshots.py`
- Modify: `apps/api/app/storage/local.py`
- Test: `apps/api/tests/test_skill_sources.py`
- Test: `apps/worker/tests/test_reproducibility_contract.py`

Artifact layout:

```text
storage/
  skill-snapshots/
    <snapshot-id>/
      manifest.json
      files/
        <relative-source-path>
```

Steps:

- [ ] Add storage helper `save_skill_source_snapshot(snapshot_id, manifest, files)`.
- [ ] Add test that artifact files are written under storage root.
- [ ] Add test that path traversal in relative source paths is rejected.
- [ ] Add service that creates `skill_source_snapshots` row and writes artifacts.
- [ ] Store `artifact_path`, `source_fingerprint`, `file_manifest`, `resolved_revision`, `snapshot_mode`.
- [ ] Run `pytest apps/api/tests/test_skill_sources.py apps/worker/tests/test_reproducibility_contract.py -q`.

Acceptance:

- Snapshot artifact contains exact source text used by the run.
- Historical result can be loaded without external repo present.
- Snapshot records never include raw uploaded user documents.

### Task 5: Wire Analysis Creation To Source Snapshots

**Files:**

- Modify: `apps/api/app/services/analyses.py`
- Modify: `apps/api/app/schemas/analyses.py`
- Test: `apps/api/tests/test_analyses_api.py`

Steps:

- [ ] Add failing API test: creating Gate analysis with unavailable source returns `400 source_unavailable`.
- [ ] Add passing API test: creating Gate analysis with available test source stores `source_snapshot_id`.
- [ ] Add run parameter fields:
  - `source_snapshot_id`
  - `snapshot_mode`
  - `source_revision`
  - `source_fingerprint`
- [ ] Reject external-skill analyses when snapshot cannot be created.
- [ ] Keep inline skills working without source snapshot.
- [ ] Run `pytest apps/api/tests/test_analyses_api.py -q`.

Acceptance:

- Main analysis is queued only after source snapshot succeeds.
- No main-analysis run can use stale DB stub prompt for Gate Challenger.

### Task 6: Make Gate Renderer Snapshot-Aware

**Files:**

- Create: `apps/worker/skills/snapshot_loader.py`
- Modify: `apps/worker/skills/gate2_challenger_renderer.py`
- Modify: `apps/worker/jobs/run_analysis.py`
- Test: `apps/worker/tests/test_skill_renderers.py`
- Test: `apps/worker/tests/test_run_analysis_job.py`

Steps:

- [ ] Add failing renderer test: prompt includes `SKILL.md`, `common-output-contract.md`, `common-synthesis-contract.md`, `common-verdict-policy.md`, selected stage rubric, and `common-adversarial-rubric.md` from snapshot.
- [ ] Add loader that reads `manifest.json` and source files from artifact path.
- [ ] Render Gate prompt from snapshot artifact, not `skill.prompt_text`.
- [ ] Include source metadata block:
  - revision;
  - fingerprint;
  - snapshot mode;
  - file manifest summary.
- [ ] Keep JSON response schema instruction, but include narrative summary fields in schema after Task 7.
- [ ] Persist rendered prompt artifact and prompt fingerprint.
- [ ] Run `pytest apps/worker/tests/test_skill_renderers.py apps/worker/tests/test_run_analysis_job.py -q`.

Acceptance:

- Worker fails with `source_snapshot_missing` if Gate analysis has no snapshot.
- Gate prompt contains the actual current external skill instructions.
- Prompt can be reproduced from stored artifacts.

### Task 7: Expand Main Analysis Contract For Gate Challenger Parity

**Files:**

- Modify: `contracts/schemas/main-analysis-result.schema.json`
- Modify: `apps/api/tests/test_contract_schemas.py`
- Modify: `apps/web/src/lib/api/types.ts`
- Modify: `apps/web/src/app/analyses/[analysisId]/page.tsx`

Add fields:

- `document_stage`
- `stage_detection`
- `verdict`
- `approval_scope`
- `narrative_summary`
- `blockers`
- `key_findings`
- `layer_1`
- `layer_2`
- `layer_3`
- `merged_block_assessment`
- `recommendations`
- `confidence`

Backward compatibility:

- Existing generic `findings` and `checks` may remain optional for old runs.
- New Gate runs should prefer `blockers`, `layer_1`, `layer_2`, `layer_3`.

Steps:

- [ ] Add schema test with a realistic Gate output including Layer 3.
- [ ] Add schema test that old minimal result remains readable only where existing API requires it.
- [ ] Update UI types.
- [ ] Update analysis page to show narrative summary and Layer 3.
- [ ] Run `pytest apps/api/tests/test_contract_schemas.py -q`.
- [ ] Run `npm --prefix apps/web run test`.

Acceptance:

- Service can store a `standard`-style narrative summary and structured layers.
- UI no longer forces Gate output into generic short findings only.

### Task 8: Implement DA Wiki Corpus Index

**Files:**

- Create: `apps/api/app/services/devils_retrieval.py`
- Test: `apps/api/tests/test_devils_retrieval.py`

MVP retrieval:

- Deterministic lexical scoring, not embeddings.
- Candidate corpus:
  - `wiki-ic/cases/*.md`
  - `wiki-ic/patterns/*.md`
  - `wiki-ic/heuristics/*.md`
  - `wiki-ic/domains/*.md`
  - `wiki-ic/personas/*.md`
  - `wiki-ic/eval/dataset-*.md`
- Query features:
  - stage;
  - domain;
  - monetization type;
  - resource ask shape;
  - key terms from parsed document;
  - main-analysis blockers.

Selected output:

- `top_cases`
- `top_patterns`
- `top_heuristics`
- `top_persona_question_examples`
- `retrieval_rationale`
- `corpus_fingerprint`

Steps:

- [ ] Add fixture DA wiki with 3 cases, 2 patterns, 2 personas, 2 eval datasets.
- [ ] Test top-k retrieval is deterministic with equal-score tie-breaking by path.
- [ ] Test self-exclusion when current document maps to a known case id.
- [ ] Test corpus fingerprint changes when a source file changes.
- [ ] Implement tokenizer, scoring, and manifest hashing.
- [ ] Run `pytest apps/api/tests/test_devils_retrieval.py -q`.

Acceptance:

- Same corpus and document always select the same retrieval items.
- Retrieval output is serializable and snapshot-ready.
- No embeddings are required for MVP.

### Task 9: Snapshot DA Retrieval Dossier

**Files:**

- Modify: `apps/api/app/services/analyses.py`
- Modify: `apps/api/app/services/skill_snapshots.py`
- Modify: `apps/api/app/services/devils_retrieval.py`
- Modify: `apps/worker/jobs/run_analysis.py`
- Test: `apps/api/tests/test_analyses_api.py`
- Test: `apps/worker/tests/test_run_predicted_comments_job.py`

Artifact layout:

```text
storage/
  retrieval-snapshots/
    <retrieval-snapshot-id>/
      dossier.json
      selected/
        <relative-wiki-path>
```

Steps:

- [ ] Create DA source snapshot after main analysis completes and before predicted-comments enqueue.
- [ ] Build DA retrieval dossier from document + main analysis.
- [ ] Save selected wiki/case/eval/persona/pattern files into retrieval artifact.
- [ ] Create `retrieval_snapshots` row.
- [ ] Store `retrieval_snapshot_id` in `predicted_comment_runs.run_parameters`.
- [ ] Run `pytest apps/api/tests/test_analyses_api.py apps/worker/tests/test_run_predicted_comments_job.py -q`.

Acceptance:

- DA run has both source snapshot and retrieval snapshot.
- DA prompt can be reconstructed without live `wiki-ic`.
- DA consulted cases/questions are visible in stored metadata.

### Task 10: Make DA Renderer Snapshot-Aware

**Files:**

- Modify: `apps/worker/skills/devils_advocate_renderer.py`
- Modify: `apps/worker/jobs/run_predicted_comments.py`
- Test: `apps/worker/tests/test_skill_renderers.py`
- Test: `apps/worker/tests/test_run_predicted_comments_job.py`

Steps:

- [ ] Add failing renderer test: DA prompt includes `ic-voting-prompt.md`, `wiki-ic/schema.md`, `wiki-ic/meta/output-format.md`, selected cases, selected patterns, selected persona examples, and main analysis context.
- [ ] Load DA source snapshot from artifact.
- [ ] Load retrieval dossier from artifact.
- [ ] Render prompt with explicit sections:
  - DA orchestration prompt;
  - source metadata;
  - main analysis context;
  - retrieval dossier;
  - selected wiki excerpts;
  - response schema.
- [ ] Fail with `retrieval_snapshot_missing` when DA mode requires RAG but dossier is absent.
- [ ] Run `pytest apps/worker/tests/test_skill_renderers.py apps/worker/tests/test_run_predicted_comments_job.py -q`.

Acceptance:

- DA no longer falls back to 45-character stub prompt.
- `consulted_pages` can be populated from actual selected retrieval files.

### Task 11: Expand DA Result Contract

**Files:**

- Modify: `contracts/schemas/devils-advocate-result.schema.json`
- Modify: `contracts/schemas/devils-advocate-query-result.schema.json`
- Modify: `apps/api/tests/test_contract_schemas.py`
- Modify: `apps/web/src/lib/api/types.ts`
- Modify: `apps/web/src/app/analyses/[analysisId]/page.tsx`

Add fields:

- `run_mode`
- `retrieval`
  - `selected_cases`
  - `selected_patterns`
  - `selected_personas`
  - `source_citations`
- `anchored_comments`
- `trailer`
  - `brutal_truth`
  - `detected_contradictions`
  - `tough_questions`
  - `actionable_jtbds`
- `ic_decision`
- `predicted_questions`
- `questions_per_persona`
- `source_citations`

Steps:

- [ ] Add schema test matching real DA trailer structure.
- [ ] Update UI to show DA trailer sections.
- [ ] Update UI to show retrieved cases and patterns.
- [ ] Run `pytest apps/api/tests/test_contract_schemas.py -q`.
- [ ] Run `npm --prefix apps/web run test`.

Acceptance:

- DA output can represent both IC voting trailer and historical-question retrieval.
- UI makes it clear which prior cases influenced the output.

### Task 12: Add Admin Source Health And Refresh UI

**Files:**

- Modify: `apps/api/app/routers/skills.py`
- Modify: `apps/api/app/schemas/skills.py`
- Modify: `apps/web/src/lib/api/skills.ts`
- Modify: `apps/web/src/app/admin/skills/page.tsx`
- Test: `apps/api/tests/test_skills_api.py`
- Test: `apps/web/src/lib/api/skills.test.ts`

Endpoints:

- `GET /admin/skills/sources`
- `GET /admin/skills/sources/{source_id}/health`
- `POST /admin/skills/sources/{source_id}/refresh`

Steps:

- [ ] Add API tests for source health success and unavailable source.
- [ ] Add API tests that refresh updates revision/fingerprint only when source is available.
- [ ] Add frontend typed client methods.
- [ ] Show source status:
  - available/unavailable;
  - current revision;
  - dirty status;
  - latest check time;
  - required paths missing.
- [ ] Run `pytest apps/api/tests/test_skills_api.py -q`.
- [ ] Run `npm --prefix apps/web run test`.

Acceptance:

- Admin can see before launching analyses whether external skill sources are usable.
- Refresh never mutates external repo beyond allowed git freshness reads/fetches.

### Task 13: Add Analysis Result Source Trace UI

**Files:**

- Modify: `apps/api/app/services/analyses.py`
- Modify: `apps/api/app/schemas/analyses.py`
- Modify: `apps/web/src/app/analyses/[analysisId]/page.tsx`
- Test: `apps/api/tests/test_analyses_api.py`
- Test: `apps/web/src/lib/api/documents.test.ts`

UI should show:

- Gate source revision and fingerprint.
- DA source revision and fingerprint.
- Snapshot mode.
- Prompt fingerprint.
- Retrieval mode and top selected cases.
- Warning for `intentional_local_run`.
- Admin-only links/expanders for raw prompt and raw provider output.

Steps:

- [ ] Add API response fields for source snapshot summaries.
- [ ] Add tests for admin sees prompt artifact metadata.
- [ ] Add tests for normal user sees safe metadata but not raw prompt if raw prompt includes document text.
- [ ] Add UI source trace section.
- [ ] Run API and web tests.

Acceptance:

- User can understand why a run differs from another run.
- Admin can debug source/prompt/retrieval issues.
- Raw document text remains protected.

### Task 14: Add Benchmark Regression Cases For TRX_SE

**Files:**

- Modify: `apps/worker/tests/test_reproducibility_contract.py`
- Create: `apps/worker/tests/fixtures/trx_se_gate_expected.json`
- Create: `apps/worker/tests/fixtures/trx_se_da_expected.json`
- Modify: `docs/acceptance/mvp-checklist.md`

Steps:

- [ ] Add fixture expectations for Gate output shape, not exact prose.
- [ ] Require Gate output includes:
  - stage detection;
  - Layer 3;
  - approval scope;
  - narrative summary;
  - blocker evidence chains.
- [ ] Require DA output includes:
  - retrieval selected cases;
  - tough questions;
  - actionable JTBDs;
  - IC decision.
- [ ] Add acceptance checklist row for external skill parity.
- [ ] Run `pytest apps/worker/tests/test_reproducibility_contract.py -q`.

Acceptance:

- A future stub prompt regression fails tests.
- `TRX_SE` no longer silently produces generic JSON-only output.

### Task 15: Manual End-To-End Verification

Commands:

```bash
docker compose -f infra/docker-compose.yml config
pytest apps/api/tests/test_skill_sources.py apps/api/tests/test_analyses_api.py apps/api/tests/test_skills_api.py -q
pytest apps/worker/tests/test_skill_renderers.py apps/worker/tests/test_run_analysis_job.py apps/worker/tests/test_run_predicted_comments_job.py apps/worker/tests/test_reproducibility_contract.py -q
npm --prefix apps/web run test
```

Manual flow:

- Start Compose with external source mounts.
- Open admin skills page and confirm:
  - Gate source available;
  - DA source available;
  - both have non-null revision/fingerprint.
- Upload `TRX_SE.md`.
- Run analysis in `production_latest` mode.
- Confirm run fails if source mount is removed.
- Confirm run succeeds when source mount exists.
- Confirm result page shows:
  - Gate Challenger source revision;
  - DA source revision;
  - Layer 3;
  - DA selected historical cases;
  - DA questions/JTBDs;
  - prompt/retrieval fingerprints.
- Re-run with same document/source/model and confirm snapshots are comparable.

## Implementation Order Recommendation

Do not start with DA RAG. Start by eliminating silent stub usage. The safest sequence:

1. Tables and source registry.
2. Compose read-only mounts and seed fix.
3. Source health/freshness checks.
4. Immutable source snapshot artifacts.
5. Gate snapshot-aware renderer.
6. Main result schema expansion.
7. DA deterministic retrieval.
8. DA snapshot-aware renderer.
9. DA schema expansion.
10. UI source trace.
11. Regression fixtures and manual TRX_SE verification.

## Open Decisions

1. **Where to store prompt artifacts:** local storage is sufficient for MVP; DB text columns are easier to query but risk large rows.
   - Recommendation: local storage artifact + DB fingerprint/path.

2. **Retrieval algorithm for MVP:** lexical deterministic retrieval vs embeddings.
   - Recommendation: lexical deterministic first; embeddings later if benchmark shows retrieval misses.

3. **Freshness strictness:** always latest vs pinned revision.
   - Recommendation: default `production_latest`, allow `pinned_revision` for benchmark reproduction and `intentional_local_run` for development.

4. **DA eval datasets in production context:** include `eval/dataset-*.md` only when run mode explicitly uses historical-question prediction.
   - Recommendation: include for `ic_hybrid`/question prediction, exclude or minimize for basic `ic_voting_full` to reduce leakage and prompt size.

5. **Provider calls for multi-pass Gate/DA:** one large call vs several calls.
   - Recommendation: keep one call for first MVP parity, then split into multi-pass workers after schemas and snapshots are stable.

## Risks And Mitigations

- **Risk:** service quality remains below Codex because prompts are over-constrained by JSON schema.
  - Mitigation: include `narrative_summary`, `approval_scope`, and full layer outputs; validate after reasoning rather than replacing reasoning with short fields.

- **Risk:** DA RAG over-anchors on retrieved analogs.
  - Mitigation: prompt must include “go beyond analog” instruction and show unique-document issue section; benchmark against TRX_SE and existing eval datasets.

- **Risk:** external source mounts make local setup brittle.
  - Mitigation: admin health page, explicit source unavailable errors, `.env.example` paths, and `intentional_local_run` mode for development.

- **Risk:** snapshots store sensitive source material.
  - Mitigation: do not snapshot raw user documents into source snapshots; keep prompt artifacts under app storage with DB ownership checks and admin-only raw access.

- **Risk:** git fetch in API path is slow or unavailable.
  - Mitigation: set timeout, cache health checks briefly, and allow pinned/offline mode only with explicit warning.

## Definition Of Done

- Fresh Gate/DA sources produce non-null revision and fingerprint.
- Source unavailable or dirty in `production_latest` blocks run creation.
- Gate worker uses source snapshot artifacts, not DB stub prompt.
- DA worker uses source snapshot and retrieval snapshot artifacts, not live wiki paths.
- TRX_SE run shows Layer 3, approval scope, narrative summary, DA historical cases, and DA tough questions.
- Analysis detail UI shows source trace and retrieval trace.
- Benchmark/regression tests fail if Gate/DA prompt_text stubs are used for external skills.
- No raw user documents, provider keys, or private production data are stored in GBrain or external skill repos.

## Verification Matrix

| Surface | Command | Expected |
|---|---|---|
| API source registry | `pytest apps/api/tests/test_skill_sources.py -q` | Source health, manifest, snapshots pass |
| API analysis creation | `pytest apps/api/tests/test_analyses_api.py -q` | Analysis queues only after snapshot |
| Worker Gate renderer | `pytest apps/worker/tests/test_skill_renderers.py -q` | Prompt contains real snapshot files |
| Worker jobs | `pytest apps/worker/tests/test_run_analysis_job.py apps/worker/tests/test_run_predicted_comments_job.py -q` | Jobs require snapshots and persist prompt fingerprints |
| Contracts | `pytest apps/api/tests/test_contract_schemas.py -q` | Rich Gate/DA schemas validate |
| Web | `npm --prefix apps/web run test` | API clients and result UI types pass |
| Compose | `docker compose -f infra/docker-compose.yml config` | External mounts and env render |

## Notes

- GBrain was unavailable during planning with `getaddrinfo ENOTFOUND`; this plan is based on repository context, current MVP plans, and local Devil's Advocate/Gate Challenger source inspection.
- Do not commit this plan unless the user explicitly asks.
