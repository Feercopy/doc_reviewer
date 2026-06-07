# Benchmark Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run reproducible benchmark evaluations over active etalons and compare skill, model, and provider quality.

**Architecture:** Benchmark requests create a benchmark row and enqueue a worker job. The worker runs selected analysis skill over each etalon document, calls a judge skill to compare with the etalon, aggregates metrics, and persists a report.

**Tech Stack:** RQ, FastAPI, SQLAlchemy JSONB, Pydantic, provider adapters, pytest.

---

## Files

- Create: `apps/api/app/services/benchmarks.py`
- Create: `apps/api/app/routers/benchmarks.py`
- Create: `apps/api/app/schemas/benchmarks.py`
- Create: `apps/worker/jobs/run_benchmark.py`
- Create: `apps/worker/benchmark/scoring.py`
- Create: `apps/worker/benchmark/judge_prompt.py`
- Create: `apps/worker/benchmark/report_builder.py`
- Create: `apps/api/tests/test_benchmarks_api.py`
- Create: `apps/worker/tests/test_benchmark_scoring.py`
- Create: `apps/worker/tests/test_run_benchmark_job.py`
- Create: `apps/web/src/app/benchmarks/page.tsx`
- Create: `apps/web/src/app/benchmarks/[benchmarkId]/page.tsx`

## API Endpoints

```text
GET /benchmarks
POST /benchmarks
GET /benchmarks/{benchmark_id}
GET /benchmarks/{benchmark_id}/report
POST /benchmarks/{benchmark_id}/cancel
```

## Benchmark Launch Request

```json
{
  "name": "Gate 2 baseline comparison",
  "description": "Main analysis skill v1 over active Gate 2 etalons",
  "etalon_ids": ["uuid"],
  "skill_id": "uuid",
  "provider": "openai_compatible",
  "model": "gpt-4.1",
  "judge_skill_id": "uuid",
  "evaluation_mode": "layer_1_and_layer_2",
  "run_parameters": {
    "temperature": 0.0,
    "max_output_tokens": 6000
  }
}
```

## Metrics

Compute separately for Layer 1 and Layer 2:

- `expected_findings_count`
- `actual_findings_count`
- `exact_matches_count`
- `partial_matches_count`
- `missed_findings_count`
- `false_positives_count`
- `precision = exact_matches_count / actual_findings_count`
- `recall = exact_matches_count / expected_findings_count`
- `f1 = 2 * precision * recall / (precision + recall)`

Rules:

- When denominator is `0`, metric is `0` except when both expected and actual counts are `0`; in that case precision, recall, and F1 are `1`.
- Partial matches are reported separately and do not count as exact matches in MVP precision and recall.
- Judge output must include evidence for each exact match, partial match, miss, and false positive.

## Skill Source Benchmarking

Benchmark records must preserve the source snapshot for every evaluated skill:

- Gate2-challenger source path, entrypoint, git revision, and fingerprint for main analysis runs.
- Devil's Advocate source path, selected wiki page set, git revision, and fingerprint for adversarial / predicted-comments runs when included in the benchmark mode.
- Judge skill source metadata when the judge is also backed by a local prompt or knowledge base.

## Judge Output Contract

```json
{
  "layer_1": {
    "exact_matches": [],
    "partial_matches": [],
    "missed_findings": [],
    "false_positives": []
  },
  "layer_2": {
    "exact_matches": [],
    "partial_matches": [],
    "missed_findings": [],
    "false_positives": []
  },
  "summary": "Short benchmark judgement",
  "recommendations": []
}
```

## Tasks

### Task 1: Benchmark API

- [ ] Implement list benchmarks.
- [ ] Implement create benchmark.
- [ ] Validate selected etalons are active.
- [ ] Validate selected skill is active and type `main_analysis`.
- [ ] Validate judge skill is active and type `benchmark_judge`.
- [ ] Validate provider key availability.
- [ ] Persist skill source snapshots for selected analysis and judge skills.
- [ ] Save all run parameters.
- [ ] Enqueue benchmark job.

Acceptance:

- benchmark row is queued;
- benchmark cannot run over draft etalons;
- all selected parameters are persisted for reproducibility.
- local skill source revisions and fingerprints are persisted for reproducibility.

### Task 2: Scoring Functions

- [ ] Implement metric calculations in `scoring.py`.
- [ ] Add tests for normal case, empty expected, empty actual, both empty, and partial-only matches.

Acceptance:

- scoring tests define denominator behavior;
- Layer 1 and Layer 2 scoring use the same function.

### Task 3: Benchmark Worker Job

- [ ] Set benchmark status `running`.
- [ ] For each etalon, run main analysis against the etalon document parsed text.
- [ ] Use Gate2-challenger renderer for Gate 2 etalons unless a benchmark explicitly selects another skill.
- [ ] Call benchmark judge with actual result and etalon expected structure.
- [ ] Validate judge output schema.
- [ ] Compute per-document Layer 1 and Layer 2 scores.
- [ ] Aggregate overall metrics.
- [ ] Persist missed findings, false positives, partial matches, judge output, and report.
- [ ] Set benchmark status `completed` or `failed`.

Acceptance:

- benchmark stores per-document and aggregate results;
- failed document run is represented in benchmark output and does not erase previous per-document results.

### Task 4: Benchmark Report

- [ ] Build report sections:
  - overall score;
  - result by document;
  - result by layer;
  - main model failures;
  - good match examples;
  - false finding examples;
  - skill improvement recommendations.
- [ ] Store report as JSON in benchmark row and render it in UI.

Acceptance:

- user can open benchmark result;
- report exposes missed findings, false positives, and partial matches.

### Task 5: Frontend Benchmark Pages

- [ ] Build benchmark list with status, provider, model, skill version, score.
- [ ] Build launch form with etalon set, skill, provider, model, judge skill, evaluation mode.
- [ ] Build benchmark result page with score cards and drill-down tables.
- [ ] Add compare affordance by linking benchmark rows with same skill or same etalon set.

Acceptance:

- user can launch benchmark from UI when provider key exists;
- result page presents Layer 1 and Layer 2 separately.

## Verification

Run:

```bash
pytest apps/api/tests/test_benchmarks_api.py apps/worker/tests/test_benchmark_scoring.py apps/worker/tests/test_run_benchmark_job.py -q
```

Expected:

- benchmark API authorization passes;
- scoring edge cases pass;
- worker persists aggregate metrics and judge output.
