from uuid import UUID

from app.models.analysis import Analysis
from app.models.document_access import DocumentAccess
from app.schemas.enums import DocumentParseStatus, DocumentType, Role, RunStatus
from app.seeds.skills import seed_baseline_skills

from test_documents_upload import create_user, enqueued_parse_jobs, login, storage_root, upload_document


def _case(client, db_session, owner):
    login(client, owner.login, "secret")
    response = upload_document(client, "case.txt", b"Gate 2 MVP metrics")
    assert response.status_code == 201
    document_id = UUID(response.json()["id"])
    from app.models.document import Document

    document = db_session.get(Document, document_id)
    document.parse_status = DocumentParseStatus.COMPLETED.value
    document.parsed_text = "Gate 2 MVP metrics"
    document.detected_document_type = DocumentType.GATE_2.value
    skill = seed_baseline_skills(db_session)[0]
    analysis = Analysis(
        document_id=document.id,
        user_id=owner.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider="openai_compatible",
        model="test-model",
        status=RunStatus.COMPLETED.value,
        summary="Completed",
        structured_output={"result": {"summary": "Completed"}},
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.commit()
    return document, analysis


def test_admin_grant_shows_only_selected_case_and_keeps_mutations_owner_only(client, db_session, storage_root, enqueued_parse_jobs):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    owner = create_user(db_session, "owner", "secret")
    viewer = create_user(db_session, "viewer", "secret")
    unrelated_owner = create_user(db_session, "other", "secret")
    document, analysis = _case(client, db_session, owner)
    client.post("/auth/logout")
    unrelated, unrelated_analysis = _case(client, db_session, unrelated_owner)

    client.post("/auth/logout")
    login(client, admin.login, "secret")
    payload = {"items": [{"analysis_id": str(analysis.id), "logins": [viewer.login]}]}
    result = client.post("/admin/documents/access/batch", json=payload)
    assert result.status_code == 200
    assert result.json()["grants_created"] == 1
    assert client.post("/admin/documents/access/batch", json=payload).json()["grants_existing"] == 1

    client.post("/auth/logout")
    login(client, viewer.login, "secret")
    documents = client.get("/documents").json()["documents"]
    assert [item["id"] for item in documents] == [str(document.id)]
    assert client.get(f"/documents/{document.id}").status_code == 200
    assert client.get(f"/analyses/{analysis.id}").status_code == 200
    assert client.get(f"/analyses/{analysis.id}/status").status_code == 200
    assert client.get(f"/documents/{document.id}/analyses/statuses").status_code == 200
    assert client.get(f"/analyses/{analysis.id}/new-summary").status_code == 200
    assert client.get(f"/documents/{unrelated.id}").status_code == 404
    assert client.get(f"/analyses/{unrelated_analysis.id}").status_code == 404
    assert client.delete(f"/documents/{document.id}").status_code == 404
    assert client.delete(f"/analyses/{analysis.id}").status_code == 404
    assert client.patch(f"/documents/{document.id}/title", json={"title": "Changed"}).status_code == 404
    assert client.post(f"/documents/{document.id}/reparse").status_code == 404
    assert client.post(
        f"/documents/{document.id}/analyses",
        json={"provider": "openai_compatible", "model": "test-model"},
    ).status_code == 404
    assert client.post(
        f"/analyses/{analysis.id}/ic-review-runs",
        data={"provider": "openai_compatible", "model": "test-model"},
    ).status_code == 404
    assert client.post(f"/analyses/{analysis.id}/details").status_code == 404
    assert client.post(f"/analyses/{analysis.id}/cancel").status_code == 404
    assert client.post(f"/analyses/{analysis.id}/new-summary").status_code == 404
    assert client.post(f"/analyses/{analysis.id}/summary-localizations").status_code == 404


def test_grant_batch_is_atomic_when_a_login_is_unknown(client, db_session, storage_root, enqueued_parse_jobs):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    owner = create_user(db_session, "owner", "secret")
    viewer = create_user(db_session, "viewer", "secret")
    document, analysis = _case(client, db_session, owner)
    client.post("/auth/logout")
    login(client, admin.login, "secret")
    result = client.post(
        "/admin/documents/access/batch",
        json={"items": [{"analysis_id": str(analysis.id), "logins": [viewer.login, "missing"]}]},
    )
    assert result.status_code == 422
    assert db_session.get(DocumentAccess, (document.id, viewer.id)) is None
