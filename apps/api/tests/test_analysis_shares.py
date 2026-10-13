from app.models.analysis import AnalysisCheckRun
from app.models.document_access import DocumentAccess
from app.schemas.enums import EntityStatus, Role, RunStatus
from app.services.ic_review import IC_REVIEW_CHECK_TYPE

from test_document_access import _case
from test_documents_upload import create_user, enqueued_parse_jobs, login, storage_root


def test_share_requires_owner_and_exposes_only_display_results(client, db_session, storage_root, enqueued_parse_jobs):
    owner = create_user(db_session, "owner", "secret")
    viewer = create_user(db_session, "viewer", "secret")
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    document, analysis = _case(client, db_session, owner)
    db_session.add(DocumentAccess(document_id=document.id, user_id=viewer.id, granted_by_id=admin.id))
    analysis.structured_output = {
        "assessment_markdown": "# Product conclusion\nDocument evidence.",
        "result": {"new_summary": {
            "version": 2, "generation_mode": "new_summary_skill",
            "ru": {"status": "completed", "payload": {
                "schema_version": "new-summary-v8", "language": "ru", "title": "Case - AI Summary",
                "stage": "Gate 2", "context": "Context", "required_elements": [],
                "private_diagnostic": "DO NOT SHARE SUMMARY DIAGNOSTICS",
                "traction_summary": {
                    "periods": ["2026", "Total"], "rows": [{"label": "Total Revenue", "values": ["1", "1"]}],
                    "total_revenue_provenance": {"method": "same_source_table", "source_block_id": "internal-block-42"},
                },
            }},
            "en": {"status": "completed", "payload": {
                "schema_version": "new-summary-v8", "language": "en", "title": "Case - AI Summary",
                "stage": "Gate 2", "context": "Context", "required_elements": [],
            }},
        }},
    }
    analysis.raw_output = "SECRET RAW MODEL OUTPUT"
    db_session.commit()

    client.post("/auth/logout")
    login(client, viewer.login, "secret")
    assert client.get(f"/analyses/{analysis.id}").status_code == 200
    assert client.post(f"/analyses/{analysis.id}/share").status_code == 404

    client.post("/auth/logout")
    login(client, owner.login, "secret")
    issued = client.post(f"/analyses/{analysis.id}/share")
    assert issued.status_code == 200
    assert issued.headers["cache-control"] == "no-store"
    token = issued.json()["token"]
    assert len(token) == 43
    assert client.post(f"/analyses/{analysis.id}/share").json()["token"] == token

    client.post("/auth/logout")
    path = f"/public/analyses/{analysis.id}"
    assert client.get(path).status_code == 404
    assert client.get(path, headers={"X-Analysis-Share-Token": "bad"}).status_code == 404
    response = client.get(path, headers={"X-Analysis-Share-Token": token})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    result = response.json()
    assert result["product_markdown"].startswith("# Product conclusion")
    assert result["summary_ru"]["context"] == "Context"
    assert result["summary_en"]["language"] == "en"
    assert "raw_output" not in result
    assert "run_parameters" not in result
    assert "SECRET RAW MODEL OUTPUT" not in response.text
    assert "DO NOT SHARE SUMMARY DIAGNOSTICS" not in response.text
    assert "internal-block-42" not in response.text
    assert result["summary_ru"]["traction_summary"]["rows"][0]["values"] == ["1", "1"]
    assert client.get(f"/analyses/{analysis.id}").status_code == 401
    assert client.get(f"/documents/{document.id}").status_code == 401

    login(client, owner.login, "secret")
    assert client.delete(f"/analyses/{analysis.id}/share").status_code == 204
    assert client.get(path, headers={"X-Analysis-Share-Token": token}).status_code == 404
    new_token = client.post(f"/analyses/{analysis.id}/share").json()["token"]
    assert new_token != token
    document.status = EntityStatus.DELETED.value
    db_session.commit()
    assert client.get(path, headers={"X-Analysis-Share-Token": new_token}).status_code == 404


def test_share_uses_latest_completed_ic_review_without_exposing_internal_output(client, db_session, storage_root, enqueued_parse_jobs):
    owner = create_user(db_session, "owner", "secret")
    document, analysis = _case(client, db_session, owner)
    check = AnalysisCheckRun(
        analysis_id=analysis.id, skill_id=analysis.skill_id, skill_version=analysis.skill_version,
        check_type=IC_REVIEW_CHECK_TYPE, provider="openai_compatible", model="test-model",
        status=RunStatus.COMPLETED.value,
        structured_output={
            "run_mode": "ic_agentic_review_compact", "executive_brief": "Financial conclusion",
            "top_findings": [], "key_numbers": [], "critical_risks": [], "data_gaps": [],
            "required_actions": [], "private_debug": "DO NOT SHARE",
        },
        raw_output="RAW IC MODEL OUTPUT", run_parameters={"secret": "hidden"},
    )
    db_session.add(check)
    db_session.commit()
    token = client.post(f"/analyses/{analysis.id}/share").json()["token"]
    client.post("/auth/logout")
    response = client.get(f"/public/analyses/{analysis.id}", headers={"X-Analysis-Share-Token": token})
    assert response.status_code == 200
    assert response.json()["financial"]["executive_brief"] == "Financial conclusion"
    assert "DO NOT SHARE" not in response.text
    assert "RAW IC MODEL OUTPUT" not in response.text


def test_deleting_analysis_invalidates_existing_share(client, db_session, storage_root, enqueued_parse_jobs):
    owner = create_user(db_session, "owner", "secret")
    document, analysis = _case(client, db_session, owner)
    token = client.post(f"/analyses/{analysis.id}/share").json()["token"]
    client.post("/auth/logout")
    analysis.deleted_at = analysis.created_at
    db_session.commit()
    assert client.get(f"/public/analyses/{analysis.id}", headers={"X-Analysis-Share-Token": token}).status_code == 404
