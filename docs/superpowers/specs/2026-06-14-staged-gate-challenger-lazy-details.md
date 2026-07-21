# Staged Gate Challenger Lazy Details Technical Specification

## Goal

Reduce first-run Gate Challenger output size and timeout risk while preserving
the current skill-driven analysis workflow, traceability, and reader experience.

The target experience:

- Devil's Advocate runs first and keeps the current behavior and UI.
- Gate Challenger runs next and performs the full reasoning work, but the
  first visible result is only the final summary/verdict.
- `Document comments` continues to show comments from Devil's Advocate.
- `Full Output` does not show full Gate Challenger Layer 1 / Layer 2 blocks
  until the user explicitly requests them.
- Clicking `Load details` starts a follow-up model request that returns Layer 1
  and Layer 2 details using the Gate Challenger context already created by the
  first request.

## Current Behavior

The current pipeline is stateless at the provider API layer:

1. API creates an `analyses` row and enqueues `run_analysis`.
2. Worker runs Devil's Advocate as a `predicted_comment_runs` row.
3. Worker converts completed Devil's Advocate output into
   `gate_challenger_layer_4_context`.
4. Worker renders one large Gate Challenger prompt and sends it through
   `/v1/chat/completions`.
5. Worker validates the full Gate Challenger response against
   `contracts/schemas/main-analysis-result.schema.json`.
6. The current main schema requires full `layer_1_markdown`, `layer_1`,
   `layer_2_markdown`, and `layer_2` in the first response.

This forces the first Gate Challenger call to generate both reader-facing
summary and full detailed checks.

## admllm Probe Findings

The isolated probe in `prototypes/admllm-session-probe` confirmed:

- `/v1/responses` works for `openai/gpt-5.5`.
- `previous_response_id` works.
- A follow-up request remembered a synthetic marker without the script
  resending it.
- `background=true` and response polling work.
- `/v1/responses/compact` is accepted.
- `/v1/responses/{id}/input_items` returned `400 model=None` for this route
  even after retrying with `model=openai/gpt-5.5`.

Implication: lazy detail loading should use `/v1/responses` and
`previous_response_id`. It should not depend on `input_items`.

## Proposed Flow

### Stage 1: Devil's Advocate

Keep existing logic unchanged:

- Run `devils_advocate_predefense` before Gate Challenger.
- Persist output in `predicted_comment_runs`.
- Preserve structured output, raw output, prompt fingerprint, skill snapshot,
  retrieval snapshot, usage, latency, and error state.
- Continue rendering `Document comments` from Devil's Advocate `role_comments`.
- Continue rendering Devil's Advocate output in `Full Output` as before.

### Stage 2: Gate Challenger Summary Run

Replace the first Gate Challenger provider call with a Responses API call.

The worker sends the normal Gate Challenger inputs:

- document title;
- document type;
- parsed document text;
- Gate Challenger skill snapshot;
- Gate Challenger references;
- response language;
- Devil's Advocate Layer 4 context;
- source and prompt trace metadata.

But the requested output contract changes from full details to compact summary:

- `verdict`;
- `summary`;
- `assessment_markdown`;
- compact `layer_1_index`;
- compact `layer_2_index`;
- `details_status: "not_requested"`;
- `details_run_id: null`;
- `revision_required: false`;
- `revision_reason: null`.

The compact indexes are not intended to replace the full layers in the UI.
They are persisted so the first verdict remains evidence-backed and the lazy
detail request has an explicit analysis state to expand.

The worker persists:

- normal `analyses` fields;
- `structured_output` with compact summary contract;
- `raw_output`;
- usage and latency;
- `run_parameters.gate_challenger_response_id`;
- `run_parameters.provider_api = "responses"`;
- prompt artifact path and prompt fingerprint.

The analysis status becomes `completed` after the summary response is valid.

### Stage 3: Full Output Before Details

`Full Output` should not render full Gate Challenger Layer 1 / Layer 2 blocks
because they do not exist yet.

Instead, the page shows:

- Gate Challenger structured summary JSON;
- Devil's Advocate output as today;
- raw outputs when the current actor is allowed to see them;
- `Load detailed Layer 1 / Layer 2` button.

The button is shown when:

- `analysis.status == completed`;
- Gate Challenger summary output exists;
- no completed detail run exists;
- no detail run is currently queued/running.

### Stage 4: Lazy Gate Challenger Details

When the user clicks `Load detailed Layer 1 / Layer 2`, the frontend calls:

```text
POST /analyses/{analysis_id}/details
```

The API:

- verifies the actor can read the analysis;
- verifies the main analysis is completed;
- verifies the main analysis has `gate_challenger_response_id`;
- returns the existing detail run if one is already queued/running/completed;
- otherwise creates a new detail run and enqueues a worker job.

The worker sends a follow-up `/v1/responses` request with:

- `model`;
- `previous_response_id = analysis.run_parameters.gate_challenger_response_id`;
- instruction to expand Layer 1 and Layer 2 details;
- the compact `structured_output` from Stage 2;
- the same response language;
- the same trace metadata;
- a schema for detailed output.

The detail prompt must say:

- expand the already produced Gate Challenger analysis state;
- preserve the original `verdict` and `summary`;
- do not invent new document evidence;
- return full Layer 1 / Layer 2 details;
- if details contradict the Stage 2 verdict, set `revision_required: true`
  and explain why instead of silently changing the verdict.

The detail worker persists:

- detail run status;
- `previous_response_id`;
- detail response id;
- structured output;
- raw output;
- usage and latency;
- prompt artifact path and prompt fingerprint;
- error message when failed.

The frontend polls until the detail run reaches a terminal state.

## Data Model

Add a new table, tentatively named `analysis_detail_runs`.

Fields:

```text
id uuid primary key
analysis_id uuid references analyses(id)
status string
provider string
model string
previous_response_id text nullable
response_id text nullable
structured_output json nullable
raw_output text nullable
error_message text nullable
latency_ms integer nullable
input_tokens integer nullable
output_tokens integer nullable
estimated_cost numeric nullable
run_parameters json not null default {}
created_at timestamp with time zone
started_at timestamp with time zone nullable
completed_at timestamp with time zone nullable
```

Indexes:

```text
analysis_id, created_at
status, created_at
provider, model
```

Only one active detail run should exist per analysis. If a completed detail run
already exists, `POST /analyses/{analysis_id}/details` returns it instead of
creating another one. A future explicit rerun endpoint can be added later if
needed.

## Contracts

### Summary Contract

Create:

```text
contracts/schemas/main-analysis-summary-result.schema.json
```

Required fields:

```json
{
  "verdict": "need_evidence",
  "summary": "Short summary text",
  "assessment_markdown": "Reader-facing Gate Challenger summary",
  "layer_1_index": [
    {
      "id": "l1-traction",
      "severity": "high",
      "issue": "Traction evidence is not decision-grade",
      "evidence_anchor": "Exact or near-exact document anchor"
    }
  ],
  "layer_2_index": [
    {
      "id": "l2-traction-1",
      "parent_layer_1_id": "l1-traction",
      "status": "fail",
      "severity": "high",
      "question": "Atomic Gate Challenger question",
      "answer": "NO",
      "short_evidence": "Compact evidence statement"
    }
  ],
  "details_status": "not_requested",
  "details_run_id": null,
  "revision_required": false,
  "revision_reason": null
}
```

### Details Contract

Create:

```text
contracts/schemas/main-analysis-details-result.schema.json
```

Required fields:

```json
{
  "analysis_id": "uuid",
  "verdict": "need_evidence",
  "summary": "Same summary unless revision_required is true",
  "layer_1_markdown": "Full reader-facing Layer 1 block",
  "layer_1": [
    {
      "id": "l1-traction",
      "severity": "high",
      "issue": "Full issue text",
      "evidence": "Full evidence text"
    }
  ],
  "layer_2_markdown": "Full reader-facing Layer 2 block",
  "layer_2": [
    {
      "id": "l2-traction-1",
      "parent_layer_1_id": "l1-traction",
      "status": "fail",
      "severity": "high",
      "question": "Atomic Gate Challenger question",
      "answer": "NO",
      "evidence": "Full evidence text",
      "issue": "Full issue text"
    }
  ],
  "revision_required": false,
  "revision_reason": null
}
```

## Provider Adapter

Add Responses API support behind the provider adapter boundary.

Do not call model providers from the frontend.

Suggested API:

```python
class ProviderAdapter:
    def run(self, request: ProviderRunRequest) -> AnalysisProviderResult:
        ...

    def run_response(self, request: ProviderResponseRequest) -> AnalysisProviderResult:
        ...
```

`ProviderResponseRequest` should include:

```text
provider
model
api_key
base_url
input
response_schema
run_parameters
previous_response_id
background
```

For `openai_compatible`, use `/v1/responses` when
`run_parameters.provider_api == "responses"`.

The adapter must capture:

- `response_id`;
- raw provider output;
- structured text;
- input/output tokens;
- latency;
- provider metadata.

For long-running detail requests, use `background=true` only if synchronous
Responses API still times out in practice. The first implementation can use
normal `/v1/responses` and keep `background=true` as a fallback.

## API

Add endpoints:

```text
POST /analyses/{analysis_id}/details
GET /analyses/{analysis_id}/details
```

`GET /analyses/{analysis_id}` should include the latest detail run summary:

```json
{
  "detail_run": {
    "id": "uuid",
    "status": "completed",
    "structured_output": {},
    "error_message": null,
    "latency_ms": 1234,
    "input_tokens": 123,
    "output_tokens": 456,
    "run_parameters": {},
    "created_at": "...",
    "started_at": "...",
    "completed_at": "..."
  }
}
```

Raw detail output follows the same authorization rule as raw main output:
admins may see it, non-admins may not.

## UI

### Gate Challenger Tab

Show:

- verdict;
- short summary;
- `assessment_markdown`.

Do not show:

- full Layer 1 markdown;
- full Layer 2 markdown;
- compact layer indexes as reader-facing sections.

### Document Comments Tab

No behavior change.

Continue using Devil's Advocate `role_comments` and parsed document anchors.

### Full Output Tab

Before details are loaded:

- show Devil's Advocate output as today;
- show Gate Challenger summary structured JSON;
- show `Load detailed Layer 1 / Layer 2`;
- do not show full Gate Layer 1 / Layer 2 blocks.

While details are running:

- disable the button;
- show a compact loading state;
- poll the analysis/detail endpoint.

After details complete:

- render full Layer 1 / Layer 2 blocks using existing `LayeredGateChecks`
  display where possible;
- show detail structured JSON;
- show raw detail output for admins.

If details fail:

- show the error on the Full Output tab;
- keep the main Gate Challenger summary visible;
- keep Devil's Advocate visible.

## Reproducibility Requirements

Every stage must remain traceable to:

- input document id and parsed text;
- provider and model;
- provider API mode (`chat_completions` or `responses`);
- source snapshot id and fingerprint;
- prompt artifact path;
- prompt fingerprint;
- raw provider output when allowed;
- structured output;
- response id / previous response id when Responses API is used;
- usage and latency when returned by provider.

The first Gate Challenger summary is considered the primary verdict. Detail
runs must not silently alter the verdict. If a detail run finds a contradiction,
it must set `revision_required`.

## Backward Compatibility

Existing completed analyses with full `layer_1` / `layer_2` in
`analysis.structured_output` should continue to render.

The frontend should support both shapes:

- legacy full output on `analysis.structured_output`;
- new staged output with details in `analysis.detail_run.structured_output`.

Existing Devil's Advocate runs remain unchanged.

## Error Handling

- Devil's Advocate failure does not block Gate Challenger summary, matching
  current behavior.
- Gate Challenger summary failure marks the main analysis failed.
- Detail failure marks only the detail run failed.
- Re-clicking `Load details` after a failed detail run may create a new detail
  run.
- Re-clicking while queued/running returns the existing active detail run.
- Re-clicking after completed returns the completed detail run.

## Acceptance Criteria

- A new analysis can complete with Gate Challenger summary only.
- Devil's Advocate output and document comments display as before.
- Full Output does not display full Gate Layer 1 / Layer 2 before details are
  requested.
- `Load detailed Layer 1 / Layer 2` creates a detail run.
- Detail run uses Responses API with `previous_response_id`.
- Completed detail run renders full Layer 1 / Layer 2.
- Failed detail run does not hide the completed summary or Devil's Advocate
  output.
- Existing legacy analyses still render their full Layer 1 / Layer 2 data.
- API and worker tests cover summary success, detail success, detail failure,
  duplicate detail request behavior, authorization, and legacy rendering.

## Open Decisions

1. Detail loading granularity:
   - recommended initial choice: one button loads both Layer 1 and Layer 2;
   - future option: separate buttons for Layer 1 and Layer 2 if usage is still
     high.
2. Responses API background mode:
   - recommended initial choice: synchronous `/v1/responses`;
   - fallback: use `background=true` if detail calls still hit gateway timeout.
3. `/responses/compact`:
   - not required for first implementation;
   - keep as a future optimization after measuring real usage and latency.
