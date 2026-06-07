from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.analysis import Analysis, PredictedCommentRun
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.models.skill import Skill
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


def test_run_analysis_queues_predicted_comments_after_success(tmp_path):
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
                    "structured_text": (
                        '{"verdict":"need_evidence","summary":"Needs stronger evidence.",'
                        '"findings":[],"checks":[]}'
                    ),
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
        assert predicted_run.status == RunStatus.QUEUED.value
        assert predicted_run.skill_id == predicted_skill.id
        assert predicted_run.provider == analysis.provider
        assert predicted_run.model == analysis.model
        assert predicted_run.run_parameters["main_analysis_id"] == str(analysis.id)
        assert predicted_run.run_parameters["skill_source_snapshot"]["name"] == "devils_advocate_predefense"
        assert predicted_run.run_parameters["mock_provider_result"]["raw_output"] == "raw predicted"
        assert enqueued == [str(predicted_run.id)]
    finally:
        _close_session(db)


def test_run_analysis_marks_predicted_comment_run_failed_when_enqueue_fails(tmp_path):
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
                    "structured_text": '{"verdict":"need_evidence","summary":"Needs evidence.","findings":[],"checks":[]}',
                    "raw_output": "raw main",
                    "latency_ms": 10,
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
        assert predicted_runs[0].error_message == "predicted_comments_enqueue_failed:redis unavailable"
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
        assert predicted_run.structured_output["ic_decision"]["verdict"] == "need_evidence"
        assert predicted_run.raw_output == "raw predicted"
        assert predicted_run.input_tokens == 7
        assert predicted_run.output_tokens == 11
        assert predicted_run.latency_ms == 25
        assert predicted_run.completed_at is not None
    finally:
        _close_session(db)


def _devils_advocate_json() -> str:
    return (
        '{"run_mode":"full_ic_voting","anchored_comments":[{"id":"C1","anchor":"metrics",'
        '"comment":"Committee will ask for incrementality evidence.","severity":"high"}],'
        '"trailer":{"executive_summary":"Needs evidence.","key_risks":["weak proof"],'
        '"missing_evidence":["control group"],"next_steps":["add experiment readout"]},'
        '"ic_decision":{"verdict":"need_evidence","rationale":"Missing proof."},'
        '"predicted_questions":["What is incremental impact?"],'
        '"consulted_wiki_pages":["risk-patterns.md"],"source_citations":["wiki-ic/risk-patterns.md"]}'
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
        role=Role.USER.value,
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
        source_fingerprint="fingerprint",
        source_metadata={"selected_wiki_pages": []},
        prompt_text="Devil's Advocate prompt",
        result_schema_path="contracts/schemas/devils-advocate-result.schema.json",
        status=EntityStatus.ACTIVE.value,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def _create_provider_key(db: Session, user: User) -> ProviderKey:
    key = ProviderKey(
        owner_id=user.id,
        provider=Provider.OPENAI_COMPATIBLE.value,
        base_url=None,
        default_model="gpt-test",
        encrypted_api_key=encrypt_secret("sk-test"),
        api_key_fingerprint="openai_compatible:...test",
    )
    db.add(key)
    db.commit()
    return key
