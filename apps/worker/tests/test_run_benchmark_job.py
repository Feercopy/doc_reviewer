import json
from io import BytesIO
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.benchmark import Benchmark
from app.models.document import Document
from app.models.etalon import Etalon
from app.models.skill import Skill
from app.models.user import User
from app.schemas.enums import (
    DocumentParseStatus,
    DocumentType,
    EntityStatus,
    EtalonSource,
    EtalonStatus,
    Provider,
    Role,
    RunStatus,
    SkillSourceType,
    SkillType,
    UserStatus,
)
from app.security.passwords import hash_password
from app.storage.local import LocalDocumentStorage
from jobs.run_benchmark import _aggregate_results, run_benchmark


def test_run_benchmark_persists_scores_judge_output_and_report(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        etalon = _create_etalon(db, document, user)
        main_skill = _create_skill(db, SkillType.MAIN_ANALYSIS)
        judge_skill = _create_skill(db, SkillType.BENCHMARK_JUDGE)
        benchmark = Benchmark(
            name="Gate 2 baseline",
            description="Benchmark",
            etalon_ids=[str(etalon.id)],
            skill_id=main_skill.id,
            skill_version=main_skill.version,
            judge_skill_id=judge_skill.id,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            started_by_id=user.id,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": _main_analysis_json_with_benchmark_ids(),
                    "raw_output": "raw analysis",
                    "latency_ms": 10,
                },
                "judge_mock_provider_result": {
                    "structured_text": _judge_v2_json(),
                    "raw_output": "raw judge",
                    "latency_ms": 5,
                },
                "etalon_snapshots": {
                    str(etalon.id): {
                        "expected_output": {
                            "verdict": "need_evidence",
                            "layer_1": [{"id": "SNAP-L1", "issue": "Snapshot Layer 1 issue."}],
                            "layer_2": [
                                {
                                    "id": "SNAP-L2",
                                    "parent_layer_1_id": "SNAP-L1",
                                    "status": "fail",
                                    "issue": "Snapshot Layer 2 issue.",
                                }
                            ],
                        }
                    }
                },
            },
        )
        db.add(benchmark)
        db.commit()

        run_benchmark(str(benchmark.id), db=db)

        db.refresh(benchmark)
        assert benchmark.status == RunStatus.COMPLETED.value, benchmark.error_message
        assert float(benchmark.layer_1_score) == 1
        assert float(benchmark.layer_2_score) == 0.5
        assert float(benchmark.f1) == 0.75
        assert benchmark.partial_matches[0]["ref_id"] == "L2-001"
        document_result = benchmark.judge_output["documents"][0]
        assert document_result["etalon_id"] == str(etalon.id)
        assert set(document_result["expected_output"]) == {"verdict", "layer_1", "layer_2"}
        assert document_result["expected_output"]["layer_1"][0]["id"] == "SNAP-L1"
        assert set(document_result["actual_output"]) == {"verdict", "layer_1", "layer_2"}
        assert "layer_3" not in document_result["actual_output"]
        assert "summary" not in document_result["actual_output"]
        assert benchmark.report["overall"]["f1"] == 0.75
    finally:
        _close_session(db)


def test_aggregate_results_uses_v2_micro_average_across_documents():
    aggregate = _aggregate_results(
        [
            _completed_document_result(score_sum=1.0, n_ref=1, n_pred=1),
            _completed_document_result(score_sum=1.0, n_ref=3, n_pred=3),
        ]
    )

    assert aggregate["precision"] == 0.5
    assert aggregate["recall"] == 0.5
    assert aggregate["f1"] == 0.5
    assert aggregate["layer_1"]["f1"] == 0.5


def _completed_document_result(*, score_sum: float, n_ref: int, n_pred: int) -> dict:
    precision = score_sum / n_pred if n_pred else 0
    recall = score_sum / n_ref if n_ref else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    return {
        "status": "completed",
        "scores": {
            "layer_1": {
                "score_sum": score_sum,
                "n_ref": n_ref,
                "n_pred": n_pred,
                "f1": f1,
            },
            "layer_2": {
                "score_sum": 0,
                "n_ref": 0,
                "n_pred": 0,
                "f1": 0,
            },
            "score_sum_total": score_sum,
            "n_ref_total": n_ref,
            "n_pred_total": n_pred,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
        "judge_output": {
            "layer_1": {"matched": [], "missed_issues": [], "false_positives": []},
            "layer_2": {"matched": [], "missed_issues": [], "false_positives": []},
        },
    }


def _main_analysis_json_with_benchmark_ids() -> str:
    return json.dumps(
        {
            "verdict": "need_evidence",
            "summary": "Needs evidence.",
            "assessment_markdown": "Оценка документа\nРекомендация: Needs evidence.",
            "findings": [],
            "checks": [],
            "layer_1_markdown": "Layer 1\nA1 — Weak traction.",
            "layer_1": [
                {
                    "id": "A1",
                    "severity": "critical",
                    "issue": "The document does not prove traction readiness.",
                    "evidence": "The mock document omits incrementality proof.",
                }
            ],
            "layer_2_markdown": "Layer 2\nA2 — No incrementality evidence.",
            "layer_2": [
                {
                    "id": "A2",
                    "parent_layer_1_id": "A1",
                    "status": "fail",
                    "severity": "high",
                    "question": "Is incrementality evidence separated from baseline effects?",
                    "answer": "NO",
                    "issue": "The metric uplift is not separated from baseline effects.",
                    "evidence": "No control group or holdout is shown.",
                }
            ],
            "layer_3": [{"id": "A3", "risk": "Should not be benchmarked."}],
        }
    )


def _judge_v2_json() -> str:
    return json.dumps(
        {
            "layer_1": {
                "n_ref": 1,
                "n_pred": 1,
                "score_sum": 1.0,
                "precision": 100.0,
                "recall": 100.0,
                "f1": 100.0,
                "matched": [
                    {
                        "ref_id": "L1-001",
                        "block": "traction",
                        "expected": "Weak traction",
                        "actual": "The document does not prove traction readiness.",
                        "score": 1.0,
                        "comment": "Same core blocker.",
                    }
                ],
                "missed_issues": [],
                "false_positives": [],
                "duplicates": [],
                "summary": "Layer 1 matched.",
            },
            "layer_2": {
                "n_ref": 1,
                "n_pred": 1,
                "score_sum": 0.5,
                "precision": 50.0,
                "recall": 50.0,
                "f1": 50.0,
                "matched": [
                    {
                        "ref_id": "L2-001",
                        "block": "metrics",
                        "expected": "No incrementality",
                        "actual": "The metric uplift is not separated from baseline effects.",
                        "score": 0.5,
                        "comment": "Same theme but incomplete.",
                    }
                ],
                "missed_issues": [],
                "false_positives": [],
                "duplicates": [],
                "summary": "Layer 2 partially matched.",
            },
            "overall": {
                "n_ref_total": 2,
                "n_pred_total": 2,
                "score_sum_total": 1.5,
                "precision": 75.0,
                "recall": 75.0,
                "f1": 75.0,
            },
            "diagnostics": {
                "valid_extra_insights_count": 0,
                "unsupported_or_wrong_false_positives_count": 0,
                "duplicate_count": 0,
                "main_reasons": ["Layer 2 is incomplete."],
                "strengths": ["Layer 1 matched."],
            },
            "recommendations": ["Tighten Layer 2 evidence."],
        }
    )


def _create_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    session._test_engine = engine  # type: ignore[attr-defined]
    return session


def _close_session(session: Session) -> None:
    engine = session._test_engine  # type: ignore[attr-defined]
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _create_user(db: Session) -> User:
    user = User(
        login=f"user-{uuid4()}",
        display_name="User",
        password_hash=hash_password("secret"),
        role=Role.ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_document(db: Session, tmp_path, user: User) -> Document:
    storage = LocalDocumentStorage(tmp_path)
    document_id = uuid4()
    stored = storage.save_raw_file(
        owner_id=user.id,
        document_id=document_id,
        original_filename="gate.txt",
        source=BytesIO(b"Gate 2 MVP metrics"),
        max_size_bytes=1024,
    )
    document = Document(
        id=document_id,
        owner_id=user.id,
        title="Gate 2",
        original_filename="gate.txt",
        mime_type="text/plain",
        file_size_bytes=stored.size_bytes,
        file_hash_sha256=stored.sha256,
        storage_path=str(stored.path),
        parse_status=DocumentParseStatus.COMPLETED.value,
        detected_document_type=DocumentType.GATE_2.value,
        parsed_text="Gate 2 MVP metrics traction risks",
        status=EntityStatus.ACTIVE.value,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _create_etalon(db: Session, document: Document, user: User) -> Etalon:
    etalon = Etalon(
        document_id=document.id,
        author_id=user.id,
        source=EtalonSource.AI_POST_ANNOTATION.value,
        document_type=DocumentType.GATE_2.value,
        expected_verdict="need_evidence",
        layer_1=[{"id": "L1-001", "title": "Weak traction"}],
        layer_2=[{"id": "L2-001", "parent_layer_1_id": "L1-001", "status": "fail", "finding": "No incrementality"}],
        key_findings=["Weak traction"],
        forbidden_false_findings=[],
        status=EtalonStatus.ACTIVE.value,
        version=1,
        raw_file_visible_to_all=False,
    )
    db.add(etalon)
    db.commit()
    db.refresh(etalon)
    return etalon


def _create_skill(db: Session, skill_type: SkillType) -> Skill:
    name = "gate2_challenger_main_analysis" if skill_type == SkillType.MAIN_ANALYSIS else "benchmark_judge"
    skill = Skill(
        name=name,
        description=name,
        version="baseline",
        skill_type=skill_type.value,
        supported_document_types=[DocumentType.GATE_2.value],
        source_type=SkillSourceType.INLINE_PROMPT.value,
        source_uri=None,
        source_entrypoint=None,
        source_revision=None,
        source_fingerprint=None,
        source_metadata={},
        prompt_text="Prompt",
        result_schema_path=(
            "contracts/schemas/main-analysis-result.schema.json"
            if skill_type == SkillType.MAIN_ANALYSIS
            else "contracts/schemas/benchmark-judge-result.schema.json"
        ),
        status=EntityStatus.ACTIVE.value,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill
