# Skills, Providers, and Secrets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Manage versioned skills, external skill sources, encrypted provider keys, provider test connections, and normalized GPT, Claude, and Hermes calls.

**Architecture:** Skills are database records with prompt text, schema references, source metadata, and source fingerprints. Provider-specific logic lives behind adapters that return a single normalized result shape to the worker.

**Tech Stack:** FastAPI, SQLAlchemy, cryptography Fernet or AES-GCM, OpenAI SDK, Anthropic SDK, HTTPX for Hermes, Pydantic.

---

## Files

- Create: `apps/api/app/security/secrets.py`
- Create: `apps/api/app/services/provider_keys.py`
- Create: `apps/api/app/services/skill_sources.py`
- Create: `apps/api/app/routers/provider_settings.py`
- Create: `apps/api/app/routers/skills.py`
- Create: `apps/api/app/schemas/provider_settings.py`
- Create: `apps/api/app/schemas/skills.py`
- Create: `apps/worker/providers/base.py`
- Create: `apps/worker/providers/openai_compatible.py`
- Create: `apps/worker/providers/anthropic_compatible.py`
- Create: `apps/worker/providers/hermes.py`
- Create: `apps/worker/providers/registry.py`
- Create: `apps/worker/skills/source_loader.py`
- Create: `apps/worker/skills/prompt_renderer.py`
- Create: `apps/worker/skills/gate2_challenger_renderer.py`
- Create: `apps/worker/skills/devils_advocate_renderer.py`
- Create: `apps/api/tests/test_provider_keys.py`
- Create: `apps/api/tests/test_skill_sources.py`
- Create: `apps/worker/tests/test_provider_adapters.py`
- Create: `apps/worker/tests/test_skill_renderers.py`

## Skill Types

Required baseline skills:

- `gate2_challenger_main_analysis`: canonical Gate 2 reviewer sourced from `/Users/iseremenko/Projects/Gate2-challenger/skills/gate2-challenger/SKILL.md`; returns verdict, recommendations, Layer 1, Layer 2, and raw notes.
- `devils_advocate_predefense`: canonical adversarial / pre-defense simulation sourced from `/Users/iseremenko/Documents/Common GPTs/devils-advocate/ic-voting-prompt.md` and its `wiki-ic/` knowledge base; returns four critique sections and predicted committee questions.
- `predicted_comments`: generic defense-question simulator fallback when Devil's Advocate is disabled or not applicable.
- `benchmark_judge`: compares model result with etalon and produces matches, misses, false positives, partial matches.
- `document_classifier`: optional AI classifier for future replacement of deterministic type detection.

## Canonical Local Skill Sources

### Gate2-challenger

Source:

```text
/Users/iseremenko/Projects/Gate2-challenger
```

Entrypoint:

```text
skills/gate2-challenger/SKILL.md
```

Role:

- default `main_analysis` skill for `Gate 2` documents;
- uses a five-pass review model: coordinator normalization, Layer 1 decision-critical review, Layer 2 atomic weak-link review, Layer 3 adversarial business and committee-risk review, synthesizer final verdict;
- must be rendered into the service's `main-analysis-result.schema.json` so UI and benchmark code do not depend on the external skill's internal artifact names.

Runtime rule:

- before each run, snapshot the entrypoint text, repository revision, and source fingerprint into `analyses.run_parameters.skill_source_snapshot`;
- do not read a changed external skill file when displaying historical results.

### Devil's Advocate

Source:

```text
/Users/iseremenko/Documents/Common GPTs/devils-advocate
```

Entrypoints:

```text
workflow-ic-cases.md
ic-voting-prompt.md
wiki-ic/
wiki-ic/schema.md
wiki-ic/meta/output-format.md
```

Role:

- default adversarial second-stage source after the main analysis runs the full `ic-voting-prompt.md` orchestrator;
- uses Avito InvCo personas, historical cases, heuristics, patterns, domains, native-comment aggregation rules, four-section trailer format, and IC decision logic;
- supports explicit run modes:
  - `ic_voting_full` is the MVP default and follows `ic-voting-prompt.md` end to end;
  - `ic_query_pattern_check` is optional and follows `/ic:query "check this draft against known red-flag patterns"` semantics for lightweight diagnostics;
  - `ic_persona_simulation` is optional and follows `/ic:query "as persona-..., review ..."` semantics;
- produces a normalized structured result with anchored reviewer comments, four-section trailer, IC decision block, predicted committee questions, consulted wiki pages, and source citations.

Runtime rule:

- load only the relevant wiki pages selected by document type, domain, detected issues, and run parameters;
- snapshot the selected wiki page slugs, source revision, and source fingerprints into the run;
- do not store raw private user documents inside the Devil's Advocate repository.

## JSON Schema Contracts

Main analysis result must include:

```json
{
  "document_type": "Gate 2",
  "document_type_confidence": 0.87,
  "verdict": "NEED_EVIDENCE",
  "verdict_summary": "Short reason",
  "confidence": 0.82,
  "key_findings": [],
  "recommendations": [],
  "layer_1": [],
  "layer_2": [],
  "raw_notes": ""
}
```

Predicted-comments result must include:

```json
{
  "summary": "Short summary",
  "overall_risk": "HIGH",
  "predicted_comments": []
}
```

Devil's Advocate default result must include:

```json
{
  "run_mode": "ic_voting_full",
  "comment_records": [],
  "trailer": {
    "brutal_truth": "The single biggest fatal flaw.",
    "detected_contradictions": [],
    "tough_questions": [],
    "actionable_jtbds": []
  },
  "ic_decision": {
    "outcome": "reject",
    "rationale": "Short reason"
  },
  "predicted_comments": [],
  "consulted_pages": [],
  "source_citations": []
}
```

Optional Devil's Advocate query result is only valid for explicitly selected `/ic:query` modes and may include:

```json
{
  "run_mode": "ic_query_pattern_check",
  "summary": "Short cited summary",
  "overall_risk": "HIGH",
  "findings": [],
  "likely_questions": [],
  "predicted_comments": [],
  "evidence_gaps": [],
  "remediation_tasks": [],
  "consulted_pages": [],
  "source_citations": []
}
```

## Provider Key Rules

- API keys are encrypted before storage.
- API key plaintext is only available inside request scope for test connection or inside worker runtime for a run.
- API key is never returned to frontend.
- API key fingerprint is shown as the last 4 characters plus provider label, for example `openai_compatible:...ABCD`.
- Admin system key can be added in the schema later; MVP starts with user keys.

## Provider Adapter Contract

All adapters return:

```python
class AnalysisProviderResult(BaseModel):
    structured_text: str
    raw_output: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    estimated_cost: Decimal | None
    provider_metadata: dict
```

Adapters accept:

```python
class ProviderRunRequest(BaseModel):
    provider: str
    model: str
    api_key: str | None
    base_url: str | None
    prompt: str
    response_schema: dict
    run_parameters: dict
```

Hermes may use `api_key=None` when it is configured as local trusted provider.

## API Endpoints

```text
GET /settings/provider-keys
PUT /settings/provider-keys/{provider}
DELETE /settings/provider-keys/{provider}
POST /settings/provider-keys/{provider}/test
GET /skills
GET /skills/{skill_id}
POST /admin/skills
PATCH /admin/skills/{skill_id}
POST /admin/skills/{skill_id}/archive
POST /admin/skills/{skill_id}/refresh-source
```

## Tasks

### Task 1: Secret Encryption

- [ ] Implement encryption and decryption in `security/secrets.py`.
- [ ] Derive encryption material from `APP_SECRET_KEY`.
- [ ] Add tests:
  - encrypted value differs from plaintext;
  - decrypt returns plaintext;
  - wrong key cannot decrypt.

Acceptance:

- provider key tests pass;
- encrypted API keys are byte strings in the database.

### Task 2: Provider Settings API

- [ ] Implement save key.
- [ ] Implement list masked provider settings.
- [ ] Implement delete key.
- [ ] Implement test connection endpoint.
- [ ] Add audit logs for create, replace, delete, test failure.

Acceptance:

- frontend never receives plaintext key;
- invalid key returns user-facing provider error;
- deletion removes encrypted key row.

### Task 3: Skills Admin API

- [ ] Implement skill list for all authenticated users.
- [ ] Implement admin create skill version.
- [ ] Implement admin archive skill version.
- [ ] Implement source refresh for local skill repositories.
- [ ] Validate `result_schema_path` points to an existing file under `contracts/schemas`.
- [ ] Validate local source paths exist for `local_skill_repo` and `local_knowledge_base`.
- [ ] Compute source fingerprint from entrypoint files and selected wiki/config files.

Acceptance:

- active skills are selectable for analyses;
- archived skills remain visible in historical analysis rows but cannot be selected for new runs.
- Gate2-challenger and Devil's Advocate seed records show source path, entrypoint, revision, and fingerprint.

### Task 3.5: Canonical Skill Source Renderers

- [ ] Implement `gate2_challenger_renderer.py` that converts the Gate2-challenger instructions into the service prompt frame and requires output compatible with `main-analysis-result.schema.json`.
- [ ] Implement `devils_advocate_renderer.py` that reads `ic-voting-prompt.md`, `wiki-ic/schema.md`, `wiki-ic/meta/output-format.md`, and selected wiki pages for the default `ic_voting_full` mode, then requires output compatible with `devils-advocate-result.schema.json`.
- [ ] Add optional `/ic:query` support in `devils_advocate_renderer.py` that reads `workflow-ic-cases.md`, `wiki-ic/schema.md`, and selected wiki pages, then requires output compatible with `devils-advocate-query-result.schema.json`.
- [ ] Add renderer tests with fixed fixture inputs.

Acceptance:

- Gate2-challenger renderer includes the five-pass review contract and Russian human-facing explanations.
- Devil's Advocate default renderer follows the full `ic-voting-prompt.md` orchestration: subagent votes, anchor validation, sanitized comments, four-section trailer, IC Decision block, and selected wiki citations.
- Devil's Advocate query renderer follows `/ic:query` pattern-check semantics only when that run mode is explicitly selected.
- Both renderers produce deterministic prompts for the same source snapshot and document input.

### Task 4: Provider Adapters

- [ ] Implement OpenAI-compatible adapter with configurable base URL.
- [ ] Implement Anthropic-compatible adapter.
- [ ] Implement Hermes HTTP adapter.
- [ ] Implement Hermes disabled error when `HERMES_ENABLED=false`.
- [ ] Add fake provider tests using mocked SDK clients.

Acceptance:

- all adapters return `AnalysisProviderResult`;
- Hermes unavailable is persisted as provider unavailable, not as generic crash.

### Task 5: Prompt Rendering

- [ ] Implement prompt renderer with inputs:
  - document title;
  - parsed text;
  - document type;
  - skill prompt or external skill source snapshot;
  - expected JSON schema.
- [ ] Add prompt rendering tests that assert schema and document type are included.

Acceptance:

- rendered prompt is deterministic for same inputs;
- prompt does not include API keys or encrypted values.

## Verification

Run:

```bash
pytest apps/api/tests/test_provider_keys.py apps/api/tests/test_skill_sources.py apps/worker/tests/test_provider_adapters.py apps/worker/tests/test_skill_renderers.py -q
```

Expected:

- encryption tests pass;
- skill source tests pass for Gate2-challenger and Devil's Advocate paths;
- provider adapter mocked tests pass;
- skill schema validation tests pass.
