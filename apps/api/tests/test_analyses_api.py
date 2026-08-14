from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.models.analysis import Analysis, AnalysisCheckRun, AnalysisCheckStep, AnalysisDetailRun, PredictedCommentRun
from app.models.base import utc_now
from app.models.document import Document
from app.models.feedback import Feedback
from app.models.provider_key import ProviderKey
from app.models.skill_source import RetrievalSnapshot, SkillSource, SkillSourceSnapshot
from app.core.config import get_settings
from app.schemas.enums import DocumentParseStatus, DocumentType, FeedbackUsefulness, Provider, Role, RunStatus
from app.security.secrets import encrypt_secret
from app.seeds.skills import seed_baseline_skills

from test_documents_upload import create_user, login, upload_document


def _disable_parse_enqueue():
    from app.main import app
    from app.routers import documents as documents_router

    app.dependency_overrides[documents_router.get_parse_document_enqueue] = lambda: lambda document_id: None
    return app, documents_router


def test_create_analysis_requires_completed_parse(client, db_session):
    app, documents_router = _disable_parse_enqueue()
    create_user(db_session, "author", "secret")
    seed_baseline_skills(db_session)
    login(client, "author", "secret")
    try:
        upload = upload_document(client, "gate.txt", b"Gate 2 MVP metrics")
        response = client.post(f"/documents/{upload.json()['id']}/analyses", json={"provider": "hermes", "model": "hermes"})
    finally:
        app.dependency_overrides.pop(documents_router.get_parse_document_enqueue, None)

    assert response.status_code == 409


def test_create_analysis_rejects_stored_dormant_progress_review(client, db_session):
    app, documents_router = _disable_parse_enqueue()
    create_user(db_session, "author", "secret")
    seed_baseline_skills(db_session)
    login(client, "author", "secret")
    try:
        upload = upload_document(client, "progress.txt", b"Progress review")
        document = db_session.get(Document, UUID(upload.json()["id"]))
        document.parse_status = DocumentParseStatus.COMPLETED.value
        document.parsed_text = "Progress review plan versus actuals"
        document.detected_document_type = DocumentType.PROGRESS_REVIEW.value
        db_session.commit()

        response = client.post(
            f"/documents/{document.id}/analyses",
            json={"provider": "hermes", "model": "hermes"},
        )
    finally:
        app.dependency_overrides.pop(documents_router.get_parse_document_enqueue, None)

    assert response.status_code == 409
    assert response.json()["detail"] == "Progress Review analysis is not enabled yet"


def test_create_analysis_queues_default_gate2_skill_with_snapshot(client, db_session, monkeypatch, tmp_path):
    enqueued: list[str] = []

    def fake_enqueue(analysis_id):
        enqueued.append(str(analysis_id))

    from app.main import app
    from app.routers import analyses as analyses_router
    from app.routers import documents as documents_router

    app.dependency_overrides[analyses_router.get_run_analysis_enqueue] = lambda: fake_enqueue
    app.dependency_overrides[documents_router.get_parse_document_enqueue] = lambda: lambda document_id: None
    try:
        monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
        get_settings.cache_clear()
        source_root = tmp_path / "gate-source"
        (source_root / "references").mkdir(parents=True)
        (source_root / "SKILL.md").write_text("Gate prompt", encoding="utf-8")
        (source_root / "references" / "rubric.md").write_text("Rubric", encoding="utf-8")

        admin = create_user(db_session, "admin", "secret", role=Role.ADMIN)
        create_user(db_session, "author", "secret")
        seed_baseline_skills(db_session)
        gate_source = db_session.query(SkillSource).filter_by(slug="gate-challenger").one()
        gate_source.source_kind = "local_directory"
        gate_source.local_path = str(source_root)
        gate_source.entrypoint = "SKILL.md"
        gate_source.required_paths = ["SKILL.md", "references"]
        db_session.commit()
        login(client, "author", "secret")
        upload = upload_document(client, "gate.txt", b"Gate 2 MVP metrics")
        document_id = UUID(upload.json()["id"])
        document = db_session.get(Document, document_id)
        document.parse_status = DocumentParseStatus.COMPLETED.value
        document.parsed_text = "Gate 2 MVP traction metrics risks business case"
        document.detected_document_type = DocumentType.GATE_2.value
        db_session.add(
            ProviderKey(
                owner_id=admin.id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url=None,
                default_model="openai/gpt-5.5",
                available_models=["openai/gpt-5.5", "google/gemini-3.5-flash"],
                encrypted_api_key=encrypt_secret("sk-test"),
                api_key_fingerprint="openai_compatible:...test",
            )
        )
        db_session.commit()

        response = client.post(
            f"/documents/{document_id}/analyses",
            json={"provider": "openai_compatible", "model": "openai/gpt-5.5"},
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["status"] == "queued"
        assert payload["skill_name"] == "gate2_challenger_main_analysis"
        assert payload["source_trace"]["source_slug"] == "gate-challenger"
        assert payload["source_trace"]["source_snapshot_id"]
        assert enqueued == [payload["id"]]
        analysis = db_session.get(Analysis, UUID(payload["id"]))
        assert analysis.status == RunStatus.QUEUED.value
        assert analysis.model == "openai/gpt-5.5"
        assert analysis.run_parameters["output_language"] == "ru"
        assert analysis.run_parameters["skill_source_snapshot"]["name"] == "gate2_challenger_main_analysis"
        source_snapshot_id = UUID(analysis.run_parameters["source_snapshot_id"])
        source_snapshot = db_session.get(SkillSourceSnapshot, source_snapshot_id)
        assert source_snapshot.source_slug == "gate-challenger"
        assert (tmp_path / "storage" / "skill-snapshots" / str(source_snapshot.id) / "files" / "SKILL.md").read_text(
            encoding="utf-8"
        ) == "Gate prompt"
    finally:
        get_settings.cache_clear()
        app.dependency_overrides.pop(analyses_router.get_run_analysis_enqueue, None)
        app.dependency_overrides.pop(documents_router.get_parse_document_enqueue, None)


def test_create_analysis_rejects_model_outside_shared_admin_allowlist(client, db_session, monkeypatch, tmp_path):
    from app.main import app
    from app.routers import analyses as analyses_router
    from app.routers import documents as documents_router

    app.dependency_overrides[analyses_router.get_run_analysis_enqueue] = lambda: lambda analysis_id: None
    app.dependency_overrides[documents_router.get_parse_document_enqueue] = lambda: lambda document_id: None
    try:
        monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
        get_settings.cache_clear()
        source_root = tmp_path / "gate-source"
        (source_root / "references").mkdir(parents=True)
        (source_root / "SKILL.md").write_text("Gate prompt", encoding="utf-8")

        admin = create_user(db_session, "admin", "secret", role=Role.ADMIN)
        create_user(db_session, "author", "secret")
        seed_baseline_skills(db_session)
        gate_source = db_session.query(SkillSource).filter_by(slug="gate-challenger").one()
        gate_source.source_kind = "local_directory"
        gate_source.local_path = str(source_root)
        gate_source.entrypoint = "SKILL.md"
        gate_source.required_paths = ["SKILL.md"]
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
        login(client, "author", "secret")
        upload = upload_document(client, "gate.txt", b"Gate 2 MVP metrics")
        document_id = UUID(upload.json()["id"])
        document = db_session.get(Document, document_id)
        document.parse_status = DocumentParseStatus.COMPLETED.value
        document.parsed_text = "Gate 2 MVP traction metrics risks business case"
        document.detected_document_type = DocumentType.GATE_2.value
        db_session.commit()

        response = client.post(
            f"/documents/{document_id}/analyses",
            json={"provider": "openai_compatible", "model": "google/gemini-3.5-flash"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "Selected model is not available"
    finally:
        get_settings.cache_clear()
        app.dependency_overrides.pop(analyses_router.get_run_analysis_enqueue, None)
        app.dependency_overrides.pop(documents_router.get_parse_document_enqueue, None)


def test_create_analysis_defaults_to_development_snapshot_when_git_metadata_is_unavailable(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    enqueued: list[str] = []

    def fake_enqueue(analysis_id):
        enqueued.append(str(analysis_id))

    from app.main import app
    from app.routers import analyses as analyses_router
    from app.routers import documents as documents_router

    app.dependency_overrides[analyses_router.get_run_analysis_enqueue] = lambda: fake_enqueue
    app.dependency_overrides[documents_router.get_parse_document_enqueue] = lambda: lambda document_id: None
    try:
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
        get_settings.cache_clear()
        source_root = tmp_path / "gate-source-without-git"
        skill_path = source_root / "skills" / "gate-challenger" / "SKILL.md"
        references_path = source_root / "skills" / "gate-challenger" / "references"
        references_path.mkdir(parents=True)
        skill_path.write_text("Gate prompt", encoding="utf-8")
        (references_path / "rubric.md").write_text("Rubric", encoding="utf-8")

        admin = create_user(db_session, "admin", "secret", role=Role.ADMIN)
        create_user(db_session, "author", "secret")
        seed_baseline_skills(db_session)
        gate_source = db_session.query(SkillSource).filter_by(slug="gate-challenger").one()
        gate_source.source_kind = "local_git_repo"
        gate_source.local_path = str(source_root)
        gate_source.entrypoint = "skills/gate-challenger/SKILL.md"
        gate_source.required_paths = ["skills/gate-challenger/SKILL.md", "skills/gate-challenger/references"]
        login(client, "author", "secret")
        upload = upload_document(client, "gate.txt", b"Gate 2 MVP metrics")
        document_id = UUID(upload.json()["id"])
        document = db_session.get(Document, document_id)
        document.parse_status = DocumentParseStatus.COMPLETED.value
        document.parsed_text = "Gate 2 MVP traction metrics risks business case"
        document.detected_document_type = DocumentType.GATE_2.value
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

        response = client.post(
            f"/documents/{document_id}/analyses",
            json={"provider": "openai_compatible", "model": "openai/gpt-5.5"},
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["source_trace"]["snapshot_mode"] == "development_current"
        analysis = db_session.get(Analysis, UUID(payload["id"]))
        source_snapshot = db_session.get(SkillSourceSnapshot, UUID(analysis.run_parameters["source_snapshot_id"]))
        assert source_snapshot.resolved_revision is None
        assert source_snapshot.dirty_details == {"git_unavailable": True}
        assert enqueued == [payload["id"]]
    finally:
        get_settings.cache_clear()
        app.dependency_overrides.pop(analyses_router.get_run_analysis_enqueue, None)
        app.dependency_overrides.pop(documents_router.get_parse_document_enqueue, None)


def test_create_analysis_uses_configured_production_export_snapshot_without_git_metadata(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    enqueued: list[str] = []

    def fake_enqueue(analysis_id):
        enqueued.append(str(analysis_id))

    from app.main import app
    from app.routers import analyses as analyses_router
    from app.routers import documents as documents_router

    app.dependency_overrides[analyses_router.get_run_analysis_enqueue] = lambda: fake_enqueue
    app.dependency_overrides[documents_router.get_parse_document_enqueue] = lambda: lambda document_id: None
    try:
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("SKILL_SOURCE_SNAPSHOT_MODE", "production_export")
        monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
        get_settings.cache_clear()
        source_root = tmp_path / "gate-source-export"
        skill_path = source_root / "skills" / "gate-challenger" / "SKILL.md"
        references_path = source_root / "skills" / "gate-challenger" / "references"
        references_path.mkdir(parents=True)
        skill_path.write_text("Gate prompt", encoding="utf-8")
        (references_path / "rubric.md").write_text("Rubric", encoding="utf-8")

        admin = create_user(db_session, "admin", "secret", role=Role.ADMIN)
        create_user(db_session, "author", "secret")
        seed_baseline_skills(db_session)
        gate_source = db_session.query(SkillSource).filter_by(slug="gate-challenger").one()
        gate_source.source_kind = "local_git_repo"
        gate_source.local_path = str(source_root)
        gate_source.entrypoint = "skills/gate-challenger/SKILL.md"
        gate_source.required_paths = ["skills/gate-challenger/SKILL.md", "skills/gate-challenger/references"]
        login(client, "author", "secret")
        upload = upload_document(client, "gate.txt", b"Gate 2 MVP metrics")
        document_id = UUID(upload.json()["id"])
        document = db_session.get(Document, document_id)
        document.parse_status = DocumentParseStatus.COMPLETED.value
        document.parsed_text = "Gate 2 MVP traction metrics risks business case"
        document.detected_document_type = DocumentType.GATE_2.value
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

        response = client.post(
            f"/documents/{document_id}/analyses",
            json={"provider": "openai_compatible", "model": "openai/gpt-5.5"},
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["source_trace"]["snapshot_mode"] == "production_export"
        analysis = db_session.get(Analysis, UUID(payload["id"]))
        source_snapshot = db_session.get(SkillSourceSnapshot, UUID(analysis.run_parameters["source_snapshot_id"]))
        assert source_snapshot.resolved_revision is None
        assert source_snapshot.dirty_details == {"git_unavailable": True}
        assert enqueued == [payload["id"]]
    finally:
        get_settings.cache_clear()
        app.dependency_overrides.pop(analyses_router.get_run_analysis_enqueue, None)
        app.dependency_overrides.pop(documents_router.get_parse_document_enqueue, None)


def test_create_analysis_rejects_unavailable_external_skill_source(client, db_session, monkeypatch, tmp_path):
    from app.main import app
    from app.routers import analyses as analyses_router
    from app.routers import documents as documents_router

    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    app.dependency_overrides[analyses_router.get_run_analysis_enqueue] = lambda: lambda analysis_id: None
    app.dependency_overrides[documents_router.get_parse_document_enqueue] = lambda: lambda document_id: None
    try:
        admin = create_user(db_session, "admin", "secret", role=Role.ADMIN)
        create_user(db_session, "author", "secret")
        seed_baseline_skills(db_session)
        gate_source = db_session.query(SkillSource).filter_by(slug="gate-challenger").one()
        gate_source.source_kind = "local_directory"
        gate_source.local_path = str(tmp_path / "missing")
        gate_source.entrypoint = "SKILL.md"
        gate_source.required_paths = ["SKILL.md"]
        login(client, "author", "secret")
        upload = upload_document(client, "gate.txt", b"Gate 2 MVP metrics")
        document_id = UUID(upload.json()["id"])
        document = db_session.get(Document, document_id)
        document.parse_status = DocumentParseStatus.COMPLETED.value
        document.parsed_text = "Gate 2 MVP traction metrics risks business case"
        document.detected_document_type = DocumentType.GATE_2.value
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

        response = client.post(
            f"/documents/{document_id}/analyses",
            json={"provider": "openai_compatible", "model": "openai/gpt-5.5"},
        )

        assert response.status_code == 409
        assert "source path does not exist" in response.json()["detail"]
    finally:
        get_settings.cache_clear()
        app.dependency_overrides.pop(analyses_router.get_run_analysis_enqueue, None)
        app.dependency_overrides.pop(documents_router.get_parse_document_enqueue, None)


def test_analysis_detail_hides_raw_output_from_non_admin(client, db_session):
    user = create_user(db_session, "author", "secret")
    skill = seed_baseline_skills(db_session)[0]
    analysis = Analysis(
        document_id=_create_completed_document(client, db_session, user),
        user_id=user.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Needs evidence",
        structured_output={"verdict": "need_evidence", "summary": "Needs evidence", "findings": [], "checks": []},
        raw_output="raw secret output",
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.commit()
    login(client, "author", "secret")

    response = client.get(f"/analyses/{analysis.id}")

    assert response.status_code == 200
    assert response.json()["raw_output"] is None


def test_compact_status_endpoints_preserve_chain_progress_without_heavy_outputs(client, db_session):
    user = create_user(db_session, "author", "secret")
    create_user(db_session, "other", "secret")
    skills = seed_baseline_skills(db_session)
    document_id = _create_completed_document(client, db_session, user)
    analysis = Analysis(
        document_id=document_id,
        user_id=user.id,
        skill_id=skills[0].id,
        skill_version=skills[0].version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Heavy summary" * 10_000,
        structured_output={"secret": "g" * 500_000},
        raw_output="raw gate secret" * 20_000,
        run_parameters={"analysis_chain_cancel_requested_at": "2026-08-07T12:00:00Z"},
    )
    db_session.add(analysis)
    db_session.flush()
    predicted = PredictedCommentRun(
        analysis_id=analysis.id,
        skill_id=skills[1].id,
        skill_version=skills[1].version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        structured_output={"secret": "d" * 500_000},
        raw_output="raw predicted secret" * 20_000,
        run_parameters={},
    )
    detail = AnalysisDetailRun(
        analysis_id=analysis.id,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.QUEUED.value,
        structured_output={"secret": "l" * 500_000},
        raw_output="raw detail secret" * 20_000,
        run_parameters={},
    )
    ic_review = AnalysisCheckRun(
        analysis_id=analysis.id,
        skill_id=skills[0].id,
        skill_version=skills[0].version,
        check_type="ic_agentic_review",
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.RUNNING.value,
        current_stage="role:ic-product-analyst",
        structured_output={"secret": "i" * 500_000},
        raw_output="raw ic secret" * 20_000,
        run_parameters={},
        artifacts=[],
        uploaded_workbook_metadata={},
    )
    db_session.add_all([predicted, detail, ic_review])
    db_session.flush()
    step = AnalysisCheckStep(
        check_run_id=ic_review.id,
        step_type="role",
        step_name="ic-financial-auditor",
        status=RunStatus.COMPLETED.value,
        raw_output="raw step secret" * 20_000,
        structured_output={"secret": "s" * 500_000},
        artifacts=[],
    )
    db_session.add(step)
    db_session.commit()
    login(client, "author", "secret")

    responses = [
        client.get(f"/analyses/{analysis.id}/status"),
        client.get(f"/documents/{document_id}/analyses/statuses"),
        client.get(f"/documents/{document_id}/progress"),
    ]

    for response in responses:
        assert response.status_code == 200
        assert len(response.content) < 20_000
        assert b"raw gate secret" not in response.content
        assert b"structured_output" not in response.content

    payload = responses[0].json()
    assert payload["chain_cancel_requested"] is True
    assert payload["predicted_comment_run"]["status"] == RunStatus.COMPLETED.value
    assert payload["detail_run"]["status"] == RunStatus.QUEUED.value
    assert payload["ic_review_run"]["status"] == RunStatus.RUNNING.value
    assert payload["ic_review_run"]["current_stage"] == "role:ic-product-analyst"
    assert payload["ic_review_run"]["steps"] == [
        {
            "id": str(step.id),
            "step_name": "ic-financial-auditor",
            "status": RunStatus.COMPLETED.value,
            "error_message": None,
            "created_at": step.created_at.isoformat(),
            "started_at": None,
            "completed_at": None,
        }
    ]

    client.post("/auth/logout")
    login(client, "other", "secret")
    assert client.get(f"/analyses/{analysis.id}/status").status_code == 404
    assert client.get(f"/documents/{document_id}/analyses/statuses").status_code == 404
    assert client.get(f"/documents/{document_id}/progress").status_code == 404


def test_document_owner_can_open_analysis_created_by_admin_for_their_document(client, db_session):
    owner = create_user(db_session, "owner", "secret")
    admin = create_user(db_session, "admin", "secret", role=Role.ADMIN)
    skill = seed_baseline_skills(db_session)[0]
    document_id = _create_completed_document_row(db_session, owner)
    analysis = Analysis(
        document_id=document_id,
        user_id=admin.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Needs evidence",
        structured_output={"verdict": "need_evidence", "summary": "Needs evidence", "findings": [], "checks": []},
        raw_output="raw secret output",
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.commit()
    login(client, "owner", "secret")

    response = client.get(f"/analyses/{analysis.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(analysis.id)
    assert response.json()["document_id"] == str(document_id)
    assert response.json()["raw_output"] is None


def test_delete_analysis_hides_owned_analysis_from_detail_and_document_list(client, db_session):
    user = create_user(db_session, "author", "secret")
    skill = seed_baseline_skills(db_session)[0]
    document_id = _create_completed_document(client, db_session, user)
    analysis = Analysis(
        document_id=document_id,
        user_id=user.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Needs evidence",
        structured_output={"verdict": "need_evidence", "summary": "Needs evidence", "findings": [], "checks": []},
        raw_output="raw secret output",
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.commit()
    login(client, "author", "secret")

    response = client.delete(f"/analyses/{analysis.id}")

    assert response.status_code == 204
    db_session.refresh(analysis)
    assert analysis.deleted_at is not None
    assert client.get(f"/analyses/{analysis.id}").status_code == 404
    list_response = client.get(f"/documents/{document_id}/analyses")
    assert list_response.status_code == 200
    assert list_response.json()["analyses"] == []


def test_delete_analysis_removes_result_runs_and_storage_artifacts(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    user = create_user(db_session, "author", "secret")
    skills = seed_baseline_skills(db_session)
    skill_source = db_session.query(SkillSource).filter_by(slug="gate-challenger").one()
    document_id = _create_completed_document(client, db_session, user)
    analysis = Analysis(
        document_id=document_id,
        user_id=user.id,
        skill_id=skills[0].id,
        skill_version=skills[0].version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Needs evidence",
        structured_output={"verdict": "need_evidence"},
        raw_output="raw secret output",
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.flush()
    predicted_run = PredictedCommentRun(
        analysis_id=analysis.id,
        skill_id=skills[1].id,
        skill_version=skills[1].version,
        provider=analysis.provider,
        model=analysis.model,
        status=RunStatus.COMPLETED.value,
        structured_output={"comments": []},
        raw_output="raw da output",
        run_parameters={},
    )
    detail_run = AnalysisDetailRun(
        analysis_id=analysis.id,
        status=RunStatus.COMPLETED.value,
        provider=analysis.provider,
        model=analysis.model,
        structured_output={"layer_1": []},
        raw_output="raw details",
        run_parameters={},
    )
    check_run = AnalysisCheckRun(
        analysis_id=analysis.id,
        skill_id=skills[2].id,
        skill_version=skills[2].version,
        check_type="ic_agentic_review",
        provider=analysis.provider,
        model=analysis.model,
        status=RunStatus.COMPLETED.value,
        structured_output={"verdict": "ok"},
        raw_output="raw ic",
        run_parameters={},
        artifacts=[],
        uploaded_workbook_metadata={},
    )
    db_session.add_all([predicted_run, detail_run, check_run])
    db_session.flush()
    check_step = AnalysisCheckStep(
        check_run_id=check_run.id,
        step_type="role",
        step_name="ic-product-analyst",
        status=RunStatus.COMPLETED.value,
        raw_output="raw role",
        structured_output={"ok": True},
        artifacts=[],
    )
    db_session.add(check_step)
    db_session.flush()

    analysis_prompt = tmp_path / "storage" / "rendered-prompts" / str(analysis.id) / "prompt.txt"
    predicted_prompt = tmp_path / "storage" / "rendered-prompts" / str(predicted_run.id) / "prompt.txt"
    source_snapshot_dir = tmp_path / "storage" / "skill-snapshots" / str(uuid4())
    retrieval_snapshot_dir = tmp_path / "storage" / "retrieval-snapshots" / str(uuid4())
    ic_artifact = tmp_path / "storage" / "ic-review" / str(analysis.id) / str(check_run.id) / "artifacts" / "raw.txt"
    for path in [analysis_prompt, predicted_prompt, source_snapshot_dir / "manifest.json", retrieval_snapshot_dir / "dossier.json", ic_artifact]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("artifact", encoding="utf-8")
    analysis.run_parameters = {"rendered_prompt_artifact_path": str(analysis_prompt)}
    predicted_run.run_parameters = {"rendered_prompt_artifact_path": str(predicted_prompt)}
    db_session.add(
        SkillSourceSnapshot(
            skill_source_id=skill_source.id,
            analysis_id=analysis.id,
            source_slug="gate-challenger",
            source_kind="local_directory",
            source_path=None,
            repo_url=None,
            requested_ref=None,
            resolved_revision="abc123",
            is_dirty=False,
            dirty_details={},
            snapshot_mode="development_current",
            source_fingerprint="fingerprint",
            file_manifest=[],
            artifact_path=str(source_snapshot_dir),
        )
    )
    db_session.add(
        RetrievalSnapshot(
            predicted_comment_run_id=predicted_run.id,
            retrieval_mode="compact",
            retrieval_version="v1",
            corpus_fingerprint="corpus",
            query_fingerprint="query",
            selected_items={},
            artifact_path=str(retrieval_snapshot_dir),
        )
    )
    db_session.commit()
    login(client, "author", "secret")

    response = client.delete(f"/analyses/{analysis.id}")

    assert response.status_code == 204
    db_session.refresh(analysis)
    assert analysis.deleted_at is not None
    assert analysis.structured_output is None
    assert analysis.raw_output is None
    assert analysis.run_parameters["deleted_by_user_id"] == str(user.id)
    assert db_session.query(PredictedCommentRun).filter_by(analysis_id=analysis.id).count() == 0
    assert db_session.query(AnalysisDetailRun).filter_by(analysis_id=analysis.id).count() == 0
    assert db_session.query(AnalysisCheckRun).filter_by(analysis_id=analysis.id).count() == 0
    assert db_session.query(AnalysisCheckStep).filter_by(check_run_id=check_run.id).count() == 0
    assert db_session.query(SkillSourceSnapshot).filter_by(analysis_id=analysis.id).count() == 0
    assert db_session.query(RetrievalSnapshot).filter_by(predicted_comment_run_id=predicted_run.id).count() == 0
    assert not analysis_prompt.parent.exists()
    assert not predicted_prompt.parent.exists()
    assert not source_snapshot_dir.exists()
    assert not retrieval_snapshot_dir.exists()
    assert not ic_artifact.exists()
    get_settings.cache_clear()


def test_delete_analysis_ignores_generic_run_parameter_path(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    user = create_user(db_session, "author", "secret")
    skill = seed_baseline_skills(db_session)[0]
    document_id = _create_completed_document(client, db_session, user)
    document = db_session.get(Document, document_id)
    document_dir = tmp_path / "storage" / "documents" / str(user.id) / str(document_id)
    assert document_dir.exists()
    analysis = Analysis(
        document_id=document_id,
        user_id=user.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        structured_output={"verdict": "approve"},
        raw_output="raw output",
        run_parameters={"path": str(document_dir)},
    )
    db_session.add(analysis)
    db_session.commit()
    login(client, "author", "secret")

    response = client.delete(f"/analyses/{analysis.id}")

    assert response.status_code == 204
    assert document_dir.exists()
    assert document.storage_path
    assert Path(document.storage_path).exists()
    get_settings.cache_clear()


def test_delete_analysis_preserves_feedback_trace_fields(client, db_session):
    user = create_user(db_session, "author", "secret")
    skill = seed_baseline_skills(db_session)[0]
    document_id = _create_completed_document(client, db_session, user)
    analysis = Analysis(
        document_id=document_id,
        user_id=user.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Needs evidence",
        structured_output={"verdict": "need_evidence"},
        raw_output="raw output",
        run_parameters={"output_language": "ru"},
    )
    db_session.add(analysis)
    db_session.flush()
    db_session.add(
        Feedback(
            user_id=user.id,
            document_id=document_id,
            analysis_id=analysis.id,
            provider=analysis.provider,
            model=analysis.model,
            skill_id=analysis.skill_id,
            skill_version=analysis.skill_version,
            usefulness=FeedbackUsefulness.USEFUL.value,
            comment="Useful trace.",
            can_use_for_benchmark=True,
        )
    )
    db_session.commit()
    login(client, "author", "secret")

    response = client.delete(f"/analyses/{analysis.id}")

    assert response.status_code == 204
    db_session.refresh(analysis)
    assert analysis.deleted_at is not None
    assert analysis.verdict == "need_evidence"
    assert analysis.summary == "Needs evidence"
    assert analysis.structured_output == {"verdict": "need_evidence"}
    assert analysis.raw_output == "raw output"
    assert analysis.run_parameters["output_language"] == "ru"
    assert analysis.run_parameters["deleted_result_trace_preserved_for_feedback"] is True


def test_delete_document_analysis_results_keeps_document_and_hides_all_owned_runs(client, db_session):
    user = create_user(db_session, "author", "secret")
    skill = seed_baseline_skills(db_session)[0]
    document_id = _create_completed_document(client, db_session, user)
    db_session.add_all(
        [
            Analysis(
                document_id=document_id,
                user_id=user.id,
                skill_id=skill.id,
                skill_version=skill.version,
                provider=Provider.OPENAI_COMPATIBLE.value,
                model="gpt-test",
                status=RunStatus.COMPLETED.value,
                structured_output={"verdict": "approve"},
                raw_output="raw output",
                run_parameters={},
            ),
            Analysis(
                document_id=document_id,
                user_id=user.id,
                skill_id=skill.id,
                skill_version=skill.version,
                provider=Provider.OPENAI_COMPATIBLE.value,
                model="gpt-test",
                status=RunStatus.FAILED.value,
                error_message="failed",
                run_parameters={},
            ),
        ]
    )
    db_session.commit()
    login(client, "author", "secret")

    response = client.delete(f"/documents/{document_id}/analyses")

    assert response.status_code == 204
    assert client.get(f"/documents/{document_id}").status_code == 200
    assert client.get(f"/documents/{document_id}/analyses").json()["analyses"] == []
    assert db_session.query(Analysis).filter(Analysis.document_id == document_id, Analysis.deleted_at.is_(None)).count() == 0


def test_delete_document_analysis_results_rejects_active_runs(client, db_session):
    user = create_user(db_session, "author", "secret")
    skill = seed_baseline_skills(db_session)[0]
    document_id = _create_completed_document(client, db_session, user)
    analysis = Analysis(
        document_id=document_id,
        user_id=user.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.RUNNING.value,
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.commit()
    login(client, "author", "secret")

    response = client.delete(f"/documents/{document_id}/analyses")

    assert response.status_code == 409
    db_session.refresh(analysis)
    assert analysis.deleted_at is None


def test_delete_document_analysis_results_checks_all_active_runs_before_deleting_artifacts(
    client,
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    user = create_user(db_session, "author", "secret")
    skill = seed_baseline_skills(db_session)[0]
    document_id = _create_completed_document(client, db_session, user)
    running = Analysis(
        document_id=document_id,
        user_id=user.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.RUNNING.value,
        run_parameters={},
        created_at=utc_now(),
    )
    completed = Analysis(
        document_id=document_id,
        user_id=user.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        structured_output={"verdict": "approve"},
        raw_output="raw output",
        run_parameters={},
        created_at=utc_now() + timedelta(seconds=1),
    )
    db_session.add_all([running, completed])
    db_session.flush()
    completed_prompt = tmp_path / "storage" / "rendered-prompts" / str(completed.id) / "prompt.txt"
    completed_prompt.parent.mkdir(parents=True)
    completed_prompt.write_text("prompt", encoding="utf-8")
    db_session.commit()
    login(client, "author", "secret")

    response = client.delete(f"/documents/{document_id}/analyses")

    assert response.status_code == 409
    db_session.refresh(completed)
    db_session.refresh(running)
    assert completed.deleted_at is None
    assert running.deleted_at is None
    assert completed_prompt.exists()
    get_settings.cache_clear()


def test_delete_running_analysis_returns_conflict(client, db_session):
    user = create_user(db_session, "author", "secret")
    skill = seed_baseline_skills(db_session)[0]
    document_id = _create_completed_document(client, db_session, user)
    analysis = Analysis(
        document_id=document_id,
        user_id=user.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.RUNNING.value,
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.commit()
    login(client, "author", "secret")

    response = client.delete(f"/analyses/{analysis.id}")

    assert response.status_code == 409
    db_session.refresh(analysis)
    assert analysis.deleted_at is None


def test_document_owner_cannot_delete_analysis_created_by_admin(client, db_session):
    owner = create_user(db_session, "owner", "secret")
    admin = create_user(db_session, "admin", "secret", role=Role.ADMIN)
    skill = seed_baseline_skills(db_session)[0]
    document_id = _create_completed_document_row(db_session, owner)
    analysis = Analysis(
        document_id=document_id,
        user_id=admin.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Needs evidence",
        structured_output={"verdict": "need_evidence", "summary": "Needs evidence", "findings": [], "checks": []},
        raw_output="raw secret output",
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.commit()
    login(client, "owner", "secret")

    response = client.delete(f"/analyses/{analysis.id}")

    assert response.status_code == 404
    db_session.refresh(analysis)
    assert analysis.deleted_at is None


def test_old_analysis_does_not_enqueue_or_expose_language_variants(client, db_session):
    from app.main import app
    from app.routers import analyses as analyses_router

    user = create_user(db_session, "author", "secret")
    skills = seed_baseline_skills(db_session)
    document_id = _create_completed_document(client, db_session, user)
    analysis = Analysis(
        document_id=document_id,
        user_id=user.id,
        skill_id=skills[0].id,
        skill_version=skills[0].version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Needs evidence",
        structured_output={"result": {"short_summary": "Нужны подтверждения"}},
        run_parameters={"output_language": "ru"},
    )
    db_session.add(analysis)
    db_session.flush()
    check_run = AnalysisCheckRun(
        analysis_id=analysis.id,
        skill_id=skills[0].id,
        skill_version=skills[0].version,
        check_type="ic_agentic_review",
        provider=analysis.provider,
        model=analysis.model,
        status=RunStatus.COMPLETED.value,
        structured_output={"run_mode": "ic_agentic_review_compact"},
        run_parameters={},
        artifacts=[],
        uploaded_workbook_metadata={},
    )
    db_session.add(check_run)
    db_session.flush()
    analysis.structured_output = {
        "result": {
            "short_summary": "Нужны подтверждения",
            "summary_localizations": {
                "version": 1,
                "source_revision": str(check_run.id),
                "ru": {"status": "completed", "payload": {"language": "ru"}},
                "en": {"status": "completed", "payload": {"language": "en"}},
            },
        }
    }
    db_session.commit()
    login(client, "author", "secret")
    enqueued: list[str] = []
    app.dependency_overrides[analyses_router.get_run_summary_localizations_enqueue] = (
        lambda: lambda analysis_id: enqueued.append(str(analysis_id))
    )
    try:
        first = client.post(f"/analyses/{analysis.id}/summary-localizations")
        second = client.post(f"/analyses/{analysis.id}/summary-localizations")
        read = client.get(f"/analyses/{analysis.id}/summary-localizations")
    finally:
        app.dependency_overrides.pop(analyses_router.get_run_summary_localizations_enqueue, None)

    assert first.status_code == 200
    assert second.status_code == 200
    assert read.status_code == 200
    assert enqueued == []
    assert first.json()["source_revision"] == str(check_run.id)
    assert first.json()["generation_mode"] is None
    assert first.json()["available"] is False
    assert first.json()["ru"]["status"] == "missing"
    assert first.json()["en"]["status"] == "missing"
    assert read.json() == second.json()

    from app.services.summary_localizations import request_summary_localizations

    created, should_enqueue = request_summary_localizations(
        db=db_session,
        analysis=analysis,
        create_if_missing=True,
    )
    assert should_enqueue is True
    assert created.available is True
    assert created.generation_mode == "independent"
    assert created.ru.status == "queued"
    assert created.en.status == "queued"


def test_cancel_analysis_preserves_completed_gate_result_and_cancels_downstream_runs(client, db_session):
    user = create_user(db_session, "author", "secret")
    skills = seed_baseline_skills(db_session)
    document_id = _create_completed_document(client, db_session, user)
    analysis = Analysis(
        document_id=document_id,
        user_id=user.id,
        skill_id=skills[0].id,
        skill_version=skills[0].version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Needs evidence",
        structured_output={"verdict": "need_evidence", "summary": "Needs evidence"},
        raw_output="raw gate output",
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.flush()
    predicted = PredictedCommentRun(
        analysis_id=analysis.id,
        skill_id=skills[1].id,
        skill_version=skills[1].version,
        provider=analysis.provider,
        model=analysis.model,
        status=RunStatus.QUEUED.value,
        run_parameters={},
    )
    ic_review = AnalysisCheckRun(
        analysis_id=analysis.id,
        skill_id=skills[2].id,
        skill_version=skills[2].version,
        check_type="ic_agentic_review",
        provider=analysis.provider,
        model=analysis.model,
        status=RunStatus.RUNNING.value,
        current_stage="role:ic-financial-auditor",
        run_parameters={},
        artifacts=[],
        uploaded_workbook_metadata={},
    )
    db_session.add_all([predicted, ic_review])
    db_session.commit()
    login(client, "author", "secret")

    response = client.post(f"/analyses/{analysis.id}/cancel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["structured_output"] == {"verdict": "need_evidence", "summary": "Needs evidence"}
    assert payload["predicted_comment_run"]["status"] == "cancelled"
    assert payload["ic_review_run"]["status"] == "cancelled"
    db_session.refresh(analysis)
    db_session.refresh(predicted)
    db_session.refresh(ic_review)
    assert analysis.status == RunStatus.COMPLETED.value
    assert analysis.structured_output == {"verdict": "need_evidence", "summary": "Needs evidence"}
    assert predicted.status == RunStatus.CANCELLED.value
    assert ic_review.status == RunStatus.CANCELLED.value
    assert ic_review.current_stage == "cancelled"


def test_cancel_completed_gate_run_records_chain_stop_before_ic_review_exists(client, db_session):
    user = create_user(db_session, "author", "secret")
    skills = seed_baseline_skills(db_session)
    document_id = _create_completed_document(client, db_session, user)
    analysis = Analysis(
        document_id=document_id,
        user_id=user.id,
        skill_id=skills[0].id,
        skill_version=skills[0].version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Needs evidence",
        structured_output={"verdict": "need_evidence", "summary": "Needs evidence"},
        raw_output="raw gate output",
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.flush()
    predicted = PredictedCommentRun(
        analysis_id=analysis.id,
        skill_id=skills[1].id,
        skill_version=skills[1].version,
        provider=analysis.provider,
        model=analysis.model,
        status=RunStatus.COMPLETED.value,
        structured_output={"run_mode": "full_ic_voting"},
        run_parameters={},
    )
    db_session.add(predicted)
    db_session.commit()
    login(client, "author", "secret")

    response = client.post(f"/analyses/{analysis.id}/cancel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["structured_output"] == {"verdict": "need_evidence", "summary": "Needs evidence"}
    assert payload["ic_review_run"] is None
    assert payload["run_parameters"]["analysis_chain_cancel_requested_at"]
    db_session.refresh(analysis)
    db_session.refresh(predicted)
    assert analysis.status == RunStatus.COMPLETED.value
    assert analysis.structured_output == {"verdict": "need_evidence", "summary": "Needs evidence"}
    assert analysis.run_parameters["analysis_chain_cancel_requested_at"]
    assert predicted.status == RunStatus.COMPLETED.value


def test_cancel_running_analysis_marks_main_run_cancelled(client, db_session):
    user = create_user(db_session, "author", "secret")
    skill = seed_baseline_skills(db_session)[0]
    analysis = Analysis(
        document_id=_create_completed_document(client, db_session, user),
        user_id=user.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.RUNNING.value,
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.commit()
    login(client, "author", "secret")

    response = client.post(f"/analyses/{analysis.id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    db_session.refresh(analysis)
    assert analysis.status == RunStatus.CANCELLED.value
    assert analysis.error_message == "cancelled_by_user"
    assert analysis.completed_at is not None


def test_analysis_detail_includes_predicted_comment_run_without_raw_for_non_admin(client, db_session):
    user = create_user(db_session, "author", "secret")
    skills = seed_baseline_skills(db_session)
    analysis = Analysis(
        document_id=_create_completed_document(client, db_session, user),
        user_id=user.id,
        skill_id=skills[0].id,
        skill_version=skills[0].version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Needs evidence",
        structured_output={"verdict": "need_evidence", "summary": "Needs evidence", "findings": [], "checks": []},
        raw_output="raw secret output",
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.flush()
    predicted = PredictedCommentRun(
        analysis_id=analysis.id,
        skill_id=skills[1].id,
        skill_version=skills[1].version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        structured_output={"run_mode": "full_ic_voting", "predicted_questions": ["What is incrementality?"]},
        raw_output="raw predicted secret",
        run_parameters={
            "skill_source_snapshot_id": "00000000-0000-0000-0000-000000000101",
            "skill_source_snapshot": {
                "id": "00000000-0000-0000-0000-000000000101",
                "name": "devils_advocate_predefense",
                "source_slug": "devils-advocate",
                "source_fingerprint": "da-source-fingerprint",
            },
            "retrieval_snapshot_id": "00000000-0000-0000-0000-000000000102",
            "retrieval_snapshot": {
                "id": "00000000-0000-0000-0000-000000000102",
                "retrieval_mode": "deterministic_topk",
                "retrieval_version": "deterministic-lexical-v1",
                "corpus_fingerprint": "corpus-fingerprint",
                "query_fingerprint": "query-fingerprint",
            },
            "prompt_fingerprint": "prompt-fingerprint",
        },
    )
    db_session.add(predicted)
    db_session.commit()
    login(client, "author", "secret")

    response = client.get(f"/analyses/{analysis.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["predicted_comment_run"]["id"] == str(predicted.id)
    assert payload["predicted_comment_run"]["skill_name"] == "devils_advocate_predefense"
    assert payload["predicted_comment_run"]["source_trace"]["source_slug"] == "devils-advocate"
    assert payload["predicted_comment_run"]["retrieval_trace"]["retrieval_mode"] == "deterministic_topk"
    assert payload["predicted_comment_run"]["structured_output"]["predicted_questions"] == ["What is incrementality?"]
    assert payload["predicted_comment_run"]["raw_output"] is None


def test_analysis_detail_includes_latest_detail_run_without_raw_for_non_admin(client, db_session):
    user = create_user(db_session, "author", "secret")
    skills = seed_baseline_skills(db_session)
    analysis = Analysis(
        document_id=_create_completed_document(client, db_session, user),
        user_id=user.id,
        skill_id=skills[0].id,
        skill_version=skills[0].version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Needs evidence",
        structured_output={
            "verdict": "need_evidence",
            "summary": "Needs evidence",
            "assessment_markdown": "Оценка документа\nНужны доказательства.",
            "stage_checklist": [
                {
                    "id": "gate2_hypothesis_results",
                    "label": "Результаты проверки гипотез из Gate 1",
                    "status": "red",
                    "evidence": "Нет фактических результатов проверки гипотез Gate 1.",
                }
            ],
            "layer_1_index": [],
            "layer_2_index": [],
            "details_status": "not_requested",
            "details_run_id": None,
            "revision_required": False,
            "revision_reason": None,
        },
        raw_output="raw summary secret",
        run_parameters={"gate_challenger_response_id": "resp-summary"},
    )
    db_session.add(analysis)
    db_session.flush()
    older_detail = AnalysisDetailRun(
        analysis_id=analysis.id,
        status=RunStatus.FAILED.value,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        previous_response_id="resp-summary",
        error_message="old failure",
        run_parameters={},
    )
    latest_detail = AnalysisDetailRun(
        analysis_id=analysis.id,
        status=RunStatus.COMPLETED.value,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        previous_response_id="resp-summary",
        response_id="resp-details",
        structured_output={"layer_1": [{"id": "L1-001"}], "layer_2": []},
        raw_output="raw detail secret",
        run_parameters={"provider_api": "responses"},
    )
    db_session.add_all([older_detail, latest_detail])
    db_session.commit()
    login(client, "author", "secret")

    response = client.get(f"/analyses/{analysis.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["detail_run"]["id"] == str(latest_detail.id)
    assert payload["detail_run"]["status"] == "completed"
    assert payload["detail_run"]["previous_response_id"] == "resp-summary"
    assert payload["detail_run"]["response_id"] == "resp-details"
    assert payload["detail_run"]["structured_output"]["layer_1"] == [{"id": "L1-001"}]
    assert payload["detail_run"]["raw_output"] is None


def test_create_analysis_detail_run_allows_missing_response_id_fallback(client, db_session):
    enqueued: list[str] = []

    from app.main import app
    from app.routers import analyses as analyses_router

    app.dependency_overrides[analyses_router.get_run_analysis_details_enqueue] = lambda: lambda detail_run_id: enqueued.append(
        str(detail_run_id)
    )
    try:
        user = create_user(db_session, "author", "secret")
        skill = seed_baseline_skills(db_session)[0]
        analysis = Analysis(
            document_id=_create_completed_document(client, db_session, user),
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.COMPLETED.value,
            verdict="need_evidence",
            summary="Needs evidence",
            structured_output={
                "verdict": "need_evidence",
                "summary": "Needs evidence",
                "assessment_markdown": "Оценка документа\nНужны доказательства.",
                "layer_1_index": [],
                "layer_2_index": [],
                "details_status": "not_requested",
                "details_run_id": None,
                "revision_required": False,
                "revision_reason": None,
            },
            run_parameters={"output_language": "ru"},
        )
        db_session.add(analysis)
        db_session.commit()
        login(client, "author", "secret")

        response = client.post(f"/analyses/{analysis.id}/details")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "queued"
        assert payload["previous_response_id"] is None
        assert payload["run_parameters"]["provider_api"] == "chat_completions_fallback"
        assert payload["run_parameters"]["fallback_reason"] == "gate_challenger_response_id_missing"
        assert enqueued == [payload["id"]]
    finally:
        app.dependency_overrides.pop(analyses_router.get_run_analysis_details_enqueue, None)


def test_create_analysis_detail_run_is_idempotent_for_active_run(client, db_session):
    enqueued: list[str] = []

    from app.main import app
    from app.routers import analyses as analyses_router

    app.dependency_overrides[analyses_router.get_run_analysis_details_enqueue] = lambda: enqueued.append
    try:
        user = create_user(db_session, "author", "secret")
        skill = seed_baseline_skills(db_session)[0]
        analysis = Analysis(
            document_id=_create_completed_document(client, db_session, user),
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.COMPLETED.value,
            verdict="need_evidence",
            summary="Needs evidence",
            structured_output={"verdict": "need_evidence", "summary": "Needs evidence"},
            run_parameters={"gate_challenger_response_id": "resp-summary", "output_language": "en"},
        )
        db_session.add(analysis)
        db_session.flush()
        existing = AnalysisDetailRun(
            analysis_id=analysis.id,
            status=RunStatus.RUNNING.value,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            previous_response_id="resp-summary",
            run_parameters={"provider_api": "responses"},
        )
        db_session.add(existing)
        db_session.commit()
        login(client, "author", "secret")

        response = client.post(f"/analyses/{analysis.id}/details")

        assert response.status_code == 200
        assert response.json()["id"] == str(existing.id)
        assert enqueued == []
    finally:
        app.dependency_overrides.pop(analyses_router.get_run_analysis_details_enqueue, None)


def test_create_analysis_detail_run_enqueues_new_run(client, db_session):
    enqueued: list[str] = []

    from app.main import app
    from app.routers import analyses as analyses_router

    app.dependency_overrides[analyses_router.get_run_analysis_details_enqueue] = lambda: lambda detail_run_id: enqueued.append(
        str(detail_run_id)
    )
    try:
        user = create_user(db_session, "author", "secret")
        skill = seed_baseline_skills(db_session)[0]
        analysis = Analysis(
            document_id=_create_completed_document(client, db_session, user),
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.COMPLETED.value,
            verdict="need_evidence",
            summary="Needs evidence",
            structured_output={"verdict": "need_evidence", "summary": "Needs evidence"},
            run_parameters={"gate_challenger_response_id": "resp-summary", "output_language": "ru"},
        )
        db_session.add(analysis)
        db_session.commit()
        login(client, "author", "secret")

        response = client.post(f"/analyses/{analysis.id}/details")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "queued"
        assert payload["previous_response_id"] == "resp-summary"
        assert payload["run_parameters"]["provider_api"] == "responses"
        assert payload["run_parameters"]["output_language"] == "ru"
        assert enqueued == [payload["id"]]
    finally:
        app.dependency_overrides.pop(analyses_router.get_run_analysis_details_enqueue, None)


def _create_completed_document(client, db_session, user):
    app, documents_router = _disable_parse_enqueue()
    login(client, user.login, "secret")
    try:
        upload = upload_document(client, "gate.txt", b"Gate 2 MVP metrics")
        client.post("/auth/logout")
    finally:
        app.dependency_overrides.pop(documents_router.get_parse_document_enqueue, None)
    document = db_session.get(Document, UUID(upload.json()["id"]))
    document.parse_status = DocumentParseStatus.COMPLETED.value
    document.parsed_text = "Gate 2 MVP metrics"
    document.detected_document_type = DocumentType.GATE_2.value
    db_session.commit()
    return document.id


def _create_completed_document_row(db_session, user):
    document = Document(
        owner_id=user.id,
        title="Gate document",
        original_filename="gate.txt",
        mime_type="text/plain",
        file_size_bytes=18,
        file_hash_sha256=f"sha256-{uuid4()}",
        storage_path="/tmp/gate.txt",
        parse_status=DocumentParseStatus.COMPLETED.value,
        parsed_text="Gate 2 MVP metrics",
        detected_document_type=DocumentType.GATE_2.value,
    )
    db_session.add(document)
    db_session.flush()
    return document.id
