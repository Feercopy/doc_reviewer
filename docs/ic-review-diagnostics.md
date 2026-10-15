# IC Review Internal Diagnostics

IC Review stores the last ten diagnostic records in
`analysis_check_runs.run_parameters.ic_review_error_diagnostics`. These records
are removed from all API responses, including admin responses. The public error
contract and analysis rules are unchanged.

Version 2 adds:

- `context`: analysis/document/check-run/step IDs, provider/model, skill ID/version,
  source snapshot ID/revision/fingerprint, and the operation being performed.
- `context.app_release_sha`: the actual worker image's release tag. Production
  Compose passes the deploy script's SHA-pinned `GATE_WORKER_IMAGE` as
  `APP_RELEASE_IMAGE`. Local or non-SHA-tagged images report `unknown`; this is
  never inferred from a developer's checkout or the current GitHub main branch.
- RQ job ID, retries remaining, and retry count when available. Unknown retry
  counts are omitted, not invented. These are queue retries, not model retries.
- Schema filename and SHA-256 of canonical schema JSON, identifying the exact
  runtime contract even when the schema has no explicit version number.
- Validation path, schema path, validator, expected size/type constraint, and
  actual type/length. Object keys not declared by the schema become `<dynamic>`.
  No actual values, enum contents, prompts, or rejected model output are logged.
- JSON line/column/position, HTTP error status/request ID when available, elapsed
  milliseconds, and nested exception details alongside existing safe DB metadata.
- For deterministic pipeline failures: script names/exit codes and validation
  failure count, without script arguments, stdout/stderr, or artifact paths.

Role errors are emitted as one `ic_review_diagnostic {JSON}` worker-log line
before database recovery. This makes the original failure observable even if
rollback, reload, or error persistence also fails. The same safe record is kept
in the database when it is writable. Plain RQ log formatting is sufficient;
no custom JSON formatter is required. A role and its outer job may each emit a
record for the same error; correlate them by check-run ID, not as two failed runs.

## Investigation

1. Obtain the analysis URL/ID and approximate failure time from the user.
2. Search worker logs for `ic_review_diagnostic` and that analysis ID. Check the
   release SHA first, then `operation`, `step_name`, schema hash, and validation
   path. For `minLength`, compare `expected` with `actual_length`.
3. With authorized server/DB access, read the persisted records (read-only SQL):

```sql
SELECT id, analysis_id, current_stage,
       run_parameters->'ic_review_error_diagnostics' AS diagnostics
FROM analysis_check_runs
WHERE analysis_id = '<analysis UUID>'
ORDER BY created_at DESC;
```

4. If there is no database record, use the worker log. If a worker was killed
   before Python handled the error, there may be neither; correlate deployment,
   process, and queue logs. This change does not add durable resume or heartbeat.

Historical version-1 records remain readable but cannot retroactively acquire
missing release/schema data. Do not re-run a user's analysis just to fill logs.
Request IDs may be absent when the adapter/provider did not return one. Logs
must never be augmented with document text, workbook values, provider keys,
raw model responses, SQL parameters, or full exception messages.

## 2026-10-15: Role transport retry and attempt log

The incident investigation found two completed Gate Challenger runs followed by
IC Review failures on different roles. Both failures were `APIConnectionError`
caused by `RemoteProtocolError`, before a model response was available. A later
run completed the financial role that had failed earlier. The user confirmed
that other documents complete successfully. This does **not** establish a
stage-specific bug or a provider-wide outage; the closing network hop remains
unknown until an attempt with response headers or more detailed transport logs.

The worker now makes at most one transport retry per IC Review role after a
provider adapter classifies a connection/protocol failure, with a 500 ms delay.
OpenAI-compatible, Anthropic-compatible, and Hermes adapters each classify
their own transport errors. The retry reuses the same role prompt and does not
rerun completed roles. Its budget is shared between the initial request and
the existing invalid-JSON regeneration. SDK retries remain zero by default for
IC roles. Before each request and before the retry delay, the worker rechecks
whether the run was cancelled; cancellation does not become a failed run.
Timeouts keep their existing fallback; HTTP status errors, invalid JSON,
schema failures, and persistence errors do not trigger this transport retry.

Each role provider attempt emits `ic_review_provider_attempt {JSON}` to the
worker log. Failed attempts use warning level. The record includes the release
SHA, analysis/check-run/step and queue IDs, provider/model, role, prompt SHA-256
and character count, configured timeouts, attempt number, elapsed milliseconds,
error and transport classes, retry delay, HTTP status, `x-request-id`, and model
response ID when available. IC Review OpenAI- and Anthropic-compatible calls
use their SDKs' raw-response wrappers to capture status and headers; Hermes
captures them from its HTTP response. Other analysis calls retain their
existing invocation path. A connection that
ends before an HTTP response has `null` status and IDs; these values must not
be inferred. No response body, document content, URL, token, or exception
message is recorded.

Failed attempt history is also saved in the internal diagnostic record above.
Successful retry history is stored as an `internal_only` step artifact. Neither
is exposed by user or admin API responses. Read-only investigation can search
worker logs by `ic_review_provider_attempt` and check-run ID, or inspect the
database's `run_parameters.ic_review_error_diagnostics` and step artifacts.

The initial PR review identified two risks: OpenAI-only retry classification
in shared orchestration, and a cancelled run making a second billable request.
Both were addressed with adapter-owned classification and a cancellation guard.
Focused tests cover both paths, including Anthropic/Hermes and cancellation
during the first error or retry delay. OpenAI and Anthropic SDK raw-response
paths were checked against local mock transports. No live provider run was used
to verify this change. Follow-up review also found that cancellation after the
final failed provider request needed the same guard, Anthropic's standard
correlation header is `request-id`, and a direct Hermes transport exception has
no nested cause. All three paths now have focused regression tests. The adapter
uses Anthropic's exported timeout type rather than importing its transitive
HTTPX package. The final local API/worker suite passed 760 tests with explicit
test CORS origins.

A further review found a check-to-write cancellation race in terminal failure
recovery. That path now conditionally claims the failed status in the database
only while the run is not cancelled; a concurrent cancellation retains its
status and the step is marked cancelled. A regression test cancels the run
during diagnostic logging, after the last provider failure. The revised local
API/worker suite passed 761 tests with explicit test CORS origins.
