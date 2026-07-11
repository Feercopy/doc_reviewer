# Project Tasks

This file is the living execution tracker for Gate Challenger Service. Keep it
short enough to scan, and use the detailed Superpowers plan files for module
implementation steps.

Primary plan index:

- `docs/superpowers/plans/2026-06-05-gate-challenger-service/00-plan-index.md`

## Task Rules

- Use checkbox status: `[ ]` not started, `[~]` in progress, `[x]` done,
  `[!]` blocked.
- Keep active work near the top of the relevant phase.
- Link detailed work to the matching plan file instead of duplicating every
  subtask here.
- Update this file when scope, status, or verification changes.
- Use repository docs, plans, task notes, git history, and nearby code/tests as
  the development context.

## Current Focus

- [x] Fix production IC Agentic Review source path: root cause was
  `infra/docker-compose.prod.yml` missing `IC_AGENTIC_REVIEW_SOURCE_PATH` and
  the `/external/ic-agentic-review` readonly mount, so production skill seeds
  fell back to the local macOS path
  `/Users/iseremenko/Documents/IC-Agentic-Review`. Added the prod env/mount for
  `api` and `worker`, added regression coverage in `basePathRouting.test.ts`,
  copied a clean `IC-Agentic-Review` source tree plus Git metadata to
  `/opt/gate-challenger/external/ic-agentic-review`, set
  `IC_AGENTIC_REVIEW_HOST_PATH` in production `infra/.env` with a backup,
  recreated `api`, `worker`, and `edge`, re-ran skill seeds, and verified the DB
  source path is `/external/ic-agentic-review`, the API container can collect
  the source manifest (`26` files), public health returns 200, and fresh
  API/worker logs are clean.
- [x] Deploy IC Agentic Review release to production: merged
  `codex/ic-agentic-review-check` into `main`, pushed `main` to origin,
  synchronized a clean `git archive` release tree to `178.250.159.250`,
  rebuilt production `api`, `worker`, and `web`, applied Alembic migration
  `202607090001`, refreshed skill seeds (`baseline skills ready: 6`),
  force-recreated `edge`, and verified container status, Alembic head, direct
  API health, canonical `/doc-challanger/api/health`, `/doc-challanger/login`,
  and fresh API/worker/edge logs.
- [x] Adjust document detail narrow-screen layout: when the document detail
  columns collapse, the `Analysis history` panel now renders above the parsed
  document text via responsive grid item ordering. Verified
  `npm --prefix apps/web run test -- responsive-ui modelTrigger documents` (`39
  passed`), `npm --prefix apps/web run build`, and rebuilt/restarted the local
  `web` container.
- [x] Simplify IC review analysis-tab UI: hid the launch controls while an
  IC review run is queued/running, removed duplicate provider/model/created
  run chips, moved active-run progress into one compact status row inside the
  tab, stopped showing the page-level "Finishing analysis" banner for IC-only
  background runs while preserving polling, and changed the launch button back
  to the page's normal primary button styling. Follow-up polish styled the
  native `.xlsx` file-selector button to match the same compact control system,
  then removed the visible Provider selector and promoted financial-model
  upload into a wider, more discoverable `.xlsx` control while preserving the
  automatic provider/model launch parameters.
  Verified
  `npm --prefix apps/web run test -- analysisPage icReviewDisplay` (`24
  passed`), `npm --prefix apps/web run build`, and rebuilt/restarted the local
  `web` container.
- [x] Reduce IC Agentic Review token cost with deterministic context packing:
  added an `ic_review_context_pack_v1` worker layer that replaces repeated full
  document/main-analysis payloads in role and synthesis prompts with a bounded
  evidence index, role-specific evidence slices, compact main-analysis/detail
  context, and optional workbook/formula context. The worker now saves
  `structured/context_pack.json` plus a fingerprint for reproducibility and
  passes the same pack to all 8 roles and synthesis, while raw provider outputs,
  synthesis prompt/raw, postprocess log, validation report, and deterministic
  artifacts remain preserved. Verified
  `.venv/bin/python -m pytest apps/worker/tests/test_ic_review_renderer.py
  apps/worker/tests/test_run_ic_agentic_review_job.py
  apps/worker/tests/test_ic_review_script_runner.py
  apps/worker/tests/test_provider_adapters.py -q` (`61 passed`). Rebuilt and
  restarted the local `worker` container with Docker Compose and verified the
  container imports `ic_review.context_pack`.
- [x] Configure local Docker Compose proxy env for
  `206.223.244.175:1080`: copied the production `OUTBOUND_PROXY_URL` credentials
  from `/opt/gate-challenger/current/infra/.env` into gitignored local `.env`
  and `infra/.env` without printing the secret. Recreated local `api` and
  `worker` without rebuild so the new env is present, re-applied the worker
  timeout hotfix files after recreation, and restarted worker. Root-caused the
  first local proxy failure to Dante ACLs on `206.223.244.175`: only
  `178.250.159.250/32` was allowed, while local container traffic arrived as
  `37.113.208.129`. Added `37.113.208.129/32` to both `client pass` and
  `socks pass` in `/etc/danted.conf` with backup
  `/etc/danted.conf.bak-local-20260710120738`, restarted `danted`, and verified
  worker egress through the proxy to `https://openrouter.ai/api/v1/models`
  returns `200 application/json`. Worker also sees IC review timeout defaults
  `600/30/3`.
- [x] Fix local IC review `a_p_i_timeout_error` on run
  `c53534ed-2709-4901-850d-0a5bb2b85ce8`: root cause was an
  OpenAI-compatible provider timeout on role `ic-product-analyst`, not legacy
  postprocess/PDF generation. The previous role completed with a larger prompt
  (`82.8s`, `34.8k` input tokens), while `ic-product-analyst` failed after
  `16.3s` with no raw provider output, matching SDK/proxy connect timeout
  behavior. The OpenAI-compatible adapter now passes `timeout_seconds`,
  `connect_timeout_seconds`, and `max_retries` into the OpenAI SDK and proxy
  HTTP client, and IC review role/synthesis calls default to `600s` total,
  `30s` connect timeout, and `3` retries while preserving explicit overrides.
  Verified
  `.venv/bin/python -m pytest apps/worker/tests/test_provider_adapters.py
  apps/worker/tests/test_ic_review_renderer.py
  apps/worker/tests/test_run_ic_agentic_review_job.py -q` (`47 passed`) and
  `.venv/bin/python -m pytest apps/worker/tests/test_run_ic_agentic_review_job.py
  apps/worker/tests/test_ic_review_script_runner.py
  apps/worker/tests/test_ic_review_renderer.py
  apps/worker/tests/test_provider_adapters.py -q` (`58 passed`). Local Docker
  image rebuild is temporarily blocked by `mirror.gcr.io` metadata connection
  refusal; copied the changed worker files into the running `infra-worker-1`
  container and restarted it, then verified inside the container that role and
  synthesis defaults are `600/30/3`. A direct worker egress probe to
  `https://openrouter.ai/api/v1/models` currently returns `ConnectTimeout` with
  no local `OUTBOUND_PROXY_URL` configured, so new runs may still fail if local
  network access to OpenRouter remains unavailable.
- [x] Remove legacy PDF generation from IC review deterministic artifacts:
  worker now saves `artifacts/legacy_report.txt` as a text debug artifact
  derived from `postprocessed_legacy_report.json`, runs `validate_report.py`
  with JSON-only input when no workbook is provided and JSON+Excel when a
  workbook is provided, and persists artifact kind `legacy_report_text` instead
  of `legacy_report_pdf`. Verified
  `.venv/bin/python -m pytest apps/worker/tests/test_ic_review_script_runner.py
  apps/worker/tests/test_run_ic_agentic_review_job.py
  apps/worker/tests/test_ic_review_renderer.py -q` (`43 passed`),
  `.venv/bin/python -m pytest apps/worker/tests/test_run_ic_agentic_review_job.py
  apps/worker/tests/test_ic_review_script_runner.py
  apps/worker/tests/test_ic_review_renderer.py
  apps/worker/tests/test_provider_adapters.py -q` (`55 passed`),
  `.venv/bin/python -m pytest apps/api/tests/test_contract_schemas.py
  apps/api/tests/test_ic_review_api.py -q` (`40 passed`), and
  `npm --prefix apps/web run test -- analysisPage icReviewDisplay` (`24
  passed`). Safe local replay on normalized stored legacy JSON with the real
  IC source scripts produced `json_postprocess=0`, `validate_report=0`,
  `0` validation failures, a `legacy_report.txt` artifact, and no
  `legacy_report.pdf`.
- [x] Fix local IC review deterministic validation failure on run
  `cb6c52c9-e949-43f3-8427-f33f2b2aca43`: root cause was not provider output
  generation but legacy-script compatibility after synthesis. The compact
  result was valid, while the legacy payload had `scenarios` as a list and
  empty sections; the original `json_postprocess.py` / `validate_report.py`
  expect `scenarios` as an object. The worker now converts
  legacy scenarios to script-compatible objects, fills empty legacy sections
  from the compact result for internal artifact generation, while keeping raw
  synthesis output unchanged. Verified
  `.venv/bin/python -m pytest apps/worker/tests/test_run_ic_agentic_review_job.py
  apps/worker/tests/test_ic_review_script_runner.py
  apps/worker/tests/test_ic_review_renderer.py
  apps/worker/tests/test_provider_adapters.py -q` (`56 passed`), rebuilt the
  local worker container, and safely replay-ran the deterministic script
  pipeline on the stored synthesis raw without model/document re-send
  (`json_postprocess` and `validate_report` exit `0`; validation has `0`
  failures).
- [x] Fix local IC review synthesis wrapper validation on run
  `f5636d12-ed1d-49e2-acaf-90e8db44c4c8`: root cause was a valid provider
  synthesis that returned compact output plus a legacy report shell, but the
  compact `role_summaries[].summary` exceeded the UI schema `maxLength` and the
  legacy `sections` object was empty. The worker now normalizes legacy sections
  before deterministic scripts and trims compact-result strings according to
  schema `maxLength` before local validation, while preserving the original raw
  synthesis output separately. Verified
  `.venv/bin/python -m pytest apps/worker/tests/test_run_ic_agentic_review_job.py
  apps/worker/tests/test_provider_adapters.py
  apps/worker/tests/test_ic_review_renderer.py -q` (`43 passed`), rebuilt the
  local worker container, and safely replay-validated the stored synthesis raw
  without printing document/model text (`8` role summaries, max summary length
  `500`, `10` legacy sections).
- [x] Fix local IC review synthesis `bad_request_error` on run
  `cf34574c-db6f-47b0-9770-6a2be56a16bd`: root cause was the OpenAI-compatible
  provider rejecting Anthropic/OpenRouter `response_format` JSON Schema for the
  synthesis wrapper. The compact result schema used numeric `minimum`/`maximum`
  bounds, and the nested compact schema kept `$ref` values that provider-side
  validation resolved against a wrapper root without `$defs`. Extended provider
  schema normalization to strip unsupported numeric bounds while preserving
  local contract validation, hoisted compact-result `$defs` to the synthesis
  wrapper root, rebuilt the local worker, and verified a minimal provider probe
  with the same model/schema succeeds without document text. Also fixed the IC
  review failed banner separator so UI no longer renders
  `IC review failedbad_request_error`, and rebuilt the local web container.
  Verified
  `.venv/bin/python -m pytest apps/worker/tests/test_provider_adapters.py
  apps/worker/tests/test_run_ic_agentic_review_job.py
  apps/worker/tests/test_ic_review_renderer.py -q` (`41 passed`) and
  `npm --prefix apps/web run test -- analysisPage` (`19 passed`).
- [x] Fix Stream Review auto-detection regression found on local document
  `e1bcfea7-e0c2-4ab8-9364-d7049354e843`: root cause was an overly strict
  detector that ignored unnumbered `Stream review` titles unless they matched
  exact `1st Stream Review` / `Stream review 2+` phrases. Added weak generic
  Stream Review signals that still require stage-supporting evidence, verified
  `.venv/bin/python -m pytest apps/api/tests/test_document_type_detector.py -q`
  (`7 passed`, existing warning), rebuilt local API/worker containers, and
  reparsed the document; it now stores `stream_review_1`, confidence `0.45`,
  with parse status `completed`.
- [x] Implement Task 10 Analysis Page IC Review Tab: added manual `IC review`
  analysis tab between document comments and full output, configured
  provider/model and output-language controls, optional client-validated
  `.xlsx` upload, completed-analysis launch gate, active-run polling via
  embedded `ic_review_run`, current-stage display, compact completed-result
  rendering without raw/admin artifacts, failed-run relaunch support, file-input
  reset after launch/invalid upload, and pure display helper coverage. Verified
  `npm --prefix apps/web run test -- analysisPage icReviewDisplay`
  (`24 passed`) and
  `npm --prefix apps/web run test -- analysisPage analysisDisplay documents
  icReviewDisplay` (`73 passed`).
- [x] Implement Task 11 IC Agentic Review verification/regression suite:
  reviewed acceptance risks, fixed worker error-message sanitization so
  `jsonschema.ValidationError` / unknown provider exceptions cannot persist
  rejected provider instances into user-visible IC review errors while raw
  outputs remain preserved separately, and added regression coverage for role
  and full worker-job schema failures. Verified
  `.venv/bin/python -m pytest apps/api/tests/test_ic_review_api.py
  apps/api/tests/test_seeds.py apps/api/tests/test_skill_sources.py
  apps/api/tests/test_contract_schemas.py -q` (`60 passed`, existing warnings),
  `.venv/bin/python -m pytest apps/worker/tests/test_ic_review_errors.py
  apps/worker/tests/test_ic_review_renderer.py
  apps/worker/tests/test_ic_review_script_runner.py
  apps/worker/tests/test_run_ic_agentic_review_job.py -q` (`42 passed`),
  `npm --prefix apps/web run test -- analysisPage icReviewDisplay documents`
  (`54 passed`), broader API regression
  `.venv/bin/python -m pytest apps/api/tests/test_analyses_api.py
  apps/api/tests/test_documents_upload.py -q` (`32 passed`, existing warnings),
  broader worker regression
  `.venv/bin/python -m pytest apps/worker/tests/test_run_analysis_job.py
  apps/worker/tests/test_run_predicted_comments_job.py -q` (`15 passed`,
  existing warning), full frontend `npm --prefix apps/web run test`
  (`120 passed`), `docker compose -f infra/docker-compose.yml config`, and
  `docker compose -f infra/docker-compose.yml up -d --build web` after starting
  Colima (rebuilt/restarted local `infra-api` and `infra-web`; Docker `npm ci`
  reported 2 moderate audit warnings).
- [x] Implement Task 9 Frontend API Client for IC Agentic Review: added
  frontend shared IC review run/step/result types, embedded
  `AnalysisRecord.ic_review_run`, FormData-based launch client with optional
  `.xlsx` file omission when absent, and read/list/latest endpoint helpers.
  Verified `npm --prefix apps/web run test -- documents` (`30 passed`).
- [x] Implement Task 8 API read model embedding for IC Agentic Review: main
  `AnalysisRead` now includes the latest `ic_agentic_review` check run via the
  existing sanitized/admin-aware IC review serializer, so normal users see
  status, compact structured output, and source trace without raw/path fields,
  while admins see raw outputs and artifact path metadata. Review fixes made
  legacy output and role-step structured outputs admin-only, recursively strip
  path-like run parameter keys for non-admins, and added stable latest-run
  ordering. Verified
  `.venv/bin/python -m pytest apps/api/tests/test_ic_review_api.py -q`
  (`19 passed`, existing warnings).
- [x] Implement Task 7 IC Agentic Review worker job: added
  `run_ic_agentic_review` orchestration for queued/running/completed/failed and
  pre-cancelled runs, source snapshot workspace preparation, optional workbook
  snapshot plus formula audit, eight ordered role calls with raw-output
  preservation, synthesis prompt/raw/compact+legacy persistence, legacy JSON
  artifact writing, deterministic script pipeline artifact/log capture,
  validation report parsing, and failed-run preservation after role/provider
  errors. Added focused mocked worker coverage for no-workbook, workbook,
  synthesis prompt/artifact persistence, role raw outputs, script artifacts, and
  provider failure after role 3. Verified
  `.venv/bin/python -m pytest apps/worker/tests/test_run_ic_agentic_review_job.py
  -q` (`3 passed`).
  Review fixes added atomic queued-only claiming/idempotency, cancelled
  finalization, parent-analysis completion gate in the worker, workbook
  upload-dir boundary checks, DB-owned source snapshot lookup with storage-root
  validation, local synthesis wrapper schema validation, legacy JSON shape/type
  validation before script persistence, bounded subprocess environment for
  deterministic scripts, latest completed detail-run context, single formula
  audit reuse, explicit failed spreadsheet audit persistence including workbook
  extraction failures, deterministic script stage transitions, and regression
  coverage. Verified
  `.venv/bin/python -m pytest apps/worker/tests/test_run_ic_agentic_review_job.py
  apps/worker/tests/test_ic_review_script_runner.py
  apps/worker/tests/test_ic_review_renderer.py -q` (`37 passed`).
- [x] Implement Task 6 prompt rendering and role execution for IC Agentic
  Review: added serializable review context construction, fixed eight-role
  prompt order, snapshot-backed role and synthesis prompt renderers, guarded
  prompt artifact persistence under `ic-review/{analysis_id}/{run_id}/prompts`,
  synthesis wrapper output for compact + legacy JSON, and direct
  provider-backed role step execution with raw-output preservation and schema
  validation, including parent-run failure marking and usage metadata on failed
  role validation. Verified
  `.venv/bin/python -m pytest apps/worker/tests/test_ic_review_renderer.py -q`
  (`10 passed`) plus `py_compile`; Task 5+6 worker tests pass together
  (`19 passed`).
- [x] Implement Task 5 worker workbook parser and deterministic IC review
  script runner: added bounded `.xlsx` snapshot extraction, snapshot-to-run
  workspace preparation with path traversal checks, DB-owned run-dir boundaries
  for script inputs/logs/artifacts, no-shell streaming subprocess runner with
  finite timeout and process-group cleanup, bounded stdout/stderr capture,
  validation reports that include stderr and exit metadata on failure,
  workbook/no-workbook script orchestration, worker
  `ic_review*` package discovery, and external runtime dependencies in
  `apps/worker/pyproject.toml`. Verified
  `.venv/bin/python -m pytest apps/worker/tests/test_ic_review_script_runner.py
  -q` (`9 passed`), including real `openpyxl` workbook extraction coverage.
- [x] Implement Task 4 API launch/read/workbook upload for IC Agentic Review:
  added manual IC review run endpoints, completed-analysis gate, provider/model
  allowlist validation, `.xlsx`-only workbook storage under
  `ic-review/{analysis_id}/{run_id}/uploads`, skill source snapshots linked to
  `analysis_check_run_id`, sanitized non-admin read models, and DB-owned
  artifact download lookup. Review fixes added admin-by-default artifact
  download visibility, IC-review run path-prefix enforcement, OpenXML `.xlsx`
  sanity validation, source-snapshot failure upload cleanup, and enqueue-failure
  marking. Verified
  `.venv/bin/python -m pytest apps/api/tests/test_ic_review_api.py -q`
  (`15 passed`, existing warnings) and
  `.venv/bin/python -m pytest apps/api/tests/test_seeds.py
  apps/api/tests/test_skill_sources.py -q` (`20 passed`, existing warnings).
- [x] Implement Task 3 seed for IC Agentic Review skill source: added
  `IC_AGENTIC_REVIEW_SOURCE_PATH`, active `ic-agentic-review` local repo source
  with the required prompt/script/font/data manifest paths, and baseline
  `ic_agentic_review` `analysis_check` skill linked to the source. Added seed
  and temporary-source manifest coverage for the IC entrypoint, all eight agent
  prompts, deterministic scripts, schema path, and Gate Challenger document
  types. Verified
  `.venv/bin/python -m pytest apps/api/tests/test_seeds.py
  apps/api/tests/test_skill_sources.py -q` (`20 passed`, existing warnings).
- [x] Implement Task 2 database foundation for IC Agentic Review checks:
  added `analysis_check_runs` and `analysis_check_steps`, added
  `analysis_check` skill type, extended skill source snapshots to support
  `analysis_check_run_id` with exactly-one-owner enforcement, and added focused
  model persistence coverage. Verified
  `.venv/bin/python -m pytest apps/api/tests/test_ic_review_api.py
  apps/api/tests/test_skill_sources.py -q` (`15 passed`), applied the new
  Alembic migration from previous head `202606180001` to `202607090001`, and
  verified downgrade deletes IC-review-owned snapshots before restoring the old
  two-owner snapshot schema. A fresh full SQLite Alembic upgrade remains
  blocked earlier at existing migration `202606080002`.
- [x] Draft implementation plan for the intermediate IC Agentic Review
  integration requested on 2026-07-09:
  `docs/superpowers/plans/2026-06-05-gate-challenger-service/12-ic-agentic-review-check.md`.
  Scope: manual `IC review` analysis tab, completed-analysis gate, optional
  `.xlsx` upload/audit on that tab, single worker flow using the original IC
  role prompts without subagents, saved role raw outputs, synthesis prompt,
  script logs, validation report, and compact UI-native result.
- [x] Assess `/Users/iseremenko/Documents/IC-Agentic-Review` integration as an
  optional user-requested analysis check. Conclusion: feasible, but should be
  integrated as a separate reproducible auxiliary run with its own schema,
  source snapshot, raw/structured outputs, artifacts, and non-blocking failure
  semantics. Full parity requires package/material support for `.xlsx` inputs
  and a worker-native replacement for the Claude Code multi-agent/desktop
  pipeline; a text-only MVP can run from existing parsed document text with
  reduced financial-audit coverage.
- [x] Audit and refresh Gate Challenger / Devil's Advocate skill sources:
  fetched local upstream refs for
  `/Users/iseremenko/Projects/Gate2-challenger` and
  `/Users/iseremenko/Documents/Common GPTs/devils-advocate`; both local
  checkouts are at `origin/main` (`a738279` for Gate Challenger, `18925f0`
  for Devil's Advocate). Gate Challenger is clean; Devil's Advocate has local
  uncommitted changes, including `ic-voting-prompt.md`, scripts, and
  `wiki-ic/ops/log.md`. Focused verification passed:
  `.venv/bin/python -m pytest apps/api/tests/test_seeds.py
  apps/api/tests/test_skill_sources.py apps/worker/tests/test_skill_renderers.py
  -q` (`27 passed`). Production read-only audit found the app uses
  `snapshot_required` skills and non-stub prompts, but production
  `/opt/gate-challenger/external/gate-challenger/skills/gate-challenger/SKILL.md`
  is older than the local latest source (`eba956...` vs `35e9a4...`), and DA
  required-source manifest also differs from local. After explicit approval,
  created production backup
  `/opt/gate-challenger/backups/skill-source-sync-20260707231535`, verified DA
  required runtime files already matched local canonical source, and updated
  only production Gate `SKILL.md` (no broad `--delete`, no references/DA
  overwrite). Refreshed only production
  `gate2_challenger_main_analysis` DB `prompt_text` and `source_fingerprint`;
  final production service manifests match local (`gate-challenger`
  `87b81d...`, `devils-advocate` `b02cd1...`). Verified production containers
  remained up and server-local plus edge `/health` returned `ok`; reran focused
  local tests (`27 passed`, same existing warnings).
- [x] Route production provider egress through Kazakhstan SOCKS5 proxy:
  installed and configured Dante on `206.223.244.175:1080` with username
  authentication and Dante allow rules for production host `178.250.159.250`.
  Updated production `/opt/gate-challenger/current/infra/.env`
  `OUTBOUND_PROXY_URL` with a root-only backup
  `.env.bak.proxy-20260707224839`, recreated production `api` and `worker`,
  and recreated `edge` to refresh Docker upstreams. Verified from production
  worker that proxied egress resolves to `206.223.244.175`, OpenRouter
  `/api/v1/models` returns `200 application/json` through the proxy, and both
  server-local plus public `/doc-challanger/api/health` return `ok`.
- [x] Reparse production DOCX document
  `dc35942a-eebe-422d-8412-b8eb2df9ee03` after the OOXML parser deployment.
  Triggered reparse through the production API on `178.250.159.250`; worker job
  `ea32f002-5739-4bc3-8c5c-43144f5462b7` completed in about 1 second.
  Verified `parse_status=completed`, `parse_error=None`,
  `detected_document_type=gate_3`, `document_type_confidence=0.85`,
  `parsed_text_len=69852`, markdown headings/tables/ordered lists present,
  `parser_name=ooxml-docx`, `parser_source=zipfile.ElementTree`, `210` blocks,
  and `27` parsed tables. No document text was printed during verification.
- [x] Port DOCX structured markdown extraction from Doc_challanger into the
  worker parser: `.docx` / `.dotx` now use a deterministic OOXML zip parser
  that preserves heading styles, numbered lists, table markdown, escaped pipes,
  `<br>` line breaks, hyperlinks from relationships, gridSpan placeholders, and
  ignores deleted/moveFrom/instrText Word nodes. DOCX `parsed_text` now stores
  the structured markdown contract, while PDF remains Docling-first. Verified
  `.venv/bin/python -m pytest apps/worker/tests/test_document_parsers.py -q`
  (`12 passed`), `.venv/bin/python -m pytest
  apps/worker/tests/test_parse_document_job.py -q` (`2 passed`, one existing
  passlib/argon2 deprecation warning), and `.venv/bin/python -m pytest
  apps/worker/tests -q` (`77 passed`, same warning). Committed as `15ca6c5`,
  pushed to `main`, synced a clean release tree to `178.250.159.250`, rebuilt
  production `worker`, and verified production container status, worker logs,
  worker parser import, server-local `/health`, and edge
  `/doc-challanger/api/health`.
- [x] Import 2026-06-25 project handoff into
  `docs/handoffs/2026-06-25-gate-challenger-service.md`: preserved production
  paths, deployment notes, recent commit history, audit findings, and external
  skill-repo context. Reconciled the imported stale dirty-state warning against
  the current clean `main` / `origin/main` at `c46f4b8`, where the
  `Document comments` markdown renderer has already been completed and
  released.
- [x] Render DOCX-derived markdown inside analysis `Document comments`: the
  analysis document/comment view now preserves headings, lists, markdown
  tables, escaped pipes, and `<br>` line breaks while keeping Devil's Advocate
  anchor highlights clickable and sorted by document order. Verified focused
  analysis display/page tests with bundled Node (`36 passed`) and
  `npm --prefix apps/web run build`. Deployed to `178.250.159.250`, rebuilt
  production web, recreated edge, verified public document/analysis routes,
  and reparsed all 3 completed production DOCX documents.
- [x] Render parser-produced HTML formatting in parsed document previews:
  `MarkdownPreview` now recognizes safe parser HTML blocks and inline tags
  (`table`, `p`, `strong`, `u`, `a`, lists) instead of showing raw tags, while
  filtering attributes to safe links only. Verified
  `npm --prefix apps/web run test -- markdownHtmlParser`, full frontend tests
  (`109 passed`), and `npm --prefix apps/web run build`. Synced the changed
  web files to `178.250.159.250`, rebuilt production web, recreated edge, and
  verified the production bundle contains the HTML renderer plus public
  `/doc-challanger/login`, `/doc-challanger/api/health`, and the affected
  document route.
- [x] Move production domain to HTTPS: public DNS for `iseremenko.ru` and
  `www.iseremenko.ru` now resolves to `178.250.159.250`, certbot issued a
  server-side Let's Encrypt certificate for both names, and production nginx
  now serves `/doc-challanger` over `https://iseremenko.ru` with `www` and HTTP
  canonical redirects. Production Compose exposes `443` and mounts
  `/etc/letsencrypt` for edge TLS termination; API production public URL/CORS
  settings were updated to include the HTTPS origin.
- [x] Fix production login Private Network Access preflight: Chrome sent
  `Access-Control-Request-Private-Network: true` for
  `/doc-challanger/api/auth/login`, and FastAPI CORS returned
  `400 Disallowed CORS private-network`. API CORS now allows private-network
  preflights for configured origins. Verified with
  `.venv/bin/python -m pytest apps/api/tests/test_health.py -q` (`4 passed`,
  one existing Starlette/httpx deprecation warning). Deployed to
  `178.250.159.250`, rebuilt production `api`, recreated `edge`, and verified
  server-local plus edge `/health` and PNA preflight for `/auth/login`. Follow-up
  after Chrome still rejected insecure `http://iseremenko.ru` as local address
  space: nginx now redirects `iseremenko.ru` to the public IP origin
  `http://178.250.159.250`, pending proper public DNS plus HTTPS for the domain.
- [x] Sharpen Gate Challenger `assessment_markdown` tone requirements:
  `gate2_challenger_renderer` now asks both summary and full main-analysis
  prompts for CEO/CPO IC language, a short Brutal Truth-style opening, and
  proven / not proven / cannot approve yet framing while preserving facts,
  verdicts, evidence, required fields, and Layer 1 / Layer 2 contracts.
  Verified with `.venv/bin/python -m pytest apps/worker/tests/test_skill_renderers.py -q`
  (`13 passed`) and `.venv/bin/python -m pytest
  apps/worker/tests/test_run_analysis_job.py -q` (`8 passed`, one existing
  passlib deprecation warning). Pushed commit `232e243` to `main`, synced the
  worker renderer to `178.250.159.250`, rebuilt production `worker`, and
  verified the new container imports the tone block plus server-local and edge
  `/health`.
- [x] Publish Gate Challenger under `iseremenko.ru/doc-challanger`: added a
  configurable Next.js base path, route helper coverage for imperative
  navigation, production nginx routing for `/doc-challanger` and
  `/doc-challanger/api`, and production Compose build args for
  `NEXT_PUBLIC_BASE_PATH=/doc-challanger`. Focused route tests, full frontend
  tests (`106 passed`), production frontend build with `/doc-challanger`, and
  production Compose config with dummy env pass locally. Synced the release
  tree to `178.250.159.250`, set production public URLs to
  `/doc-challanger/api` and `http://iseremenko.ru/doc-challanger/api`, rebuilt
  production web, recreated edge, and verified container status, root
  `/doc-challanger/login` redirects, edge `/doc-challanger/login`, edge
  `/doc-challanger/api/health`, and `_next` assets under `/doc-challanger`.
  External IP checks for `http://178.250.159.250/doc-challanger/login` and
  `/doc-challanger/api/health` pass. Public DNS for `iseremenko.ru` still
  returns no A/NS records on 2026-06-23; Selectel DNS setup remains required.
- [x] Fix analysis detail permissions for document-visible analyses: direct
  `GET /analyses/{analysis_id}` now authorizes through the linked active
  document, so a non-admin user who can view the analyzed document can open
  analyses inside it even when the run was created by an admin. Analysis delete
  remains run-owner/admin scoped. Verified the RED regression and relevant API
  suite with `STORAGE_ROOT=/private/tmp/gate-challenger-api-test-storage
  .venv/bin/python -m pytest -p no:cacheprovider
  apps/api/tests/test_analyses_api.py apps/api/tests/test_feedback.py
  apps/api/tests/test_documents_upload.py apps/api/tests/test_authz_policies.py
  -q` (`40 passed`) and full API tests (`141 passed`). Synced changed files
  to `178.250.159.250`, rebuilt production `api`, verified container status,
  server-local `/health` and edge `/api/health`, and confirmed production
  access for analysis `7ee2684b-8e44-44c7-9c4d-15b1e27a479c` with its
  document owner actor.
- [x] Compact analysis launch controls in production: moved model selection,
  output language, and `Start analysis` into a button-like toolbar directly
  under `Analysis history`, removing the standalone `Analysis setup` block from
  the document hero. Verified focused document-detail test, full frontend tests
  (`101 passed`), local production web build, pushed commit `80433ee` to
  `main`, synchronized the release tree to `178.250.159.250`, rebuilt
  production web, recreated edge, and verified production container status plus
  server-local `/api/health` and `/login` through nginx edge.
- [x] Rework document detail actions and deploy to production: moved
  `Download raw` / `Reparse` / `Delete` to the document title level and moved
  `Model`, `Output language`, and `Start analysis` into an explicit
  `Analysis setup` block. Verified full frontend tests (`101 passed`), local
  production web build, pushed commit `5fa3b99` to `main`, synchronized the
  release tree to `178.250.159.250`, rebuilt production web, recreated edge,
  and verified production container status plus server-local `/api/health` and
  `/login` through nginx edge.
- [x] Fix Devil's Advocate JSON parsing for literal control characters:
  production analysis `74e1c7f8-7699-416c-8be0-15b8e4f5aa8a` completed the
  main Gate Challenger run, but the linked DA prepass failed because provider
  `choices[0].message.content` contained literal tab characters inside
  `anchor_text` JSON strings (`Cost allocation, %\t3%\t37%...`). The worker
  JSON validator now retries only `Invalid control character` failures with
  permissive JSON string parsing while preserving schema validation. Verified
  RED/GREEN regression coverage and full worker tests with
  `.venv/bin/python -m pytest -p no:cacheprovider apps/worker/tests -q`
  (`73 passed`, one existing passlib warning).
- [x] Audit latest production Gate Challenger layer delivery: analysis
  `9feae0ff-ca4c-4256-aa64-a170636b2f05` is a staged Gate 3 summary run with
  `details_status=not_requested`, `7` compact Layer 1 index items, and `17`
  compact Layer 2 index items. Its prompt snapshot included the selected
  `gate-3-rubric.md` and all `80/80` Gate 3 atomic Layer 2 questions, so the
  summary prompt did not lose the rubric at load time. No production
  `analysis_detail_runs` exist yet, so full detailed Layer 1 / Layer 2 output
  has not been exercised in production; the detail schema/prompt and grouped UI
  do not currently enforce or test exact original-rubric question completeness.
- [x] Implement admin feedback dashboard: add exact nullable feedback rating,
  preserve legacy usefulness-only feedback, return filtered admin feedback
  summary, expose Feedback in the admin top navigation, and rebuild
  `/admin/feedback` around improvement signals and run-level feedback details.
  Verified full API tests, targeted API feedback/admin tests, full frontend
  tests, Compose config, diff whitespace, local web/API container rebuild,
  local Alembic upgrade to `202606180001`, API `/health`, and web `/login`.
  Committed `e9a66e2`, fast-forward merged to `main`, pushed to origin, synced
  clean release tree to `178.250.159.250`, rebuilt production API/worker/web,
  applied production Alembic upgrade to `202606180001`, restarted edge, and
  verified production container status, Alembic current, server-local
  `/api/health`, `/login`, `/admin/feedback`, unauthenticated
  `/api/admin/feedback` auth failure, and fresh service logs.
- [x] Recover Devil's Advocate role comments from truncated provider output:
  production analysis `9feae0ff-ca4c-4256-aa64-a170636b2f05` has a failed
  DA prepass with `structured_output = null`, but the raw provider message
  contains a complete `role_comments` array before the JSON truncation point.
  The analysis page now falls back to parsing that completed array from
  admin-visible raw output, so Document comments and the DA role comments table
  can render even when later JSON fields were cut off.
- [x] Improve failed Devil's Advocate truncation display on analysis pages:
  frontend now maps `Unterminated string starting at...` DA failures to a
  readable provider-truncation message, and admin-visible raw provider output
  can recover `native_markdown` from a truncated JSON string so the Devil's
  Advocate block still renders like other analyses when the markdown field was
  completed before truncation. Verified focused analysis display test, full
  frontend tests, production frontend build, and full worker tests locally.
- [x] Compact Devil's Advocate prepass output for Gate Challenger Layer 4:
  worker-created DA prepass runs now mark
  `devils_advocate_output_contract=compact_prepass`, and the DA renderer uses
  that flag to request a concise JSON contract instead of a full UI report:
  short `native_markdown`, at most 3 contradictions, exactly one role comment
  per voter, 3 tough questions, 3 JTBDs, compact citations, and no Markdown
  role-comments table. Full DA report behavior remains available for runs that
  are not `run_order=before_gate_challenger`. Verified focused RED/GREEN
  coverage and full worker tests with `.venv/bin/python -m pytest
  apps/worker/tests -q` (`72 passed`, one existing passlib warning).
- [x] Diagnose production analysis
  `9feae0ff-ca4c-4256-aa64-a170636b2f05` JSON failure: main Gate
  Challenger run completed successfully, but the linked Devil's Advocate
  prepass `1c289e8d-61cf-4966-b2b6-24f03915fedf` failed parsing provider
  output. OpenRouter/Anthropic returned `finish_reason=length` with exactly
  `completion_tokens=20000`; the assistant content length was `50061`
  characters and ended mid-JSON, producing Python `JSONDecodeError:
  Unterminated string starting at line 1 column 50056`. The document parse was
  completed (`goods-loans-progress-review.docx`, parsed text about 56k
  characters), and the DA prompt artifact was about 157k bytes / 66,952 prompt
  tokens, so the root cause is DA prepass output truncation at the configured
  `max_output_tokens=20000`, not a frontend rendering issue.
- [x] Assemble production timeout repro bundle for analysis
  `6c7ac1d8-83ce-48e1-87c2-2dd676b7415f`: copied saved main Responses API
  prompt, Devil's Advocate prepass Chat Completions prompt, source `Gate_3.pdf`,
  schemas, metadata, and a stdlib Python repro script under ignored
  `repro/admllm-timeout-6c7ac1d8/`, plus
  `repro/admllm-timeout-6c7ac1d8.tar.gz`. Verified prompt/PDF hashes against
  production and dry-ran both request payload builders. Since `analyses` do not
  persist provider `base_url`, recovered the run-time
  `https://admllm.data-light.ru/v1` value from the 2026-06-15 provider-key
  audit log; the key was later replaced with OpenRouter on 2026-06-18.
- [x] Implement Gate2 benchmark etalon flow in branch
  `codex/gate2-etalon-benchmark-layers`: added admin import of Gate2
  originals and Layer 1 / Layer 2 CSV etalons into project
  documents/etalons, source metadata and snapshots, judge v2 prompt seeding,
  layer-only benchmark comparison, v2 micro-average scoring, `.dotx` parsing,
  and frontend API client support. Full API tests, full worker tests, full
  frontend unit tests, production web build, Compose config, and diff hygiene
  checks pass locally; e2e remains not run because `E2E_ADMIN_LOGIN` /
  `E2E_ADMIN_PASSWORD` are not set. Merged into `main`, pushed to origin,
  deployed release `cfb7441` to `178.250.159.250`, rebuilt production
  API/worker/web, applied Alembic upgrade to `202606170002`, reseeded baseline
  skills, recreated edge to refresh Docker upstreams, and verified production
  container status, public `/api/health`, public `/login`, unauthenticated
  Gate2 import returns auth failure instead of not-found, bootstrap admin
  `login` then `/auth/me`, and fresh API/worker/edge logs with no new `502`.
  Follow-up production enablement synced `benchmark/` into the mounted Gate
  Challenger source, cleaned macOS metadata files, reseeded `benchmark_judge`
  to the Gate2 v2 prompt, imported 4 active Gate2 benchmark etalons/originals
  (`genai`, `pws`, `travel`, `trx-se`), fixed `.dotx` template parsing in the
  worker, rebuilt production worker with prod compose env, and verified all 4
  imported originals are parsed successfully.
- [x] Diagnose and restore production auth/API `502 Bad Gateway`: root cause
  was nginx edge holding a stale resolved Docker upstream after the API
  container was rebuilt. Edge still proxied `/api/*` to old API IP
  `172.18.0.5`, while the current API container was `172.18.0.4` and answered
  direct health/auth requests. Restarted `infra-edge-1` on
  `178.250.159.250`; verified edge `/api/health` returns `200`, unauthenticated
  auth probes return normal `401`, and bootstrap admin `login` then `/auth/me`
  returns `200`. Follow-up: restart edge after API/web container replacement or
  change nginx config to runtime-resolve Docker service names.
- [x] Start structured document parse artifacts on branch
  `codex/structured-parse-artifacts`: worker parsers now keep the existing
  `parsed_text` string contract while also producing a `document_parse_artifact.v1`
  JSON contract with source metadata, parser metadata, markdown/plain outputs,
  block spans, and quality diagnostics. Parse jobs persist `parsed.txt`,
  `parsed.md`, `structured.json`, and `quality.json` under the existing parsed
  artifact directory, and audit metadata records parser/quality summary
  without storage paths. Added lightweight `docling-slim` as the preferred
  `.docx`/`.pdf` worker adapter when installed, with fallback to the current
  python-docx/pypdf adapters when unavailable or conversion fails; the full
  `docling` package was avoided because it pulls Torch/CUDA into the production
  worker image. Verified focused
  parser/parse-job/schema tests, full worker tests, and full API tests. Merged
  into `main`, pushed to origin, deployed to `178.250.159.250`, rebuilt
  production API/worker with `docling-slim`, verified production container
  status, API `/health`, `/login`, worker startup logs, and confirmed
  `docling.document_converter` is importable inside the production worker.
- [x] Fix document-detail low-resolution analysis history action clipping:
  root cause was the two-column document detail grid letting the Analysis
  history panel become narrower than its 560px table at compact desktop widths,
  pushing the `Open` action into horizontal overflow. Added a 1440px responsive
  rule that shrinks `Parsed document` first and preserves a 600px history
  column before the existing single-column breakpoint. Verified focused
  responsive test, full frontend tests, production web build, local web/API
  container rebuild, and local `/login` plus `/health` smoke.
- [x] Add analysis deletion: implemented soft-delete for analysis runs via
  `deleted_at`, `DELETE /analyses/{analysis_id}` with owner/admin access,
  hidden deleted runs from user/admin analysis reads and lists, blocked
  feedback on deleted analyses, and added a guarded Delete action on the
  analysis result page that returns to the source document. Verified full API
  tests, full worker tests, full frontend unit tests, production web build,
  Compose config, local web/API container rebuild, Alembic upgrade to
  `202606170001`, local container status, API `/health`, and web `/login`.
  Merged into `main`, deployed to `178.250.159.250`, rebuilt production
  API/worker/web, applied production Alembic upgrade to `202606170001`,
  verified production container status, public `/api/health`, public `/login`,
  public unauthenticated `DELETE /api/analyses/{id}` returns auth failure
  instead of method-not-allowed, and checked fresh API/web/worker logs.
- [x] Fix production document-detail workflow card height mismatch: root cause
  is the document-detail stepper using flex cross-axis centering, so shorter
  status cards such as `Ready` keep their content-height while neighboring
  cards wrap to two text lines. Changed `.gc-stepper` to stretch items per
  flex row and added responsive UI coverage. Focused responsive test, full
  frontend test suite, and production web build pass locally. Deployed to
  `178.250.159.250`, rebuilt production web, verified container status,
  `/api/health`, `/login`, the document route, and confirmed the built
  `/documents/[documentId]` bundle contains `align-items: stretch`.
- [x] Add editing for saved provider key Model and Allowlist in Settings:
  implemented local `PATCH /settings/provider-keys/{provider}` to update
  `default_model` and `available_models` without replacing encrypted key
  material, added inline edit/save/cancel controls in the saved keys table, and
  verified API/frontend tests plus production frontend build locally. Deployed
  to `178.250.159.250`, rebuilt production API/web, and verified container
  status, edge `/api/health`, direct `/settings`, and unauthenticated
  `PATCH /settings/provider-keys/openai_compatible` returns auth failure
  instead of method-not-allowed.
- [x] Reduce Devil's Advocate prompt size without dropping retrieval evidence:
  renderer no longer sends the expanded retrieval `evidence_packet` twice.
  The retrieval dossier block now contains compact selection/trace metadata and
  marks the full packet as included in the separate expanded evidence section,
  while selected item excerpts and full retrieved evidence remain available to
  the model. Verified focused DA renderer/job tests and the full worker test
  suite. Deployed to `178.250.159.250`, rebuilt production worker, verified
  container status, API health, `/login`, worker logs, and confirmed the
  production worker imports the compact retrieval helper.
- [x] Implement resilient Document comments anchoring: frontend anchor matching
  now falls back from exact/case-insensitive search to whitespace-normalized,
  punctuation-normalized, and high-confidence token-window matching while
  preserving original parsed-text spans. Devil's Advocate prompt/schema now
  require short source quotes copied from parsed document text instead of
  paraphrased/broad anchor summaries. Verified focused analysis display tests,
  full frontend tests, production frontend build, full API tests, full worker
  tests, local web container rebuild, Compose container status, API health, and
  web `/login` smoke. Read-only projection against the production DOM for
  analysis `6946539f-53a3-4605-b05c-2822fbd427dd` matched all 4 existing
  comments: 1 whitespace-normalized match and 3 token-window matches. Deployed
  to `178.250.159.250`, rebuilt production API/worker/web, verified public
  `/api/health`, public `/login`, production container status, and confirmed
  the analysis UI now renders 4 anchor groups, 4 matched comment cards, and 0
  unmatched cards.
- [x] Diagnose production analysis `6946539f-53a3-4605-b05c-2822fbd427dd`
  Document comments anchoring: the page has 4 Devil's Advocate role comments
  and parsed text loads correctly, but 0 document anchor spans render because
  all 4 `anchor_text` values fail the current exact/case-insensitive frontend
  match. One anchor would match after whitespace/punctuation normalization;
  the others only partially overlap the parsed text, so they remain visible as
  unlinked comment cards.
- [x] Reduce Gate Challenger main prompt size for known stage documents without
  dropping reproducibility: source snapshots still persist the full
  Gate-challenger reference set, but the worker renderer now sends only common
  references plus the matching stage rubric to the model. For `gate_2` runs
  this removes the Gate 3 and Stream Review rubrics from the model input while
  retaining Gate 2, verdict, synthesis, adversarial, output-contract, and
  stage-detection rules. Verified with focused renderer coverage and the full
  worker test suite.
- [x] Record and verify infrastructure access note: root SSH to
  `178.250.159.250` works with explicit identity `~/.ssh/my-server-codex`
  (codex key) and returns `root`; the default identities are rejected for that
  host. Root SSH to `avi-ix-devbox04` with the same key was rejected
  (`publickey`). Private key material must not be stored or committed.
- [x] Render an explicit blank paragraph after the Gate Challenger verdict line:
  production data already contains a blank line after `Recommendation`, but the
  markdown renderer intentionally skipped blank lines. The renderer now inserts
  an `aria-hidden` spacer paragraph after standalone recommendation verdicts,
  so the separation is structural instead of relying on collapsed markdown
  whitespace. Local focused markdown tests, full frontend tests, and production
  build pass. Deployed to `178.250.159.250`, rebuilt production web, verified
  health/container status, and confirmed the built production bundle contains
  `gc-md-paragraph-spacer` with `height: 1.62em`.
- [x] Increase visible spacing after the Gate Challenger verdict line: the
  previous paragraph split reached production but still looked nearly identical
  because the default paragraph margin was too small. Standalone
  `Recommendation:` verdict paragraphs now receive a dedicated lead-label
  class with a larger bottom margin. Local focused markdown tests, full
  frontend tests, and production build pass. Deployed to `178.250.159.250`,
  rebuilt production web, verified health/login/container status, and confirmed
  the built production bundle contains `gc-md-paragraph--lead-label` with
  `margin-bottom: 28px`.
- [x] Add visual separation between Gate Challenger verdict and following
  narrative text: markdown paragraph parsing now treats section-label lines
  such as `Decision Context:` as a new paragraph instead of joining them into
  the previous verdict line. Local focused markdown tests, full frontend tests,
  and production build pass. Deployed the updated web to `178.250.159.250` and
  verified server-side API health, `/login`, and container status. Local web
  container rebuild remains blocked because the Docker daemon is not running
  after the earlier Colima image checksum mismatch.
- [x] Fix Gate Challenger markdown display bug where a bold standalone section
  label after a loose ordered list was rendered as part of the previous list,
  causing the following improvement items to keep numbering as 6/7/... instead
  of restarting visually. Added parser coverage for the Gate output shape and
  verified the focused parser test, full frontend unit suite, and production
  frontend build locally. Deployed the code to `178.250.159.250`, rebuilt
  production web/API/worker containers, and verified server-side API health,
  `/login`, and container status. Local web container rebuild is blocked by a
  Colima image checksum mismatch while starting Docker.
- [x] Diagnose production analysis `7142b87b-76a5-499e-b76c-463ff94bfbb6`
  failure: main worker job failed before provider call while creating the
  Devil's Advocate source snapshot because `/external/devils-advocate` had
  the source files nested under an absolute local path instead of at the
  configured source root. Re-synchronized the required DA files/directories to
  the production source root and verified the production container can now
  collect a 96-file DA manifest in `production_export` mode.
- [x] Fix production `git command failed: rev-parse HEAD` for exported skill
  source directories: added configurable `SKILL_SOURCE_SNAPSHOT_MODE`, set
  prod compose default to `production_export`, and verified API snapshots can
  persist manifest/fingerprint artifacts from read-only source exports without
  git metadata while strict `production_latest` remains available.
- [x] Deploy production MVP to new server `178.250.159.250`: installed Docker,
  Compose, Git, and rsync; synchronized the current working tree plus clean
  git snapshot copies of the Gate Challenger and Devil's Advocate skill
  sources; created server-local production `.env` and bootstrap admin
  credentials under `/root/gate-challenger-admin.txt`; rebuilt and started
  postgres, redis, api, worker, web, and nginx edge on host port 80; applied
  Alembic migrations, seeded 5 baseline skills, created admin user `admin`,
  and verified public `http://178.250.159.250/api/health`,
  `http://178.250.159.250/login`, admin login/me, and container status.
- [x] Move production entrypoint off port 80 on `avi-ix-devbox04`: production
  compose now defaults nginx edge to host port `8092` and binds direct API/web
  published ports to `127.0.0.1`, so the shared devbox main address is no
  longer occupied by this project. Deployed release
  `20260615-000224-port8092-e7d3cb6`, rebuilt web with
  `NEXT_PUBLIC_API_BASE_URL=http://avi-ix-devbox04:8092/api`, verified
  server-side `/api/health`, `/login`, CORS for `http://avi-ix-devbox04:8092`,
  admin auth, and skill listing through port `8092`; direct Codex sandbox HTTP
  access to devbox still times out due the external network path.
- [x] Fix responsive UI artifacts across the main web screens: analysis tabs
  now wrap instead of clipping `Full Output`, route-local buttons/links/inputs
  keep 44px touch targets, document filter tabs wrap on compact widths, the
  analysis feedback action leaves bottom breathing room, and checkbox labels
  have a 44px tap target. Follow-up desktop audit fixed document-detail
  workflow metadata clipping and parsed Markdown table cell clipping at
  1366px/1024px. Also synchronized the web e2e mock/scenario with the current
  Devil's Advocate contract and analysis feedback flow. Verified with focused
  responsive tests, full frontend tests, production build, e2e MVP flow, local
  web container rebuild, and localhost browser audits at mobile, 1024px, and
  1366px across documents, analysis, etalons, benchmarks, settings, and admin
  routes.
- [x] Deploy production MVP to `avi-ix-devbox04`: added production compose,
  production Next.js Dockerfile, configurable CORS origins, external skill
  source mounts, and nginx edge proxy for `http://avi-ix-devbox04/api` plus
  Next.js web at `http://avi-ix-devbox04`; local API/worker/frontend tests and
  builds passed, prod Alembic upgrade/admin bootstrap/skill seeding completed,
  server-side edge/API/web/worker smoke passed, and a test document upload was
  parsed and deleted successfully. Direct HTTP from the Codex sandbox to
  `avi-ix-devbox04` timed out even though the server listens on 80/3000/8000
  and answers on all local interfaces, so any remaining access issue is outside
  the app/container layer.
- [x] Restrict Etalons and Benchmarks top navigation to admins: shared app
  navigation now hides `/etalons` and `/benchmarks` for `user` and
  `annotator` roles while keeping them visible for `admin`. Verified with the
  focused app navigation test, full frontend tests, production build, and local
  web container rebuild.
- [x] Tighten Devil's Advocate comment output after TRX_SE regression: service
  prompt now treats real names as a pre-flight anomaly to anonymize with
  fictional neutral placeholders instead of stopping, requires the visible
  Role comments section to be a Markdown table with role/vote/decision/anchor
  quote/comment/type/severity columns, and the DA JSON schema rejects
  completed `role_comments` with empty `comments` arrays. Verified with full
  API and worker test suites, rebuilt local API/worker containers, and checked
  API `/health`.
- [x] Diagnose latest Devil's Advocate comment-format regression on TRX_SE:
  old good run `2f855fc5-e8cf-49e1-b8b2-d00789f91520` used
  `anthropic/claude-opus-4.6`, produced pipe-table role comments plus 20
  structured `role_comments[].comments[]`; latest `openai/gpt-5.5` runs
  `4510f287-3163-4231-ada9-5bc47e04be54` /
  `35a0f9e6-d2b3-4365-956c-33e6ada43137` used the same DA source and
  retrieval fingerprints but stopped at pre-flight on non-anonymized names,
  persisted 0 structured role comments, and therefore had no table-shaped data
  for the UI to render.
- [x] Compare latest staged TRX_SE run with older legacy TRX_SE runs:
  latest `b6ce453c-bf8a-4aae-86a5-07d855eea0a4` completed with summary-only
  Gate Challenger plus completed detail run
  `030bcdd0-085f-4d8d-9af6-66ea14ef5aa9`; quality/coverage improved
  materially with 8 Layer 1 and 12 structured Layer 2 checks, while total
  on-demand detail cost/latency is higher than old Gemini legacy full runs.
- [x] Fix Layer 2 detailed-check card spacing/wrapping: long Layer 2 questions
  now wrap inside the card instead of stretching the row, and compact
  Issue/Evidence fields have horizontal inset padding so text no longer starts
  flush against the card edge. Verified with frontend tests and production
  build, web/API container rebuild, Docker status, and localhost browser smoke.
- [x] Fix lazy detail Layer 1 / Layer 2 UI merging when detail markdown uses
  shorthand bullets such as `- L1-1: ...` and `- L2-1: ...`: the parser now
  extracts those IDs, merges markdown sections with structured JSON by ID,
  keeps structured Layer 2 questions authoritative for shorthand detail
  records, and avoids duplicate empty synthetic Layer 1 cards. Verified with
  frontend tests, production build, web/API container rebuild, Docker status,
  and localhost browser smoke.
- [x] Implement staged Gate Challenger lazy details: new analyses can persist a
  Responses API summary contract with `gate_challenger_response_id`, lazy
  `analysis_detail_runs` load full Layer 1 / Layer 2 via
  `previous_response_id`, API exposes `POST/GET /analyses/{id}/details`, and
  Full Output can request/poll/render completed or failed detail runs while
  legacy full analyses keep rendering. Verified with full API tests, full
  worker tests, full frontend unit tests, production build, Compose config,
  Docker rebuild/restart for API/worker/web, Alembic upgrade to
  `202606140002`, and localhost browser smoke; e2e did not start because
  `E2E_ADMIN_LOGIN` / `E2E_ADMIN_PASSWORD` were not set.
- [x] Add document-title editing from the document detail pencil action:
  `PATCH /documents/{id}/title` now trims and validates titles with ownership
  checks and audit logging, the frontend API exposes `patchDocumentTitle`, and
  the detail page switches the title row into an inline editor with Save,
  Cancel, and Escape-to-cancel behavior. Verified with
  `.venv/bin/python -m pytest apps/api/tests -q`, focused
  document-detail/API frontend tests, `npm --prefix apps/web run build`, Compose
  config, web container rebuild, and localhost browser smoke; full frontend
  unit suite still fails on unrelated in-progress lazy-details tests in
  `apps/web/src/app/analyses/[analysisId]/*`.
- [x] Save staged Gate Challenger lazy-details technical specification in
  `docs/superpowers/specs/2026-06-14-staged-gate-challenger-lazy-details.md`.
- [x] Add and run isolated `prototypes/admllm-session-probe` for admllm
  Responses API: `/v1/responses` works with `previous_response_id` on
  `openai/gpt-5.5`, follow-up remembered the synthetic marker without
  resending it, `background=true` and `/responses/compact` were accepted,
  while `/responses/{id}/input_items` returned `model=None` 400 even after a
  retry with `model=openai/gpt-5.5`.
- [x] Diagnose analysis `36a2b89c-7f19-4acc-9666-bea9bcc9aee6`
  timeout: Devil's Advocate prepass completed in 44s, then the main Gate
  Challenger `openai_compatible` / `openai/gpt-5.5` call through
  `https://admllm.data-light.ru/v1` failed after roughly 3 minutes with
  upstream `InternalServerError` request-id
  `25aa1f00-adf2-42ff-a79d-94d1bd500269`; failed call returned no usage, but
  the saved main prompt is 286,847 chars / 289,036 bytes, with an estimated
  61.5k input tokens based on successful same-document Gate Challenger runs;
  the preceding Devil's Advocate prepass completed in 44.154s with 58,304 input
  tokens and 3,790 output tokens.
- [x] Add an in-page waiting loader and automatic polling to the Gate
  Challenger analysis result page while the main or Devil's Advocate run is
  `queued` / `running`; polling stops on terminal statuses. Verified with the
  focused analysis page test, full frontend tests, production build, Compose
  config, web container rebuild, and localhost browser smoke.
- [x] Fix the document-detail `Model` button display by replacing the
  concatenated text chevron with a dedicated CSS chevron and trigger spacing,
  and simplify the model popover to only output language, model selection, and
  save; verified with frontend tests, production build, web container rebuild,
  and a localhost browser check.
- [x] Move analysis-page `Detailed checks` and the full Devil's Advocate
  display into `Full Output`, leaving the main Gate Challenger tab focused on
  summary/narrative output and removing the standalone Devil's Advocate tab;
  verified with analysis page tests, full frontend tests, production build,
  web container rebuild, and localhost browser smoke.
- [x] Fix `short summary` display on the analysis page so summary text uses
  the full card width instead of the old 92-character measure; verified with
  the analysis page frontend test, production build, and web container
  rebuild.
- [x] Move analysis-page feedback collection to variant 2: a floating
  bottom-right action opens a compact feedback sheet instead of reserving a
  right-side card beside the analysis content. Verified with the analysis page
  frontend test, production build, and web container rebuild.
- [x] Remove the `Etalon draft` card and create-draft action from the
  analysis result page for now; verified with the analysis page frontend test
  production build, and web container rebuild.
- [x] Add the analysis result `Document comments` tab between Gate Challenger
  and Devil's Advocate: Devil's Advocate `role_comments` now map onto parsed
  document anchors, render Google Docs-style role comment cards with vote-based
  avatar rings, and support bidirectional anchor/card highlighting. Verified
  with focused frontend tests, production build, and web container rebuild;
  localhost analysis browser check reached the login screen without local
  credentials.
- [x] Restrict model selection to admin-managed shared provider settings:
  admin provider keys now carry a model allowlist seeded with
  `anthropic/claude-opus-4.7`, `anthropic/claude-sonnet-4.6`,
  `deepseek/deepseek-v4-pro`, `google/gemini-3.5-flash`, `openai/gpt-5.5`,
  and `qwen/qwen3.5-397b-a17b`; non-admin analysis and benchmark launches use
  the shared admin key and select from the allowlist instead of free model
  input. Verified with API/worker/frontend tests, production build, Alembic
  upgrade on local Postgres, and rebuilt local API/web/worker containers.
- [x] Realign Gate Challenger Layer 1 / Layer 2 display with the original
  skill output contract for analysis `8a4f393b-e2b3-4947-9fca-b247ed2dfbb1`:
  Layer 1 renders `issue` / `evidence` / `severity`, Layer 2 renders
  `question` / `answer` / `evidence` / `issue`, and non-skill Layer 2 fields
  such as `Risk`, `Recommendation`, and `Reference` are not shown; verified
  with full API, worker, and web tests, production build, web container
  rebuild, and localhost browser checks.
- [x] Redesign the analysis result Layer 1 / Layer 2 display: the Gate
  Challenger tab now shows a full collapsed Layer 1 checklist by canonical
  block name and verdict, includes PASS/no-material markdown-only sections,
  nests linked Layer 2 checks, and exposes Layer 2 question answers/evidence;
  verified with frontend tests, production build, web container rebuild, and a
  localhost browser check on analysis `8a4f393b-e2b3-4947-9fca-b247ed2dfbb1`.
- [x] Add a structured Devil's Advocate to Gate Challenger Layer 4 synthesis:
  completed DA prepass results now produce ranked must-review signals,
  role consensus, decision metadata, and open IC questions, and the Gate prompt
  tells the model not to silently drop critical/high/important DA signals.
- [x] Remove the Gate Challenger section subtitle from the analysis result page
  so `skill · provider · model` stays only in Run details; verified with the
  analysis frontend test slice, production build, and web container rebuild.
- [x] Diagnose current Layer 1 / Layer 2 glue for analysis
  `8a4f393b-e2b3-4947-9fca-b247ed2dfbb1`: the main Gate Challenger view
  renders 6 structured Layer 1 groups and 5 structured Layer 2 checks, while
  the saved markdown also contains a `Problem framing and segments: PASS`
  / `No material issue` Layer 1 section plus its Layer 2 `answer: YES`
  question; those PASS-only markdown sections are visible only in Full Output.
- [x] Finish the Paper Document detail page cleanup: replace the remaining
  dark-detail shell with the `Editable / Document detail` light layout,
  top-level document actions, compact model popover, workflow cards, parsed
  markdown panel, and tabular analysis history; verified with the Documents
  frontend test slice and production build.
- [x] Implement the Paper feedback card on the analysis result page: replace
  the old usefulness select/benchmark checkbox with a 5-point icon rating,
  optional comment textarea with a 1000-character counter, and full-width
  submit action while preserving the existing feedback API usefulness contract.
- [x] Add structured Layer 1 / Layer 2 rendering on the analysis result page:
  Layer 2 questions now group under their parent Layer 1 item and show the
  contract `status` as `PASS` / `PARTIAL` / `FAIL`, with the Gate Challenger
  output schema and prompt updated so future runs return `layer_2.status`.
- [x] Diagnose analysis `23998695-0529-44b0-9b04-f1a50e898e2d` failure:
  both Devil's Advocate prepass and Gate Challenger main run used
  `openai_compatible` / `anthropic/claude-opus-4.6` and timed out upstream
  after roughly three minutes per provider request; the page can appear
  `running` until refreshed because the analysis detail UI fetches once and
  does not poll running runs.
- [x] Fix Devil's Advocate prepass failures when OpenAI-compatible Gemini
  returns only `run_mode` plus rich `native_markdown`: worker validation now
  normalizes that markdown into the required structured contract while
  preserving raw provider output; verified with worker/API tests.
- [x] Diagnose degraded Gate Challenger output for analysis
  `f0d07e82-8bfd-49fe-98b2-f6a185146978`: the run used
  `openai_compatible` / `gemini-3.5-flash`, the Devil's Advocate prepass failed
  schema validation after returning only `run_mode` and `native_markdown`, Gate
  Challenger therefore ran without `gate_challenger_layer_4_context`, and the
  document has `detected_document_type=gate_3` but
  `manual_document_type=gate_2`, causing run metadata and rendered prompts to
  disagree about the stage.
- [x] Diagnose Devil's Advocate table rendering discrepancy: the older
  `anthropic/claude-opus-4.6` run returned pipe-table Markdown plus
  `anchored_comments`, while the newer `gemini-3.5-flash` RU prepass returned
  prose sections without pipe tables or anchored comments, so the UI had no
  table-shaped Markdown to render.
- [x] Lock Devil's Advocate role-comment output to the original skill contract:
  `role_comments[].comments[]` now uses `anchor_text`, `body`,
  `comment_type`, and `severity`, with schema, worker prompt, UI extraction,
  and tests aligned to that shape.
- [x] Create root `AGENTS.md` with project, workflow, security, and
  repository-local context instructions.
- [x] Create root `TASKS.md` aligned with the MVP phase plan.
- [x] Finish full Phase 1 Docker Compose runtime verification using verified
  public mirror image defaults.
- [x] Verify frontend package install, tests, production build, and critical
  npm audit threshold.
- [x] Verify Phase 1 API login/admin/ownership smoke and Alembic
  upgrade/downgrade in a local backend venv.
- [x] Implement Phase 2 backend document upload slice: supported file upload,
  local raw storage, queued document rows, and user/admin ownership visibility.
- [x] Implement Phase 2 backend parser/job slice: `.txt`, `.md`, `.docx`, and
  `.pdf` parsers, parsed artifact storage, deterministic type detection, parse
  status updates, and upload enqueue wiring.
- [x] Implement document detail API/UI slice plus Phase 3 main-analysis MVP:
  parsed/raw/reparse endpoints, manual type override, provider key settings,
  skill list, analysis launch/detail, worker main-analysis job, provider
  adapters, and feedback capture.
- [x] Complete Phase 3 second-stage runtime: Gate2/Devil's Advocate prompt
  renderers, Devil's Advocate predicted-comments worker job, reproducible
  second-stage run metadata, API detail embedding, and result UI block.
- [x] Close Phase 3 skill admin/runtime hardening: admin skill create, archive,
  patch, source refresh, schema/source validation, provider key test endpoint,
  and worker skill-source availability checks.
- [x] Implement Phase 4 backend etalon foundation: Layer 1/Layer 2 payload
  validation, draft creation from completed analyses, ownership checks, and
  admin/annotator active-status guard.
- [x] Implement Phase 4 backend etalon review lifecycle: list/detail,
  draft editing, annotation queue, publish, and archive endpoints.
- [x] Complete Phase 4 remaining MVP: past-defense import, benchmark API,
  benchmark worker scoring/reporting, and etalon/benchmark UI pages.
- [x] Add deletion workflows for documents, admin-only users, and admin-only
  etalons using reproducibility-preserving soft-delete status.
- [x] Implement external Gate Challenger and Devil's Advocate runtime snapshots:
  source registry, immutable source artifacts, DA deterministic retrieval
  dossier, snapshot-aware worker renderers, prompt fingerprints, and API/UI
  source/retrieval trace summaries.
- [x] Lock native output contracts for TRX-SE-style runs: Gate Challenger
  renders assessment summary followed by strict Layer 1 and Layer 2, and
  Devil's Advocate renders native `ic-voting-prompt.md` IC voting output before
  structured JSON details.
- [x] Improve document detail Analysis form so it defaults to the saved provider
  model from settings while still allowing a per-run model override; verified
  with frontend tests and production build.
- [x] Redesign the MVP web interface into a dark enterprise review console
  across documents, upload, analysis, benchmarks, etalons, annotation,
  settings, and admin pages while preserving existing API actions; verified
  with frontend/API tests, production build, code-review pass, login browser
  smoke, and the full Playwright MVP flow.
- [x] Fix responsive layout regressions in the dark redesign: app content no
  longer overflows beside the sidebar, phone navigation fits without horizontal
  scrolling, and the documents table switches to card rows on tablet/phone
  widths.
- [x] Fix document queue table compression at medium desktop widths: the side
  activity panels now stack below the table before the type/readiness columns
  become too narrow, and short type badges such as `GATE 2` stay on one line.
- [x] Simplify the dark redesign navigation and documents workspace: remove
  redundant environment/admin chips and duplicate document side panels, move
  primary navigation from the left sidebar to a top header, fold user/logout
  controls into that header, and widen the document detail workspace for dense
  review screens.
- [x] Consolidate document upload into the main Documents page and remove the
  redundant `/documents/upload` route and navigation item.
- [x] Fix document detail overflow by narrowing the launch-analysis column and
  rendering analysis history as compact rows inside the panel instead of a wide
  table that pushes the page past the viewport.
- [x] Simplify document detail controls: remove duplicate header actions and
  manual document type editing, keep document actions in one panel, and make
  analysis launch use a saved provider key with an editable model.
- [x] Remove low-value parsed-text helpers from document detail so the parsed
  text panel shows the document content directly without search controls or
  section chips.
- [x] Merge document actions and analysis launch controls into one compact
  document-detail button block, moving provider/model selection into a small
  modal opened from the Model button.
- [x] Render parsed document text and native analysis outputs as Markdown,
  including headings, emphasis, lists, code blocks, and scroll-safe tables
  without adding a frontend dependency.
- [x] Remove the internal vertical scroll from the document Parsed text panel
  so the full parsed markdown content expands on the page.
- [x] Replace the low-value Latest callout in document Analysis history with
  Model and Start new analysis actions, keeping file actions separate.
- [x] Shorten failed analysis messages in document history cards by showing a
  compact provider error summary while keeping the raw error in hover details.
- [x] Simplify the analysis result page: remove the Evidence Workbench eyebrow
  and duplicate hero summary, move provider/model/skill and run metrics into a
  Run details modal with trace data, and remove the duplicate side trace card.
- [x] Switch analysis result display to skill-level markdown passthrough: show
  Gate Challenger and Devil's Advocate outputs as the model-facing markdown
  fields first, with structured JSON kept only in Full Output for diagnostics.
- [x] Keep Gate Challenger main analysis text separate from detailed checks:
  Layer 1 and Layer 2 markdown now render below it under a collapsed
  `Детализированные проверки` section.
- [x] Remove duplicate verdict display from the analysis result sidebar so the
  verdict appears only once in the page header.
- [x] Compact the document detail workflow status into the right side of the
  title row and move raw download, reparse, and delete actions into the parsed
  document panel; verified desktop and 390px mobile layout with no horizontal
  overflow.
- [x] Fix Markdown table rendering for Devil's Advocate outputs: typed table
  columns now keep readable widths and scroll horizontally inside the markdown
  block instead of squeezing `TYPE` and `SEVERITY` into vertical text.
- [x] Fix Markdown loose ordered lists in Gate Challenger outputs: numbered
  sections with paragraphs and nested bullets now stay in one ordered list
  instead of restarting every item at `1`.
- [x] Add the analyzed document title to the Analysis page header and render
  the run date as plain muted text below the title instead of a `Created` chip.
- [x] Add a document analysis RU/EN output-language toggle that stores the
  choice in `run_parameters` and injects the matching language requirement into
  Gate Challenger and Devil's Advocate prompts.
- [x] Reorder analysis execution so Devil's Advocate runs before Gate
  Challenger, persists as the traceable predicted-comment run, and passes its
  Brutal Truth plus Detected Contradictions & Missing Proofs into the Gate
  prompt as Layer 4 expert context.
- [x] Restore the Gate Challenger analysis `short summary` block at the top of
  the result view and remove the duplicated `Оценка документа` heading from
  the lower narrative markdown block.
- [x] Reduce oversized markdown headings in analysis outputs by keeping
  markdown heading styles isolated from page-level analysis title styles.
- [x] Tighten Gate Challenger Layer 1 output contract so Layer 1 items expose
  only `issue`, `evidence`, and `severity` instead of the older expanded
  `title` / `impact` / `recommendation` shape.
- [x] Split Devil's Advocate result markdown into three reader-facing sections:
  pre-role critique, Role comments / voter synthesis, and Actionable JTBDs;
  verified with frontend tests, production build, and web container rebuild.
- [x] Upgrade Devil's Advocate retrieval from excerpt-only dossier to expanded
  evidence packets: selected wiki cases, patterns, heuristics, personas, and
  matching raw comments/minutes are snapshotted into `evidence_packet.md` and
  injected into the DA prompt; DB-imported past-defense etalons remain out of
  provider prompts until a dedicated access/privacy policy is added.
- [x] Finish the Paper Documents screen cleanup: remove the old dark-style
  override stack, align upload/search/table layout with `Editable / Documents`,
  add compact file markers and parse labels, and verify with frontend tests,
  production build, web container rebuild, and localhost browser layout smoke;
  full e2e is blocked locally until `E2E_ADMIN_LOGIN` and
  `E2E_ADMIN_PASSWORD` are set.
- [x] Tighten the Documents `Document type` control to match Paper: use a
  `Select document type` placeholder, title-case option/table labels, and a
  custom select chevron instead of the raw native select look.

## Phase 1: Skeleton And Data Foundation

Source plans:

- `docs/superpowers/plans/2026-06-05-gate-challenger-service/01-bootstrap-architecture.md`
- `docs/superpowers/plans/2026-06-05-gate-challenger-service/02-data-model-rbac.md`
- `docs/superpowers/plans/2026-06-05-gate-challenger-service/03-auth-admin-users.md`

Tasks:

- [x] Create monorepo skeleton: `apps/web`, `apps/api`, `apps/worker`,
  `contracts/schemas`, and `infra`.
- [x] Add `.gitignore`, `.env.example`, and root `README.md`.
- [x] Scaffold FastAPI `/health`, settings, DB session, and health test.
- [x] Scaffold worker queues and worker health job.
- [x] Scaffold Next.js TypeScript app and initial authenticated route structure.
- [x] Add initial shared JSON schema contracts.
- [x] Implement database schema, enums, migrations, and RBAC ownership rules.
- [x] Implement auth, sessions, and admin-created users.

Exit criteria:

- [x] Local Docker Compose config renders.
- [x] Database migrations run cleanly in local SQLite smoke verification.
- [x] Admin can create a user in local API smoke verification.
- [x] User can log in and access authenticated API state in local smoke
  verification.
- [x] Tests cover auth and role checks.
- [x] Frontend `/login`, `/documents`, `/admin/users`, and `/health` build and
  test successfully.
- [x] Ownership policy assertions pass in a direct Python check independent of
  unavailable backend dependencies.
- [x] Full Docker Compose stack starts with PostgreSQL, Redis, API, worker, and
  web containers.

## Phase 2: Document Workflow

Source plans:

- `docs/superpowers/plans/2026-06-05-gate-challenger-service/04-documents-parsing-storage.md`
- Document workflow portions of
  `docs/superpowers/plans/2026-06-05-gate-challenger-service/09-frontend-ui.md`

Tasks:

- [x] Implement document upload for `.docx`, `.pdf`, `.md`, and `.txt`.
- [x] Store raw files under local MVP storage with database ownership checks.
- [x] Parse and persist document text.
- [x] Detect document type and support manual override.
- [x] Show document history and document detail pages.
- [x] Enforce user/admin document visibility.

Exit criteria:

- [x] Authenticated user uploads supported files.
- [x] Raw file and parsed text are persisted.
- [x] Document type can be manually overridden.
- [x] User sees own documents; admin sees all documents.

## Phase 3: AI Analysis Runtime

Source plans:

- `docs/superpowers/plans/2026-06-05-gate-challenger-service/05-skills-providers-secrets.md`
- `docs/superpowers/plans/2026-06-05-gate-challenger-service/06-analysis-worker-results-feedback.md`
- Analysis UI portions of
  `docs/superpowers/plans/2026-06-05-gate-challenger-service/09-frontend-ui.md`

Tasks:

- [x] Implement encrypted provider key storage and masked settings API.
- [x] Implement provider adapters for OpenAI-compatible, Anthropic-compatible,
  and Hermes modes.
- [x] Implement versioned skill registry and source snapshotting.
- [x] Render Gate2-challenger and Devil's Advocate prompts into normalized
  schema contracts.
- [x] Enqueue and execute analysis jobs in workers.
- [x] Persist structured output, raw output, run parameters, cost/token metadata,
  and errors.
- [x] Add analysis result UI and feedback flow.

Exit criteria:

- [x] User can save an encrypted provider key.
- [x] User can launch an analysis.
- [x] Worker persists structured and raw outputs.
- [x] Predicted-comments or Devil's Advocate second stage runs after main
  analysis.
- [x] User can leave feedback.

## Phase 4: Etalons And Benchmarks

Source plans:

- `docs/superpowers/plans/2026-06-05-gate-challenger-service/07-etalons-annotation.md`
- `docs/superpowers/plans/2026-06-05-gate-challenger-service/08-benchmark-engine.md`
- Etalon and benchmark UI portions of
  `docs/superpowers/plans/2026-06-05-gate-challenger-service/09-frontend-ui.md`

Tasks:

- [x] Create etalon drafts from analysis results.
- [x] Implement admin etalon review and activation.
- [x] Implement benchmark runs over active etalons.
- [x] Persist judge output, aggregate metrics, misses, false positives, and
  partial matches.
- [x] Add etalon and benchmark UI.

Exit criteria:

- [x] User creates etalon draft from analysis.
- [x] Admin can activate etalon.
- [x] Benchmark runs over active etalons.
- [x] Benchmark persists precision, recall, F1, missed findings, false
  positives, and partial matches.

## Phase 5: Admin, Audit, Hardening

Source plans:

- `docs/superpowers/plans/2026-06-05-gate-challenger-service/10-admin-observability-testing.md`
- Remaining admin portions of
  `docs/superpowers/plans/2026-06-05-gate-challenger-service/09-frontend-ui.md`

Tasks:

- [x] Implement admin views for users, documents, analyses, skills, etalons,
  benchmarks, and feedback.
- [x] Add audit log service and required audit events.
- [x] Add structured API and worker logging with request/job IDs.
- [x] Add reproducibility contract tests for analyses and benchmarks.
- [x] Create `docs/acceptance/mvp-checklist.md`.
- [x] Add one root-level `test` command or Makefile target.
- [x] Run the full MVP acceptance suite with seeded admin credentials and the
  local API/worker stack.
- [x] Align document type selection with canonical Gate Challenger stages:
  Gate 2, 1st Stream Review, 2+ Stream Review, and Gate 3.
- [x] Add soft-delete endpoints for documents, users, and admin etalons with
  audit records and active-list filtering.

Exit criteria:

- [x] Admin sections cover all MVP operational entities.
- [x] Audit log records sensitive actions without secrets.
- [x] Reproducibility metadata is covered by automated tests.
- [x] MVP checklist maps each acceptance criterion to a verification method.

## Out Of MVP

- Full annotator queue automation.
- Scheduled and bulk benchmarks.
- PPTX and Google Docs/Slides import.
- Organization-level shared provider keys.
- Complex team workspaces.
- UI comments inside documents.
- Etalon version diff UI.

## Decision Log

- 2026-06-07: Added root agent and task workflow documents.
- 2026-06-07: Implemented Phase 1 scaffold, initial schema migration, RBAC
  ownership helpers, cookie session auth, admin user management, bootstrap admin
  seed, baseline skill seed helper, and minimal Next.js authenticated routes.
  Runtime verification is blocked by DNS failures to PyPI, GitHub release
  assets, and npm package installation; Docker daemon setup also depends on
  Colima image download.
- 2026-06-08: Implemented external skill runtime reproducibility. Gate
  Challenger and Devil's Advocate external sources are configured as
  `skill_sources`, snapshotted per run into local artifacts, rendered by workers
  from immutable snapshots, and exposed through API/UI trace summaries. Devil's
  Advocate now builds deterministic lexical retrieval dossiers from the
  snapshotted `wiki-ic` corpus before predicted-comments enqueue.
- 2026-06-07: Frontend dependencies installed using project-local npm cache.
  `npm --prefix apps/web run test`, `npm --prefix apps/web run build`, and
  `npm --prefix apps/web audit --audit-level=critical` pass after updating
  Vitest to 4.1.8. Two moderate Next/PostCSS advisories remain with only a
  breaking `npm audit fix --force` path reported by npm audit.
- 2026-06-07: Reconfirmed backend runtime blockers. `curl` resolves
  `registry.npmjs.org`, but resolving `files.pythonhosted.org` and
  `release-assets.githubusercontent.com` times out; `pip` and `uv pip` cannot
  install backend dependencies, and Colima cannot download its VM image.
- 2026-06-07: Built a local `.venv-backend` using system-site packages,
  cached FastAPI/Starlette, and GitHub source installs for SQLAlchemy, Mako,
  and Alembic. Verified backend imports, password hashing fallback, Alembic
  `upgrade head` and `downgrade base` against SQLite, and a FastAPI TestClient
  smoke covering `/health`, admin login, `/auth/me`, admin user creation/list,
  non-admin 403, blocked user login denial, ownership policies, and worker
  health job. Docker daemon remains unavailable, so full Compose stack with
  PostgreSQL/Redis is still not verified.
- 2026-06-07: Retried Docker Desktop after the daemon became available.
  `docker ps` succeeds and Compose config renders. Full Compose startup remains
  blocked by external DNS failures to Docker Hub (`registry-1.docker.io`) for
  `postgres:16-alpine`/`redis:7-alpine`. Cached-image fallbacks were checked:
  Supabase PostgreSQL and Studio/Node images are present, but no Redis image is
  available, and the cached Python image lacks `pydantic-settings`, `psycopg`,
  `redis`, `rq`, and `passlib`. Installing those or Redis from PyPI/Alpine is
  also blocked by DNS failures to `files.pythonhosted.org` and Alpine package
  repositories.
- 2026-06-07: Found a working registry path through `mirror.gcr.io` for official
  PostgreSQL, Redis, Python, and Node images. Updated Compose defaults and
  `.env.example` to use that public mirror while preserving env overrides.
  Regenerated the web `package-lock.json` in a Linux Node container so Docker
  `npm ci` includes Linux optional dependency entries. Verified full Compose
  stack startup, PostgreSQL Alembic `upgrade head`, bootstrap admin seed, API
  `/health`, admin login with HTTP-only cookie, `/auth/me`, admin user create
  and list, non-admin `403` on admin users, blocked-user login denial,
  ownership policy assertions inside the API image, RQ worker health job
  execution through Redis, and web `/login` plus `/health` routes on port 3000.
- 2026-06-07: Browser-level login smoke found a loopback host mismatch:
  opening the web app at `127.0.0.1:3000` while the API client targeted
  `localhost:8000` caused failed browser auth. Added a CORS regression for both
  `localhost` and `127.0.0.1`, allowed both frontend origins in the API, and made
  the web API client align local API hostname with the current browser hostname.
  Verified browser login reaches `/documents` and the admin users UI creates and
  lists a user.
- 2026-06-07: Completed the document detail and main-analysis MVP slice. The API
  exposes parsed text, raw download, manual document type override, reparse,
  provider key settings, skills, analyses, and feedback. The worker now has
  OpenAI-compatible, Anthropic-compatible, Hermes, and mock provider adapters,
  validates structured output against shared schemas, and persists raw output,
  token/cost metadata, verdict, summary, status, and errors. Predicted-comments
  and specialized Gate2/Devil's Advocate renderers remain open Phase 3 work.
- 2026-06-07: Closed the Phase 3 second-stage runtime slice. Added
  Gate2-challenger and Devil's Advocate prompt renderers, `run_predicted_comments`
  worker job, second-stage reproducibility metadata on `predicted_comment_runs`,
  automatic enqueue after successful main analysis, enqueue-failure handling that
  preserves the completed main analysis, API embedding of the latest predicted
  comment run, and a Devil's Advocate result UI block.
- 2026-06-08: Closed the remaining Phase 3 skill/provider gaps. Added admin
  skill create, patch, archive, and source-refresh endpoints; result schema and
  local source validation; deterministic source fingerprint refresh; provider
  key configuration test endpoint without plaintext key exposure; provider-key
  and skill audit events; and worker failures for unavailable or changed
  external skill sources before provider calls.
- 2026-06-08: Started Phase 4 with the backend etalon foundation. Added
  Pydantic validation for expected verdict, Layer 1, Layer 2, evidence, and
  Layer 2 parent links; added `POST /analyses/{analysis_id}/etalon-draft`;
  draft creation now enforces analysis ownership, completed-analysis
  precondition, source `ai_post_annotation`, and admin/annotator-only active
  status.
- 2026-06-08: Added the backend etalon review lifecycle. Authenticated users can
  list active etalons and their own drafts; admin/annotator can review drafts
  through the annotation queue, edit non-archived etalons, publish drafts to
  active, and archive etalons. Draft authors can edit their own drafts, but
  normal users cannot edit active etalons or publish/archive lifecycle state.
- 2026-06-08: Completed Phase 4 MVP. Added past-defense import with raw document
  storage, parse enqueue, and imported etalon drafts; benchmark API and worker
  execution over active etalons; nested benchmark judge output contract;
  precision/recall/F1 scoring with partial-match reporting; persisted benchmark
  report JSON; and frontend pages for etalons, annotation, benchmark launch, and
  benchmark results.
- 2026-06-08: Implemented Phase 5 admin/audit/hardening slice. Added admin
  sections for documents, analyses, skills, etalons, benchmarks, and feedback;
  centralized audit recording with secret redaction; request/job/provider
  structured logging; reproducibility contract tests; MVP acceptance checklist;
  root `make test`; and the initial Playwright e2e spec/preflight.
- 2026-06-08: Closed MVP acceptance testing. Added Playwright as a web dev
  dependency, expanded the e2e spec into the full admin/user document-analysis
  flow, made the e2e runner start the production Next.js build automatically,
  excluded e2e specs from Vitest, ignored Playwright artifacts, and verified
  `make test` end-to-end: 106 backend/worker tests, 16 frontend unit tests,
  Next.js production build, Docker Compose config, and the full Playwright MVP
  flow pass.
- 2026-06-08: Aligned user-selectable document types to the current Gate
  Challenger skill stages: `gate_2`, `stream_review_1`,
  `stream_review_2_plus`, and `gate_3`. Kept `unknown` as the internal
  auto-detection fallback, removed old Gate 1/progress/strategy/generic stream
  options from selection, updated deterministic detection and baseline skill
  source path to `skills/gate-challenger/SKILL.md`, and verified API, worker,
  frontend unit tests plus web production build.
- 2026-06-08: Added soft-delete API coverage for documents, users, and admin
  etalons. Deletes mark rows as `deleted`, preserve artifacts/history, filter
  active user-facing lists, and record `document.deleted`, `user.deleted`, and
  `etalon.deleted` audit events.
- 2026-06-08: Added local SOCKS5 outbound proxy support for API/worker runtime
  and Python image builds through `OUTBOUND_PROXY_URL`. Provider adapters now
  pass proxy-aware HTTP clients for OpenAI-compatible, Anthropic-compatible, and
  Hermes calls while respecting `NO_PROXY` for local service hosts. Verified
  worker/API tests, Compose config, Python image build, and worker-container
  SOCKS availability.
- 2026-06-09: Implemented the dark enterprise frontend redesign from generated
  prototypes. AppShell now uses a sidebar workspace layout and the main MVP
  screens use dark graphite panels, dense tables, evidence workbench layouts,
  benchmark QA dashboards, and animated upload/loading affordances. Review
  fixes preserved full parsed text traceability, clarified document readiness
  vs verdict labeling, and made annotation JSON editors tolerate invalid draft
  input without discarding edits. Full e2e exposed an analysis-contract vs
  etalon-draft payload mismatch, so draft creation now maps current Gate
  Challenger Layer 1/2 output into annotation payload fields while preserving
  the older etalon-shaped input. Verified API etalon tests, frontend unit
  tests, production build, Compose config, independent review/tester agents,
  login browser smoke, and the full Playwright MVP flow.
- 2026-06-09: Fixed dark redesign responsiveness after browser review. Replaced
  document-page `100vw` width calculations with container-relative widths,
  compacted the mobile topbar/navigation, and converted the documents table to
  card rows on tablet/phone widths. Verified no page-level horizontal overflow
  at 1280, 1024, 768, 390, 360, and 320 px; frontend tests, production build,
  and the full Playwright MVP flow pass.
- 2026-06-10: Reordered analysis runtime so Devil's Advocate now runs as a
  pre-Gate expert critique inside `run_analysis`. The completed DA run remains
  persisted in `predicted_comment_runs`, and its `brutal_truth` plus
  `detected_contradictions` are stored in
  `analyses.run_parameters.gate_challenger_layer_4_context` and injected into
  the Gate Challenger prompt as Layer 4 expert context to strengthen or
  supplement document-grounded Gate findings.
- 2026-06-10: Fixed local Docker Start Analysis failures with
  `git command failed: rev-parse HEAD`. The API now defaults missing
  `snapshot_mode` to `development_current` when `APP_ENV=development`, so
  mounted external skill directories without usable git metadata can still be
  snapshotted for local testing while non-development defaults remain
  `production_latest`.
- 2026-06-10: Restored the analysis result short-summary presentation by
  rendering `analyses.summary` / `structured_output.summary` as a dedicated
  `short summary` block above Gate Challenger markdown, while stripping only
  the leading `Оценка документа` / `Document assessment` heading from the
  lower narrative block. Verified with the new focused display-helper test, all
  frontend unit tests, the production frontend build, rebuilt local web
  container, and a browser check of analysis
  `ef79c6fa-826e-417f-b601-0d21d2f9df3f`.
- 2026-06-10: Reduced oversized markdown `#` headings inside analysis outputs
  by scoping the markdown preview heading rules above page-level analysis
  heading styles, so model-supplied report titles no longer inherit the main
  page title size. Verified with frontend unit tests, production frontend
  build, and rebuilt local web container.
- 2026-06-10: Root-caused extra `title`, `impact`, and `recommendation` blocks
  in Gate Challenger Layer 1 to the local main-analysis JSON Schema and prompt,
  not the UI renderer. Updated the Layer 1 schema/prompt to require only
  `id`, `severity`, `issue`, and `evidence`, added a contract test rejecting
  the old expanded Layer 1 shape, and refreshed affected mock provider outputs.
  Verified with targeted API/worker tests and full `apps/api/tests` +
  `apps/worker/tests`; rebuilt the local worker container.
- 2026-06-10: Audited local Gate Challenger and Devil's Advocate renderers
  against their external skill sources. Key drift points: Gate output is forced
  into a service JSON contract and DA prepass is injected into Gate as Layer 4;
  Devil's Advocate is normalized to JSON/native markdown instead of producing
  annotated `.docx` comments, and the current `full_ic_voting` naming differs
  from older plan text that used `ic_voting_full`.
- 2026-06-11: Applied the new Paper light enterprise redesign across the main
  frontend surfaces: app shell, documents list/detail, analysis result,
  benchmarks list/detail, login, markdown, tables, forms, statuses, and nested
  Layer 1/Layer 2 result blocks. Added a frontend token regression test,
  rebuilt the local web container, and verified desktop/mobile browser views
  have the Paper light background without visible dark legacy blocks or
  horizontal overflow. Rebuilt the worker container after confirming it still
  had the stale main-analysis schema without `layer_2.status`; updated the e2e
  MVP fixture to the tightened Layer 1 contract and current tabbed Devil's
  Advocate UI. Verified `npm --prefix apps/web run test`, `npm --prefix
  apps/web run build`, and the full Playwright MVP flow against
  `http://127.0.0.1:3000`. Backend contract pytest could not run in the host or
  runtime api container because pytest/dev dependencies are not installed
  there.
- 2026-07-10: Debugged a local document parsing stall after rebuilding the
  frontend/API stack. The web and API containers were healthy, but the worker
  service was not running, leaving the uploaded document queued in Redis. Started
  and rebuilt the worker container; the queued `.docx` parse completed, the
  document moved to `parse_status=completed`, Redis document queue drained to
  zero, and local web/API checks returned HTTP 200 on `127.0.0.1`.
- 2026-07-10: Fixed local `ERR_SOCKET_NOT_CONNECTED` failures on
  `http://localhost:3000` after tracing them to broken IPv6 localhost forwarding
  in the Docker/Colima port binding. Updated local Compose to publish API/web on
  `127.0.0.1` and to use `http://127.0.0.1:8000` as the public API base URL.
  Recreated API/web containers and verified both `localhost` and `127.0.0.1`
  return HTTP 200 for the document page and API docs.
- 2026-07-10: Fixed local Start Analysis precondition
  `No active main analysis skill is available`. Root cause was an empty local
  `skills` table after reinitializing local users/documents. Added local Compose
  IC Agentic Review source mount/env so baseline seeding has all external
  sources, recreated API/worker containers, ran `app.seeds.skills`, and verified
  six active baseline skills including `gate2_challenger_main_analysis`.
- 2026-07-10: Fixed local Start Analysis `Failed to fetch` caused by API 500
  during skill source snapshot creation. The local database was still at
  Alembic `202606180001` while the code expected `202607090001`, so
  `skill_source_snapshots.analysis_check_run_id` was missing. Ran
  `alembic upgrade head` in the API container and verified snapshot creation for
  `gate-challenger` succeeds in a rollback smoke test.
- 2026-07-10: Root-caused missing Devil's Advocate output on analysis
  `4878a5fa-fbf6-4049-97cb-a889b9939896` to document typing, not DA runtime.
  The uploaded document was `detected_document_type=unknown` with no manual
  override, so the DA prepass skipped the `devils_advocate_predefense` skill
  and no `predicted_comment_run` was created. Fixed the document detail launch
  payload to prefer `manual_document_type` over `detected_document_type` and
  verified the focused frontend tests pass.
