from uuid import UUID

from app.models.analysis import Analysis, PredictedCommentRun
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.schemas.enums import DocumentParseStatus, DocumentType, Provider, RunStatus
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


def test_create_analysis_queues_default_gate2_skill_with_snapshot(client, db_session, monkeypatch):
    enqueued: list[str] = []

    def fake_enqueue(analysis_id):
        enqueued.append(str(analysis_id))

    from app.main import app
    from app.routers import analyses as analyses_router
    from app.routers import documents as documents_router

    app.dependency_overrides[analyses_router.get_run_analysis_enqueue] = lambda: fake_enqueue
    app.dependency_overrides[documents_router.get_parse_document_enqueue] = lambda: lambda document_id: None
    try:
        create_user(db_session, "author", "secret")
        seed_baseline_skills(db_session)
        login(client, "author", "secret")
        upload = upload_document(client, "gate.txt", b"Gate 2 MVP metrics")
        document_id = UUID(upload.json()["id"])
        document = db_session.get(Document, document_id)
        document.parse_status = DocumentParseStatus.COMPLETED.value
        document.parsed_text = "Gate 2 MVP traction metrics risks business case"
        document.detected_document_type = DocumentType.GATE_2.value
        db_session.add(
            ProviderKey(
                owner_id=document.owner_id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url=None,
                default_model="gpt-test",
                encrypted_api_key=b"encrypted",
                api_key_fingerprint="openai_compatible:...test",
            )
        )
        db_session.commit()

        response = client.post(
            f"/documents/{document_id}/analyses",
            json={"provider": "openai_compatible", "model": "gpt-test"},
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["status"] == "queued"
        assert payload["skill_name"] == "gate2_challenger_main_analysis"
        assert enqueued == [payload["id"]]
        analysis = db_session.get(Analysis, UUID(payload["id"]))
        assert analysis.status == RunStatus.QUEUED.value
        assert analysis.run_parameters["skill_source_snapshot"]["name"] == "gate2_challenger_main_analysis"
    finally:
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
        run_parameters={"skill_source_snapshot": {"name": "devils_advocate_predefense"}},
    )
    db_session.add(predicted)
    db_session.commit()
    login(client, "author", "secret")

    response = client.get(f"/analyses/{analysis.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["predicted_comment_run"]["id"] == str(predicted.id)
    assert payload["predicted_comment_run"]["skill_name"] == "devils_advocate_predefense"
    assert payload["predicted_comment_run"]["structured_output"]["predicted_questions"] == ["What is incrementality?"]
    assert payload["predicted_comment_run"]["raw_output"] is None


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
