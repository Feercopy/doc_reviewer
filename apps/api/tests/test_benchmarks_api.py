import json
from uuid import UUID

from app.main import app
from app.models.benchmark import Benchmark
from app.models.document import Document
from app.models.etalon import Etalon
from app.routers import benchmarks as benchmarks_router
from app.schemas.enums import DocumentParseStatus, DocumentType, EtalonSource, EtalonStatus, Provider, Role, RunStatus
from app.seeds.skills import seed_baseline_skills

from test_documents_upload import create_user, login, upload_document
from test_etalons import _valid_etalon_payload


def test_admin_can_create_queued_benchmark_over_active_etalons(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    skills = seed_baseline_skills(db_session)
    active = _create_etalon(client, db_session, admin, EtalonStatus.ACTIVE)
    enqueued: list[str] = []
    app.dependency_overrides[benchmarks_router.get_run_benchmark_enqueue] = lambda: lambda benchmark_id: enqueued.append(str(benchmark_id))
    try:
        login(client, admin.login, "secret")
        response = client.post(
            "/benchmarks",
            json={
                "name": "Gate 2 baseline",
                "description": "Main skill over active etalons",
                "etalon_ids": [str(active.id)],
                "skill_id": str(skills[0].id),
                "provider": "openai_compatible",
                "model": "gpt-test",
                "judge_skill_id": str(skills[3].id),
                "evaluation_mode": "layer_1_and_layer_2",
                "run_parameters": {
                    "mock_provider_result": {
                        "structured_text": _main_analysis_json(),
                        "raw_output": "raw analysis",
                        "latency_ms": 1,
                    },
                    "judge_mock_provider_result": {
                        "structured_text": '{"layer_1":{"exact_matches":[],"partial_matches":[],"missed_findings":[],"false_positives":[]},"layer_2":{"exact_matches":[],"partial_matches":[],"missed_findings":[],"false_positives":[]},"summary":"No findings expected.","recommendations":[]}',
                        "raw_output": "raw judge",
                        "latency_ms": 1,
                    },
                },
            },
        )
    finally:
        app.dependency_overrides.pop(benchmarks_router.get_run_benchmark_enqueue, None)

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["etalon_ids"] == [str(active.id)]
    assert payload["skill_version"] == skills[0].version
    assert payload["judge_skill_id"] == str(skills[3].id)
    assert payload["run_parameters"]["skill_source_snapshot"]["name"] == "gate2_challenger_main_analysis"
    assert payload["run_parameters"]["judge_skill_source_snapshot"]["name"] == "benchmark_judge"
    snapshot = payload["run_parameters"]["etalon_snapshots"][str(active.id)]
    assert snapshot["document_id"] == str(active.document_id)
    assert snapshot["document_hash_sha256"]
    assert set(snapshot["expected_output"]) == {"verdict", "layer_1", "layer_2"}
    assert snapshot["expected_output"]["verdict"] == active.expected_verdict
    assert enqueued == [payload["id"]]

    benchmark = db_session.get(Benchmark, UUID(payload["id"]))
    assert benchmark.status == RunStatus.QUEUED.value


def test_benchmark_create_rejects_draft_etalons(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    skills = seed_baseline_skills(db_session)
    draft = _create_etalon(client, db_session, admin, EtalonStatus.DRAFT)
    login(client, admin.login, "secret")

    response = client.post(
        "/benchmarks",
        json={
            "name": "Draft benchmark",
            "description": "Should fail",
            "etalon_ids": [str(draft.id)],
            "skill_id": str(skills[0].id),
            "provider": "openai_compatible",
            "model": "gpt-test",
            "judge_skill_id": str(skills[3].id),
            "evaluation_mode": "layer_1_and_layer_2",
            "run_parameters": {"mock_provider_result": {"structured_text": "{}", "raw_output": "raw", "latency_ms": 1}},
        },
    )

    assert response.status_code == 409
    assert db_session.query(Benchmark).count() == 0


def test_benchmark_create_rejects_unparsed_etalon_original(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    skills = seed_baseline_skills(db_session)
    active = _create_etalon(client, db_session, admin, EtalonStatus.ACTIVE)
    document = db_session.get(Document, active.document_id)
    document.parse_status = DocumentParseStatus.QUEUED.value
    document.parsed_text = None
    db_session.commit()
    login(client, admin.login, "secret")

    response = client.post(
        "/benchmarks",
        json={
            "name": "Unparsed benchmark",
            "description": "Should fail",
            "etalon_ids": [str(active.id)],
            "skill_id": str(skills[0].id),
            "provider": "openai_compatible",
            "model": "gpt-test",
            "judge_skill_id": str(skills[3].id),
            "evaluation_mode": "layer_1_and_layer_2",
            "run_parameters": {"mock_provider_result": {"structured_text": "{}", "raw_output": "raw", "latency_ms": 1}},
        },
    )

    assert response.status_code == 409
    assert db_session.query(Benchmark).count() == 0


def test_non_admin_cannot_manage_benchmarks(client, db_session):
    create_user(db_session, "user", "secret")
    login(client, "user", "secret")

    response = client.get("/benchmarks")

    assert response.status_code == 403


def _main_analysis_json() -> str:
    return json.dumps(
        {
            "verdict": "need_evidence",
            "summary": "Needs evidence.",
            "assessment_markdown": "Оценка документа\nРекомендация: Needs evidence.",
            "findings": [],
            "checks": [],
            "layer_1_markdown": "Layer 1\nL1-001 — Weak traction.",
            "layer_1": [
                {
                    "id": "L1-001",
                    "severity": "critical",
                    "issue": "The document does not prove traction readiness.",
                    "evidence": "The mock document omits incrementality proof.",
                }
            ],
            "layer_2_markdown": "Layer 2\nL2-001 — No incrementality evidence.",
            "layer_2": [
                {
                    "id": "L2-001",
                    "parent_layer_1_id": "L1-001",
                    "status": "fail",
                    "severity": "high",
                    "question": "Is incrementality evidence separated from baseline effects?",
                    "answer": "NO",
                    "issue": "The metric uplift is not separated from baseline effects.",
                    "evidence": "No control group or holdout is shown.",
                }
            ],
        }
    )


def _create_etalon(client, db_session, user, status: EtalonStatus) -> Etalon:
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
