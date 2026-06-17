from uuid import UUID

from app.models.analysis import Analysis, AnalysisDetailRun, PredictedCommentRun
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.models.skill_source import SkillSource, SkillSourceSnapshot
from app.core.config import get_settings
from app.schemas.enums import DocumentParseStatus, DocumentType, Provider, Role, RunStatus
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


def test_create_analysis_detail_run_requires_summary_response_id(client, db_session):
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
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.commit()
    login(client, "author", "secret")

    response = client.post(f"/analyses/{analysis.id}/details")

    assert response.status_code == 409
    assert response.json()["detail"] == "Gate Challenger response id is missing"


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
