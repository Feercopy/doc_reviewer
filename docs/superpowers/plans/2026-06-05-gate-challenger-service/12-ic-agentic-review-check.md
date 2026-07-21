# IC Agentic Review Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a manually launched IC Agentic Review tab inside a completed product analysis, with optional `.xlsx` financial-model audit and reproducible raw, prompt, script, validation, and compact result artifacts.

**Architecture:** IC Agentic Review is a separate auxiliary analysis run, not part of the main Gate Challenger run and not a predicted-comments run. The frontend exposes a dedicated analysis tab where the user launches the check after the product analysis has completed, optionally attaching one `.xlsx` model. The worker runs one RQ job that calls the provider directly for each original IC role prompt and a synthesis prompt, then runs the original deterministic scripts from a snapshotted `IC-Agentic-Review` source; the UI renders only a compact structured result.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, RQ, Redis, existing provider adapters, JSON Schema, Next.js, TypeScript, Python subprocess with no shell, `openpyxl`, `reportlab`, `scipy`, `numpy`.

---

## Scope

This plan implements a middle version between a text-only MVP and full multi-material IC package review.

Included:

- Manual launch from a new `IC review` tab on `/analyses/{analysisId}`.
- Launch is allowed only when the main product analysis status is `completed`.
- One optional `.xlsx` upload at launch time.
- If `.xlsx` is present, run spreadsheet extraction, `formula_auditor.py`, and `excel_audit.py`.
- If `.xlsx` is absent, mark spreadsheet audit as `not_provided` and skip spreadsheet checks.
- Run the original eight IC role prompts as direct provider calls inside one worker job, not as Claude Code subagents.
- Persist raw output for every role call.
- Persist synthesis prompt and synthesis raw output.
- Persist postprocess log, validation report, and deterministic script artifacts.
- Render a compact UI-native result, not the long PDF report.
- Preserve legacy-compatible JSON, generated debug text, and XLSX as internal reproducibility artifacts when scripts produce them.

Not included:

- General document-package upload outside the analysis page.
- Multiple financial models per IC review run.
- `.xls`, `.xlsm`, `.csv`, or Google Sheets import.
- Live web browsing for `ic-web-researcher`; the role receives only document, main-analysis, and uploaded workbook context.
- Scheduled or automatic IC review runs.
- Reusing Claude Code Agent/subagent infrastructure.

## External Source

Canonical source:

```text
/Users/iseremenko/Documents/IC-Agentic-Review
```

Required source paths to snapshot:

```text
CLAUDE.md
.claude/commands/invest-analysis.md
.claude/agents/ic-financial-auditor.md
.claude/agents/ic-product-analyst.md
.claude/agents/ic-market-analyst.md
.claude/agents/ic-web-researcher.md
.claude/agents/ic-benchmark-valuation.md
.claude/agents/ic-team-legal.md
.claude/agents/ic-tech-dd.md
.claude/agents/ic-risk-scenario.md
.claude/agents/_common_rules.md
scripts/invest/config.py
scripts/invest/formula_auditor.py
scripts/invest/json_postprocess.py
scripts/invest/marker_parser.py
scripts/invest/metrics_lookup.py
scripts/invest/pdf_generator.py
scripts/invest/excel_audit.py
scripts/invest/validate_report.py
scripts/invest/run_pipeline.py
data/metrics_dictionary.json
data/internal_codes
fonts/DejaVuSans.ttf
fonts/DejaVuSans-Bold.ttf
```

The worker must execute scripts from the saved source snapshot, not from mutable source paths.

## Data Contracts

### Compact UI Result

Create `contracts/schemas/ic-agentic-review-result.schema.json`.

Required top-level fields:

```json
{
  "run_mode": "ic_agentic_review_compact",
  "verdict": "GO | CONDITIONAL | NO-GO | FREEZE | UNKNOWN",
  "executive_brief": "Short answer-first IC conclusion.",
  "confidence": 0.0,
  "top_findings": [],
  "key_numbers": [],
  "spreadsheet_audit": {
    "status": "not_provided | completed | failed",
    "summary": "",
    "formula_issues_count": 0,
    "critical_formula_issues_count": 0,
    "source_filename": null
  },
  "critical_risks": [],
  "data_gaps": [],
  "required_actions": [],
  "questions_for_team": [],
  "role_summaries": [],
  "validation": {
    "status": "pass | warn | fail | not_run",
    "summary": "",
    "warnings_count": 0,
    "failures_count": 0
  },
  "artifacts": []
}
```

Limits for UI readability:

- `top_findings`: 3-7 items.
- `critical_risks`: 3-7 items.
- `data_gaps`: 3-7 items.
- `required_actions`: 3-7 items.
- `questions_for_team`: 3-7 items.
- `executive_brief`: 400-1,200 characters.
- Role summary text: 120-500 characters each.

### Role Step Result

Create `contracts/schemas/ic-agentic-role-result.schema.json`.

Required fields:

```json
{
  "role": "ic-financial-auditor",
  "section_keys": ["section_4"],
  "summary": "Role-level finding summary.",
  "findings": [
    {
      "title": "Finding title",
      "severity": "blocker | critical | high | medium | info | data_gap",
      "evidence": "Document or workbook-grounded evidence.",
      "recommendation": "Specific remediation."
    }
  ],
  "data_gaps": [],
  "numbers_used": []
}
```

The raw provider output for each role is stored even if JSON parsing or schema validation fails.

### Legacy-Compatible JSON

The synthesis step also stores `legacy_report_json`, shaped like the original `IC-Agentic-Review` report JSON:

- `meta`
- `sections.section_1` through `sections.section_10`
- `scenarios`
- `formula_issues`
- `kpis`
- `risks_structured`
- `appendices`

This JSON is used only for the original deterministic scripts and validation. The user-facing UI reads the compact result.

## File Map

### Contracts

- Create: `contracts/schemas/ic-agentic-review-result.schema.json`
- Create: `contracts/schemas/ic-agentic-role-result.schema.json`
- Modify: `apps/api/tests/test_contract_schemas.py`

### API Models And Migrations

- Modify: `apps/api/app/models/analysis.py`
- Modify: `apps/api/app/models/skill_source.py`
- Create: `apps/api/alembic/versions/202607090001_ic_agentic_review_runs.py`
- Modify: `apps/api/app/schemas/enums.py`
- Modify: `apps/api/app/schemas/analyses.py`

### API Services And Routers

- Create: `apps/api/app/services/ic_review.py`
- Create: `apps/api/app/routers/ic_review.py`
- Modify: `apps/api/app/main.py`
- Modify: `apps/api/app/services/analysis_jobs.py`
- Modify: `apps/api/app/services/skill_snapshots.py`
- Modify: `apps/api/app/seeds/skills.py`
- Create: `apps/api/tests/test_ic_review_api.py`
- Modify: `apps/api/tests/test_seeds.py`
- Modify: `apps/api/tests/test_skill_sources.py`

### Storage

- Modify: `apps/api/app/storage/local.py`

New storage layout:

```text
{STORAGE_ROOT}/ic-review/{analysis_id}/{run_id}/uploads/{sha256}-{safe_filename}.xlsx
{STORAGE_ROOT}/ic-review/{analysis_id}/{run_id}/prompts/{step_name}.txt
{STORAGE_ROOT}/ic-review/{analysis_id}/{run_id}/raw/{step_name}.txt
{STORAGE_ROOT}/ic-review/{analysis_id}/{run_id}/structured/{step_name}.json
{STORAGE_ROOT}/ic-review/{analysis_id}/{run_id}/scripts/{script_name}.stdout.txt
{STORAGE_ROOT}/ic-review/{analysis_id}/{run_id}/scripts/{script_name}.stderr.txt
{STORAGE_ROOT}/ic-review/{analysis_id}/{run_id}/artifacts/formula_audit.json
{STORAGE_ROOT}/ic-review/{analysis_id}/{run_id}/artifacts/postprocessed_legacy_report.json
{STORAGE_ROOT}/ic-review/{analysis_id}/{run_id}/artifacts/legacy_report.txt
{STORAGE_ROOT}/ic-review/{analysis_id}/{run_id}/artifacts/legacy_audit.xlsx
{STORAGE_ROOT}/ic-review/{analysis_id}/{run_id}/artifacts/validation_report.txt
```

### Worker

- Create: `apps/worker/jobs/run_ic_agentic_review.py`
- Create: `apps/worker/ic_review/__init__.py`
- Create: `apps/worker/ic_review/context.py`
- Create: `apps/worker/ic_review/renderer.py`
- Create: `apps/worker/ic_review/role_runner.py`
- Create: `apps/worker/ic_review/script_runner.py`
- Create: `apps/worker/ic_review/workbook_parser.py`
- Modify: `apps/worker/pyproject.toml`
- Create: `apps/worker/tests/test_ic_review_renderer.py`
- Create: `apps/worker/tests/test_ic_review_script_runner.py`
- Create: `apps/worker/tests/test_run_ic_agentic_review_job.py`

### Frontend

- Modify: `apps/web/src/lib/api/documents.ts`
- Create: `apps/web/src/lib/api/ic-review.ts`
- Modify: `apps/web/src/app/analyses/[analysisId]/page.tsx`
- Modify: `apps/web/src/app/analyses/[analysisId]/analysisDisplay.ts`
- Create: `apps/web/src/app/analyses/[analysisId]/icReviewDisplay.ts`
- Create: `apps/web/src/app/analyses/[analysisId]/icReviewDisplay.test.ts`
- Modify: `apps/web/src/app/analyses/[analysisId]/analysisPage.test.ts`

## Runtime Flow

1. User opens completed analysis.
2. User switches to `IC review` tab.
3. Tab shows latest IC review run if one exists.
4. If no active run exists, user can launch a new run.
5. User optionally selects one `.xlsx` file.
6. API validates analysis access and completed main status.
7. API creates `analysis_check_runs` row with `check_type=ic_agentic_review`.
8. API stores uploaded workbook under `STORAGE_ROOT`.
9. API snapshots the `IC-Agentic-Review` source and links it to the check run.
10. API enqueues `run_ic_agentic_review`.
11. Worker prepares document context from parsed document text and completed main-analysis structured output.
12. If workbook exists, worker extracts a bounded workbook text summary and runs `formula_auditor.py`.
13. Worker renders and runs the eight role prompts through the existing provider adapter.
14. Worker stores each role prompt, raw output, structured output, token counts, latency, and errors.
15. Worker renders synthesis prompt and calls the provider.
16. Worker stores synthesis prompt, raw synthesis output, compact result, and legacy-compatible JSON.
17. Worker runs deterministic scripts from the source snapshot:
    - `json_postprocess.py`
    - save `legacy_report.txt` debug text from the postprocessed JSON
    - `excel_audit.py` only when `.xlsx` is provided
    - `validate_report.py`
18. Worker stores script stdout, stderr, generated artifacts, and validation report.
19. Worker marks run `completed` when compact result validates and scripts finish without `FAIL`.
20. Worker marks run `failed` when compact result cannot be validated, source snapshot is unavailable, provider key is missing, or a required deterministic script fails.

## Tasks

### Task 1: Contracts And Schema Tests

**Files:**

- Create: `contracts/schemas/ic-agentic-review-result.schema.json`
- Create: `contracts/schemas/ic-agentic-role-result.schema.json`
- Modify: `apps/api/tests/test_contract_schemas.py`

- [ ] Add the compact IC review result schema with bounded arrays and `additionalProperties=false`.
- [ ] Add the role result schema with role enum values for the eight IC roles.
- [ ] Add schema tests that validate a minimal compact result, a full compact result, and one role result.
- [ ] Add schema tests that reject unsupported verdicts, missing `spreadsheet_audit.status`, and more than 7 `top_findings`.
- [ ] Run `pytest apps/api/tests/test_contract_schemas.py -q`.

Expected: contract schema tests pass.

Acceptance:

- Schemas are strict enough for UI assumptions.
- The compact result can represent both workbook and no-workbook runs.
- The role result schema can represent each of the eight original IC roles.

### Task 2: Database Models And Migration

**Files:**

- Modify: `apps/api/app/models/analysis.py`
- Modify: `apps/api/app/models/skill_source.py`
- Modify: `apps/api/app/schemas/enums.py`
- Create: `apps/api/alembic/versions/202607090001_ic_agentic_review_runs.py`
- Create: `apps/api/tests/test_ic_review_api.py`
- Modify: `apps/api/tests/test_skill_sources.py`

- [ ] Add `SkillType.ANALYSIS_CHECK = "analysis_check"`.
- [ ] Add model `AnalysisCheckRun` with:
  - `id`
  - `analysis_id`
  - `skill_id`
  - `skill_version`
  - `check_type`
  - `provider`
  - `model`
  - `status`
  - `current_stage`
  - `structured_output`
  - `legacy_output`
  - `raw_output`
  - `error_message`
  - `latency_ms`
  - `input_tokens`
  - `output_tokens`
  - `estimated_cost`
  - `run_parameters`
  - `artifacts`
  - `uploaded_workbook_metadata`
  - `created_at`
  - `started_at`
  - `completed_at`
- [ ] Add model `AnalysisCheckStep` with:
  - `id`
  - `check_run_id`
  - `step_type`
  - `step_name`
  - `status`
  - `prompt_fingerprint`
  - `prompt_artifact_path`
  - `raw_output`
  - `structured_output`
  - `error_message`
  - `latency_ms`
  - `input_tokens`
  - `output_tokens`
  - `estimated_cost`
  - `artifacts`
  - `created_at`
  - `started_at`
  - `completed_at`
- [ ] Extend `SkillSourceSnapshot` with nullable `analysis_check_run_id`.
- [ ] Replace the two-owner check constraint with a three-owner check constraint: exactly one of `analysis_id`, `predicted_comment_run_id`, or `analysis_check_run_id` is not null.
- [ ] Add indexes on `analysis_check_runs.analysis_id, created_at`, `analysis_check_runs.status, created_at`, and `analysis_check_steps.check_run_id, step_name`.
- [ ] Add model persistence tests for run, step, and source snapshot ownership.
- [ ] Run `pytest apps/api/tests/test_ic_review_api.py apps/api/tests/test_skill_sources.py -q`.

Expected: tests pass and Alembic migration upgrades cleanly in test database.

Acceptance:

- IC review runs are separate from main analyses, predicted comments, and detail runs.
- Source snapshots can be linked directly to an IC review run.
- Multiple IC review runs can exist for one completed analysis.

### Task 3: Seed IC Agentic Review Skill Source

**Files:**

- Modify: `apps/api/app/seeds/skills.py`
- Modify: `apps/api/tests/test_seeds.py`
- Modify: `apps/api/tests/test_skill_sources.py`

- [ ] Add environment variable `IC_AGENTIC_REVIEW_SOURCE_PATH` with default `/Users/iseremenko/Documents/IC-Agentic-Review`.
- [ ] Add `SkillSource` seed with slug `ic-agentic-review`, `source_kind=local_git_repo`, entrypoint `.claude/commands/invest-analysis.md`, and required paths listed in this plan.
- [ ] Add `Skill` seed:
  - `name=ic_agentic_review`
  - `version=baseline`
  - `skill_type=analysis_check`
  - `supported_document_types` equal to Gate Challenger document types
  - `result_schema_path=contracts/schemas/ic-agentic-review-result.schema.json`
  - `runtime_mode=snapshot_required`
- [ ] Add seed tests that assert source path, entrypoint, required paths, schema path, and supported document types.
- [ ] Add source manifest test that includes all eight `ic-*.md` agent prompts and all deterministic scripts.
- [ ] Run `pytest apps/api/tests/test_seeds.py apps/api/tests/test_skill_sources.py -q`.

Expected: seed and source snapshot tests pass.

Acceptance:

- New deployments seed IC Agentic Review as an active analysis check skill.
- Historical IC review runs can reproduce the exact source prompt and script set.

### Task 4: API Launch, Read, And Workbook Upload

**Files:**

- Create: `apps/api/app/services/ic_review.py`
- Create: `apps/api/app/routers/ic_review.py`
- Modify: `apps/api/app/main.py`
- Modify: `apps/api/app/services/analysis_jobs.py`
- Modify: `apps/api/app/schemas/analyses.py`
- Modify: `apps/api/app/storage/local.py`
- Create: `apps/api/tests/test_ic_review_api.py`

API endpoints:

```text
POST /analyses/{analysis_id}/ic-review-runs
GET /analyses/{analysis_id}/ic-review-runs
GET /analyses/{analysis_id}/ic-review-runs/latest
GET /ic-review-runs/{run_id}
GET /ic-review-runs/{run_id}/artifacts/{artifact_key}
```

Launch request format:

```text
multipart/form-data
provider=openai_compatible
model=<model>
output_language=ru
financial_model=<optional .xlsx file>
```

- [ ] Implement `create_ic_review_run_for_analysis`.
- [ ] Validate actor can read the parent analysis.
- [ ] Validate parent analysis status is `completed`; otherwise return `409`.
- [ ] Validate selected provider key and model using the same allowlist rules as main analysis.
- [ ] Validate optional workbook extension is exactly `.xlsx`.
- [ ] Store workbook under the IC review storage layout and record filename, size, sha256, and storage path in `uploaded_workbook_metadata`.
- [ ] Create a source snapshot for the `ic-agentic-review` skill and link it to `analysis_check_run_id`.
- [ ] Store `run_parameters` with `output_language`, `spreadsheet_mode`, `source_snapshot_id`, `source_fingerprint`, `source_revision`, and `skill_source_snapshot`.
- [ ] Enqueue `run_ic_agentic_review`.
- [ ] Implement list/latest/read endpoints with the same analysis authorization boundary as main analysis.
- [ ] Hide step raw outputs and artifact paths from non-admin response fields.
- [ ] Implement artifact download through database-owned paths only; never accept a raw filesystem path.
- [ ] Add tests for:
  - cannot launch before main analysis completes;
  - can launch after completed analysis;
  - normal user cannot launch for inaccessible analysis;
  - `.pdf` workbook upload returns `415`;
  - no workbook creates `spreadsheet_mode=not_provided`;
  - workbook upload records sha256 and size;
  - raw outputs are admin-only.
- [ ] Run `pytest apps/api/tests/test_ic_review_api.py -q`.

Expected: IC review API tests pass.

Acceptance:

- IC review is manually launched and gated on completed product analysis.
- Workbook upload is scoped to the IC review run, not to general document upload.
- Uploaded workbook paths are protected by database ownership checks.

### Task 5: Worker Workbook Parser And Script Runner

**Files:**

- Create: `apps/worker/ic_review/workbook_parser.py`
- Create: `apps/worker/ic_review/script_runner.py`
- Modify: `apps/worker/pyproject.toml`
- Create: `apps/worker/tests/test_ic_review_script_runner.py`

- [ ] Add worker dependencies matching the external project runtime: `reportlab`, `openpyxl`, `scipy`, `numpy`, and `PyPDF2`.
- [ ] Implement bounded workbook extraction:
  - max 12 sheets;
  - max 80 rows per sheet;
  - max 30 columns per row;
  - include formulas and data-only values where available;
  - include sheet names and dimensions;
  - redact cells longer than 2,000 characters.
- [ ] Implement `prepare_snapshot_workspace` that copies the source snapshot files into a per-run storage workspace.
- [ ] Implement `run_source_script` using `subprocess.run(["python", "scripts/invest/json_postprocess.py", str(legacy_report_path)], shell=False)` style argument lists assembled by the caller.
- [ ] Set `cwd` to the snapshot workspace root.
- [ ] Capture stdout, stderr, exit code, elapsed milliseconds, and output artifact paths.
- [ ] Implement script calls:
  - `formula_auditor.py <xlsx> --json --output <formula_audit.json>`
  - `json_postprocess.py <legacy_report.json>`
  - Save `<legacy_report.txt>` from `<postprocessed_json>` as a debug artifact instead of generating PDF.
  - `excel_audit.py --source <xlsx> --data <postprocessed_json> --formula-json <formula_audit.json> --output <legacy_audit.xlsx>`
  - `validate_report.py --json <postprocessed_json> --excel <legacy_audit.xlsx>` when workbook exists.
- [ ] For no-workbook runs, skip `formula_auditor.py` and `excel_audit.py`, then run `validate_report.py --json <postprocessed_json>`.
- [ ] Store each script stdout/stderr file even when the script fails.
- [ ] Add tests using tiny fixture scripts under `tmp_path` to verify:
  - no shell is used;
  - stdout/stderr are persisted;
  - nonzero exit code is represented as a failed script result;
  - no-workbook mode skips formula and Excel audit scripts.
- [ ] Run `pytest apps/worker/tests/test_ic_review_script_runner.py -q`.

Expected: script runner tests pass.

Acceptance:

- The worker runs deterministic scripts from the source snapshot.
- Spreadsheet checks only run when the user uploaded `.xlsx`.
- Script logs are saved as first-class reproducibility artifacts.

### Task 6: Prompt Rendering And Role Execution

**Files:**

- Create: `apps/worker/ic_review/context.py`
- Create: `apps/worker/ic_review/renderer.py`
- Create: `apps/worker/ic_review/role_runner.py`
- Create: `apps/worker/tests/test_ic_review_renderer.py`

Role order:

```text
ic-financial-auditor
ic-product-analyst
ic-market-analyst
ic-web-researcher
ic-benchmark-valuation
ic-team-legal
ic-tech-dd
ic-risk-scenario
```

- [ ] Build `ICReviewContext` from:
  - document title;
  - document type;
  - parsed document text;
  - main analysis verdict, summary, structured output, and detail output when present;
  - optional workbook extraction summary;
  - optional formula auditor JSON summary;
  - output language.
- [ ] Build `render_role_prompt` that reads the role prompt from source snapshot and wraps it with:
  - original role instructions;
  - document context;
  - main Gate Challenger result context;
  - workbook context when present;
  - compact role JSON schema;
  - instruction to return only JSON matching `ic-agentic-role-result.schema.json`.
- [ ] Build `render_synthesis_prompt` that reads `.claude/commands/invest-analysis.md`, includes all role structured outputs, and requests:
  - compact UI result;
  - legacy-compatible JSON;
  - no direct PDF prose;
  - Russian output by default.
- [ ] Add renderer tests that assert:
  - all eight role prompt names can be loaded from snapshot;
  - prompt includes the main analysis verdict;
  - prompt includes workbook context only when workbook exists;
  - synthesis prompt includes all eight role outputs;
  - prompt includes the compact schema name.
- [ ] Implement `run_role_step` with existing provider adapter and existing JSON parse/validate helper.
- [ ] Persist `AnalysisCheckStep` before provider call with `status=running`.
- [ ] Persist prompt artifact path and prompt fingerprint before provider call.
- [ ] Persist raw output immediately after provider returns.
- [ ] Persist structured output after schema validation.
- [ ] On role failure, mark the step failed and mark the run failed after saving the error and any available raw output.
- [ ] Run `pytest apps/worker/tests/test_ic_review_renderer.py -q`.

Expected: renderer tests pass.

Acceptance:

- No Claude Code subagent or background-agent mechanism is used.
- Every role is a direct provider call inside one worker job.
- Raw output for each role is saved even when parsing fails.

### Task 7: IC Review Worker Job

**Files:**

- Create: `apps/worker/jobs/run_ic_agentic_review.py`
- Create: `apps/worker/tests/test_run_ic_agentic_review_job.py`

- [ ] Implement `enqueue_run_ic_agentic_review` in `apps/api/app/services/analysis_jobs.py`.
- [ ] Implement worker state transitions:
  - `queued -> running -> completed`
  - `queued -> running -> failed`
  - `queued -> cancelled`
- [ ] Load run, parent analysis, document, skill, provider key, source snapshot, and optional workbook.
- [ ] Set `current_stage=preparing_context`.
- [ ] If workbook exists, run workbook parser and `formula_auditor.py`; store formula audit artifact and log paths.
- [ ] Set `current_stage=role:<role_name>` for each role.
- [ ] Run each role in the required order and persist a step row.
- [ ] Set `current_stage=synthesis`.
- [ ] Render synthesis prompt, persist it, call provider, save raw synthesis output, and validate compact result.
- [ ] Persist `structured_output` from compact result.
- [ ] Persist `legacy_output` from synthesis `legacy_report_json`.
- [ ] Set `current_stage=postprocess`.
- [ ] Run `json_postprocess.py` and update legacy artifact path.
- [ ] Set `current_stage=legacy_artifacts`.
- [ ] Save `legacy_report.txt` debug text from the postprocessed JSON.
- [ ] If workbook exists, run `excel_audit.py`.
- [ ] Set `current_stage=validation`.
- [ ] Run `validate_report.py` and parse counts of `[FAIL]` and `[!]`.
- [ ] Store `validation_report.txt` path and validation summary in `structured_output.validation`.
- [ ] Mark run `completed` when compact schema validation passed and validation report has zero failures.
- [ ] Mark run `failed` when provider, schema, source snapshot, or required script failures prevent a compact result.
- [ ] Add worker tests with mocked provider adapter and fake script runner:
  - completed run without workbook skips spreadsheet audit;
  - completed run with workbook runs formula and Excel audit;
  - role raw output is persisted for all eight roles;
  - synthesis prompt artifact path is persisted;
  - postprocess log and validation report artifact paths are persisted;
  - provider failure after role 3 leaves first three raw outputs saved and marks run failed.
- [ ] Run `pytest apps/worker/tests/test_run_ic_agentic_review_job.py -q`.

Expected: worker job tests pass.

Acceptance:

- One worker job owns the whole IC review flow.
- The run is reproducible from saved document, main analysis, source snapshot, prompts, raw outputs, structured outputs, run parameters, and script artifacts.
- Spreadsheet audit is explicit: `not_provided`, `completed`, or `failed`.

### Task 8: API Read Models And Admin Raw Output

**Files:**

- Modify: `apps/api/app/schemas/analyses.py`
- Modify: `apps/api/app/services/analyses.py`
- Modify: `apps/api/app/services/ic_review.py`
- Create: `apps/api/tests/test_ic_review_api.py`

- [ ] Add `AnalysisCheckRunRead` and `AnalysisCheckStepRead`.
- [ ] Add latest IC review run to `AnalysisRead` as `ic_review_run`.
- [ ] Include only compact `structured_output` for normal users.
- [ ] Include role raw outputs, synthesis raw output, script logs, and artifact paths only for admins.
- [ ] Add `source_trace` support for IC review run source snapshot.
- [ ] Add tests that normal users see run status and compact result but not raw outputs.
- [ ] Add tests that admins see step raw outputs and script artifact metadata.
- [ ] Run `pytest apps/api/tests/test_ic_review_api.py -q`.

Expected: API read model tests pass.

Acceptance:

- The analysis page can render latest IC review state in the same response as main analysis.
- Raw provider and script artifacts follow existing admin visibility rules.

### Task 9: Frontend API Client

**Files:**

- Modify: `apps/web/src/lib/api/documents.ts`
- Create: `apps/web/src/lib/api/ic-review.ts`
- Modify: `apps/web/src/lib/api/documents.test.ts`

- [ ] Add TypeScript types for `AnalysisCheckRunRecord`, `AnalysisCheckStepRecord`, compact IC review result, and validation summary.
- [ ] Add `createIcReviewRun(analysisId, payload)` using `FormData`.
- [ ] Add `getIcReviewRun(runId)`.
- [ ] Add `listIcReviewRuns(analysisId)`.
- [ ] Add `getLatestIcReviewRun(analysisId)`.
- [ ] Add tests that multipart launch sends provider, model, output language, and optional file.
- [ ] Add tests that no-file launch does not append `financial_model`.
- [ ] Run `npm --prefix apps/web run test -- documents`.

Expected: frontend API tests pass.

Acceptance:

- The UI can start and refresh IC review runs without constructing trusted filesystem paths.

### Task 10: Analysis Page IC Review Tab

**Files:**

- Modify: `apps/web/src/app/analyses/[analysisId]/page.tsx`
- Create: `apps/web/src/app/analyses/[analysisId]/icReviewDisplay.ts`
- Create: `apps/web/src/app/analyses/[analysisId]/icReviewDisplay.test.ts`
- Modify: `apps/web/src/app/analyses/[analysisId]/analysisPage.test.ts`

- [ ] Add tab id `icReview` with label `IC review`.
- [ ] Disable launch controls when main analysis status is not `completed`.
- [ ] Show a compact empty state explaining that IC review starts manually after product analysis completion.
- [ ] Add provider/model selection using the same configured model list already used on document detail.
- [ ] Add output language selection.
- [ ] Add `.xlsx` file input with client-side extension check.
- [ ] Add launch button.
- [ ] On launch, create run and set it as current tab state.
- [ ] Poll while run status is `queued` or `running`.
- [ ] Show current stage from `current_stage`.
- [ ] Render completed compact result:
  - verdict;
  - executive brief;
  - top findings;
  - key numbers;
  - spreadsheet audit status;
  - critical risks;
  - data gaps;
  - required actions;
  - questions for team;
  - validation summary.
- [ ] Show failed run error and allow launching a new run.
- [ ] Add tests for:
  - launch disabled before completed analysis;
  - launch enabled after completed analysis;
  - no workbook path shows `Spreadsheet audit not provided`;
  - completed compact result renders all sections;
  - running state shows current stage.
- [ ] Run `npm --prefix apps/web run test -- analysisPage icReviewDisplay`.

Expected: analysis page tests pass.

Acceptance:

- IC review is discoverable inside the analysis page, but never starts automatically.
- The user can upload `.xlsx` directly on the tab.
- The UI stays concise and does not render the legacy PDF report as primary output.

### Task 11: Verification And Regression Suite

**Files:**

- Modify: `TASKS.md`

- [ ] Run API tests:

```bash
pytest apps/api/tests/test_ic_review_api.py apps/api/tests/test_seeds.py apps/api/tests/test_skill_sources.py apps/api/tests/test_contract_schemas.py -q
```

- [ ] Run worker tests:

```bash
pytest apps/worker/tests/test_ic_review_renderer.py apps/worker/tests/test_ic_review_script_runner.py apps/worker/tests/test_run_ic_agentic_review_job.py -q
```

- [ ] Run frontend tests:

```bash
npm --prefix apps/web run test -- analysisPage icReviewDisplay documents
```

- [ ] Run broader affected suites:

```bash
pytest apps/api/tests/test_analyses_api.py apps/api/tests/test_documents_upload.py -q
pytest apps/worker/tests/test_run_analysis_job.py apps/worker/tests/test_run_predicted_comments_job.py -q
npm --prefix apps/web run test
docker compose -f infra/docker-compose.yml config
```

- [ ] Update `TASKS.md` with implementation status and exact verification results.

Acceptance:

- Existing Gate Challenger and Devil's Advocate flows still pass.
- Existing document upload still rejects `.xlsx` in the main document upload path.
- IC review tab accepts `.xlsx` only inside its own launch flow.
- No provider key, raw document, raw provider output, or workbook content is written to application logs.

## Implementation Notes

- Do not change the main document upload supported file list for this plan. `.xlsx` belongs only to IC review launch.
- Do not reuse `predicted_comment_runs`; IC review is not predicted comments.
- Do not call model providers from the frontend.
- Do not trust artifact paths from the frontend.
- Do not store raw private document text in the `IC-Agentic-Review` source repository.
- Do not display legacy PDF as the main result. The compact schema is the product UI contract.
- Do not create commits unless the user explicitly asks.

## Self-Review

Spec coverage:

- Separate tab inside completed analysis: Task 10.
- Manual launch only after product analysis completes: Tasks 4 and 10.
- Optional `.xlsx` upload/parser/audit on the tab: Tasks 4, 5, 7, and 10.
- No workbook means no spreadsheet checks: Tasks 5, 7, and 10.
- Same original deterministic workflow scripts: Task 5 and Task 7.
- Unified worker flow without subagents: Task 6 and Task 7.
- Save raw output for every role: Task 6 and Task 7.
- Save synthesis prompt: Task 6 and Task 7.
- Save postprocess log and validation report: Task 5 and Task 7.
- Short UI-native output based on original structure: Data Contracts and Task 10.
- Reproducible source snapshot: Task 3 and Task 4.

Placeholder scan:

- No placeholder markers or unspecified follow-up placeholders are present.
- Every task names concrete files and verification commands.

Type consistency:

- API and frontend use `AnalysisCheckRun`.
- Database uses `AnalysisCheckRun` and `AnalysisCheckStep`.
- Skill type uses `analysis_check`.
- Skill name uses `ic_agentic_review`.
