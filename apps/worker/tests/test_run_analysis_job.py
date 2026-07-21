import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.core.config import get_settings
from app.models.analysis import Analysis, PredictedCommentRun
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.models.skill import Skill
from app.models.skill_source import SkillSource
from app.models.user import User
from app.schemas.enums import (
    DocumentParseStatus,
    DocumentType,
    EntityStatus,
    Provider,
    RunStatus,
    SkillSourceType,
    SkillType,
    UserStatus,
    Verdict,
    Role,
)
from app.security.passwords import hash_password
from app.security.secrets import encrypt_secret
from app.storage.local import LocalDocumentStorage
from jobs.run_analysis import _should_use_responses_api, run_analysis


def test_run_analysis_persists_structured_and_raw_output(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        key = ProviderKey(
            owner_id=_create_user(db, role=Role.ADMIN).id,
            provider=Provider.OPENAI_COMPATIBLE.value,
            base_url=None,
            default_model="gpt-test",
            encrypted_api_key=encrypt_secret("sk-test"),
            api_key_fingerprint="openai_compatible:...test",
        )
        db.add(key)
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
                    "structured_text": _main_analysis_summary_json("Needs stronger metric evidence."),
                    "raw_output": "raw provider text",
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "latency_ms": 30,
                }
            },
        )
        db.add(analysis)
        db.commit()

        run_analysis(str(analysis.id), db=db)

        db.refresh(analysis)
        assert analysis.status == RunStatus.COMPLETED.value
        assert analysis.verdict == Verdict.NEED_EVIDENCE.value
        assert analysis.summary == "Needs stronger metric evidence."
        assert analysis.raw_output == "raw provider text"
        assert analysis.input_tokens == 10
        assert analysis.output_tokens == 20
        assert analysis.latency_ms == 30
    finally:
        _close_session(db)


def test_run_analysis_skips_cancelled_run_without_provider_call(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.CANCELLED.value,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": _main_analysis_summary_json("Should not be persisted."),
                    "raw_output": "provider should not run",
                    "latency_ms": 1,
                }
            },
        )
        db.add(analysis)
        db.commit()

        run_analysis(str(analysis.id), db=db)

        db.refresh(analysis)
        assert analysis.status == RunStatus.CANCELLED.value
        assert analysis.structured_output is None
        assert analysis.raw_output is None
        assert analysis.started_at is None
    finally:
        _close_session(db)


def test_run_analysis_requests_automatic_ic_review_after_completed_gate_run(tmp_path, monkeypatch):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        db.add(
            ProviderKey(
                owner_id=_create_user(db, role=Role.ADMIN).id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url=None,
                default_model="gpt-test",
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
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={
                "output_language": "en",
                "mock_provider_result": {
                    "structured_text": _main_analysis_summary_json("Needs stronger metric evidence."),
                    "raw_output": "raw provider text",
                    "latency_ms": 30,
                },
            },
        )
        db.add(analysis)
        db.commit()

        check_run_id = uuid4()
        captured = {}

        def fake_create_automatic_ic_review_run_for_analysis(*, db, analysis, output_language):
            captured["analysis_id"] = analysis.id
            captured["output_language"] = output_language
            return SimpleNamespace(id=check_run_id, status=RunStatus.QUEUED.value, created_for_request=True)

        monkeypatch.setattr(
            "jobs.run_analysis.create_automatic_ic_review_run_for_analysis",
            fake_create_automatic_ic_review_run_for_analysis,
        )
        enqueued_ic_review_run_ids = []

        run_analysis(str(analysis.id), db=db, enqueue_ic_review=enqueued_ic_review_run_ids.append)

        db.refresh(analysis)
        assert analysis.status == RunStatus.COMPLETED.value
        assert captured == {"analysis_id": analysis.id, "output_language": "en"}
        assert enqueued_ic_review_run_ids == [check_run_id]
    finally:
        _close_session(db)


def test_run_analysis_skips_automatic_ic_review_when_chain_cancelled(tmp_path, monkeypatch):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        db.add(
            ProviderKey(
                owner_id=_create_user(db, role=Role.ADMIN).id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url=None,
                default_model="gpt-test",
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
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={
                "analysis_chain_cancel_requested_at": "2026-07-20T10:00:00+00:00",
                "mock_provider_result": {
                    "structured_text": _main_analysis_summary_json("Needs stronger metric evidence."),
                    "raw_output": "raw provider text",
                    "latency_ms": 30,
                },
            },
        )
        db.add(analysis)
        db.commit()

        def fake_create_automatic_ic_review_run_for_analysis(**kwargs):
            raise AssertionError("automatic IC Review should not be created after chain cancellation")

        monkeypatch.setattr(
            "jobs.run_analysis.create_automatic_ic_review_run_for_analysis",
            fake_create_automatic_ic_review_run_for_analysis,
        )
        enqueued_ic_review_run_ids = []

        run_analysis(str(analysis.id), db=db, enqueue_ic_review=enqueued_ic_review_run_ids.append)

        db.refresh(analysis)
        assert analysis.status == RunStatus.COMPLETED.value
        assert analysis.structured_output["summary"] == "Needs stronger metric evidence."
        assert enqueued_ic_review_run_ids == []
    finally:
        _close_session(db)


def test_run_analysis_uses_responses_api_for_gate_challenger_summary(tmp_path):
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
            status=RunStatus.QUEUED.value,
            run_parameters={
                "mock_provider_response_result": {
                    "structured_text": _main_analysis_summary_json("Needs stronger metric evidence."),
                    "raw_output": "raw responses summary",
                    "input_tokens": 100,
                    "output_tokens": 40,
                    "latency_ms": 300,
                    "provider_metadata": {"response_id": "resp-summary-1"},
                }
            },
        )
        db.add(analysis)
        db.commit()

        run_analysis(str(analysis.id), db=db)

        db.refresh(analysis)
        assert analysis.status == RunStatus.COMPLETED.value
        assert analysis.verdict == Verdict.NEED_EVIDENCE.value
        assert analysis.summary == "Needs stronger metric evidence."
        assert analysis.structured_output["details_status"] == "not_requested"
        assert "layer_1_markdown" not in analysis.structured_output
        assert "layer_2_markdown" not in analysis.structured_output
        assert analysis.raw_output == "raw responses summary"
        assert analysis.run_parameters["provider_api"] == "responses"
        assert analysis.run_parameters["gate_challenger_response_id"] == "resp-summary-1"
        assert analysis.input_tokens == 100
        assert analysis.output_tokens == 40
        rendered_prompt = Path(analysis.run_parameters["rendered_prompt_artifact_path"]).read_text(encoding="utf-8")
        assert "details_status" in rendered_prompt
        assert "layer_1_index" in rendered_prompt
        assert "layer_1_markdown" not in rendered_prompt
    finally:
        _close_session(db)


def test_gate_challenger_does_not_auto_use_responses_api_for_quotio_base_url(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        provider_key = ProviderKey(
            owner_id=_create_user(db, role=Role.ADMIN).id,
            provider=Provider.OPENAI_COMPATIBLE.value,
            base_url="http://host.docker.internal:8317/v1",
            default_model="claude-opus-4-7",
            encrypted_api_key=encrypt_secret("sk-test"),
            api_key_fingerprint="openai_compatible:...test",
        )
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="claude-opus-4-7",
            status=RunStatus.QUEUED.value,
            run_parameters={},
        )

        assert (
            _should_use_responses_api(
                analysis=analysis,
                provider=Provider.OPENAI_COMPATIBLE,
                provider_key=provider_key,
                skill=skill,
            )
            is False
        )
    finally:
        _close_session(db)


def test_gate_challenger_allows_explicit_responses_api_for_custom_base_url(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        provider_key = ProviderKey(
            owner_id=_create_user(db, role=Role.ADMIN).id,
            provider=Provider.OPENAI_COMPATIBLE.value,
            base_url="http://host.docker.internal:8317/v1",
            default_model="gpt-test",
            encrypted_api_key=encrypt_secret("sk-test"),
            api_key_fingerprint="openai_compatible:...test",
        )
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={"provider_api": "responses"},
        )

        assert (
            _should_use_responses_api(
                analysis=analysis,
                provider=Provider.OPENAI_COMPATIBLE,
                provider_key=provider_key,
                skill=skill,
            )
            is True
        )
    finally:
        _close_session(db)


def test_run_analysis_uses_summary_schema_with_chat_completions_for_quotio_base_url(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        db.add(
            ProviderKey(
                owner_id=_create_user(db, role=Role.ADMIN).id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url="http://host.docker.internal:8317/v1",
                default_model="claude-opus-4-7",
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
            model="claude-opus-4-7",
            status=RunStatus.QUEUED.value,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": _main_analysis_summary_json("Needs stronger metric evidence."),
                    "raw_output": "raw chat summary",
                    "input_tokens": 100,
                    "output_tokens": 40,
                    "latency_ms": 300,
                }
            },
        )
        db.add(analysis)
        db.commit()

        run_analysis(str(analysis.id), db=db)

        db.refresh(analysis)
        assert analysis.status == RunStatus.COMPLETED.value
        assert analysis.verdict == Verdict.NEED_EVIDENCE.value
        assert analysis.summary == "Needs stronger metric evidence."
        assert analysis.structured_output["details_status"] == "not_requested"
        assert "layer_1_markdown" not in analysis.structured_output
        assert "provider_api" not in analysis.run_parameters
        rendered_prompt = Path(analysis.run_parameters["rendered_prompt_artifact_path"]).read_text(encoding="utf-8")
        assert "details_status" in rendered_prompt
        assert "layer_1_index" in rendered_prompt
        assert "layer_1_markdown" not in rendered_prompt
    finally:
        _close_session(db)


def test_run_analysis_marks_missing_provider_key_failed(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={},
        )
        db.add(analysis)
        db.commit()

        run_analysis(str(analysis.id), db=db)

        db.refresh(analysis)
        assert analysis.status == RunStatus.FAILED.value
        assert analysis.error_message == "provider_key_missing"
    finally:
        _close_session(db)


def test_run_analysis_persists_structured_text_when_json_parse_fails(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        db.add(
            ProviderKey(
                owner_id=_create_user(db, role=Role.ADMIN).id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url=None,
                default_model="gpt-test",
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
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": "Оценка документа\nnot json",
                    "raw_output": "",
                    "latency_ms": 30,
                }
            },
        )
        db.add(analysis)
        db.commit()

        run_analysis(str(analysis.id), db=db)

        db.refresh(analysis)
        assert analysis.status == RunStatus.FAILED.value
        assert "Expecting value" in analysis.error_message
        assert analysis.raw_output == "Оценка документа\nnot json"
    finally:
        _close_session(db)


def test_run_analysis_marks_changed_external_skill_source_unavailable(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        source = tmp_path / "SKILL.md"
        source.write_text("Original Gate 2 instructions.", encoding="utf-8")
        skill = _create_skill(
            db,
            source_uri=str(tmp_path),
            source_entrypoint="SKILL.md",
            source_fingerprint="expected-old-fingerprint",
        )
        db.add(
            ProviderKey(
                owner_id=_create_user(db, role=Role.ADMIN).id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url=None,
                default_model="gpt-test",
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
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={
                "skill_source_snapshot": {
                    "source_type": SkillSourceType.LOCAL_SKILL_REPO.value,
                    "source_fingerprint": "expected-old-fingerprint",
                },
                "mock_provider_result": {
                    "structured_text": _main_analysis_json("Should not run provider."),
                    "raw_output": "provider should not be called",
                    "latency_ms": 1,
                },
            },
        )
        db.add(analysis)
        db.commit()

        run_analysis(str(analysis.id), db=db)

        db.refresh(analysis)
        assert analysis.status == RunStatus.FAILED.value
        assert analysis.error_message == "skill_source_unavailable"
        assert analysis.raw_output is None
    finally:
        _close_session(db)


def test_run_analysis_persists_rendered_prompt_from_source_snapshot(tmp_path, monkeypatch):
    db = _create_session()
    try:
        monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
        get_settings.cache_clear()
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(
            db,
            source_uri=str(tmp_path / "missing-live-source"),
            source_entrypoint="skills/gate-challenger/SKILL.md",
            source_fingerprint="old-live-fingerprint",
        )
        skill.skill_source_id = uuid4()
        skill.runtime_mode = "snapshot_required"
        skill.prompt_text = "Stub prompt should not be used"
        db.add(
            ProviderKey(
                owner_id=_create_user(db, role=Role.ADMIN).id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url=None,
                default_model="gpt-test",
                encrypted_api_key=encrypt_secret("sk-test"),
                api_key_fingerprint="openai_compatible:...test",
            )
        )

        source_snapshot_id = uuid4()
        snapshot_dir = tmp_path / "skill-snapshots" / str(source_snapshot_id)
        skill_file = snapshot_dir / "files" / "skills" / "gate-challenger" / "SKILL.md"
        reference_file = snapshot_dir / "files" / "skills" / "gate-challenger" / "references" / "rubric.md"
        reference_file.parent.mkdir(parents=True)
        skill_file.write_text("Snapshot Gate instructions", encoding="utf-8")
        reference_file.write_text("Snapshot reference rubric", encoding="utf-8")
        (snapshot_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "source_slug": "gate-challenger",
                    "resolved_revision": "abc123",
                    "source_fingerprint": "snapshot-fingerprint",
                    "files": [
                        {"path": "skills/gate-challenger/SKILL.md", "sha256": "skill-hash"},
                        {"path": "skills/gate-challenger/references/rubric.md", "sha256": "rubric-hash"},
                    ],
                }
            ),
            encoding="utf-8",
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
                "source_snapshot_id": str(source_snapshot_id),
                "source_snapshot_artifact_path": str(snapshot_dir),
                "skill_source_snapshot": {
                    "id": str(source_snapshot_id),
                    "artifact_path": str(snapshot_dir),
                    "source_fingerprint": "snapshot-fingerprint",
                },
                "mock_provider_result": {
                    "structured_text": _main_analysis_summary_json("Needs stronger metric evidence."),
                    "raw_output": "raw provider text",
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "latency_ms": 30,
                },
            },
        )
        db.add(analysis)
        db.commit()

        run_analysis(str(analysis.id), db=db)

        db.refresh(analysis)
        assert analysis.status == RunStatus.COMPLETED.value
        assert analysis.run_parameters["prompt_fingerprint"]
        prompt_path = analysis.run_parameters["rendered_prompt_artifact_path"]
        rendered_prompt = Path(prompt_path).read_text(encoding="utf-8")
        assert "Snapshot Gate instructions" in rendered_prompt
        assert "Snapshot reference rubric" in rendered_prompt
        assert "Stub prompt should not be used" not in rendered_prompt
    finally:
        get_settings.cache_clear()
        _close_session(db)


def test_run_analysis_runs_devils_advocate_before_gate_and_passes_layer_4_context(tmp_path, monkeypatch):
    db = _create_session()
    try:
        monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
        get_settings.cache_clear()
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        main_skill = _create_skill(db)
        predicted_skill = _create_predicted_skill(db, tmp_path)
        db.add(
            ProviderKey(
                owner_id=_create_user(db, role=Role.ADMIN).id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url=None,
                default_model="gpt-test",
                encrypted_api_key=encrypt_secret("sk-test"),
                api_key_fingerprint="openai_compatible:...test",
            )
        )
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=main_skill.id,
            skill_version=main_skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": _main_analysis_summary_json("Gate uses expert layer 4."),
                    "raw_output": "raw main",
                    "latency_ms": 30,
                },
                "predicted_comments_mock_provider_result": {
                    "structured_text": _devils_advocate_json(),
                    "raw_output": "raw predicted",
                    "latency_ms": 20,
                },
            },
        )
        db.add(analysis)
        db.commit()

        enqueued_run_ids = []
        run_analysis(str(analysis.id), db=db, enqueue_predicted_comments=enqueued_run_ids.append)

        predicted_run = db.query(PredictedCommentRun).filter(PredictedCommentRun.analysis_id == analysis.id).one()
        db.refresh(analysis)
        assert analysis.status == RunStatus.COMPLETED.value
        assert predicted_run.skill_id == predicted_skill.id
        assert predicted_run.status == RunStatus.COMPLETED.value
        assert enqueued_run_ids == []

        layer_4_context = analysis.run_parameters["gate_challenger_layer_4_context"]
        assert layer_4_context["source"] == "devils_advocate_predefense"
        assert layer_4_context["predicted_comment_run_id"] == str(predicted_run.id)
        assert layer_4_context["brutal_truth"] == "Fatal flaw."
        assert layer_4_context["detected_contradictions"][0]["title"] == "Gross profit not shown"
        synthesis = layer_4_context["synthesis"]
        assert synthesis["version"] == "devils-advocate-layer-4-synthesis-v1"
        assert synthesis["decision"]["verdict"] == "rework"
        assert synthesis["must_review_signals"][0]["theme"] == "Gross profit not shown"
        assert synthesis["must_review_signals"][0]["source"] == "detected_contradiction"
        assert synthesis["must_review_signals"][0]["must_review"] is True
        assert any(signal["theme"] == "Subsidy-dependent economics" for signal in synthesis["must_review_signals"])
        assert "MP rejects: No incrementality proof." in synthesis["role_consensus"]
        assert "What is gross profit?" in synthesis["open_ic_questions"]

        rendered_prompt = Path(analysis.run_parameters["rendered_prompt_artifact_path"]).read_text(encoding="utf-8")
        assert "Layer 4" in rendered_prompt
        assert "Devil's Advocate expert analysis" in rendered_prompt
        assert "The Brutal Truth" in rendered_prompt
        assert "Fatal flaw." in rendered_prompt
        assert "Detected Contradictions & Missing Proofs" in rendered_prompt
        assert "Gross profit not shown" in rendered_prompt
        assert "strengthen or supplement Gate Challenger" in rendered_prompt
        assert "Layer 4 synthesis - must-review Devil's Advocate signals" in rendered_prompt
        assert "Subsidy-dependent economics" in rendered_prompt
        assert "CEO/CPO IC language" in rendered_prompt
        assert "Brutal Truth" in rendered_prompt
        assert "what is proven / what is not proven / what cannot be approved yet" in rendered_prompt
    finally:
        get_settings.cache_clear()
        _close_session(db)


def test_run_analysis_propagates_snapshot_mode_to_predicted_comments(tmp_path, monkeypatch):
    db = _create_session()
    try:
        monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
        get_settings.cache_clear()
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        main_skill = _create_skill(db)
        source = SkillSource(
            slug="devils-advocate",
            display_name="Devil's Advocate",
            source_kind=SkillSourceType.LOCAL_KNOWLEDGE_BASE.value,
            local_path=str(tmp_path / "devils-advocate"),
            repo_url=None,
            default_ref=None,
            entrypoint="ic-voting-prompt.md",
            required_paths=[],
            update_policy="manual",
            status=EntityStatus.ACTIVE.value,
        )
        db.add(source)
        db.flush()
        predicted_skill = Skill(
            name="devils_advocate_predefense",
            description="Devil's Advocate",
            version="baseline",
            skill_type=SkillType.PREDICTED_COMMENTS.value,
            supported_document_types=[DocumentType.GATE_2.value],
            source_type=SkillSourceType.LOCAL_KNOWLEDGE_BASE.value,
            skill_source_id=source.id,
            source_uri=source.local_path,
            source_entrypoint=source.entrypoint,
            source_revision=None,
            source_fingerprint="devils-fingerprint",
            source_metadata={},
            prompt_text="Critique the document.",
            result_schema_path="contracts/schemas/predicted-comments-result.schema.json",
            runtime_mode="snapshot_required",
            status=EntityStatus.ACTIVE.value,
        )
        db.add(predicted_skill)
        db.add(
            ProviderKey(
                owner_id=_create_user(db, role=Role.ADMIN).id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url=None,
                default_model="gpt-test",
                encrypted_api_key=encrypt_secret("sk-test"),
                api_key_fingerprint="openai_compatible:...test",
            )
        )
        db.commit()

        captured_snapshot_modes = []
        captured_analysis_check_run_ids = []

        def fake_create_skill_source_snapshot(
            *,
            db,
            storage,
            source,
            analysis_id,
            predicted_comment_run_id,
            analysis_check_run_id,
            snapshot_mode,
        ):
            captured_snapshot_modes.append(snapshot_mode)
            captured_analysis_check_run_ids.append(analysis_check_run_id)
            return SimpleNamespace(
                id=uuid4(),
                source_slug="devils-advocate",
                resolved_revision=None,
                source_fingerprint="devils-snapshot-fingerprint",
                artifact_path=str(tmp_path / "skill-snapshot"),
                snapshot_mode=snapshot_mode,
                is_dirty=False,
            )

        def fake_create_devils_retrieval_snapshot(**kwargs):
            return SimpleNamespace(
                id=uuid4(),
                artifact_path=str(tmp_path / "retrieval-snapshot"),
                retrieval_mode="fixture",
                retrieval_version="test",
                corpus_fingerprint="corpus-fingerprint",
                query_fingerprint="query-fingerprint",
                selected_items={},
            )

        monkeypatch.setattr("jobs.run_analysis.create_skill_source_snapshot", fake_create_skill_source_snapshot)
        monkeypatch.setattr("jobs.run_analysis.create_devils_retrieval_snapshot", fake_create_devils_retrieval_snapshot)

        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=main_skill.id,
            skill_version=main_skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={
                "snapshot_mode": "development_current",
                "output_language": "en",
                "mock_provider_result": {
                    "structured_text": _main_analysis_summary_json("Needs stronger metric evidence."),
                    "raw_output": "raw provider text",
                    "latency_ms": 30,
                },
            },
        )
        db.add(analysis)
        db.commit()

        enqueued_run_ids = []
        run_analysis(str(analysis.id), db=db, enqueue_predicted_comments=enqueued_run_ids.append)

        predicted_run = db.query(PredictedCommentRun).filter(PredictedCommentRun.analysis_id == analysis.id).one()
        assert enqueued_run_ids == []
        assert captured_snapshot_modes == ["development_current"]
        assert captured_analysis_check_run_ids == [None]
        assert predicted_run.run_parameters["snapshot_mode"] == "development_current"
        assert predicted_run.run_parameters["output_language"] == "en"
        assert predicted_run.run_parameters["max_output_tokens"] == 20000
        assert predicted_run.run_parameters["response_format"] == {"type": "json_object"}
        assert predicted_run.run_parameters["run_order"] == "before_gate_challenger"
        assert predicted_run.run_parameters["skill_source_snapshot"]["snapshot_mode"] == "development_current"
    finally:
        get_settings.cache_clear()
        _close_session(db)


def _create_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    session._test_engine = engine  # type: ignore[attr-defined]
    return session


def _main_analysis_json(summary: str = "Needs evidence.") -> str:
    return json.dumps(
        {
            "verdict": "need_evidence",
            "summary": summary,
            "assessment_markdown": f"Оценка документа\nРекомендация: {summary}",
            "findings": [],
            "checks": [],
            "layer_1_markdown": "Layer 1\nL1-001 — Decision-critical blocker.",
            "layer_1": [
                {
                    "id": "L1-001",
                    "severity": "critical",
                    "issue": "Mandatory readiness is not proven.",
                    "evidence": "The document does not close the required proof.",
                }
            ],
            "layer_2_markdown": "Layer 2\nL2-001 — Atomic weak-link finding.",
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
        }
    )


def _main_analysis_summary_json(summary: str = "Needs evidence.") -> str:
    return json.dumps(
        {
            "verdict": "need_evidence",
            "summary": summary,
            "assessment_markdown": f"Оценка документа\nРекомендация: {summary}",
            "layer_1_index": [
                {
                    "id": "L1-001",
                    "severity": "high",
                    "issue": "Mandatory readiness is not proven.",
                    "evidence_anchor": "The document does not close the required proof.",
                }
            ],
            "layer_2_index": [
                {
                    "id": "L2-001",
                    "parent_layer_1_id": "L1-001",
                    "status": "fail",
                    "severity": "high",
                    "question": "Is the key target evidenced?",
                    "answer": "NO",
                    "short_evidence": "The mock document omits the proof.",
                }
            ],
            "details_status": "not_requested",
            "details_run_id": None,
            "revision_required": False,
            "revision_reason": None,
        }
    )


def _close_session(session: Session) -> None:
    engine = session._test_engine  # type: ignore[attr-defined]
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _create_user(db: Session, role: Role = Role.USER) -> User:
    user = User(
        login=f"user-{uuid4()}",
        display_name="User",
        password_hash=hash_password("secret"),
        role=role.value,
        status=UserStatus.ACTIVE.value,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_document(db: Session, tmp_path, user: User) -> Document:
    storage = LocalDocumentStorage(tmp_path)
    document_id = uuid4()
    stored = storage.save_raw_file(
        owner_id=user.id,
        document_id=document_id,
        original_filename="gate.txt",
        source=BytesIO(b"Gate 2 MVP metrics"),
        max_size_bytes=1024,
    )
    document = Document(
        id=document_id,
        owner_id=user.id,
        title="Gate 2",
        original_filename="gate.txt",
        mime_type="text/plain",
        file_size_bytes=stored.size_bytes,
        file_hash_sha256=stored.sha256,
        storage_path=str(stored.path),
        parse_status=DocumentParseStatus.COMPLETED.value,
        detected_document_type=DocumentType.GATE_2.value,
        parsed_text="Gate 2 MVP metrics traction risks",
        status=EntityStatus.ACTIVE.value,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _create_skill(
    db: Session,
    *,
    source_uri: str | None = None,
    source_entrypoint: str | None = None,
    source_fingerprint: str | None = None,
) -> Skill:
    skill = Skill(
        name="gate2_challenger_main_analysis",
        description="Gate 2",
        version="baseline",
        skill_type=SkillType.MAIN_ANALYSIS.value,
        supported_document_types=[DocumentType.GATE_2.value],
        source_type=SkillSourceType.LOCAL_SKILL_REPO.value if source_uri else SkillSourceType.INLINE_PROMPT.value,
        source_uri=source_uri,
        source_entrypoint=source_entrypoint,
        source_revision=None,
        source_fingerprint=source_fingerprint,
        source_metadata={},
        prompt_text="Analyze Gate 2 document.",
        result_schema_path="contracts/schemas/main-analysis-result.schema.json",
        status=EntityStatus.ACTIVE.value,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def _create_predicted_skill(db: Session, tmp_path) -> Skill:
    prompt_path = tmp_path / "ic-voting-prompt.md"
    prompt_path.write_text("IC voting orchestrator", encoding="utf-8")
    skill = Skill(
        name="devils_advocate_predefense",
        description="Devil's Advocate",
        version="baseline",
        skill_type=SkillType.PREDICTED_COMMENTS.value,
        supported_document_types=[DocumentType.GATE_2.value],
        source_type=SkillSourceType.LOCAL_KNOWLEDGE_BASE.value,
        source_uri=str(prompt_path),
        source_entrypoint="ic-voting-prompt.md",
        source_revision="revision",
        source_fingerprint=None,
        source_metadata={"selected_wiki_pages": []},
        prompt_text="Devil's Advocate prompt",
        result_schema_path="contracts/schemas/devils-advocate-result.schema.json",
        status=EntityStatus.ACTIVE.value,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def _devils_advocate_json() -> str:
    return json.dumps(
        {
            "run_mode": "full_ic_voting",
            "native_markdown": (
                "Devil's Advocate\n\n"
                "The Brutal Truth\n\nFatal flaw.\n\n"
                "Detected Contradictions & Missing Proofs\n\n- Gross profit not shown."
            ),
            "preflight_summary": ["Stage: Gate-2"],
            "brutal_truth": "Fatal flaw.",
            "detected_contradictions": [
                {
                    "section": "FAQ 4",
                    "title": "Gross profit not shown",
                    "body": "Revenue is shown but gross profit is absent.",
                    "comment_type": "missing_data",
                    "severity": "critical",
                    "citations": ["[[financial-revenue-and-gross-profit]]"],
                }
            ],
            "role_comments": [
                {
                    "voter": "MP",
                    "vote": "reject",
                    "rationale": "No incrementality proof.",
                    "comments": [
                        {
                            "anchor_text": "Subsidy-dependent economics",
                            "body": "Cohorts may collapse when incentives are removed.",
                            "comment_type": "weak_argument",
                            "severity": "critical",
                        }
                    ],
                },
                {
                    "voter": "CPO",
                    "vote": "reject",
                    "rationale": "Funnel target missed.",
                    "comments": [
                        {
                            "anchor_text": "CR contact to payment",
                            "body": "Which product change closes the funnel gap?",
                            "comment_type": "missing_data",
                            "severity": "important",
                        }
                    ],
                },
                {
                    "voter": "TechDir",
                    "vote": "reject",
                    "rationale": "No A/B delta.",
                    "comments": [
                        {
                            "anchor_text": "A/B delta",
                            "body": "Where is the experiment readout?",
                            "comment_type": "methodology_issue",
                            "severity": "important",
                        }
                    ],
                },
                {
                    "voter": "VertDir",
                    "vote": "approve",
                    "rationale": "Direction is useful.",
                    "comments": [
                        {
                            "anchor_text": "Business Services",
                            "body": "Keep the vertical rollout gated by evidence.",
                            "comment_type": "risk_not_addressed",
                            "severity": "minor",
                        }
                    ],
                },
            ],
            "tough_questions": [
                {"question": "What is gross profit?", "persona": "[[persona-cfo]]"},
                {"question": "What is incremental impact?", "persona": "[[persona-managing-partner]]"},
                {"question": "Where is the A/B delta?", "persona": "[[persona-technical-director]]"},
            ],
            "actionable_jtbds": [
                "Show gross profit and cumulative uplift.",
                "Separate Stage 1 from Stage 2 HC ask.",
                "Set a hard closure-test KPI gate.",
            ],
            "anchored_comments": [],
            "trailer": {
                "executive_summary": "Needs evidence.",
                "key_risks": ["weak proof"],
                "missing_evidence": ["gross profit"],
                "next_steps": ["add gross profit proof"],
            },
            "ic_decision": {
                "verdict": "rework",
                "vote_tally": {"MP": "reject", "CPO": "reject", "TechDir": "reject", "VertDir": "approve"},
                "rationale": "Missing proof.",
                "conditions": [],
                "heuristics_fired": [],
                "patterns_fired": [],
                "precedents_anchored": [],
                "next_ic": "After evidence update",
            },
            "predicted_questions": [],
            "consulted_wiki_pages": [],
            "source_citations": [],
            "retrieval": {
                "retrieval_mode": "deterministic_topk",
                "corpus_fingerprint": "corpus-fingerprint",
                "selected_cases": [],
                "selected_patterns": [],
                "selected_questions": [],
            },
        }
    )
