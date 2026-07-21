# MVP Acceptance Checklist

Source: section 18 of `ТЗ- сайт-анализатор документов инвестиционных защит.docx`.

| Criterion | Verification |
| --- | --- |
| Administrator can create a user. | API: `apps/api/tests/test_admin_users.py`; UI smoke: `apps/web/tests/e2e/mvp-flow.spec.cjs`. |
| User can log in with login and password. | API: `apps/api/tests/test_auth.py`; frontend API: `apps/web/src/lib/api/auth.test.ts`; e2e smoke. |
| User can upload a document. | API: `apps/api/tests/test_documents_upload.py`; e2e upload page reachability. |
| Original file is saved as raw. | API: `apps/api/tests/test_documents_upload.py::test_upload_supported_file_creates_queued_document_and_raw_file`. |
| Document parses into text. | Worker: `apps/worker/tests/test_parse_document_job.py`; parsers: `apps/worker/tests/test_document_parsers.py`. |
| System detects document type or allows manual choice. | API: `apps/api/tests/test_document_type_detector.py` and `apps/api/tests/test_documents_upload.py::test_manual_document_type_override_is_saved_separately`. |
| User can launch analysis through GPT or Claude-compatible provider. | API: `apps/api/tests/test_analyses_api.py`; worker/provider: `apps/worker/tests/test_run_analysis_job.py`, `apps/worker/tests/test_provider_adapters.py`. |
| Analysis result is saved. | Worker: `apps/worker/tests/test_run_analysis_job.py::test_run_analysis_persists_structured_and_raw_output`. |
| User sees verdict, findings, recommendations, Layer 1, and Layer 2. | Contract schemas: `apps/api/tests/test_contract_schemas.py`; UI build covers result route; manual check on `/analyses/{id}`. |
| User can open full analysis output. | UI/manual check on `/analyses/{id}` full structured output block; API: `apps/api/tests/test_analyses_api.py`. |
| Second skill predicts possible comments. | Worker: `apps/worker/tests/test_run_predicted_comments_job.py`; UI result block covered by Next build. |
| User can leave feedback. | API: `apps/api/tests/test_feedback.py`; admin feedback UI route build. |
| User sees own document history. | API: `apps/api/tests/test_documents_upload.py::test_user_sees_only_own_documents_and_admin_sees_all`; UI `/documents`. |
| Administrator sees all documents and analyses. | API: `apps/api/tests/test_admin_sections.py`; UI `/admin/documents` and `/admin/analyses`. |
| User can create etalon draft from analysis result. | API: `apps/api/tests/test_etalons.py`; UI `/etalons` and `/annotation/{id}` build. |
| Benchmark can run over at least one active etalon set. | API: `apps/api/tests/test_benchmarks_api.py`; worker: `apps/worker/tests/test_run_benchmark_job.py`. |
| Benchmark saves Layer 1, Layer 2, and overall scores. | Worker: `apps/worker/tests/test_run_benchmark_job.py`; scoring: `apps/worker/tests/test_benchmark_scoring.py`. |
| Runs save provider, model, skill version, and raw output. | Worker: `apps/worker/tests/test_reproducibility_contract.py`; API/worker analysis tests. |
| Hermes can be called as provider or is visibly disabled by configuration. | API: analysis precondition tests; settings UI lists Hermes provider; `.env.example` exposes `HERMES_ENABLED`. |

Full local verification entrypoint:

```bash
make test
```

The `test` target runs API tests, worker tests, frontend unit tests, frontend
production build, Docker Compose config validation, and the web e2e command. If
`E2E_BASE_URL` is omitted, the e2e runner starts the built web app on port
`3000`. The local API/worker stack must be running, and `E2E_ADMIN_LOGIN` plus
`E2E_ADMIN_PASSWORD` must point to a seeded admin account.
