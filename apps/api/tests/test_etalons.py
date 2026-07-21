from uuid import UUID

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.main import app
from app.models.analysis import Analysis
from app.models.document import Document
from app.models.etalon import Etalon
from app.routers import etalons as etalons_router
from app.schemas.enums import DocumentParseStatus, DocumentType, EtalonSource, EtalonStatus, Provider, Role, RunStatus
from app.schemas.etalons import EtalonPayload
from app.seeds.skills import seed_baseline_skills

from test_documents_upload import create_user, login, upload_document


@pytest.fixture()
def storage_root(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture()
def enqueued_parse_jobs():
    enqueued: list[str] = []
    app.dependency_overrides[etalons_router.get_parse_document_enqueue] = lambda: lambda document_id: enqueued.append(str(document_id))
    yield enqueued
    app.dependency_overrides.pop(etalons_router.get_parse_document_enqueue, None)


def test_etalon_payload_validates_layer_parent_links():
    payload = _valid_etalon_payload()

    etalon_payload = EtalonPayload.model_validate(payload)

    assert etalon_payload.expected_verdict == "need_evidence"
    assert etalon_payload.layer_2[0].parent_layer_1_id == "L1-001"


def test_etalon_payload_rejects_orphan_layer_2_parent():
    payload = _valid_etalon_payload()
    payload["layer_2"][0]["parent_layer_1_id"] = "L1-missing"

    with pytest.raises(ValidationError, match="parent_layer_1_id"):
        EtalonPayload.model_validate(payload)


def test_etalon_payload_rejects_invalid_severity():
    payload = _valid_etalon_payload()
    payload["layer_1"][0]["severity"] = "urgent"

    with pytest.raises(ValidationError):
        EtalonPayload.model_validate(payload)


def test_etalon_payload_requires_expected_verdict():
    payload = _valid_etalon_payload()
    payload.pop("expected_verdict")

    with pytest.raises(ValidationError):
        EtalonPayload.model_validate(payload)


def test_user_can_create_etalon_draft_from_own_completed_analysis(client, db_session):
    user = create_user(db_session, "author", "secret")
    analysis = _create_completed_analysis(client, db_session, user)
    login(client, "author", "secret")

    response = client.post(f"/analyses/{analysis.id}/etalon-draft")

    assert response.status_code == 201
    payload = response.json()
    assert payload["document_id"] == str(analysis.document_id)
    assert payload["author_id"] == str(user.id)
    assert payload["source"] == "ai_post_annotation"
    assert payload["status"] == "draft"
    assert payload["expected_verdict"] == "need_evidence"
    assert payload["layer_1"][0]["id"] == "L1-001"
    assert payload["layer_2"][0]["parent_layer_1_id"] == "L1-001"
    assert payload["key_findings"] == ["Missing incrementality"]

    etalon = db_session.query(Etalon).one()
    assert etalon.document_id == analysis.document_id
    assert etalon.author_id == user.id
    assert etalon.status == EtalonStatus.DRAFT.value


def test_create_etalon_draft_maps_gate_challenger_layers(client, db_session):
    user = create_user(db_session, "author", "secret")
    analysis = _create_completed_analysis(client, db_session, user)
    analysis.structured_output = {
        "verdict": "need_evidence",
        "summary": "Needs stronger metric evidence.",
        "assessment_markdown": "Оценка документа\nРекомендация: strengthen metric evidence before approval.",
        "findings": [],
        "checks": [],
        "layer_1_markdown": "Layer 1\nL1-001 - Metric proof is incomplete.",
        "layer_1": [
            {
                "id": "L1-001",
                "severity": "high",
                "issue": "The document claims traction without a control-group readout.",
                "evidence": "The document names traction but does not provide a cohort readout.",
            }
        ],
        "layer_2_markdown": "Layer 2\nL2-001 - Incrementality evidence is missing.",
        "layer_2": [
            {
                "id": "L2-001",
                "parent_layer_1_id": "L1-001",
                "status": "fail",
                "severity": "high",
                "question": "Is incrementality evidence tied to a holdout?",
                "answer": "NO",
                "issue": "The claimed metric lift is not tied to a holdout.",
                "evidence": "No cohort, control group, or before-after guardrail is provided.",
            }
        ],
        "key_findings": ["Metric proof is incomplete"],
    }
    db_session.commit()
    login(client, "author", "secret")

    response = client.post(f"/analyses/{analysis.id}/etalon-draft")

    assert response.status_code == 201
    payload = response.json()
    assert payload["layer_1"][0]["dimension"] == "Analysis finding"
    assert payload["layer_1"][0]["status"] == "fail"
    assert payload["layer_1"][0]["summary"] == "The document claims traction without a control-group readout."
    assert payload["layer_1"][0]["evidence"][0]["quote"] == "The document names traction but does not provide a cohort readout."
    assert payload["layer_2"][0]["check"] == "Is incrementality evidence tied to a holdout?"
    assert payload["layer_2"][0]["finding"] == "The claimed metric lift is not tied to a holdout."
    assert payload["layer_2"][0]["expected_fix"] == ""


def test_user_cannot_create_etalon_draft_from_another_users_analysis(client, db_session):
    owner = create_user(db_session, "owner", "secret")
    create_user(db_session, "other", "secret")
    analysis = _create_completed_analysis(client, db_session, owner)
    login(client, "other", "secret")

    response = client.post(f"/analyses/{analysis.id}/etalon-draft")

    assert response.status_code == 404
    assert db_session.query(Etalon).count() == 0


def test_admin_can_create_active_etalon_from_analysis(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    analysis = _create_completed_analysis(client, db_session, admin)
    login(client, "admin", "secret")

    response = client.post(f"/analyses/{analysis.id}/etalon-draft", json={"status": "active"})

    assert response.status_code == 201
    assert response.json()["status"] == "active"
    assert db_session.query(Etalon).one().status == EtalonStatus.ACTIVE.value


def test_normal_user_cannot_create_active_etalon_from_analysis(client, db_session):
    user = create_user(db_session, "author", "secret")
    analysis = _create_completed_analysis(client, db_session, user)
    login(client, "author", "secret")

    response = client.post(f"/analyses/{analysis.id}/etalon-draft", json={"status": "active"})

    assert response.status_code == 403
    assert db_session.query(Etalon).count() == 0


def test_etalon_list_shows_active_etalons_and_own_drafts(client, db_session):
    alice = create_user(db_session, "alice", "secret")
    bob = create_user(db_session, "bob", "secret")
    active = _create_etalon(client, db_session, alice, EtalonStatus.ACTIVE)
    alice_draft = _create_etalon(client, db_session, alice, EtalonStatus.DRAFT)
    bob_draft = _create_etalon(client, db_session, bob, EtalonStatus.DRAFT)

    login(client, "bob", "secret")
    bob_response = client.get("/etalons")

    assert bob_response.status_code == 200
    assert {item["id"] for item in bob_response.json()["etalons"]} == {str(active.id), str(bob_draft.id)}

    client.post("/auth/logout")
    login(client, "alice", "secret")
    alice_response = client.get("/etalons")

    assert alice_response.status_code == 200
    assert {item["id"] for item in alice_response.json()["etalons"]} == {str(active.id), str(alice_draft.id)}


def test_etalon_detail_respects_visibility(client, db_session):
    alice = create_user(db_session, "alice", "secret")
    create_user(db_session, "bob", "secret")
    draft = _create_etalon(client, db_session, alice, EtalonStatus.DRAFT)
    active = _create_etalon(client, db_session, alice, EtalonStatus.ACTIVE)

    login(client, "bob", "secret")

    forbidden = client.get(f"/etalons/{draft.id}")
    visible = client.get(f"/etalons/{active.id}")

    assert forbidden.status_code == 404
    assert visible.status_code == 200
    assert visible.json()["id"] == str(active.id)


def test_author_can_patch_own_draft_and_version_increments(client, db_session):
    author = create_user(db_session, "author", "secret")
    etalon = _create_etalon(client, db_session, author, EtalonStatus.DRAFT)
    update_payload = _valid_etalon_payload()
    update_payload["expected_verdict"] = "reject"
    update_payload["defense_comments"] = "Real committee rejected this defense."
    update_payload["key_findings"] = ["No incrementality", "No scale proof"]
    login(client, "author", "secret")

    response = client.patch(f"/etalons/{etalon.id}", json=update_payload)

    assert response.status_code == 200
    payload = response.json()
    assert payload["expected_verdict"] == "reject"
    assert payload["defense_comments"] == "Real committee rejected this defense."
    assert payload["key_findings"] == ["No incrementality", "No scale proof"]
    assert payload["version"] == 2


def test_normal_user_cannot_patch_active_etalon(client, db_session):
    author = create_user(db_session, "author", "secret")
    etalon = _create_etalon(client, db_session, author, EtalonStatus.ACTIVE)
    update_payload = _valid_etalon_payload()
    update_payload["expected_verdict"] = "reject"
    login(client, "author", "secret")

    response = client.patch(f"/etalons/{etalon.id}", json=update_payload)

    assert response.status_code == 403


def test_patch_rejects_invalid_layer_parent_before_write(client, db_session):
    author = create_user(db_session, "author", "secret")
    etalon = _create_etalon(client, db_session, author, EtalonStatus.DRAFT)
    update_payload = _valid_etalon_payload()
    update_payload["layer_2"][0]["parent_layer_1_id"] = "L1-missing"
    login(client, "author", "secret")

    response = client.patch(f"/etalons/{etalon.id}", json=update_payload)

    assert response.status_code == 409
    db_session.refresh(etalon)
    assert etalon.version == 1
    assert etalon.layer_2[0]["parent_layer_1_id"] == "L1-001"


def test_admin_can_publish_draft_and_normal_user_cannot(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    author = create_user(db_session, "author", "secret")
    draft = _create_etalon(client, db_session, author, EtalonStatus.DRAFT)
    login(client, "author", "secret")

    forbidden = client.post(f"/etalons/{draft.id}/publish")
    assert forbidden.status_code == 403
    client.post("/auth/logout")

    login(client, admin.login, "secret")
    response = client.post(f"/etalons/{draft.id}/publish")

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert db_session.get(Etalon, draft.id).status == EtalonStatus.ACTIVE.value


def test_admin_can_archive_etalon_and_remove_it_from_normal_list(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    author = create_user(db_session, "author", "secret")
    active = _create_etalon(client, db_session, author, EtalonStatus.ACTIVE)
    login(client, admin.login, "secret")

    archive = client.post(f"/etalons/{active.id}/archive")
    assert archive.status_code == 200
    assert archive.json()["status"] == "archived"
    client.post("/auth/logout")

    login(client, "author", "secret")
    listing = client.get("/etalons")

    assert listing.status_code == 200
    assert listing.json()["etalons"] == []


def test_annotation_queue_requires_admin_or_annotator(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    annotator = create_user(db_session, "annotator", "secret", Role.ANNOTATOR)
    author = create_user(db_session, "author", "secret")
    draft = _create_etalon(client, db_session, author, EtalonStatus.DRAFT)
    _create_etalon(client, db_session, author, EtalonStatus.ACTIVE)

    login(client, "author", "secret")
    forbidden = client.get("/annotation/queue")
    assert forbidden.status_code == 403
    client.post("/auth/logout")

    login(client, annotator.login, "secret")
    annotator_queue = client.get("/annotation/queue")
    assert annotator_queue.status_code == 200
    assert [item["id"] for item in annotator_queue.json()["etalons"]] == [str(draft.id)]
    client.post("/auth/logout")

    login(client, admin.login, "secret")
    admin_queue = client.get("/annotation/queue")
    assert admin_queue.status_code == 200
    assert [item["id"] for item in admin_queue.json()["etalons"]] == [str(draft.id)]


def test_past_defense_import_creates_document_and_draft_etalon(client, db_session, storage_root, enqueued_parse_jobs):
    user = create_user(db_session, "author", "secret")
    login(client, user.login, "secret")

    response = client.post(
        "/documents/past-defense",
        data={
            "title": "Past Gate 2 Defense",
            "document_type": "gate_2",
            "expected_verdict": "reject",
            "real_defense_status": "rejected",
            "defense_date": "2026-05-12",
            "defense_comments": "Committee rejected the scaling argument.",
            "notes": "Use as hard benchmark case.",
            "raw_file_visible_to_all": "true",
        },
        files={"file": ("past-defense.txt", b"Past defense document", "text/plain")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source"] == "imported_defense"
    assert payload["status"] == "draft"
    assert payload["expected_verdict"] == "reject"
    assert payload["document_type"] == "gate_2"
    assert payload["real_defense_status"] == "rejected"
    assert payload["raw_file_visible_to_all"] is True
    assert "2026-05-12" in payload["defense_comments"]
    assert "Committee rejected the scaling argument." in payload["defense_comments"]
    assert "Use as hard benchmark case." in payload["defense_comments"]

    etalon = db_session.query(Etalon).one()
    document = db_session.get(Document, etalon.document_id)
    assert document.title == "Past Gate 2 Defense"
    assert document.parse_status == DocumentParseStatus.QUEUED.value
    assert document.manual_document_type == DocumentType.GATE_2.value
    assert enqueued_parse_jobs == [str(document.id)]


def _valid_etalon_payload():
    return {
        "expected_verdict": "need_evidence",
        "layer_1": [
            {
                "id": "L1-001",
                "dimension": "Traction credibility",
                "status": "fail",
                "severity": "high",
                "title": "Traction does not prove scaling",
                "summary": "Pilot results are extrapolated without scaling evidence.",
                "evidence": [{"quote": "pilot grew 10%", "location": "page 5"}],
                "recommendation": "Add cohort and incrementality analysis.",
                "confidence": 0.8,
            }
        ],
        "layer_2": [
            {
                "id": "L2-001",
                "parent_layer_1_id": "L1-001",
                "check": "Is there evidence of incrementality?",
                "status": "partial",
                "severity": "medium",
                "finding": "Incrementality is claimed but not measured.",
                "evidence": [{"quote": "impact was positive", "location": "page 8"}],
                "expected_fix": "Show control group and significance.",
                "confidence": 0.76,
            }
        ],
        "key_findings": ["Missing incrementality"],
    }


def _create_etalon(client, db_session, user, status: EtalonStatus) -> Etalon:
    analysis = _create_completed_analysis(client, db_session, user)
    payload = _valid_etalon_payload()
    document = db_session.get(Document, analysis.document_id)
    etalon = Etalon(
        document_id=document.id,
        author_id=user.id,
        source=EtalonSource.AI_POST_ANNOTATION.value,
        document_type=DocumentType.GATE_2.value,
        real_defense_status=None,
        defense_comments=None,
        expected_verdict=payload["expected_verdict"],
        layer_1=payload["layer_1"],
        layer_2=payload["layer_2"],
        key_findings=payload["key_findings"],
        forbidden_false_findings=[],
        status=status.value,
        version=1,
        raw_file_visible_to_all=False,
    )
    db_session.add(etalon)
    db_session.commit()
    db_session.refresh(etalon)
    return etalon


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
        structured_output={
            "verdict": "need_evidence",
            "summary": "Needs evidence",
            "layer_1": [
                {
                    "id": "L1-001",
                    "dimension": "Traction credibility",
                    "status": "fail",
                    "severity": "high",
                    "title": "Traction does not prove scaling",
                    "summary": "Pilot results are extrapolated without scaling evidence.",
                    "evidence": [{"quote": "pilot grew 10%", "location": "page 5"}],
                    "recommendation": "Add cohort and incrementality analysis.",
                    "confidence": 0.8,
                }
            ],
            "layer_2": [
                {
                    "id": "L2-001",
                    "parent_layer_1_id": "L1-001",
                    "check": "Is there evidence of incrementality?",
                    "status": "partial",
                    "severity": "medium",
                    "finding": "Incrementality is claimed but not measured.",
                    "evidence": [{"quote": "impact was positive", "location": "page 8"}],
                    "expected_fix": "Show control group and significance.",
                    "confidence": 0.76,
                }
            ],
            "key_findings": ["Missing incrementality"],
            "findings": [],
            "checks": [],
        },
        raw_output="raw",
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.commit()
    db_session.refresh(analysis)
    return analysis
