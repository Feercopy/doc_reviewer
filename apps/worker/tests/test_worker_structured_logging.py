import logging

from app.models.analysis import Analysis
from app.models.provider_key import ProviderKey
from app.schemas.enums import Provider, RunStatus
from app.security.secrets import encrypt_secret
from jobs.run_analysis import run_analysis

from test_run_analysis_job import (
    _close_session,
    _create_document,
    _create_session,
    _create_skill,
    _create_user,
    _main_analysis_json,
)


def test_worker_and_provider_logs_include_job_context_without_api_key(tmp_path, caplog):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        db.add(
            ProviderKey(
                owner_id=user.id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url=None,
                default_model="gpt-test",
                encrypted_api_key=encrypt_secret("sk-should-not-log"),
                api_key_fingerprint="openai_compatible:...-log",
            )
        )
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": _main_analysis_json("Needs evidence."),
                    "raw_output": "raw output",
                    "input_tokens": 3,
                    "output_tokens": 4,
                    "latency_ms": 5,
                },
                "api_key": "sk-should-not-log",
            },
        )
        db.add(analysis)
        db.commit()

        with caplog.at_level(logging.INFO):
            run_analysis(str(analysis.id), db=db, enqueue_predicted_comments=lambda run_id: None)

        worker_records = [record for record in caplog.records if record.name == "gate_challenger.worker"]
        provider_records = [record for record in caplog.records if record.name == "gate_challenger.provider"]
        assert any(record.job_type == "run_analysis" and record.entity_id == str(analysis.id) for record in worker_records)
        assert any(record.status == "completed" for record in worker_records)
        assert any(record.provider == "openai_compatible" and record.model == "gpt-test" for record in provider_records)
        assert any(record.input_tokens == 3 and record.output_tokens == 4 and record.latency_ms == 5 for record in provider_records)
        assert "sk-should-not-log" not in caplog.text
    finally:
        _close_session(db)
