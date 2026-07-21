import json
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.core.config import get_settings
from app.models.analysis import Analysis, PredictedCommentRun
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.models.skill import Skill
from app.models.skill_source import RetrievalSnapshot, SkillSource, SkillSourceSnapshot
from app.models.user import User
from app.schemas.enums import (
    DocumentParseStatus,
    DocumentType,
    EntityStatus,
    Provider,
    Role,
    RunStatus,
    SkillSourceType,
    SkillType,
    UserStatus,
)
from app.security.passwords import hash_password
from app.security.secrets import encrypt_secret
from jobs.run_analysis import run_analysis
from jobs.run_predicted_comments import run_predicted_comments


def test_run_analysis_runs_predicted_comments_before_gate_after_success(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, user)
        main_skill = _create_main_skill(db)
        predicted_skill = _create_predicted_skill(db, tmp_path)
        _create_provider_key(db, user)
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=main_skill.id,
            skill_version=main_skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": _main_analysis_json("Needs stronger evidence."),
                    "raw_output": "raw main",
                    "latency_ms": 10,
                },
                "predicted_comments_mock_provider_result": {
                    "structured_text": _devils_advocate_json(),
                    "raw_output": "raw predicted",
                    "latency_ms": 20,
                },
            },
        )
        db.add(analysis)
        db.commit()
        enqueued: list[str] = []

        run_analysis(str(analysis.id), db=db, enqueue_predicted_comments=lambda run_id: enqueued.append(str(run_id)))

        db.refresh(analysis)
        predicted_run = db.execute(select(PredictedCommentRun)).scalar_one()
        assert analysis.status == RunStatus.COMPLETED.value
        assert predicted_run.status == RunStatus.COMPLETED.value
        assert predicted_run.skill_id == predicted_skill.id
        assert predicted_run.provider == analysis.provider
        assert predicted_run.model == analysis.model
        assert predicted_run.run_parameters["main_analysis_id"] == str(analysis.id)
        assert predicted_run.run_parameters["skill_source_snapshot"]["name"] == "devils_advocate_predefense"
        assert predicted_run.run_parameters["mock_provider_result"]["raw_output"] == "raw predicted"
        assert predicted_run.run_parameters["run_order"] == "before_gate_challenger"
        assert analysis.run_parameters["gate_challenger_layer_4_context"]["predicted_comment_run_id"] == str(predicted_run.id)
        assert enqueued == []
    finally:
        _close_session(db)


def test_run_predicted_comments_skips_cancelled_run(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, user)
        main_skill = _create_main_skill(db)
        predicted_skill = _create_predicted_skill(db, tmp_path)
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=main_skill.id,
            skill_version=main_skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.COMPLETED.value,
            verdict="need_evidence",
            summary="Needs stronger evidence.",
            structured_output={"layer_1": [], "layer_2": []},
            raw_output="raw main",
            run_parameters={},
        )
        db.add(analysis)
        db.flush()
        predicted_run = PredictedCommentRun(
            analysis_id=analysis.id,
            skill_id=predicted_skill.id,
            skill_version=predicted_skill.version,
            provider=analysis.provider,
            model=analysis.model,
            status=RunStatus.CANCELLED.value,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": _devils_advocate_json(),
                    "raw_output": "provider should not run",
                    "latency_ms": 1,
                }
            },
        )
        db.add(predicted_run)
        db.commit()

        run_predicted_comments(str(predicted_run.id), db=db)

        db.refresh(predicted_run)
        assert predicted_run.status == RunStatus.CANCELLED.value
        assert predicted_run.structured_output is None
        assert predicted_run.raw_output is None
        assert predicted_run.started_at is None
    finally:
        _close_session(db)


def test_run_analysis_snapshots_devils_advocate_source_and_retrieval_before_gate(tmp_path, monkeypatch):
    db = _create_session()
    try:
        monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
        get_settings.cache_clear()
        user = _create_user(db)
        document = _create_document(db, user)
        document.parsed_text = "Marketplace growth asks for budget but lacks incrementality control group."
        main_skill = _create_main_skill(db)
        predicted_skill = _create_predicted_skill_with_source(db, tmp_path)
        _create_provider_key(db, user)
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=main_skill.id,
            skill_version=main_skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": _main_analysis_json("Needs incrementality evidence."),
                    "raw_output": "raw main",
                    "latency_ms": 10,
                },
                "predicted_comments_mock_provider_result": {
                    "structured_text": _devils_advocate_json(),
                    "raw_output": "raw predicted",
                    "latency_ms": 20,
                },
            },
        )
        db.add(analysis)
        db.commit()
        enqueued: list[str] = []

        run_analysis(str(analysis.id), db=db, enqueue_predicted_comments=lambda run_id: enqueued.append(str(run_id)))

        predicted_run = db.execute(select(PredictedCommentRun)).scalar_one()
        source_snapshot_id = predicted_run.run_parameters["skill_source_snapshot_id"]
        retrieval_snapshot_id = predicted_run.run_parameters["retrieval_snapshot_id"]
        source_snapshot = db.get(SkillSourceSnapshot, UUID(source_snapshot_id))
        retrieval_snapshot = db.get(RetrievalSnapshot, UUID(retrieval_snapshot_id))
        assert predicted_run.status == RunStatus.COMPLETED.value
        assert predicted_run.skill_id == predicted_skill.id
        assert source_snapshot.source_slug == "devils-advocate"
        assert retrieval_snapshot.retrieval_mode == "deterministic_topk"
        assert predicted_run.run_parameters["skill_source_snapshot"]["id"] == source_snapshot_id
        assert predicted_run.run_parameters["retrieval_snapshot"]["id"] == retrieval_snapshot_id
        assert predicted_run.run_parameters["run_order"] == "before_gate_challenger"
        assert predicted_run.run_parameters["devils_advocate_output_contract"] == "compact_prepass"
        dossier_path = tmp_path / "storage" / "retrieval-snapshots" / retrieval_snapshot_id / "dossier.json"
        dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
        assert "wiki-ic/cases/ic-2025-292.md" in dossier["selected_paths"]
        evidence_paths = [
            section["path"] for section in dossier["evidence_packet"]["sections"]
        ]
        assert "wiki-ic/cases/ic-2025-292.md" in evidence_paths
        assert "wiki-ic/raw/comments/raw-ic-2025-292-comments.md" in evidence_paths
        assert "wiki-ic/raw/minutes/raw-ic-2025-292-minutes.md" in evidence_paths
        evidence_packet_path = tmp_path / "storage" / "retrieval-snapshots" / retrieval_snapshot_id / "evidence_packet.md"
        evidence_packet_text = evidence_packet_path.read_text(encoding="utf-8")
        assert "marketplace budget incrementality control group holdout" in evidence_packet_text
        assert "real MP comment: how much is incremental?" in evidence_packet_text
        assert "real IC decision: rework until KPI gate is closed" in evidence_packet_text
        rendered_prompt = Path(predicted_run.run_parameters["rendered_prompt_artifact_path"]).read_text(encoding="utf-8")
        assert "Compact Devil's Advocate prepass output contract" in rendered_prompt
        assert "native_markdown must be at most 1200 characters" in rendered_prompt
        assert "| Role | Vote | Decision | Anchor quote | Comment | Type | Severity |" not in rendered_prompt
        assert analysis.run_parameters["gate_challenger_layer_4_context"]["brutal_truth"] == "Fatal flaw."
        assert enqueued == []
    finally:
        get_settings.cache_clear()
        _close_session(db)


def test_run_analysis_keeps_main_completed_when_devils_advocate_prepass_fails(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, user)
        main_skill = _create_main_skill(db)
        _create_predicted_skill(db, tmp_path)
        _create_provider_key(db, user)
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=main_skill.id,
            skill_version=main_skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": _main_analysis_json("Needs evidence."),
                    "raw_output": "raw main",
                    "latency_ms": 10,
                },
                "predicted_comments_mock_provider_result": {
                    "structured_text": "The Brutal Truth\nnot json",
                    "raw_output": "",
                    "latency_ms": 20,
                },
            },
        )
        db.add(analysis)
        db.commit()

        run_analysis(
            str(analysis.id),
            db=db,
            enqueue_predicted_comments=lambda run_id: (_ for _ in ()).throw(RuntimeError("redis unavailable")),
        )

        db.refresh(analysis)
        predicted_runs = db.execute(select(PredictedCommentRun)).scalars().all()
        assert analysis.status == RunStatus.COMPLETED.value
        assert len(predicted_runs) == 1
        assert predicted_runs[0].status == RunStatus.FAILED.value
        assert "Expecting value" in predicted_runs[0].error_message
        assert "gate_challenger_layer_4_context" not in analysis.run_parameters
    finally:
        _close_session(db)


def test_run_predicted_comments_persists_structured_raw_and_metadata(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, user)
        main_skill = _create_main_skill(db)
        predicted_skill = _create_predicted_skill(db, tmp_path)
        _create_provider_key(db, user)
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=main_skill.id,
            skill_version=main_skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.COMPLETED.value,
            verdict="need_evidence",
            summary="Needs stronger evidence.",
            structured_output={"layer_1": [], "layer_2": []},
            raw_output="raw main",
            run_parameters={},
        )
        db.add(analysis)
        db.flush()
        predicted_run = PredictedCommentRun(
            analysis_id=analysis.id,
            skill_id=predicted_skill.id,
            skill_version=predicted_skill.version,
            provider=analysis.provider,
            model=analysis.model,
            status=RunStatus.QUEUED.value,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": _devils_advocate_json(),
                    "raw_output": "raw predicted",
                    "input_tokens": 7,
                    "output_tokens": 11,
                    "latency_ms": 25,
                }
            },
        )
        db.add(predicted_run)
        db.commit()

        run_predicted_comments(str(predicted_run.id), db=db)

        db.refresh(predicted_run)
        assert predicted_run.status == RunStatus.COMPLETED.value
        assert predicted_run.structured_output["ic_decision"]["verdict"] == "rework"
        assert predicted_run.raw_output == "raw predicted"
        assert predicted_run.input_tokens == 7
        assert predicted_run.output_tokens == 11
        assert predicted_run.latency_ms == 25
        assert predicted_run.completed_at is not None
    finally:
        _close_session(db)


def test_run_predicted_comments_persists_structured_text_when_json_parse_fails(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, user)
        main_skill = _create_main_skill(db)
        predicted_skill = _create_predicted_skill(db, tmp_path)
        _create_provider_key(db, user)
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=main_skill.id,
            skill_version=main_skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.COMPLETED.value,
            verdict="need_evidence",
            summary="Needs stronger evidence.",
            structured_output={"layer_1": [], "layer_2": []},
            raw_output="raw main",
            run_parameters={},
        )
        db.add(analysis)
        db.flush()
        predicted_run = PredictedCommentRun(
            analysis_id=analysis.id,
            skill_id=predicted_skill.id,
            skill_version=predicted_skill.version,
            provider=analysis.provider,
            model=analysis.model,
            status=RunStatus.QUEUED.value,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": "The Brutal Truth\nnot json",
                    "raw_output": "",
                    "latency_ms": 25,
                }
            },
        )
        db.add(predicted_run)
        db.commit()

        run_predicted_comments(str(predicted_run.id), db=db)

        db.refresh(predicted_run)
        assert predicted_run.status == RunStatus.FAILED.value
        assert "Expecting value" in predicted_run.error_message
        assert predicted_run.raw_output == "The Brutal Truth\nnot json"
    finally:
        _close_session(db)


def test_run_predicted_comments_requires_retrieval_snapshot_for_external_da(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, user)
        main_skill = _create_main_skill(db)
        predicted_skill = _create_predicted_skill_with_source(db, tmp_path)
        _create_provider_key(db, user)
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=main_skill.id,
            skill_version=main_skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.COMPLETED.value,
            verdict="need_evidence",
            summary="Needs stronger evidence.",
            structured_output={"layer_1": [], "layer_2": []},
            raw_output="raw main",
            run_parameters={},
        )
        db.add(analysis)
        db.flush()
        source_snapshot_id = uuid4()
        source_snapshot_artifact_path = _create_da_source_snapshot_artifact(tmp_path, source_snapshot_id)
        predicted_run = PredictedCommentRun(
            analysis_id=analysis.id,
            skill_id=predicted_skill.id,
            skill_version=predicted_skill.version,
            provider=analysis.provider,
            model=analysis.model,
            status=RunStatus.QUEUED.value,
            run_parameters={
                "skill_source_snapshot_id": str(source_snapshot_id),
                "skill_source_snapshot": {
                    "id": str(source_snapshot_id),
                    "artifact_path": str(source_snapshot_artifact_path),
                    "source_fingerprint": "source-fingerprint",
                },
                "mock_provider_result": {
                    "structured_text": _devils_advocate_json(),
                    "raw_output": "raw predicted",
                    "latency_ms": 25,
                },
            },
        )
        db.add(predicted_run)
        db.commit()

        run_predicted_comments(str(predicted_run.id), db=db)

        db.refresh(predicted_run)
        assert predicted_run.status == RunStatus.FAILED.value
        assert predicted_run.error_message == "retrieval_snapshot_missing"
    finally:
        _close_session(db)


def test_run_predicted_comments_renders_prompt_from_source_and_retrieval_snapshots(tmp_path, monkeypatch):
    db = _create_session()
    try:
        monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
        get_settings.cache_clear()
        user = _create_user(db)
        document = _create_document(db, user)
        main_skill = _create_main_skill(db)
        predicted_skill = _create_predicted_skill_with_source(db, tmp_path)
        _create_provider_key(db, user)
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=main_skill.id,
            skill_version=main_skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.COMPLETED.value,
            verdict="need_evidence",
            summary="Needs stronger evidence.",
            structured_output={"findings": [{"id": "F1", "title": "Missing incrementality proof"}]},
            raw_output="raw main",
            run_parameters={},
        )
        db.add(analysis)
        db.flush()
        source_snapshot_id = uuid4()
        retrieval_snapshot_id = uuid4()
        source_snapshot_artifact_path = _create_da_source_snapshot_artifact(tmp_path, source_snapshot_id)
        retrieval_snapshot_artifact_path = _create_da_retrieval_snapshot_artifact(tmp_path, retrieval_snapshot_id)
        predicted_run = PredictedCommentRun(
            analysis_id=analysis.id,
            skill_id=predicted_skill.id,
            skill_version=predicted_skill.version,
            provider=analysis.provider,
            model=analysis.model,
            status=RunStatus.QUEUED.value,
            run_parameters={
                "skill_source_snapshot_id": str(source_snapshot_id),
                "retrieval_snapshot_id": str(retrieval_snapshot_id),
                "skill_source_snapshot": {
                    "id": str(source_snapshot_id),
                    "artifact_path": str(source_snapshot_artifact_path),
                    "source_fingerprint": "source-fingerprint",
                },
                "retrieval_snapshot": {
                    "id": str(retrieval_snapshot_id),
                    "artifact_path": str(retrieval_snapshot_artifact_path),
                },
                "mock_provider_result": {
                    "structured_text": _devils_advocate_json(),
                    "raw_output": "raw predicted",
                    "latency_ms": 25,
                },
            },
        )
        db.add(predicted_run)
        db.commit()

        run_predicted_comments(str(predicted_run.id), db=db)

        db.refresh(predicted_run)
        assert predicted_run.status == RunStatus.COMPLETED.value
        assert predicted_run.run_parameters["prompt_fingerprint"]
        rendered_prompt = Path(predicted_run.run_parameters["rendered_prompt_artifact_path"]).read_text(encoding="utf-8")
        assert "Snapshot IC voting orchestrator" in rendered_prompt
        assert "Snapshot incrementality excerpt" in rendered_prompt
        assert "Expanded retrieval evidence packet:" in rendered_prompt
        assert "Snapshot incrementality full case text should now be included" in rendered_prompt
        assert "Devil's Advocate stub should not be used" not in rendered_prompt
    finally:
        get_settings.cache_clear()
        _close_session(db)


def _devils_advocate_json() -> str:
    return json.dumps(
        {
            "run_mode": "full_ic_voting",
            "native_markdown": (
                "🔴 Devil's Advocate — IC+Gate 3: Safe Deal\n\n"
                "Pre-flight summary\n- Stage: Gate-3\n\n---\nThe Brutal Truth\n\nFatal flaw.\n\n"
                "---\nDetected Contradictions & Missing Proofs\n\n- Missing proof.\n\n"
                "---\nThe \"Tough Co-CEO\" Questions\n\n1. What is incremental?\n\n"
                "---\nActionable JTBDs\n\n1. Add a hard KPI gate.\n\n"
                "=== IC Decision ===\nVerdict: Rework"
            ),
            "preflight_summary": ["Stage: Gate-3"],
            "brutal_truth": "Fatal flaw.",
            "detected_contradictions": [
                {
                    "section": "FAQ 4",
                    "title": "Gross profit not shown",
                    "body": "Revenue is shown but gross profit is absent.",
                    "comment_type": "missing_data",
                    "severity": "critical",
                    "citations": ["[[financial-revenue-and-gross-profit]]"],
                }
            ],
            "role_comments": [
                {
                    "voter": "MP",
                    "vote": "reject",
                    "rationale": "No incrementality proof.",
                    "comments": [
                        _role_comment_item(
                            anchor_text="CR contact to payment",
                            body="What is the baseline and control group?",
                            severity="critical",
                        )
                    ],
                },
                {
                    "voter": "CPO",
                    "vote": "reject",
                    "rationale": "Funnel target missed.",
                    "comments": [
                        _role_comment_item(
                            anchor_text="CR contact to payment",
                            body="Which product change closes the funnel gap?",
                        )
                    ],
                },
                {
                    "voter": "TechDir",
                    "vote": "reject",
                    "rationale": "No A/B delta.",
                    "comments": [
                        _role_comment_item(
                            anchor_text="A/B delta",
                            body="Where is the experiment readout?",
                            comment_type="methodology_issue",
                        )
                    ],
                },
                {
                    "voter": "VertDir",
                    "vote": "approve",
                    "rationale": "Direction is useful.",
                    "comments": [
                        _role_comment_item(
                            anchor_text="Business Services",
                            body="Keep the vertical rollout gated by evidence.",
                            comment_type="risk_not_addressed",
                            severity="minor",
                        )
                    ],
                },
            ],
            "tough_questions": [
                {"question": "What is incremental impact?", "persona": "[[persona-managing-partner]]"},
                {"question": "Why is Stage 2 treated as proven?", "persona": "[[persona-product-director]]"},
                {"question": "Where is the A/B delta?", "persona": "[[persona-technical-director]]"},
            ],
            "actionable_jtbds": [
                "Set a hard closure-test KPI gate.",
                "Show gross profit and cumulative uplift.",
                "Separate Stage 1 from Stage 2 HC ask.",
            ],
            "anchored_comments": [
                {
                    "id": "C1",
                    "anchor": "metrics",
                    "comment": "Committee will ask for incrementality evidence.",
                    "severity": "high",
                }
            ],
            "trailer": {
                "executive_summary": "Needs evidence.",
                "key_risks": ["weak proof"],
                "missing_evidence": ["control group"],
                "next_steps": ["add experiment readout"],
            },
            "ic_decision": {
                "verdict": "rework",
                "vote_tally": {"MP": "reject", "CPO": "reject", "TechDir": "reject", "VertDir": "approve"},
                "rationale": "Missing proof.",
                "conditions": ["Set a hard closure-test KPI gate."],
                "heuristics_fired": ["[[financial-hockey-stick]]"],
                "patterns_fired": ["[[experimental-traction-gap]]"],
                "precedents_anchored": ["[[ic-2025-292]]"],
                "next_ic": "Q1 2027 after closure-test results",
            },
            "predicted_questions": ["What is incremental impact?"],
            "consulted_wiki_pages": ["risk-patterns.md"],
            "source_citations": ["wiki-ic/risk-patterns.md"],
            "retrieval": {
                "retrieval_mode": "deterministic_topk",
                "corpus_fingerprint": "corpus-fingerprint",
                "selected_cases": ["wiki-ic/cases/incrementality.md"],
                "selected_patterns": ["wiki-ic/patterns/missing-proof.md"],
                "selected_questions": ["What is the control group?"],
            },
        }
    )


def _role_comment_item(
    *,
    anchor_text: str,
    body: str,
    comment_type: str = "missing_data",
    severity: str = "important",
) -> dict:
    return {
        "anchor_text": anchor_text,
        "body": body,
        "comment_type": comment_type,
        "severity": severity,
    }


def _main_analysis_json(summary: str = "Needs evidence.") -> str:
    return json.dumps(
        {
            "verdict": "need_evidence",
            "summary": summary,
            "assessment_markdown": f"Оценка документа\nРекомендация: {summary}",
            "layer_1_index": [
                {
                    "id": "L1-001",
                    "severity": "critical",
                    "issue": "Mandatory readiness is not proven.",
                    "evidence_anchor": "The document does not close the required proof.",
                }
            ],
            "layer_2_index": [
                {
                    "id": "L2-001",
                    "parent_layer_1_id": "L1-001",
                    "status": "fail",
                    "severity": "high",
                    "question": "Is the key target evidenced?",
                    "answer": "NO",
                    "short_evidence": "The mock document omits the proof.",
                }
            ],
            "details_status": "not_requested",
            "details_run_id": None,
            "revision_required": False,
            "revision_reason": None,
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


def _create_user(db: Session, role: Role = Role.USER) -> User:
    user = User(
        login=f"user-{uuid4()}",
        display_name="User",
        password_hash=hash_password("secret"),
        role=role.value,
        status=UserStatus.ACTIVE.value,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_document(db: Session, user: User) -> Document:
    document = Document(
        owner_id=user.id,
        title="Gate 2",
        original_filename="gate.txt",
        mime_type="text/plain",
        file_size_bytes=128,
        file_hash_sha256="hash",
        storage_path="/tmp/gate.txt",
        parse_status=DocumentParseStatus.COMPLETED.value,
        detected_document_type=DocumentType.GATE_2.value,
        parsed_text="Gate 2 MVP metrics traction risks",
        status=EntityStatus.ACTIVE.value,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _create_main_skill(db: Session) -> Skill:
    skill = Skill(
        name="gate2_challenger_main_analysis",
        description="Gate 2",
        version="baseline",
        skill_type=SkillType.MAIN_ANALYSIS.value,
        supported_document_types=[DocumentType.GATE_2.value],
        source_type=SkillSourceType.INLINE_PROMPT.value,
        source_uri=None,
        source_entrypoint=None,
        source_revision=None,
        source_fingerprint=None,
        source_metadata={},
        prompt_text="Analyze Gate 2 document.",
        result_schema_path="contracts/schemas/main-analysis-result.schema.json",
        status=EntityStatus.ACTIVE.value,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def _create_predicted_skill(db: Session, tmp_path) -> Skill:
    prompt_path = tmp_path / "ic-voting-prompt.md"
    prompt_path.write_text("IC voting orchestrator", encoding="utf-8")
    skill = Skill(
        name="devils_advocate_predefense",
        description="Devil's Advocate",
        version="baseline",
        skill_type=SkillType.PREDICTED_COMMENTS.value,
        supported_document_types=[DocumentType.GATE_2.value],
        source_type=SkillSourceType.LOCAL_KNOWLEDGE_BASE.value,
        source_uri=str(prompt_path),
        source_entrypoint="ic-voting-prompt.md",
        source_revision="revision",
        source_fingerprint=None,
        source_metadata={"selected_wiki_pages": []},
        prompt_text="Devil's Advocate prompt",
        result_schema_path="contracts/schemas/devils-advocate-result.schema.json",
        status=EntityStatus.ACTIVE.value,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def _create_predicted_skill_with_source(db: Session, tmp_path) -> Skill:
    source_root = tmp_path / "devils-source"
    (source_root / "wiki-ic" / "meta").mkdir(parents=True)
    (source_root / "wiki-ic" / "cases").mkdir(parents=True)
    (source_root / "wiki-ic" / "patterns").mkdir(parents=True)
    (source_root / "wiki-ic" / "personas").mkdir(parents=True)
    (source_root / "wiki-ic" / "raw" / "comments").mkdir(parents=True)
    (source_root / "wiki-ic" / "raw" / "minutes").mkdir(parents=True)
    (source_root / "ic-voting-prompt.md").write_text("IC voting orchestrator snapshot", encoding="utf-8")
    (source_root / "workflow-ic-cases.md").write_text("Workflow", encoding="utf-8")
    (source_root / "wiki-ic" / "CLAUDE.md").write_text("Wiki instructions", encoding="utf-8")
    (source_root / "wiki-ic" / "schema.md").write_text("Wiki schema", encoding="utf-8")
    (source_root / "wiki-ic" / "meta" / "output-format.md").write_text("Output format", encoding="utf-8")
    (source_root / "wiki-ic" / "cases" / "ic-2025-292.md").write_text(
        "marketplace budget incrementality control group holdout",
        encoding="utf-8",
    )
    (source_root / "wiki-ic" / "raw" / "comments" / "raw-ic-2025-292-comments.md").write_text(
        "real MP comment: how much is incremental?",
        encoding="utf-8",
    )
    (source_root / "wiki-ic" / "raw" / "minutes" / "raw-ic-2025-292-minutes.md").write_text(
        "real IC decision: rework until KPI gate is closed",
        encoding="utf-8",
    )
    (source_root / "wiki-ic" / "patterns" / "missing-proof.md").write_text(
        "missing incrementality proof",
        encoding="utf-8",
    )
    (source_root / "wiki-ic" / "personas" / "cfo.md").write_text(
        "CFO asks for incremental return on budget",
        encoding="utf-8",
    )
    source = SkillSource(
        slug="devils-advocate",
        display_name="Devil's Advocate",
        source_kind="local_directory",
        local_path=str(source_root),
        repo_url=None,
        default_ref=None,
        entrypoint="ic-voting-prompt.md",
        required_paths=["ic-voting-prompt.md", "workflow-ic-cases.md", "wiki-ic"],
        update_policy="require_latest",
        status=EntityStatus.ACTIVE.value,
    )
    db.add(source)
    db.flush()
    skill = Skill(
        name="devils_advocate_predefense",
        description="Devil's Advocate",
        version="baseline",
        skill_type=SkillType.PREDICTED_COMMENTS.value,
        supported_document_types=[DocumentType.GATE_2.value],
        source_type=SkillSourceType.LOCAL_KNOWLEDGE_BASE.value,
        skill_source_id=source.id,
        source_uri=str(source_root / "ic-voting-prompt.md"),
        source_entrypoint="ic-voting-prompt.md",
        source_revision=None,
        source_fingerprint=None,
        source_metadata={},
        prompt_text="Devil's Advocate stub should not be used",
        result_schema_path="contracts/schemas/devils-advocate-result.schema.json",
        runtime_mode="snapshot_required",
        status=EntityStatus.ACTIVE.value,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def _create_provider_key(db: Session, user: User) -> ProviderKey:
    key = ProviderKey(
        owner_id=_create_user(db, role=Role.ADMIN).id,
        provider=Provider.OPENAI_COMPATIBLE.value,
        base_url=None,
        default_model="gpt-test",
        encrypted_api_key=encrypt_secret("sk-test"),
        api_key_fingerprint="openai_compatible:...test",
    )
    db.add(key)
    db.commit()
    return key


def _create_da_source_snapshot_artifact(tmp_path, source_snapshot_id):
    source_snapshot_dir = tmp_path / "skill-snapshots" / str(source_snapshot_id)
    files_dir = source_snapshot_dir / "files"
    (files_dir / "wiki-ic" / "meta").mkdir(parents=True)
    (files_dir / "wiki-ic" / "cases").mkdir(parents=True)
    (files_dir / "ic-voting-prompt.md").write_text("Snapshot IC voting orchestrator", encoding="utf-8")
    (files_dir / "wiki-ic" / "schema.md").write_text("Snapshot wiki schema", encoding="utf-8")
    (files_dir / "wiki-ic" / "meta" / "output-format.md").write_text("Snapshot output format", encoding="utf-8")
    (files_dir / "wiki-ic" / "cases" / "incrementality.md").write_text(
        "Snapshot incrementality full case text should now be included",
        encoding="utf-8",
    )
    (source_snapshot_dir / "manifest.json").write_text(
        json.dumps(
            {
                "source_slug": "devils-advocate",
                "source_fingerprint": "source-fingerprint",
                "files": [
                    {"path": "ic-voting-prompt.md", "sha256": "prompt-hash"},
                    {"path": "wiki-ic/schema.md", "sha256": "schema-hash"},
                    {"path": "wiki-ic/meta/output-format.md", "sha256": "format-hash"},
                    {"path": "wiki-ic/cases/incrementality.md", "sha256": "case-hash"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return source_snapshot_dir


def _create_da_retrieval_snapshot_artifact(tmp_path, retrieval_snapshot_id):
    retrieval_snapshot_dir = tmp_path / "retrieval-snapshots" / str(retrieval_snapshot_id)
    retrieval_snapshot_dir.mkdir(parents=True)
    (retrieval_snapshot_dir / "dossier.json").write_text(
        json.dumps(
            {
                "retrieval_mode": "deterministic_topk",
                "retrieval_version": "deterministic-lexical-v1",
                "corpus_fingerprint": "corpus-fingerprint",
                "query_fingerprint": "query-fingerprint",
                "selected_paths": ["wiki-ic/cases/incrementality.md"],
                "selected_items": {
                    "top_cases": [
                        {
                            "path": "wiki-ic/cases/incrementality.md",
                            "score": 4,
                            "excerpt": "Snapshot incrementality excerpt",
                        }
                    ],
                },
                "evidence_packet": {
                    "packet_version": "expanded-wiki-evidence-v1",
                    "sections": [
                        {
                            "path": "wiki-ic/cases/incrementality.md",
                            "source_group": "top_cases",
                            "sha256": "case-hash",
                            "content": "Snapshot incrementality full case text should now be included",
                            "truncated": False,
                        }
                    ],
                    "markdown": (
                        "# wiki-ic/cases/incrementality.md\n"
                        "Snapshot incrementality full case text should now be included"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )
    return retrieval_snapshot_dir
