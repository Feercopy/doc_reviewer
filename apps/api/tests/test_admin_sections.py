from decimal import Decimal
from uuid import UUID

import pytest

from app.core.config import get_settings
from app.main import app
from app.models.analysis import Analysis
from app.models.audit_log import AuditLog
from app.models.benchmark import Benchmark
from app.models.document import Document
from app.models.etalon import Etalon
from app.models.feedback import Feedback
from app.schemas.enums import (
    DocumentParseStatus,
    DocumentType,
    EtalonSource,
    EtalonStatus,
    FeedbackUsefulness,
    Provider,
    Role,
    RunStatus,
)
from app.seeds.skills import seed_baseline_skills
from app.routers import documents as documents_router

from test_documents_upload import create_user, login, upload_document
from test_etalons import _valid_etalon_payload


@pytest.fixture(autouse=True)
def isolated_upload_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    app.dependency_overrides[documents_router.get_parse_document_enqueue] = lambda: lambda document_id: None
    yield
    app.dependency_overrides.pop(documents_router.get_parse_document_enqueue, None)
    get_settings.cache_clear()


def test_admin_documents_support_filters_and_include_owner_metadata(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    alice = create_user(db_session, "alice", "secret")
    bob = create_user(db_session, "bob", "secret")

    alice_document = _document_for_user(client, db_session, alice, "alice-gate.txt", DocumentType.GATE_2)
    _document_for_user(client, db_session, bob, "bob-stream.txt", DocumentType.STREAM_REVIEW_1)

    login(client, admin.login, "secret")
    response = client.get(f"/admin/documents?owner_id={alice.id}&document_type=gate_2")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["documents"]] == [str(alice_document.id)]
    assert payload["documents"][0]["owner_login"] == "alice"
    assert payload["documents"][0]["parsed_text_available"] is True

    forbidden = _as_user_get(client, db_session, "/admin/documents")
    assert forbidden.status_code == 403


def test_admin_documents_hide_deleted_documents(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    user = create_user(db_session, "analyst", "secret")
    document = _document_for_user(client, db_session, user, "gate.txt", DocumentType.GATE_2)

    login(client, admin.login, "secret")
    delete_response = client.delete(f"/documents/{document.id}")
    assert delete_response.status_code == 204

    response = client.get("/admin/documents")

    assert response.status_code == 200
    assert response.json()["documents"] == []


def test_admin_analyses_support_filters_and_expose_raw_output(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    user = create_user(db_session, "analyst", "secret")
    skills = seed_baseline_skills(db_session)
    document = _document_for_user(client, db_session, user, "gate.txt", DocumentType.GATE_2)
    _analysis(
        db_session,
        document=document,
        user_id=user.id,
        skill_id=skills[0].id,
        skill_version=skills[0].version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        raw_output="raw model output",
    )
    _analysis(
        db_session,
        document=document,
        user_id=user.id,
        skill_id=skills[0].id,
        skill_version=skills[0].version,
        provider=Provider.ANTHROPIC_COMPATIBLE.value,
        model="claude-test",
        status=RunStatus.FAILED.value,
        raw_output="failed raw",
    )

    login(client, admin.login, "secret")
    response = client.get("/admin/analyses?provider=openai_compatible&status=completed")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["analyses"]) == 1
    assert payload["analyses"][0]["provider"] == "openai_compatible"
    assert payload["analyses"][0]["raw_output"] == "raw model output"
    assert payload["analyses"][0]["document_title"] == "Investment Defense"
    assert payload["analyses"][0]["user_login"] == "analyst"


def test_admin_analyses_hide_deleted_runs(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    user = create_user(db_session, "analyst", "secret")
    skills = seed_baseline_skills(db_session)
    document = _document_for_user(client, db_session, user, "gate.txt", DocumentType.GATE_2)
    analysis = _analysis(
        db_session,
        document=document,
        user_id=user.id,
        skill_id=skills[0].id,
        skill_version=skills[0].version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
    )

    login(client, admin.login, "secret")
    delete_response = client.delete(f"/analyses/{analysis.id}")
    response = client.get("/admin/analyses")

    assert delete_response.status_code == 204
    assert response.status_code == 200
    assert response.json()["analyses"] == []


def test_admin_etalons_and_benchmarks_list_all_statuses(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    user = create_user(db_session, "analyst", "secret")
    skills = seed_baseline_skills(db_session)
    active = _etalon_for_user(client, db_session, user, EtalonStatus.ACTIVE)
    draft = _etalon_for_user(client, db_session, user, EtalonStatus.DRAFT)
    benchmark = Benchmark(
        name="Gate 2 baseline",
        description="Admin visible benchmark",
        etalon_ids=[str(active.id)],
        skill_id=skills[0].id,
        skill_version=skills[0].version,
        judge_skill_id=skills[3].id,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        started_by_id=admin.id,
        overall_score=Decimal("0.75"),
        layer_1_score=Decimal("0.80"),
        layer_2_score=Decimal("0.70"),
        precision=Decimal("0.60"),
        recall=Decimal("0.90"),
        f1=Decimal("0.72"),
        run_parameters={"evaluation_mode": "layer_1_and_layer_2"},
    )
    db_session.add(benchmark)
    db_session.commit()

    login(client, admin.login, "secret")
    etalons = client.get("/admin/etalons?status=draft")
    benchmarks = client.get("/admin/benchmarks?status=completed")

    assert etalons.status_code == 200
    assert [item["id"] for item in etalons.json()["etalons"]] == [str(draft.id)]
    assert etalons.json()["etalons"][0]["author_login"] == "analyst"
    assert benchmarks.status_code == 200
    assert [item["id"] for item in benchmarks.json()["benchmarks"]] == [str(benchmark.id)]
    assert benchmarks.json()["benchmarks"][0]["started_by_login"] == "admin"


def test_admin_can_delete_etalon_and_non_admin_cannot(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    user = create_user(db_session, "analyst", "secret")
    etalon = _etalon_for_user(client, db_session, user, EtalonStatus.ACTIVE)

    login(client, user.login, "secret")
    forbidden = client.delete(f"/admin/etalons/{etalon.id}")
    assert forbidden.status_code == 403
    client.post("/auth/logout")

    login(client, admin.login, "secret")
    deleted = client.delete(f"/admin/etalons/{etalon.id}")

    assert deleted.status_code == 204
    db_session.refresh(etalon)
    assert etalon.status == EtalonStatus.DELETED.value
    assert db_session.query(AuditLog).filter_by(action="etalon.deleted", entity_id=etalon.id).count() == 1

    normal_list = _as_user_get(client, db_session, "/etalons")
    assert normal_list.status_code == 200
    assert normal_list.json()["etalons"] == []

    login(client, admin.login, "secret")
    deleted_list = client.get("/admin/etalons?status=deleted")
    assert deleted_list.status_code == 200
    assert [item["id"] for item in deleted_list.json()["etalons"]] == [str(etalon.id)]


def test_admin_feedback_filters_by_model_skill_user_and_verdict(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    user = create_user(db_session, "analyst", "secret")
    skills = seed_baseline_skills(db_session)
    document = _document_for_user(client, db_session, user, "gate.txt", DocumentType.GATE_2)
    analysis = _analysis(
        db_session,
        document=document,
        user_id=user.id,
        skill_id=skills[0].id,
        skill_version=skills[0].version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
    )
    feedback = Feedback(
        user_id=user.id,
        document_id=document.id,
        analysis_id=analysis.id,
        provider=analysis.provider,
        model=analysis.model,
        skill_id=analysis.skill_id,
        skill_version=analysis.skill_version,
        usefulness=FeedbackUsefulness.PARTIALLY_USEFUL.value,
        verdict_correct=False,
        can_use_for_benchmark=True,
    )
    db_session.add(feedback)
    db_session.commit()

    login(client, admin.login, "secret")
    response = client.get(
        f"/admin/feedback?model=gpt-test&skill_id={skills[0].id}&user_id={user.id}&verdict=need_evidence"
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["feedback"]] == [str(feedback.id)]
    assert payload["feedback"][0]["user_login"] == "analyst"
    assert payload["feedback"][0]["analysis_verdict"] == "need_evidence"


def _as_user_get(client, db_session, path: str):
    client.post("/auth/logout")
    create_user(db_session, "normal", "secret")
    login(client, "normal", "secret")
    return client.get(path)


def _document_for_user(client, db_session, user, filename: str, document_type: DocumentType) -> Document:
    client.post("/auth/logout")
    login(client, user.login, "secret")
    response = upload_document(client, filename, b"Gate 2 MVP metrics")
    assert response.status_code == 201
    document = db_session.get(Document, UUID(response.json()["id"]))
    document.parse_status = DocumentParseStatus.COMPLETED.value
    document.parsed_text = "Parsed Gate 2 MVP metrics"
    document.detected_document_type = document_type.value
    db_session.commit()
    db_session.refresh(document)
    return document


def _analysis(
    db_session,
    *,
    document: Document,
    user_id,
    skill_id,
    skill_version: str,
    provider: str,
    model: str,
    status: str,
    raw_output: str = "raw",
    verdict: str | None = None,
) -> Analysis:
    analysis = Analysis(
        document_id=document.id,
        user_id=user_id,
        skill_id=skill_id,
        skill_version=skill_version,
        provider=provider,
        model=model,
        status=status,
        verdict=verdict,
        summary="Needs evidence",
        structured_output={"verdict": verdict or "need_evidence", "summary": "Needs evidence"},
        raw_output=raw_output,
        run_parameters={"temperature": 0},
    )
    db_session.add(analysis)
    db_session.commit()
    db_session.refresh(analysis)
    return analysis


def _etalon_for_user(client, db_session, user, status: EtalonStatus) -> Etalon:
    document = _document_for_user(client, db_session, user, f"{status.value}.txt", DocumentType.GATE_2)
    payload = _valid_etalon_payload()
    etalon = Etalon(
        document_id=document.id,
        author_id=user.id,
        source=EtalonSource.AI_POST_ANNOTATION.value,
        document_type=DocumentType.GATE_2.value,
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
