from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4
import hashlib
import zipfile

import pytest

from app.models.analysis import Analysis, AnalysisCheckRun, AnalysisCheckStep
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.models.skill import Skill
from app.models.skill_source import SkillSource, SkillSourceSnapshot
from app.models.user import User
from app.core.config import get_settings
from app.schemas.enums import DocumentParseStatus, DocumentType, Provider, Role, RunStatus, SkillType, UserStatus
from app.security.passwords import hash_password
from app.security.secrets import encrypt_secret
from app.seeds.skills import seed_baseline_skills

from test_documents_upload import create_user, login


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_analysis_check_runs_allow_multiple_runs_for_completed_analysis(db_session):
    analysis, skill = _create_completed_analysis_with_skill(db_session)

    first_run = AnalysisCheckRun(
        analysis_id=analysis.id,
        skill_id=skill.id,
        skill_version=skill.version,
        check_type="ic_agentic_review",
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="openai/gpt-5.5",
        status=RunStatus.COMPLETED.value,
        current_stage="synthesis",
        structured_output={"verdict": "CONDITIONAL"},
        legacy_output={"sections": {}},
        raw_output="raw synthesis output",
        latency_ms=1234,
        input_tokens=100,
        output_tokens=50,
        estimated_cost=Decimal("0.42"),
        run_parameters={"temperature": 0},
        artifacts=[{"path": "/storage/ic-review/report.pdf"}],
        uploaded_workbook_metadata={"filename": "model.xlsx"},
    )
    second_run = AnalysisCheckRun(
        analysis_id=analysis.id,
        skill_id=skill.id,
        skill_version=skill.version,
        check_type="ic_agentic_review",
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="openai/gpt-5.5",
        status=RunStatus.QUEUED.value,
        current_stage="queued",
        run_parameters={"temperature": 0.2},
        artifacts=[],
        uploaded_workbook_metadata={},
    )
    db_session.add_all([first_run, second_run])
    db_session.commit()

    runs = db_session.query(AnalysisCheckRun).filter_by(analysis_id=analysis.id).order_by(AnalysisCheckRun.created_at).all()
    assert [run.id for run in runs] == [first_run.id, second_run.id]
    assert runs[0].structured_output == {"verdict": "CONDITIONAL"}
    assert runs[0].legacy_output == {"sections": {}}
    assert runs[0].uploaded_workbook_metadata == {"filename": "model.xlsx"}


def test_analysis_check_steps_persist_prompt_outputs_and_artifacts(db_session):
    analysis, skill = _create_completed_analysis_with_skill(db_session)
    check_run = AnalysisCheckRun(
        analysis_id=analysis.id,
        skill_id=skill.id,
        skill_version=skill.version,
        check_type="ic_agentic_review",
        provider=Provider.ANTHROPIC_COMPATIBLE.value,
        model="anthropic/claude-sonnet",
        status=RunStatus.RUNNING.value,
        current_stage="ic-financial-auditor",
        run_parameters={},
        artifacts=[],
        uploaded_workbook_metadata={},
    )
    db_session.add(check_run)
    db_session.flush()

    step = AnalysisCheckStep(
        check_run_id=check_run.id,
        step_type="role",
        step_name="ic-financial-auditor",
        status=RunStatus.COMPLETED.value,
        prompt_fingerprint="prompt-sha",
        prompt_artifact_path="/storage/ic-review/prompts/ic-financial-auditor.txt",
        raw_output="raw role output",
        structured_output={"role": "ic-financial-auditor", "findings": []},
        latency_ms=500,
        input_tokens=10,
        output_tokens=20,
        estimated_cost=Decimal("0.01"),
        artifacts=[{"path": "/storage/ic-review/raw/ic-financial-auditor.txt"}],
    )
    db_session.add(step)
    db_session.commit()

    persisted = db_session.query(AnalysisCheckStep).filter_by(check_run_id=check_run.id).one()
    assert persisted.step_name == "ic-financial-auditor"
    assert persisted.prompt_artifact_path == "/storage/ic-review/prompts/ic-financial-auditor.txt"
    assert persisted.raw_output == "raw role output"
    assert persisted.structured_output["role"] == "ic-financial-auditor"
    assert persisted.artifacts == [{"path": "/storage/ic-review/raw/ic-financial-auditor.txt"}]


def test_cannot_launch_ic_review_before_main_analysis_completes(client, db_session, monkeypatch, tmp_path):
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.RUNNING)
    login(client, "author", "secret")

    response = client.post(
        f"/analyses/{analysis.id}/ic-review-runs",
        data={"provider": "openai_compatible", "model": "openai/gpt-5.5", "output_language": "ru"},
    )

    assert response.status_code == 409


def test_can_launch_ic_review_after_completed_analysis(client, db_session, monkeypatch, tmp_path):
    enqueued = _override_ic_review_enqueue()
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    login(client, "author", "secret")

    try:
        response = client.post(
            f"/analyses/{analysis.id}/ic-review-runs",
            data={"provider": "openai_compatible", "model": "openai/gpt-5.5", "output_language": "ru"},
        )
    finally:
        _clear_ic_review_enqueue_override()

    assert response.status_code == 201
    payload = response.json()
    assert payload["analysis_id"] == str(analysis.id)
    assert payload["status"] == "queued"
    assert payload["run_parameters"]["output_language"] == "ru"
    assert payload["run_parameters"]["spreadsheet_mode"] == "not_provided"
    assert payload["source_trace"]["source_slug"] == "ic-agentic-review"
    assert enqueued == [payload["id"]]
    source_snapshot = db_session.get(SkillSourceSnapshot, UUID(payload["run_parameters"]["source_snapshot_id"]))
    assert source_snapshot.analysis_check_run_id == UUID(payload["id"])


def test_normal_user_cannot_launch_ic_review_for_inaccessible_analysis(client, db_session, monkeypatch, tmp_path):
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED, login_name="owner")
    create_user(db_session, "other", "secret")
    login(client, "other", "secret")

    response = client.post(
        f"/analyses/{analysis.id}/ic-review-runs",
        data={"provider": "openai_compatible", "model": "openai/gpt-5.5", "output_language": "ru"},
    )

    assert response.status_code == 404


def test_pdf_workbook_upload_returns_415(client, db_session, monkeypatch, tmp_path):
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    login(client, "author", "secret")

    response = client.post(
        f"/analyses/{analysis.id}/ic-review-runs",
        data={"provider": "openai_compatible", "model": "openai/gpt-5.5", "output_language": "ru"},
        files={"financial_model": ("model.pdf", b"%PDF", "application/pdf")},
    )

    assert response.status_code == 415


def test_no_workbook_creates_not_provided_spreadsheet_mode(client, db_session, monkeypatch, tmp_path):
    _override_ic_review_enqueue()
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    login(client, "author", "secret")

    try:
        response = client.post(
            f"/analyses/{analysis.id}/ic-review-runs",
            data={"provider": "openai_compatible", "model": "openai/gpt-5.5", "output_language": "ru"},
        )
    finally:
        _clear_ic_review_enqueue_override()

    assert response.status_code == 201
    payload = response.json()
    assert payload["run_parameters"]["spreadsheet_mode"] == "not_provided"
    assert payload["uploaded_workbook_metadata"] == {}


def test_workbook_upload_records_sha256_and_size(client, db_session, monkeypatch, tmp_path):
    _override_ic_review_enqueue()
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    workbook = _xlsx_bytes()
    login(client, "author", "secret")

    try:
        response = client.post(
            f"/analyses/{analysis.id}/ic-review-runs",
            data={"provider": "openai_compatible", "model": "openai/gpt-5.5", "output_language": "ru"},
            files={
                "financial_model": (
                    "financial model.xlsx",
                    BytesIO(workbook),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    finally:
        _clear_ic_review_enqueue_override()

    assert response.status_code == 201
    payload = response.json()
    assert payload["run_parameters"]["spreadsheet_mode"] == "uploaded"
    assert payload["uploaded_workbook_metadata"]["filename"] == "financial model.xlsx"
    assert payload["uploaded_workbook_metadata"]["size_bytes"] == len(workbook)
    assert payload["uploaded_workbook_metadata"]["sha256"] == hashlib.sha256(workbook).hexdigest()
    assert "storage_path" not in payload["uploaded_workbook_metadata"]

    run = db_session.get(AnalysisCheckRun, UUID(payload["id"]))
    stored_path = Path(run.uploaded_workbook_metadata["storage_path"])
    assert stored_path.read_bytes() == workbook
    assert stored_path.name.endswith("-financial_model.xlsx")


def test_invalid_xlsx_bytes_return_415_and_do_not_leave_queued_run(client, db_session, monkeypatch, tmp_path):
    _override_ic_review_enqueue()
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    login(client, "author", "secret")

    try:
        response = client.post(
            f"/analyses/{analysis.id}/ic-review-runs",
            data={"provider": "openai_compatible", "model": "openai/gpt-5.5", "output_language": "ru"},
            files={
                "financial_model": (
                    "financial model.xlsx",
                    BytesIO(b"not a zip"),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    finally:
        _clear_ic_review_enqueue_override()

    assert response.status_code == 415
    assert db_session.query(AnalysisCheckRun).filter_by(analysis_id=analysis.id).count() == 0


def test_source_snapshot_failure_after_workbook_upload_removes_run_upload_directory(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    _override_ic_review_enqueue()
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    ic_source = db_session.query(SkillSource).filter_by(slug="ic-agentic-review").one()
    ic_source.required_paths = ["missing.md"]
    db_session.commit()
    login(client, "author", "secret")

    try:
        response = client.post(
            f"/analyses/{analysis.id}/ic-review-runs",
            data={"provider": "openai_compatible", "model": "openai/gpt-5.5", "output_language": "ru"},
            files={
                "financial_model": (
                    "financial model.xlsx",
                    BytesIO(_xlsx_bytes()),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    finally:
        _clear_ic_review_enqueue_override()

    assert response.status_code == 409
    assert db_session.query(AnalysisCheckRun).filter_by(analysis_id=analysis.id).count() == 0
    upload_root = tmp_path / "storage" / "ic-review" / str(analysis.id)
    assert not list(upload_root.glob("*/uploads/*")) if upload_root.exists() else True


def test_enqueue_failure_marks_ic_review_run_failed(client, db_session, monkeypatch, tmp_path):
    from app.main import app
    from app.routers import ic_review as ic_review_router

    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)

    def failing_enqueue(run_id):
        raise RuntimeError("redis unavailable")

    app.dependency_overrides[ic_review_router.get_run_ic_agentic_review_enqueue] = lambda: failing_enqueue
    login(client, "author", "secret")

    try:
        response = client.post(
            f"/analyses/{analysis.id}/ic-review-runs",
            data={"provider": "openai_compatible", "model": "openai/gpt-5.5", "output_language": "ru"},
        )
    finally:
        app.dependency_overrides.pop(ic_review_router.get_run_ic_agentic_review_enqueue, None)

    assert response.status_code == 500
    run = db_session.query(AnalysisCheckRun).filter_by(analysis_id=analysis.id).one()
    assert run.status == RunStatus.FAILED.value
    assert run.current_stage == "enqueue_failed"
    assert "Failed to enqueue" in run.error_message


def test_ic_review_raw_outputs_are_admin_only(client, db_session, monkeypatch, tmp_path):
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    skill = db_session.query(Skill).filter_by(name="ic_agentic_review").one()
    run = AnalysisCheckRun(
        analysis_id=analysis.id,
        skill_id=skill.id,
        skill_version=skill.version,
        check_type="ic_agentic_review",
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="openai/gpt-5.5",
        status=RunStatus.COMPLETED.value,
        current_stage="synthesis",
        structured_output={"verdict": "conditional"},
        legacy_output={"sections": {}},
        raw_output="run raw output",
        run_parameters={
            "source_snapshot_artifact_path": str(tmp_path / "snapshot"),
            "synthesis_prompt_artifact_path": str(tmp_path / "synthesis.txt"),
            "skill_source_snapshot": {"artifact_path": str(tmp_path / "snapshot"), "source_slug": "ic-agentic-review"},
        },
        artifacts=[{"key": "validation_report", "path": str(tmp_path / "report.txt"), "filename": "report.txt"}],
        uploaded_workbook_metadata={"storage_path": str(tmp_path / "model.xlsx"), "filename": "model.xlsx"},
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        AnalysisCheckStep(
            check_run_id=run.id,
            step_type="role",
            step_name="ic-financial-auditor",
            status=RunStatus.COMPLETED.value,
            prompt_artifact_path=str(tmp_path / "prompt.txt"),
            raw_output="step raw output",
            structured_output={"role": "ic-financial-auditor"},
            artifacts=[{"key": "raw", "path": str(tmp_path / "raw.txt"), "filename": "raw.txt"}],
        )
    )
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    db_session.commit()

    login(client, "author", "secret")
    user_response = client.get(f"/ic-review-runs/{run.id}")
    assert user_response.status_code == 200
    user_payload = user_response.json()
    assert user_payload["raw_output"] is None
    assert user_payload["legacy_output"] is None
    assert user_payload["steps"][0]["raw_output"] is None
    assert user_payload["steps"][0]["structured_output"] is None
    assert "path" not in user_payload["artifacts"][0]
    assert "storage_path" not in user_payload["uploaded_workbook_metadata"]
    assert "source_snapshot_artifact_path" not in user_payload["run_parameters"]
    assert "synthesis_prompt_artifact_path" not in user_payload["run_parameters"]
    assert "artifact_path" not in user_payload["run_parameters"]["skill_source_snapshot"]
    client.post("/auth/logout")

    login(client, admin.login, "secret")
    admin_response = client.get(f"/ic-review-runs/{run.id}")
    assert admin_response.status_code == 200
    admin_payload = admin_response.json()
    assert admin_payload["raw_output"] == "run raw output"
    assert admin_payload["legacy_output"] == {"sections": {}}
    assert admin_payload["steps"][0]["raw_output"] == "step raw output"
    assert admin_payload["steps"][0]["structured_output"] == {"role": "ic-financial-auditor"}
    assert admin_payload["artifacts"][0]["path"] == str(tmp_path / "report.txt")
    assert admin_payload["uploaded_workbook_metadata"]["storage_path"] == str(tmp_path / "model.xlsx")
    assert admin_payload["run_parameters"]["source_snapshot_artifact_path"] == str(tmp_path / "snapshot")
    assert admin_payload["run_parameters"]["synthesis_prompt_artifact_path"] == str(tmp_path / "synthesis.txt")
    assert admin_payload["run_parameters"]["skill_source_snapshot"]["artifact_path"] == str(tmp_path / "snapshot")


def test_analysis_read_embeds_latest_ic_review_run_sanitized_for_normal_user(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    skill = db_session.query(Skill).filter_by(name="ic_agentic_review").one()
    older_run = AnalysisCheckRun(
        analysis_id=analysis.id,
        skill_id=skill.id,
        skill_version=skill.version,
        check_type="ic_agentic_review",
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="openai/gpt-5.5",
        status=RunStatus.COMPLETED.value,
        current_stage="done",
        structured_output={"verdict": "NO-GO"},
        raw_output="older raw output",
        run_parameters={},
        artifacts=[],
        uploaded_workbook_metadata={},
        created_at=datetime(2026, 7, 9, 10, 0, tzinfo=UTC),
    )
    latest_run = _create_ic_review_visibility_run(
        db_session,
        analysis=analysis,
        skill=skill,
        tmp_path=tmp_path,
        created_at=datetime(2026, 7, 9, 11, 0, tzinfo=UTC),
    )
    db_session.add_all([older_run, latest_run])
    db_session.commit()
    login(client, "author", "secret")

    response = client.get(f"/analyses/{analysis.id}")

    assert response.status_code == 200
    payload = response.json()["ic_review_run"]
    assert payload["id"] == str(latest_run.id)
    assert payload["status"] == "completed"
    assert payload["structured_output"] == {"verdict": "CONDITIONAL", "executive_brief": "Compact result"}
    assert payload["legacy_output"] is None
    assert payload["source_trace"]["source_slug"] == "ic-agentic-review"
    assert payload["raw_output"] is None
    assert payload["steps"][0]["raw_output"] is None
    assert payload["steps"][0]["structured_output"] is None
    assert payload["steps"][0]["prompt_artifact_path"] is None
    assert "path" not in payload["artifacts"][0]
    assert "path" not in payload["steps"][0]["artifacts"][0]
    assert "storage_path" not in payload["uploaded_workbook_metadata"]
    assert "source_snapshot_artifact_path" not in payload["run_parameters"]
    assert "synthesis_prompt_artifact_path" not in payload["run_parameters"]
    assert "artifact_path" not in payload["run_parameters"]["skill_source_snapshot"]


def test_analysis_read_embeds_latest_ic_review_run_with_admin_raw_and_paths(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    skill = db_session.query(Skill).filter_by(name="ic_agentic_review").one()
    latest_run = _create_ic_review_visibility_run(
        db_session,
        analysis=analysis,
        skill=skill,
        tmp_path=tmp_path,
        created_at=datetime(2026, 7, 9, 11, 0, tzinfo=UTC),
    )
    db_session.add(latest_run)
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    db_session.commit()
    login(client, admin.login, "secret")

    response = client.get(f"/analyses/{analysis.id}")

    assert response.status_code == 200
    payload = response.json()["ic_review_run"]
    assert payload["id"] == str(latest_run.id)
    assert payload["raw_output"] == "run raw output"
    assert payload["legacy_output"] == {"sections": {}}
    assert payload["steps"][0]["raw_output"] == "step raw output"
    assert payload["steps"][0]["structured_output"] == {"role": "ic-financial-auditor"}
    assert payload["steps"][0]["prompt_artifact_path"] == str(tmp_path / "prompt.txt")
    assert payload["artifacts"][0]["path"] == str(tmp_path / "script-report.txt")
    assert payload["steps"][0]["artifacts"][0]["path"] == str(tmp_path / "script-log.txt")
    assert payload["uploaded_workbook_metadata"]["storage_path"] == str(tmp_path / "model.xlsx")
    assert payload["run_parameters"]["source_snapshot_artifact_path"] == str(tmp_path / "snapshot.zip")
    assert payload["run_parameters"]["synthesis_prompt_artifact_path"] == str(tmp_path / "synthesis.txt")
    assert payload["run_parameters"]["skill_source_snapshot"]["artifact_path"] == str(tmp_path / "snapshot.zip")


def test_analysis_read_embedded_ic_review_latest_order_has_stable_id_tiebreaker(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    skill = db_session.query(Skill).filter_by(name="ic_agentic_review").one()
    same_created_at = datetime(2026, 7, 9, 11, 0, tzinfo=UTC)
    lower_id_run = _create_ic_review_visibility_run(
        db_session,
        analysis=analysis,
        skill=skill,
        tmp_path=tmp_path,
        created_at=same_created_at,
        run_id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    higher_id_run = _create_ic_review_visibility_run(
        db_session,
        analysis=analysis,
        skill=skill,
        tmp_path=tmp_path,
        created_at=same_created_at,
        run_id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
    )
    db_session.add_all([lower_id_run, higher_id_run])
    db_session.commit()
    login(client, "author", "secret")

    response = client.get(f"/analyses/{analysis.id}")

    assert response.status_code == 200
    assert response.json()["ic_review_run"]["id"] == str(higher_id_run.id)


def test_ic_review_list_and_latest_endpoints_use_stable_latest_order(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    skill = db_session.query(Skill).filter_by(name="ic_agentic_review").one()
    same_created_at = datetime(2026, 7, 9, 11, 0, tzinfo=UTC)
    lower_id_run = _create_ic_review_visibility_run(
        db_session,
        analysis=analysis,
        skill=skill,
        tmp_path=tmp_path,
        created_at=same_created_at,
        run_id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    higher_id_run = _create_ic_review_visibility_run(
        db_session,
        analysis=analysis,
        skill=skill,
        tmp_path=tmp_path,
        created_at=same_created_at,
        run_id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
    )
    db_session.add_all([lower_id_run, higher_id_run])
    db_session.commit()
    login(client, "author", "secret")

    list_response = client.get(f"/analyses/{analysis.id}/ic-review-runs")
    latest_response = client.get(f"/analyses/{analysis.id}/ic-review-runs/latest")

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["runs"]] == [str(higher_id_run.id), str(lower_id_run.id)]
    assert latest_response.status_code == 200
    assert latest_response.json()["id"] == str(higher_id_run.id)


def test_non_admin_cannot_download_admin_only_ic_review_artifact_by_key(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    run = _create_ic_review_run_with_artifact(db_session, analysis, tmp_path, visibility=None)
    login(client, "author", "secret")

    response = client.get(f"/ic-review-runs/{run.id}/artifacts/raw")

    assert response.status_code == 404


def test_non_admin_can_download_user_visible_ic_review_artifact_by_key(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    run = _create_ic_review_run_with_artifact(db_session, analysis, tmp_path, visibility="user")
    login(client, "author", "secret")

    response = client.get(f"/ic-review-runs/{run.id}/artifacts/raw")

    assert response.status_code == 200
    assert response.content == b"raw artifact"


def test_admin_can_download_db_owned_ic_review_artifact(client, db_session, monkeypatch, tmp_path):
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    run = _create_ic_review_run_with_artifact(db_session, analysis, tmp_path, visibility=None)
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    login(client, admin.login, "secret")

    response = client.get(f"/ic-review-runs/{run.id}/artifacts/raw")

    assert response.status_code == 200
    assert response.content == b"raw artifact"


def test_ic_review_artifact_path_outside_run_directory_returns_404(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path)
    analysis = _create_analysis_for_api(db_session, status=RunStatus.COMPLETED)
    skill = db_session.query(Skill).filter_by(name="ic_agentic_review").one()
    run = AnalysisCheckRun(
        analysis_id=analysis.id,
        skill_id=skill.id,
        skill_version=skill.version,
        check_type="ic_agentic_review",
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="openai/gpt-5.5",
        status=RunStatus.COMPLETED.value,
        run_parameters={},
        artifacts=[],
        uploaded_workbook_metadata={},
    )
    db_session.add(run)
    db_session.flush()
    outside_file = tmp_path / "storage" / "ic-review" / str(analysis.id) / "other-run" / "artifacts" / "raw.txt"
    outside_file.parent.mkdir(parents=True)
    outside_file.write_bytes(b"wrong run")
    run.artifacts = [
        {
            "key": "raw",
            "path": str(outside_file),
            "filename": "raw.txt",
            "media_type": "text/plain",
            "visibility": "user",
        }
    ]
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    db_session.commit()
    login(client, admin.login, "secret")

    response = client.get(f"/ic-review-runs/{run.id}/artifacts/raw")

    assert response.status_code == 404


def _create_completed_analysis_with_skill(db_session):
    user = User(
        login="author",
        display_name="Author",
        password_hash=hash_password("secret"),
        role=Role.USER.value,
        status=UserStatus.ACTIVE.value,
    )
    db_session.add(user)
    db_session.flush()
    document = Document(
        owner_id=user.id,
        title="Investment Defense",
        original_filename="gate.txt",
        mime_type="text/plain",
        file_size_bytes=42,
        file_hash_sha256="0" * 64,
        storage_path="/storage/gate.txt",
        parse_status=DocumentParseStatus.COMPLETED.value,
        detected_document_type=DocumentType.GATE_3.value,
        parsed_text="Completed Gate 3 defense text",
    )
    skill = Skill(
        name="ic_agentic_review",
        description="IC Agentic Review",
        version="2026-07-09",
        skill_type=SkillType.ANALYSIS_CHECK.value,
        supported_document_types=[DocumentType.GATE_3.value],
        source_type="local_skill_repo",
        prompt_text="prompt",
        result_schema_path="contracts/schemas/ic-agentic-review-result.schema.json",
    )
    db_session.add_all([document, skill])
    db_session.flush()
    analysis = Analysis(
        document_id=document.id,
        user_id=user.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="openai/gpt-5.5",
        status=RunStatus.COMPLETED.value,
        structured_output={"summary": "completed"},
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.commit()
    return analysis, skill


def _configure_ic_review_dependencies(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()

    source_root = tmp_path / "ic-source"
    command = source_root / ".claude" / "commands" / "invest-analysis.md"
    command.parent.mkdir(parents=True)
    command.write_text("IC prompt", encoding="utf-8")

    admin = db_session.query(User).filter_by(login="provider-admin").one_or_none()
    if admin is None:
        admin = create_user(db_session, "provider-admin", "secret", Role.ADMIN)
    seed_baseline_skills(db_session)
    ic_source = db_session.query(SkillSource).filter_by(slug="ic-agentic-review").one()
    ic_source.source_kind = "local_directory"
    ic_source.local_path = str(source_root)
    ic_source.entrypoint = ".claude/commands/invest-analysis.md"
    ic_source.required_paths = [".claude/commands/invest-analysis.md"]
    db_session.add(
        ProviderKey(
            owner_id=admin.id,
            provider=Provider.OPENAI_COMPATIBLE.value,
            base_url=None,
            default_model="openai/gpt-5.5",
            available_models=["openai/gpt-5.5"],
            encrypted_api_key=encrypt_secret("sk-test"),
            api_key_fingerprint="openai_compatible:...test",
        )
    )
    db_session.commit()


def _create_analysis_for_api(db_session, *, status: RunStatus, login_name: str = "author") -> Analysis:
    user = db_session.query(User).filter_by(login=login_name).one_or_none()
    if user is None:
        user = create_user(db_session, login_name, "secret")
    skill = db_session.query(Skill).filter_by(name="gate2_challenger_main_analysis").one()
    document = Document(
        owner_id=user.id,
        title="Investment Defense",
        original_filename="gate.txt",
        mime_type="text/plain",
        file_size_bytes=42,
        file_hash_sha256="1" * 64,
        storage_path="/storage/gate.txt",
        parse_status=DocumentParseStatus.COMPLETED.value,
        detected_document_type=DocumentType.GATE_3.value,
        parsed_text="Completed Gate 3 defense text",
    )
    db_session.add(document)
    db_session.flush()
    analysis = Analysis(
        document_id=document.id,
        user_id=user.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="openai/gpt-5.5",
        status=status.value,
        structured_output={"summary": "completed"} if status == RunStatus.COMPLETED else None,
        run_parameters={"output_language": "ru"},
    )
    db_session.add(analysis)
    db_session.commit()
    db_session.refresh(analysis)
    return analysis


def _override_ic_review_enqueue() -> list[str]:
    from app.main import app
    from app.routers import ic_review as ic_review_router

    enqueued: list[str] = []

    def fake_enqueue(run_id):
        enqueued.append(str(run_id))

    app.dependency_overrides[ic_review_router.get_run_ic_agentic_review_enqueue] = lambda: fake_enqueue
    return enqueued


def _clear_ic_review_enqueue_override() -> None:
    from app.main import app
    from app.routers import ic_review as ic_review_router

    app.dependency_overrides.pop(ic_review_router.get_run_ic_agentic_review_enqueue, None)


def _xlsx_bytes() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types></Types>")
        archive.writestr("xl/workbook.xml", "<workbook></workbook>")
    return buffer.getvalue()


def _create_ic_review_run_with_artifact(db_session, analysis: Analysis, tmp_path, *, visibility: str | None):
    skill = db_session.query(Skill).filter_by(name="ic_agentic_review").one()
    run = AnalysisCheckRun(
        analysis_id=analysis.id,
        skill_id=skill.id,
        skill_version=skill.version,
        check_type="ic_agentic_review",
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="openai/gpt-5.5",
        status=RunStatus.COMPLETED.value,
        run_parameters={},
        artifacts=[],
        uploaded_workbook_metadata={},
    )
    db_session.add(run)
    db_session.flush()
    artifact_path = tmp_path / "storage" / "ic-review" / str(analysis.id) / str(run.id) / "raw" / "raw.txt"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"raw artifact")
    artifact = {
        "key": "raw",
        "path": str(artifact_path),
        "filename": "raw.txt",
        "media_type": "text/plain",
    }
    if visibility:
        artifact["visibility"] = visibility
    run.artifacts = [artifact]
    db_session.commit()
    db_session.refresh(run)
    return run


def _create_ic_review_visibility_run(
    db_session,
    *,
    analysis: Analysis,
    skill: Skill,
    tmp_path,
    created_at: datetime,
    run_id: UUID | None = None,
) -> AnalysisCheckRun:
    run = AnalysisCheckRun(
        id=run_id or uuid4(),
        analysis_id=analysis.id,
        skill_id=skill.id,
        skill_version=skill.version,
        check_type="ic_agentic_review",
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="openai/gpt-5.5",
        status=RunStatus.COMPLETED.value,
        current_stage="synthesis",
        structured_output={"verdict": "CONDITIONAL", "executive_brief": "Compact result"},
        legacy_output={"sections": {}},
        raw_output="run raw output",
        run_parameters={
            "source_snapshot_id": "00000000-0000-0000-0000-000000000001",
            "source_snapshot_artifact_path": str(tmp_path / "snapshot.zip"),
            "synthesis_prompt_artifact_path": str(tmp_path / "synthesis.txt"),
            "source_revision": "abc123",
            "source_fingerprint": "sha256:source",
            "snapshot_mode": "copy",
            "skill_source_snapshot": {
                "id": "00000000-0000-0000-0000-000000000001",
                "source_slug": "ic-agentic-review",
                "source_revision": "abc123",
                "source_fingerprint": "sha256:source",
                "artifact_path": str(tmp_path / "snapshot.zip"),
                "snapshot_mode": "copy",
                "is_dirty": False,
            },
        },
        artifacts=[{"key": "validation_report", "path": str(tmp_path / "script-report.txt"), "filename": "report.txt"}],
        uploaded_workbook_metadata={"storage_path": str(tmp_path / "model.xlsx"), "filename": "model.xlsx"},
        created_at=created_at,
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        AnalysisCheckStep(
            check_run_id=run.id,
            step_type="script",
            step_name="validate_report",
            status=RunStatus.COMPLETED.value,
            prompt_artifact_path=str(tmp_path / "prompt.txt"),
            raw_output="step raw output",
            structured_output={"role": "ic-financial-auditor"},
            artifacts=[{"key": "script_log", "path": str(tmp_path / "script-log.txt"), "filename": "script-log.txt"}],
            created_at=created_at + timedelta(seconds=1),
        )
    )
    return run
