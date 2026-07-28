import json

from app.core.config import get_settings
from app.models.analysis import Analysis, AnalysisDetailRun
from app.models.provider_key import ProviderKey
from app.schemas.enums import Provider, RunStatus, Verdict, Role
from app.security.secrets import encrypt_secret
from jobs.run_analysis_details import run_analysis_details
from test_run_analysis_job import _close_session, _create_document, _create_session, _create_skill, _create_user


def test_run_analysis_details_uses_previous_response_id_and_persists_details(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        db.add(
            ProviderKey(
                owner_id=_create_user(db, role=Role.ADMIN).id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url="https://admllm.test/v1",
                default_model="openai/gpt-5.5",
                encrypted_api_key=encrypt_secret("sk-test"),
                api_key_fingerprint="openai_compatible:...test",
            )
        )
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="openai/gpt-5.5",
            status=RunStatus.COMPLETED.value,
            verdict=Verdict.NEED_EVIDENCE.value,
            summary="Needs evidence",
            structured_output=_summary_output(),
            run_parameters={
                "provider_api": "responses",
                "gate_challenger_response_id": "resp-summary-1",
                "output_language": "en",
            },
        )
        db.add(analysis)
        db.flush()
        detail_run = AnalysisDetailRun(
            analysis_id=analysis.id,
            status=RunStatus.QUEUED.value,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="openai/gpt-5.5",
            previous_response_id="resp-summary-1",
            run_parameters={
                "provider_api": "responses",
                "mock_provider_response_result": {
                    "structured_text": json.dumps(_details_output(str(analysis.id))),
                    "raw_output": "raw detail responses",
                    "input_tokens": 50,
                    "output_tokens": 75,
                    "latency_ms": 250,
                    "provider_metadata": {"response_id": "resp-detail-1"},
                },
            },
        )
        db.add(detail_run)
        db.commit()

        run_analysis_details(str(detail_run.id), db=db)

        db.refresh(detail_run)
        db.refresh(analysis)
        assert analysis.status == RunStatus.COMPLETED.value
        assert detail_run.status == RunStatus.COMPLETED.value
        assert detail_run.previous_response_id == "resp-summary-1"
        assert detail_run.response_id == "resp-detail-1"
        assert detail_run.structured_output["layer_1"][0]["id"] == "L1-001"
        assert detail_run.raw_output == "raw detail responses"
        assert detail_run.input_tokens == 50
        assert detail_run.output_tokens == 75
        assert detail_run.run_parameters["provider_api"] == "responses"
        assert detail_run.run_parameters["prompt_fingerprint"]
        assert detail_run.run_parameters["rendered_prompt_artifact_path"]
    finally:
        _close_session(db)


def test_run_analysis_details_falls_back_to_saved_prompt_without_previous_response_id(tmp_path, monkeypatch):
    db = _create_session()
    try:
        storage_root = tmp_path / "storage"
        monkeypatch.setenv("STORAGE_ROOT", str(storage_root))
        get_settings.cache_clear()
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        prompt_path = storage_root / "prompts" / str(document.id) / "rendered.txt"
        prompt_path.parent.mkdir(parents=True)
        prompt_path.write_text("Original Gate Challenger prompt with full parsed document evidence.", encoding="utf-8")
        db.add(
            ProviderKey(
                owner_id=_create_user(db, role=Role.ADMIN).id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url="https://admllm.test/v1",
                default_model="openai/gpt-5.5",
                encrypted_api_key=encrypt_secret("sk-test"),
                api_key_fingerprint="openai_compatible:...test",
            )
        )
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="openai/gpt-5.5",
            status=RunStatus.COMPLETED.value,
            verdict=Verdict.NEED_EVIDENCE.value,
            summary="Needs evidence",
            structured_output=_summary_output(),
            run_parameters={
                "output_language": "en",
                "rendered_prompt_artifact_path": str(prompt_path),
            },
        )
        db.add(analysis)
        db.flush()
        detail_run = AnalysisDetailRun(
            analysis_id=analysis.id,
            status=RunStatus.QUEUED.value,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="openai/gpt-5.5",
            previous_response_id=None,
            run_parameters={
                "provider_api": "chat_completions_fallback",
                "mock_provider_result": {
                    "structured_text": json.dumps(_details_output(str(analysis.id))),
                    "raw_output": "raw detail fallback",
                    "input_tokens": 150,
                    "output_tokens": 175,
                    "latency_ms": 350,
                },
            },
        )
        db.add(detail_run)
        db.commit()

        run_analysis_details(str(detail_run.id), db=db)

        db.refresh(detail_run)
        db.refresh(analysis)
        assert analysis.status == RunStatus.COMPLETED.value
        assert analysis.structured_output["details_status"] == RunStatus.COMPLETED.value
        assert detail_run.status == RunStatus.COMPLETED.value
        assert detail_run.previous_response_id is None
        assert detail_run.response_id is None
        assert detail_run.structured_output["layer_1"][0]["id"] == "L1-001"
        assert detail_run.raw_output == "raw detail fallback"
        assert detail_run.input_tokens == 150
        assert detail_run.output_tokens == 175
        assert detail_run.run_parameters["provider_api"] == "chat_completions_fallback"
        assert detail_run.run_parameters["fallback_reason"] == "gate_challenger_response_id_missing"
        rendered_prompt = get_settings().storage_root
        prompt_text = open(detail_run.run_parameters["rendered_prompt_artifact_path"], encoding="utf-8").read()
        assert str(rendered_prompt) in detail_run.run_parameters["rendered_prompt_artifact_path"]
        assert "Original Gate Challenger prompt with full parsed document evidence." in prompt_text
    finally:
        _close_session(db)
        get_settings.cache_clear()


def test_run_analysis_details_failure_keeps_main_analysis_completed(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        db.add(
            ProviderKey(
                owner_id=_create_user(db, role=Role.ADMIN).id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url="https://admllm.test/v1",
                default_model="openai/gpt-5.5",
                encrypted_api_key=encrypt_secret("sk-test"),
                api_key_fingerprint="openai_compatible:...test",
            )
        )
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="openai/gpt-5.5",
            status=RunStatus.COMPLETED.value,
            verdict=Verdict.NEED_EVIDENCE.value,
            summary="Needs evidence",
            structured_output=_summary_output(),
            run_parameters={"provider_api": "responses", "gate_challenger_response_id": "resp-summary-1"},
        )
        db.add(analysis)
        db.flush()
        detail_run = AnalysisDetailRun(
            analysis_id=analysis.id,
            status=RunStatus.QUEUED.value,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="openai/gpt-5.5",
            previous_response_id="resp-summary-1",
            run_parameters={
                "provider_api": "responses",
                "mock_provider_response_result": {
                    "structured_text": "not json",
                    "raw_output": "raw invalid detail",
                    "latency_ms": 100,
                },
            },
        )
        db.add(detail_run)
        db.commit()

        run_analysis_details(str(detail_run.id), db=db)

        db.refresh(analysis)
        db.refresh(detail_run)
        assert analysis.status == RunStatus.COMPLETED.value
        assert detail_run.status == RunStatus.FAILED.value
        assert "Expecting value" in detail_run.error_message
        assert detail_run.raw_output == "raw invalid detail"
    finally:
        _close_session(db)


def test_run_analysis_details_does_not_overwrite_cancelled_status_after_provider_race(tmp_path, monkeypatch):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        db.add(
            ProviderKey(
                owner_id=_create_user(db, role=Role.ADMIN).id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url="https://admllm.test/v1",
                default_model="openai/gpt-5.5",
                encrypted_api_key=encrypt_secret("sk-test"),
                api_key_fingerprint="openai_compatible:...test",
            )
        )
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="openai/gpt-5.5",
            status=RunStatus.COMPLETED.value,
            verdict=Verdict.NEED_EVIDENCE.value,
            summary="Needs evidence",
            structured_output=_summary_output(),
            run_parameters={"provider_api": "responses", "gate_challenger_response_id": "resp-summary-1"},
        )
        db.add(analysis)
        db.flush()
        detail_run = AnalysisDetailRun(
            analysis_id=analysis.id,
            status=RunStatus.QUEUED.value,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="openai/gpt-5.5",
            previous_response_id="resp-summary-1",
            run_parameters={
                "provider_api": "responses",
                "mock_provider_response_result": {
                    "structured_text": json.dumps(_details_output(str(analysis.id))),
                    "raw_output": "raw detail responses",
                    "provider_metadata": {"response_id": "resp-detail-1"},
                    "latency_ms": 100,
                },
            },
        )
        db.add(detail_run)
        db.commit()

        def cancel_then_parse(*args, **kwargs):
            db.refresh(detail_run)
            detail_run.status = RunStatus.CANCELLED.value
            detail_run.error_message = "cancelled_by_user"
            db.commit()
            return json.loads(kwargs["structured_text"])

        monkeypatch.setattr("jobs.run_analysis_details.parse_and_validate_json_output", cancel_then_parse)

        run_analysis_details(str(detail_run.id), db=db)

        db.refresh(detail_run)
        assert detail_run.status == RunStatus.CANCELLED.value
        assert detail_run.error_message == "cancelled_by_user"
        assert detail_run.structured_output is None
        assert detail_run.raw_output is None
    finally:
        _close_session(db)


def _summary_output() -> dict:
    return {
        "verdict": "need_evidence",
        "summary": "Needs evidence",
        "assessment_markdown": "Document assessment\nNeeds evidence.",
        "stage_checklist": [
            {
                "id": "gate2_hypothesis_results",
                "label": "Результаты проверки гипотез из Gate 1",
                "status": "red",
                "evidence": "The mock document omits Gate 1 hypothesis results.",
            }
        ],
        "layer_1_index": [],
        "layer_2_index": [],
        "details_status": "not_requested",
        "details_run_id": None,
        "revision_required": False,
        "revision_reason": None,
    }


def _details_output(analysis_id: str) -> dict:
    return {
        "analysis_id": analysis_id,
        "verdict": "need_evidence",
        "summary": "Needs evidence",
        "layer_1_markdown": "Layer 1\nL1-001 - Missing proof.",
        "layer_1": [
            {
                "id": "L1-001",
                "severity": "high",
                "issue": "Mandatory readiness is not proven.",
                "evidence": "The document does not close the required proof.",
            }
        ],
        "layer_2_markdown": "Layer 2\nL2-001 - Missing atomic proof.",
        "layer_2": [
            {
                "id": "L2-001",
                "parent_layer_1_id": "L1-001",
                "status": "fail",
                "severity": "high",
                "question": "Is the key target evidenced?",
                "answer": "NO",
                "issue": "A key target is not evidenced.",
                "evidence": "The mock document omits the proof.",
            }
        ],
        "revision_required": False,
        "revision_reason": None,
    }
