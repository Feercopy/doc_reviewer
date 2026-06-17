from uuid import UUID

from app.models.analysis import Analysis
from app.models.feedback import Feedback
from app.models.document import Document
from app.schemas.enums import DocumentParseStatus, DocumentType, FeedbackUsefulness, Provider, Role, RunStatus
from app.seeds.skills import seed_baseline_skills

from test_documents_upload import create_user, login, upload_document


def test_user_can_submit_feedback_for_accessible_analysis(client, db_session):
    user = create_user(db_session, "author", "secret")
    analysis = _create_completed_analysis(client, db_session, user)
    login(client, "author", "secret")

    response = client.post(
        f"/analyses/{analysis.id}/feedback",
        json={
            "usefulness": "useful",
            "verdict_correct": True,
            "has_false_findings": False,
            "has_missed_findings": True,
            "comment": "Missed one risk.",
            "can_use_for_benchmark": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["usefulness"] == "useful"
    assert db_session.query(Feedback).one().comment == "Missed one risk."


def test_user_cannot_submit_feedback_for_deleted_analysis(client, db_session):
    user = create_user(db_session, "author", "secret")
    analysis = _create_completed_analysis(client, db_session, user)
    login(client, "author", "secret")
    delete_response = client.delete(f"/analyses/{analysis.id}")

    response = client.post(
        f"/analyses/{analysis.id}/feedback",
        json={
            "usefulness": "useful",
            "verdict_correct": True,
            "has_false_findings": False,
            "has_missed_findings": False,
            "comment": "Should be hidden.",
            "can_use_for_benchmark": False,
        },
    )

    assert delete_response.status_code == 204
    assert response.status_code == 404
    assert db_session.query(Feedback).count() == 0


def test_admin_can_list_feedback_and_mark_processed(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    user = create_user(db_session, "author", "secret")
    analysis = _create_completed_analysis(client, db_session, user)
    feedback = Feedback(
        user_id=user.id,
        document_id=analysis.document_id,
        analysis_id=analysis.id,
        provider=analysis.provider,
        model=analysis.model,
        skill_id=analysis.skill_id,
        skill_version=analysis.skill_version,
        usefulness=FeedbackUsefulness.PARTIALLY_USEFUL.value,
        verdict_correct=False,
        has_false_findings=True,
        has_missed_findings=False,
        comment="Too broad.",
        can_use_for_benchmark=False,
    )
    db_session.add(feedback)
    db_session.commit()
    login(client, admin.login, "secret")

    listing = client.get("/admin/feedback")
    assert listing.status_code == 200
    assert listing.json()["feedback"][0]["comment"] == "Too broad."

    processed = client.patch(f"/admin/feedback/{feedback.id}/processed")
    assert processed.status_code == 200
    assert processed.json()["processed_at"] is not None


def _create_completed_analysis(client, db_session, user):
    from app.main import app
    from app.routers import documents as documents_router

    app.dependency_overrides[documents_router.get_parse_document_enqueue] = lambda: lambda document_id: None
    try:
        login(client, user.login, "secret")
        upload = upload_document(client, "gate.txt", b"Gate 2 MVP metrics")
        client.post("/auth/logout")
    finally:
        app.dependency_overrides.pop(documents_router.get_parse_document_enqueue, None)
    document = db_session.get(Document, UUID(upload.json()["id"]))
    document.parse_status = DocumentParseStatus.COMPLETED.value
    document.parsed_text = "Gate 2 MVP metrics"
    document.detected_document_type = DocumentType.GATE_2.value
    skill = seed_baseline_skills(db_session)[0]
    analysis = Analysis(
        document_id=document.id,
        user_id=user.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Needs evidence",
        structured_output={"verdict": "need_evidence", "summary": "Needs evidence", "findings": [], "checks": []},
        raw_output="raw",
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.commit()
    db_session.refresh(analysis)
    return analysis
