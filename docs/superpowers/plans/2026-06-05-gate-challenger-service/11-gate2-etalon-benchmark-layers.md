# Gate2 Etalon Layer Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import Gate2 benchmark originals and Layer 1 / Layer 2 etalons into the project data store, then benchmark Gate Challenger by running the original document through the normal main-analysis flow and judging the resulting layers against the imported etalon with `LLM-as-a-judge для оценки v2.txt`.

**Architecture:** Add an admin-only Gate2 benchmark import path that discovers benchmark cases using the same matching rules as `skillbench`, copies each original document into managed project storage as a first-class `Document`, normalizes the paired Layer 1 / Layer 2 etalon CSV into the service `Etalon` contract stored in PostgreSQL, and stores source hashes for reproducibility. Benchmark runs then execute the selected Gate Challenger skill on the imported original document using the same main-analysis renderer/snapshot path as normal analyses, extract the final Layer 1 and Layer 2 output, and judge that output against the imported etalon using the `LLM-as-a-judge для оценки v2.txt` policy. The improvement-planner/editor loop from `skillbench-orchestrator` is intentionally excluded.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, RQ worker jobs, Python CSV parsing, Next.js TypeScript admin UI, pytest.

**Implementation status 2026-06-17:** Initial branch implementation is in progress. Completed pieces include Gate2 case discovery, CSV normalization, admin import endpoint, managed original document copy, etalon source metadata, benchmark creation etalon snapshots, judge v2 prompt seeding/schema/scoring, layer-only actual/expected benchmark comparison, `.dotx` parsing, and frontend typed API support. Focused API/worker/frontend tests pass locally. Remaining work before merge is broader verification and any product UI polish the team wants beyond the typed import endpoint.

---

## Current Findings

- `EtalonPayload` already has Layer 1 and Layer 2, but the app has no importer for `Gate2-challenger/benchmark/Эталоны`.
- Gate2 originals and etalons must be imported into this service's own database/storage before they are benchmarkable. Runtime benchmark execution must not depend on reading mutable external benchmark files.
- Current benchmark tests use mock full outputs, so they do not catch real Gate2 source snapshot or staged-result issues.
- `run_benchmark` passes the whole actual output to the judge. The `skillbench-orchestrator` reference says scoring must use only normalized Layer 1 and Layer 2.
- `create_benchmark` stores `skill_source_snapshot(skill)` metadata, but it does not create a snapshot artifact path. The Gate2 prompt renderer requires an artifact path for `snapshot_required` skills.
- `Gate2-challenger/benchmark/original` includes `.dotx`, while current document upload and worker parsing support `.docx`, `.pdf`, `.md`, and `.txt`.
- `Gate2-challenger/benchmark/Эталоны/csv_by_document/*.csv` is the most stable import source. Markdown etalons should be stored as trace metadata or fallback only.
- `Gate2-challenger/benchmark/LLM-as-a-judge для оценки v2.txt` is the required judge policy. It uses fixed etalon atomization, pair scores `0..1`, and micro-average totals. Current `scoring.py` averages L1/L2 F1 and treats partials as non-scoring, so it must change.

## Files

- Create: `apps/api/app/services/gate2_benchmark_cases.py`
- Create: `apps/api/alembic/versions/202606170002_add_etalon_source_metadata.py`
- Create: `apps/api/tests/test_gate2_benchmark_import.py`
- Create: `apps/worker/benchmark/layer_outputs.py`
- Create: `apps/worker/benchmark/judge_v2.py`
- Modify: `apps/api/app/core/config.py`
- Modify: `.env.example`
- Modify: `apps/api/app/models/etalon.py`
- Modify: `apps/api/app/schemas/enums.py`
- Modify: `apps/api/app/schemas/etalons.py`
- Modify: `apps/api/app/seeds/skills.py`
- Modify: `apps/api/app/services/documents.py`
- Modify: `apps/api/app/services/etalons.py`
- Modify: `apps/api/app/services/benchmarks.py`
- Modify: `apps/api/app/routers/etalons.py`
- Modify: `apps/api/tests/test_seeds.py`
- Modify: `apps/api/tests/test_etalons.py`
- Modify: `apps/api/tests/test_benchmarks_api.py`
- Modify: `contracts/schemas/benchmark-judge-result.schema.json`
- Modify: `apps/worker/parsers/__init__.py`
- Modify: `apps/worker/jobs/run_benchmark.py`
- Modify: `apps/worker/benchmark/judge_prompt.py`
- Modify: `apps/worker/benchmark/scoring.py`
- Modify: `apps/worker/benchmark/report_builder.py`
- Modify: `apps/worker/tests/test_document_parsers.py`
- Modify: `apps/worker/tests/test_benchmark_scoring.py`
- Modify: `apps/worker/tests/test_run_benchmark_job.py`
- Modify: `apps/web/src/lib/api/etalons.ts`
- Modify: `apps/web/src/app/etalons/page.tsx`
- Modify: `apps/web/src/app/etalons/[etalonId]/page.tsx`

## Data Mapping

Gate2 CSV rows have columns:

```text
section,block,status,item_type,item_id,field,value
```

Layer 1 mapping:

- Verdict row: `section=Layer 1`, `block=verdict`, `field=value`.
- Dimension status row: `section=Layer 1`, `item_type=dimension`, `field=status`.
- Issue rows: `section=Layer 1`, `item_type=issue`, grouped by `(block, item_id)`.
- `EtalonLayer1Item.id`: `L1-{slug(block)}-{item_id}`.
- `dimension`: CSV `block`.
- `status`: lowercased dimension status, mapped to `pass`, `partial`, `fail`, or `not_applicable`.
- `severity`: lowercased issue severity, default `medium` if absent.
- `title` and `summary`: issue text.
- `evidence`: issue evidence with location `Gate2 benchmark etalon: Layer 1 / {block}`.

Layer 2 mapping:

- Atomic check rows: `section=Layer 2`, `item_type=atomic_check`, grouped by `(block, item_id)`.
- `EtalonLayer2Item.id`: `L2-{slug(block)}-{item_id}`.
- `parent_layer_1_id`: first imported Layer 1 issue id for the same `block`; if none exists, create a synthetic Layer 1 item for that block before validation.
- `check`: atomic check `question`.
- `status`: answer mapped as `YES -> pass`, `PARTIAL -> partial`, `NO -> fail`; fallback to block status.
- `severity`: derive `fail -> high`, `partial -> medium`, `pass -> low`, unless a future CSV field supplies severity.
- `finding`: atomic check `issue`.
- `evidence`: atomic check `evidence` with location `Gate2 benchmark etalon: Layer 2 / {block}`.
- `expected_fix`: empty string for MVP because the current Gate2 CSV does not contain a repair field.

Source metadata stored on the etalon:

```json
{
  "source_kind": "gate2_benchmark",
  "case_name": "trx-se",
  "benchmark_dir": "/external/gate-challenger/benchmark",
  "original_path": "benchmark/original/TRX_SE.md",
  "original_sha256": "...",
  "etalon_csv_path": "benchmark/Эталоны/csv_by_document/SE TRX bench.csv",
  "etalon_csv_sha256": "...",
  "etalon_markdown_path": "benchmark/Эталоны/SE TRX bench.md",
  "etalon_markdown_sha256": "...",
  "input_doc_url": "https://...",
  "csv_rows": 123
}
```

Imported project state:

- `documents` row: one managed copy of each original from `benchmark/original`, owned by the importing admin or a dedicated benchmark owner, with raw bytes stored under `STORAGE_ROOT`.
- `documents.parsed_text`: parsed text of that imported original. Benchmark runs read this field, not the external original path.
- `etalons` row: one project etalon per imported Gate2 case, linked by `etalons.document_id` to the imported original document.
- `etalons.layer_1` / `etalons.layer_2`: normalized expected benchmark atoms stored in PostgreSQL JSON.
- `etalons.source_metadata`: provenance only. External paths and hashes explain where the imported data came from, but benchmark execution must use the database/storage copy.
- `skills` row for `benchmark_judge`: prompt text must come from `benchmark/LLM-as-a-judge для оценки v2.txt` when available, with source path/hash captured in skill metadata.

Benchmark execution flow:

1. Resolve active imported etalon rows from PostgreSQL.
2. Load the linked imported original `Document` and its `parsed_text`.
3. Run Gate Challenger main analysis against that document using the selected provider/model and the same Gate2 renderer/source snapshot path used by normal analysis runs.
4. If the main run returns staged summary output, request or run detail expansion so the benchmark has final full Layer 1 and Layer 2.
5. Extract only final actual verdict, Layer 1, and Layer 2 from the main-analysis result.
6. Build judge input from imported expected verdict/Layer 1/Layer 2 and actual verdict/Layer 1/Layer 2.
7. Judge with the v2 policy from `LLM-as-a-judge для оценки v2.txt`.
8. Persist analysis trace, expected output, actual layer output, judge output, and score metrics in the benchmark result.

## Tasks

### Task 1: Branch And Baseline

- [ ] **Step 1: Create implementation branch when work starts**

Run:

```bash
git switch -c codex/gate2-etalon-benchmark-layers
```

Expected: branch is created from the current base. Do this only after the user approves implementation.

- [ ] **Step 2: Confirm clean starting context**

Run:

```bash
git status --short
```

Expected: no unrelated changes are present, or unrelated changes are documented before editing.

### Task 2: Gate2 Benchmark Case Discovery And CSV Normalization

- [ ] **Step 1: Add configuration**

Add `gate2_benchmark_dir` to `apps/api/app/core/config.py`, defaulting to `Path("/external/gate-challenger/benchmark")`, and add `GATE2_BENCHMARK_DIR=/external/gate-challenger/benchmark` to `.env.example`.

- [ ] **Step 2: Write failing tests for case discovery**

Create `apps/api/tests/test_gate2_benchmark_import.py` with a temp benchmark tree containing:

```text
benchmark/original/TRX_SE.md
benchmark/original/travel.dotx
benchmark/Эталоны/SE TRX bench.md
benchmark/Эталоны/Travel bench.md
benchmark/Эталоны/csv_by_document/SE TRX bench.csv
benchmark/Эталоны/csv_by_document/Travel bench.csv
```

Expected assertions:

- `TRX_SE.md` matches `SE TRX bench.csv`;
- `travel.dotx` matches `Travel bench.csv`;
- case names match `trx-se` and `travel`;
- ambiguous or unmatched originals are reported, not silently imported.

- [ ] **Step 3: Implement discovery helper**

Create `apps/api/app/services/gate2_benchmark_cases.py` with:

- token matching equivalent to `Gate2-challenger/skillbench/cases.py`;
- support for `original` suffixes `.md`, `.txt`, `.docx`, `.dotx`;
- preference order: `Эталоны/csv_by_document/*.csv`, then `Эталоны/normalized/*`, then `Эталоны/*`;
- SHA-256 calculation for original, CSV, and Markdown etalon files.

- [ ] **Step 4: Write failing tests for CSV normalization**

Use a compact CSV fixture with one verdict, two Layer 1 issues, and two Layer 2 atomic checks. Expected:

- verdict `NEED_EVIDENCE` becomes `need_evidence`;
- Layer 1 IDs are stable and unique;
- Layer 2 parent ids point to existing Layer 1 ids;
- uppercase statuses and severities become service enum values;
- missing Layer 2 severity is derived.

- [ ] **Step 5: Implement CSV-to-`EtalonPayload` parser**

Implement pure functions:

```python
discover_gate2_benchmark_cases(benchmark_dir: Path) -> list[Gate2BenchmarkCase]
parse_gate2_etalon_csv(path: Path) -> Gate2EtalonParseResult
gate2_case_to_etalon_payload(case: Gate2BenchmarkCase) -> EtalonPayload
```

Expected: parser output validates through `EtalonPayload.model_validate`.

### Task 3: Etalon Source Metadata And Import Source Type

- [ ] **Step 1: Add enum value**

Add `EtalonSource.GATE2_BENCHMARK = "gate2_benchmark"` in `apps/api/app/schemas/enums.py`.

- [ ] **Step 2: Add metadata column**

Create Alembic migration `202606170002_add_etalon_source_metadata.py`:

```python
op.add_column("etalons", sa.Column("source_metadata", sa.JSON(), nullable=False, server_default="{}"))
op.alter_column("etalons", "source_metadata", server_default=None)
```

Downgrade removes the column.

- [ ] **Step 3: Update model and schema**

Add `source_metadata: Mapped[dict]` to `apps/api/app/models/etalon.py` and `source_metadata: dict` to `EtalonRead`.

- [ ] **Step 4: Backfill constructor call sites**

All existing `Etalon(...)` constructors in services and tests must pass `source_metadata={}` unless they are Gate2 imports.

### Task 4: Admin Import Endpoint

- [ ] **Step 1: Add local-file document creation helper**

In `apps/api/app/services/documents.py`, add a helper that copies a trusted local benchmark original into `LocalDocumentStorage`, creates a `Document`, and sets:

- `owner_id` to the importing admin;
- `manual_document_type` default `gate_2`;
- `parse_status=queued`;
- `original_filename` from the external file name.

This helper must still use `LocalDocumentStorage.save_raw_file` so frontend and worker file access remain guarded by database ownership checks.

- [ ] **Step 2: Add `.dotx` support**

Add `.dotx` to API supported document extensions and worker `parse_file`. Route `.dotx` through the existing DOCX parser.

- [ ] **Step 3: Implement import service**

In `apps/api/app/services/etalons.py`, add:

```python
import_gate2_benchmark_etalons(
    *,
    db: Session,
    actor: User,
    storage: LocalDocumentStorage,
    benchmark_dir: Path,
    activate: bool,
) -> Gate2ImportResult
```

Rules:

- admin only;
- discover cases from `benchmark_dir`;
- create or reuse stored `Document` by original SHA-256 and source metadata;
- create etalon from parsed CSV payload;
- store `source=gate2_benchmark`;
- store source metadata and original document link;
- default to `draft`; allow `active` only when `activate=true`;
- enqueue parse jobs for newly created or unparsed documents.

- [ ] **Step 4: Add API endpoint**

Add:

```text
POST /etalons/import/gate2-benchmark
```

Request:

```json
{
  "benchmark_dir": null,
  "activate": true
}
```

Response includes imported, skipped, updated, unmatched, and parse-enqueued case counts plus imported `EtalonRead` rows.

- [ ] **Step 5: Add API tests**

Cover:

- non-admin gets `403`;
- admin imports four sample cases from temp benchmark directory;
- imported etalon has Layer 1 and Layer 2;
- imported etalon points to the imported document;
- source metadata contains paths and hashes;
- `.dotx` original is accepted and parse job is enqueued;
- reimport with unchanged hashes is idempotent.

### Task 5: LLM-as-a-judge V2 Prompt And Scoring Contract

- [ ] **Step 1: Seed the v2 judge prompt**

Update `apps/api/app/seeds/skills.py` so the `benchmark_judge` skill reads prompt text from:

```text
{GATE2_BENCHMARK_DIR}/LLM-as-a-judge для оценки v2.txt
```

when the file exists. Store the prompt source path and SHA-256 in `Skill.source_metadata`.

Expected fallback: if the file is unavailable in a test or non-Gate2 environment, keep the existing inline fallback prompt but mark `source_metadata={"fallback": true}`.

- [ ] **Step 2: Add seed tests**

In `apps/api/tests/test_seeds.py`, add coverage that a temp `LLM-as-a-judge для оценки v2.txt` becomes the `benchmark_judge.prompt_text` and that its hash is captured.

- [ ] **Step 3: Upgrade judge result schema**

Modify `contracts/schemas/benchmark-judge-result.schema.json` to support the v2 policy as JSON:

```json
{
  "layer_1": {
    "n_ref": 13,
    "n_pred": 12,
    "score_sum": 9.75,
    "precision": 81.25,
    "recall": 75.0,
    "f1": 78.0,
    "matched": [
      {
        "ref_id": "Layer 1 / Problem framing and segments / item 1",
        "block": "Problem framing and segments",
        "expected": "...",
        "actual": "...",
        "score": 0.75,
        "comment": "...",
        "mapping_note": null
      }
    ],
    "missed_issues": [],
    "false_positives": [],
    "duplicates": [],
    "summary": "..."
  },
  "layer_2": {
    "n_ref": 40,
    "n_pred": 38,
    "score_sum": 30.5,
    "precision": 80.26,
    "recall": 76.25,
    "f1": 78.2,
    "matched": [],
    "missed_issues": [],
    "false_positives": [],
    "duplicates": [],
    "summary": "..."
  },
  "overall": {
    "n_ref_total": 53,
    "n_pred_total": 50,
    "score_sum_total": 40.25,
    "precision": 80.5,
    "recall": 75.94,
    "f1": 78.15
  },
  "diagnostics": {
    "valid_extra_insights_count": 0,
    "unsupported_or_wrong_false_positives_count": 0,
    "duplicate_count": 0,
    "main_reasons": [],
    "strengths": []
  },
  "recommendations": []
}
```

Keep backward-compatible normalization in worker tests only if existing persisted mock results need it; new benchmark results should use the v2 shape.

- [ ] **Step 4: Add judge prompt builder tests**

In `apps/worker/tests/test_run_benchmark_job.py`, assert that judge input includes:

- `LLM-as-a-judge для оценки v2` prompt text;
- expected Layer 1 and Layer 2 from imported etalon;
- actual Layer 1 and Layer 2 from Gate Challenger output;
- no Layer 3, no executive summary, no final synthesis.

- [ ] **Step 5: Update scoring to v2 micro-average**

Modify `apps/worker/benchmark/scoring.py` so scores come from the judge v2 fields:

- per-layer `precision`, `recall`, `f1`;
- overall `precision`, `recall`, `f1`;
- `score_sum_total / n_pred_total` and `score_sum_total / n_ref_total` micro-average behavior.

If judge output omits `overall`, compute it from `layer_1.score_sum`, `layer_2.score_sum`, `layer_1.n_ref`, `layer_2.n_ref`, `layer_1.n_pred`, and `layer_2.n_pred`.

- [ ] **Step 6: Add scoring tests**

In `apps/worker/tests/test_benchmark_scoring.py`, add cases proving:

- partial match score `0.5` contributes to both precision and recall;
- false positives reduce precision through `n_pred`;
- missed issues reduce recall through `n_ref`;
- overall score uses micro-average, not `(L1 F1 + L2 F1) / 2`.

### Task 6: Benchmark Creation Reproducibility

- [ ] **Step 1: Snapshot selected skills for benchmark runs**

Move analysis snapshot attachment logic into a shared service or add benchmark-specific equivalent in `apps/api/app/services/benchmarks.py`.

Expected run parameters:

```json
{
  "source_snapshot_id": "...",
  "source_snapshot_artifact_path": "...",
  "skill_source_snapshot": {
    "artifact_path": "...",
    "snapshot_mode": "production_latest"
  },
  "judge_skill_source_snapshot": {...}
}
```

- [ ] **Step 2: Store imported etalon snapshots in benchmark parameters**

At benchmark creation, store a read-time copy of each selected etalon's expected verdict, Layer 1, Layer 2, document id, document hash, and `source_metadata` in `run_parameters["etalon_snapshots"]`.

- [ ] **Step 3: Validate benchmark input documents are parsed**

Extend `_resolve_active_etalons` to reject active etalons whose original document is not `parse_status=completed` or has empty `parsed_text`.

- [ ] **Step 4: Add API tests**

Cover:

- benchmark over imported Gate2 etalon stores skill artifact snapshot path;
- benchmark over unparsed imported document returns `409`;
- benchmark stores `etalon_snapshots` with Layer 1 and Layer 2.

### Task 7: Worker Main-Run Layer Benchmark Execution

- [ ] **Step 1: Add actual-output extractor tests**

Create worker tests for `apps/worker/benchmark/layer_outputs.py`:

- full `main-analysis-result` returns verdict, Layer 1, and Layer 2;
- summary-only result with `layer_1_index/layer_2_index` is rejected for benchmark scoring;
- detail-style result returns Layer 1 and Layer 2;
- malformed result raises a clear `BenchmarkLayerOutputError`.

- [ ] **Step 2: Implement layer extraction**

Create:

```python
def extract_benchmark_layers(output: dict) -> dict:
    ...
```

Return only:

```json
{
  "verdict": "need_evidence",
  "layer_1": [...],
  "layer_2": [...]
}
```

Do not include executive summary, Layer 3, merged blockers, full synthesis, or improvement recommendations.

- [ ] **Step 3: Update judge prompt input**

Modify `build_judge_prompt` so the judge receives:

- expected verdict;
- expected Layer 1;
- expected Layer 2;
- actual verdict;
- actual Layer 1;
- actual Layer 2;
- judge prompt text.

It must not receive Layer 3 or synthesis data.

- [ ] **Step 4: Update `run_benchmark` to use the main-analysis path**

In `_run_one_etalon`:

- create or persist a benchmark document run trace for the imported original document;
- run Gate Challenger against that document with the same renderer, source snapshot, provider/model, and run-parameter handling used by normal main analysis;
- if the result is staged summary output, run or request the detail expansion and use the completed detail output for benchmark scoring;
- parse full provider output;
- call `extract_benchmark_layers(actual_output)`;
- use the benchmark-time etalon snapshot as expected output when available;
- call judge with layer-only actual output;
- compute scores using the judge v2 micro-average contract;
- persist `analysis_id` or equivalent benchmark run trace id, `detail_run_id` when used, `expected_output`, `actual_output`, `judge_output`, and `scores` in each document result.

- [ ] **Step 5: Add worker tests**

Cover:

- real benchmark run uses only `actual_output.layer_1/layer_2` in judge prompt;
- Layer 3 in actual output is not sent to judge;
- summary-only actual output fails that document with a clear error;
- completed documents still aggregate when one case fails;
- expected output is persisted per document for reproducibility.

### Task 8: Report And UI Traceability

- [ ] **Step 1: Update report builder**

Add per-document report fields:

- case name;
- document title;
- original filename;
- source original path/hash;
- source etalon path/hash;
- Layer 1 counts and F1;
- Layer 2 counts and F1;
- failed document error if any.

- [ ] **Step 2: Update frontend etalon types**

Expose `source_metadata` in `apps/web/src/lib/api/etalons.ts`.

- [ ] **Step 3: Update etalon pages**

Show Gate2 source trace on etalon list/detail when `source === "gate2_benchmark"`:

- case name;
- original file path;
- etalon CSV path;
- imported hashes.

- [ ] **Step 4: Add import affordance**

On admin-visible `/etalons`, add a compact Gate2 benchmark import action that calls `POST /etalons/import/gate2-benchmark` and shows imported/skipped/queued counts.

- [ ] **Step 5: Add frontend tests**

Cover:

- Gate2 source metadata renders on detail page;
- import action shows success counts;
- non-admin navigation remains unchanged.

### Task 9: Verification

- [ ] **Step 1: API focused tests**

Run:

```bash
pytest apps/api/tests/test_gate2_benchmark_import.py apps/api/tests/test_etalons.py apps/api/tests/test_benchmarks_api.py -q
```

Expected: import, etalon validation, and benchmark creation tests pass.

- [ ] **Step 2: Worker focused tests**

Run:

```bash
pytest apps/worker/tests/test_document_parsers.py apps/worker/tests/test_benchmark_scoring.py apps/worker/tests/test_run_benchmark_job.py -q
```

Expected: `.dotx` parsing, scoring, layer-only judge input, and benchmark persistence tests pass.

- [ ] **Step 3: Frontend focused tests**

Run:

```bash
npm --prefix apps/web run test -- etalons benchmarks
```

Expected: changed etalon/benchmark UI tests pass.

- [ ] **Step 4: Broader checks**

Run:

```bash
pytest apps/api/tests -q
pytest apps/worker/tests -q
npm --prefix apps/web run test
docker compose -f infra/docker-compose.yml config
```

Expected: all available checks pass.

- [ ] **Step 5: Local UI rebuild after frontend changes**

Run:

```bash
docker compose -f infra/docker-compose.yml up -d --build web
```

Expected: web container is rebuilt so `/etalons` and `/benchmarks` show the updated UI.

## Acceptance Criteria

- Admin can import Gate2 benchmark cases from `Gate2-challenger/benchmark`.
- Each imported original exists as a managed project `Document` row with raw bytes copied under `STORAGE_ROOT`.
- Each imported etalon exists as a project `Etalon` row with non-empty PostgreSQL-stored Layer 1 and Layer 2.
- Each imported etalon is linked to the managed `Document` copied from `benchmark/original`.
- Source paths and SHA-256 hashes for original and etalon files are stored.
- Benchmark creation refuses imported etalons whose original document is not parsed.
- Real Gate2 benchmark runs have a usable skill source snapshot artifact path.
- Benchmark execution first runs Gate Challenger main analysis on the imported original document, then extracts final Layer 1 and Layer 2 for judging.
- Judge policy comes from `Gate2-challenger/benchmark/LLM-as-a-judge для оценки v2.txt`.
- Judge input contains only expected/actual verdict, Layer 1, and Layer 2.
- Layer 3, executive summary, final synthesis, and improvement-analysis artifacts are excluded from scoring.
- Benchmark result persists per-document main-analysis trace, expected output, actual layer output, judge output, and scores.
- Partial matches contribute numeric score according to judge v2, and overall benchmark metrics use micro-average.
- Reports and UI show Layer 1, Layer 2, and overall v2 metrics separately.

## Non-Goals

- Do not implement the `skillbench-orchestrator` improvement planner.
- Do not edit Gate2 skill prompts, judge prompts, benchmark originals, or etalon files.
- Do not add scheduled or bulk benchmark automation beyond the existing benchmark run flow.
- Do not use Layer 3 for score credit until the etalon contract explicitly includes Layer 3.
- Do not leave benchmark originals or etalons as external-only references; external paths are provenance, not runtime data.

## Open Decisions Before Implementation

- Whether the import endpoint should default `activate` to `true` for admin convenience or `false` for safer review.
- Whether reimporting changed Gate2 source files should update the existing etalon version or archive the old etalon and create a new one.
- Whether the UI import action should be available only on `/etalons` or also on `/benchmarks` as a preflight action.
