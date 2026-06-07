from io import BytesIO
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.analysis import Analysis
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.models.skill import Skill
from app.models.user import User
from app.schemas.enums import (
    DocumentParseStatus,
    DocumentType,
    EntityStatus,
    Provider,
    RunStatus,
    SkillSourceType,
    SkillType,
    UserStatus,
    Verdict,
    Role,
)
from app.security.passwords import hash_password
from app.security.secrets import encrypt_secret
from app.storage.local import LocalDocumentStorage
from jobs.run_analysis import run_analysis


def test_run_analysis_persists_structured_and_raw_output(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        key = ProviderKey(
            owner_id=user.id,
            provider=Provider.OPENAI_COMPATIBLE.value,
            base_url=None,
            default_model="gpt-test",
            encrypted_api_key=encrypt_secret("sk-test"),
            api_key_fingerprint="openai_compatible:...test",
        )
        db.add(key)
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": '{"verdict":"need_evidence","summary":"Needs stronger metric evidence.","findings":[],"checks":[]}',
                    "raw_output": "raw provider text",
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "latency_ms": 30,
                }
            },
        )
        db.add(analysis)
        db.commit()

        run_analysis(str(analysis.id), db=db)

        db.refresh(analysis)
        assert analysis.status == RunStatus.COMPLETED.value
        assert analysis.verdict == Verdict.NEED_EVIDENCE.value
        assert analysis.summary == "Needs stronger metric evidence."
        assert analysis.raw_output == "raw provider text"
        assert analysis.input_tokens == 10
        assert analysis.output_tokens == 20
        assert analysis.latency_ms == 30
    finally:
        _close_session(db)


def test_run_analysis_marks_missing_provider_key_failed(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(db)
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={},
        )
        db.add(analysis)
        db.commit()

        run_analysis(str(analysis.id), db=db)

        db.refresh(analysis)
        assert analysis.status == RunStatus.FAILED.value
        assert analysis.error_message == "provider_key_missing"
    finally:
        _close_session(db)


def test_run_analysis_marks_changed_external_skill_source_unavailable(tmp_path):
    db = _create_session()
    try:
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        source = tmp_path / "SKILL.md"
        source.write_text("Original Gate 2 instructions.", encoding="utf-8")
        skill = _create_skill(
            db,
            source_uri=str(tmp_path),
            source_entrypoint="SKILL.md",
            source_fingerprint="expected-old-fingerprint",
        )
        db.add(
            ProviderKey(
                owner_id=user.id,
                provider=Provider.OPENAI_COMPATIBLE.value,
                base_url=None,
                default_model="gpt-test",
                encrypted_api_key=encrypt_secret("sk-test"),
                api_key_fingerprint="openai_compatible:...test",
            )
        )
        analysis = Analysis(
            document_id=document.id,
            user_id=user.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=Provider.OPENAI_COMPATIBLE.value,
            model="gpt-test",
            status=RunStatus.QUEUED.value,
            run_parameters={
                "skill_source_snapshot": {
                    "source_type": SkillSourceType.LOCAL_SKILL_REPO.value,
                    "source_fingerprint": "expected-old-fingerprint",
                },
                "mock_provider_result": {
                    "structured_text": '{"verdict":"need_evidence","summary":"Should not run provider.","findings":[],"checks":[]}',
                    "raw_output": "provider should not be called",
                    "latency_ms": 1,
                },
            },
        )
        db.add(analysis)
        db.commit()

        run_analysis(str(analysis.id), db=db)

        db.refresh(analysis)
        assert analysis.status == RunStatus.FAILED.value
        assert analysis.error_message == "skill_source_unavailable"
        assert analysis.raw_output is None
    finally:
        _close_session(db)


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


def _create_skill(
    db: Session,
    *,
    source_uri: str | None = None,
    source_entrypoint: str | None = None,
    source_fingerprint: str | None = None,
) -> Skill:
    skill = Skill(
        name="gate2_challenger_main_analysis",
        description="Gate 2",
        version="baseline",
        skill_type=SkillType.MAIN_ANALYSIS.value,
        supported_document_types=[DocumentType.GATE_2.value],
        source_type=SkillSourceType.LOCAL_SKILL_REPO.value if source_uri else SkillSourceType.INLINE_PROMPT.value,
        source_uri=source_uri,
        source_entrypoint=source_entrypoint,
        source_revision=None,
        source_fingerprint=source_fingerprint,
        source_metadata={},
        prompt_text="Analyze Gate 2 document.",
        result_schema_path="contracts/schemas/main-analysis-result.schema.json",
        status=EntityStatus.ACTIVE.value,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill
