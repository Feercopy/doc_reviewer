import json

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


def _summary_output() -> dict:
    return {
        "verdict": "need_evidence",
        "summary": "Needs evidence",
        "assessment_markdown": "Document assessment\nNeeds evidence.",
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
