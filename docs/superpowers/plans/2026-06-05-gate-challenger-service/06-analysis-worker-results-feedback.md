# Analysis Worker, Results, and Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run document analyses asynchronously, persist reproducible results, run predicted-comments analysis, and collect user feedback.

**Architecture:** The API creates analysis rows and enqueues jobs. The worker loads the document, skill, provider key, and run parameters; calls the provider; validates or repairs JSON; persists structured and raw output; then enqueues predicted-comments analysis.

**Tech Stack:** RQ, Redis, FastAPI, SQLAlchemy, Pydantic, jsonschema, provider adapters.

---

## Files

- Create: `apps/api/app/services/analyses.py`
- Create: `apps/api/app/routers/analyses.py`
- Create: `apps/api/app/routers/feedback.py`
- Create: `apps/api/app/schemas/analyses.py`
- Create: `apps/api/app/schemas/feedback.py`
- Create: `apps/worker/jobs/run_analysis.py`
- Create: `apps/worker/jobs/run_predicted_comments.py`
- Create: `apps/worker/results/json_repair.py`
- Create: `apps/worker/results/schema_validation.py`
- Create: `apps/api/tests/test_analyses_api.py`
- Create: `apps/api/tests/test_feedback.py`
- Create: `apps/worker/tests/test_run_analysis_job.py`
- Create: `apps/worker/tests/test_json_repair.py`
- Create: `apps/web/src/app/analyses/[analysisId]/page.tsx`
- Create: `apps/web/src/components/analysis/Layer1Panel.tsx`
- Create: `apps/web/src/components/analysis/Layer2Table.tsx`
- Create: `apps/web/src/components/analysis/PredictedCommentsPanel.tsx`
- Create: `apps/web/src/components/analysis/FeedbackForm.tsx`

## API Endpoints

```text
POST /documents/{document_id}/analyses
GET /documents/{document_id}/analyses
GET /analyses/{analysis_id}
GET /analyses/{analysis_id}/raw-output
POST /analyses/{analysis_id}/feedback
GET /admin/feedback
PATCH /admin/feedback/{feedback_id}/processed
```

## Analysis Launch Request

```json
{
  "provider": "openai_compatible",
  "model": "gpt-4.1",
  "skill_id": "uuid",
  "document_type_override": "gate_2",
  "run_parameters": {
    "temperature": 0.2,
    "max_output_tokens": 6000
  }
}
```

## Worker State Transitions

Main analysis:

```text
queued -> running -> completed
queued -> running -> failed
queued -> cancelled
```

Predicted-comments run:

```text
queued after main analysis completed
running
completed or failed
```

Default skill mapping:

- `Gate 2` main analysis uses `gate2_challenger_main_analysis`.
- Predicted-comments / adversarial review uses `devils_advocate_predefense` after the main analysis completes.
- Generic `predicted_comments` is used only when Devil's Advocate is disabled, source validation fails, or the document type is outside the Devil's Advocate scope.

Failure handling:

- provider error: store raw provider error and user-facing error message;
- invalid JSON: store raw output, try repair once, validate repaired JSON;
- repair failure: mark failed and keep raw output;
- missing provider key: mark failed with `provider_key_missing`;
- Hermes disabled: mark failed with `provider_unavailable`.
- external skill source missing or fingerprint mismatch: mark failed with `skill_source_unavailable` before provider call.

## Tasks

### Task 1: Analysis API

- [ ] Implement create analysis endpoint.
- [ ] Validate document ownership.
- [ ] Validate document parse status is `completed`.
- [ ] Validate selected skill is active and type `main_analysis`.
- [ ] Resolve default skill to `gate2_challenger_main_analysis` when document type is `gate_2` and user did not override skill.
- [ ] Validate provider settings exist unless provider is enabled Hermes.
- [ ] Snapshot skill source metadata into `run_parameters`.
- [ ] Create analysis row with full run parameters.
- [ ] Enqueue `run_analysis`.

Acceptance:

- cannot analyze another user's document;
- cannot analyze unparsed document;
- analysis row is queued and reproducible parameters are saved.
- Gate 2 analysis records include Gate2-challenger source path, entrypoint, revision, and fingerprint.

### Task 2: Main Analysis Job

- [ ] Load analysis row.
- [ ] Set status `running` and `started_at`.
- [ ] Render prompt.
- [ ] For `gate2_challenger_main_analysis`, render through the Gate2-challenger renderer.
- [ ] Call provider adapter.
- [ ] Save raw output.
- [ ] Parse JSON.
- [ ] Try repair once if JSON parse fails.
- [ ] Validate against main analysis schema.
- [ ] Save structured output, verdict, summary, tokens, cost, latency.
- [ ] Set status `completed`.
- [ ] Enqueue predicted-comments job.

Acceptance:

- successful run persists structured output and raw output;
- failed run records error and raw output if available;
- predicted-comments job is queued only after completed main analysis.

### Task 3: Predicted Comments Job

- [ ] Load completed main analysis.
- [ ] Load active `devils_advocate_predefense` skill by default.
- [ ] Include main Layer 1 and Layer 2 findings in prompt context.
- [ ] Render Devil's Advocate in `run_mode = ic_voting_full` by default, following the full `ic-voting-prompt.md` orchestration.
- [ ] Include document type, detected domain signals, main verdict, and selected Devil's Advocate wiki page citations.
- [ ] Call same provider and model by default.
- [ ] Validate against `devils-advocate-result.schema.json`.
- [ ] Map `comment_records`, `trailer`, `ic_decision`, `predicted_comments`, consulted pages, and citations into the result UI's Devil's Advocate block.
- [ ] Persist row in `predicted_comment_runs`.

Acceptance:

- result page can show predicted comments separately from main analysis;
- result page can show Devil's Advocate anchored comments, brutal truth, contradictions, tough questions, actionable JTBDs, IC decision, and consulted wiki pages;
- `/ic:query` result shape is used only when the run was explicitly created with a query run mode;
- failure of second skill does not invalidate completed main analysis.

### Task 4: Analysis Result API

- [ ] Implement analysis detail endpoint.
- [ ] Return main structured output.
- [ ] Return predicted-comments output when available.
- [ ] Hide raw output from non-admins.
- [ ] Include document metadata, provider, model, skill version, timestamps.

Acceptance:

- user sees own result;
- admin can see raw output;
- non-admin cannot see raw output.

### Task 5: Feedback API

- [ ] Implement feedback create endpoint.
- [ ] Validate feedback belongs to current user's accessible analysis.
- [ ] Persist usefulness, verdict correctness, false findings, missed findings, comment, benchmark-use checkbox.
- [ ] Implement admin feedback list and processed marker.

Acceptance:

- feedback is linked to user, document, analysis, provider, model, skill, and skill version;
- admin can filter feedback by model, skill, user, verdict.

### Task 6: Frontend Result UI

- [ ] Build result top card with document title, type, date, verdict, provider, model, skill version, status.
- [ ] Build short summary section.
- [ ] Build Layer 1 panel for dimensions from the spec.
- [ ] Build Layer 2 table with status, severity, evidence, recommendation, confidence.
- [ ] Build predicted-comments panel.
- [ ] Build full structured output view.
- [ ] Build admin-only raw output view.
- [ ] Build feedback form.

Acceptance:

- page supports readable drill-down from summary to Layer 2;
- predicted comments are visible as a separate block;
- feedback submission works from the result page.

## Verification

Run:

```bash
pytest apps/api/tests/test_analyses_api.py apps/api/tests/test_feedback.py apps/worker/tests/test_run_analysis_job.py apps/worker/tests/test_json_repair.py -q
```

Expected:

- API tests pass;
- worker tests cover success, invalid JSON repair, provider failure, missing key, and Hermes unavailable.
