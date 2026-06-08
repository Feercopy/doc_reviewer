import json
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.core.config import get_settings
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
                    "structured_text": _main_analysis_json("Needs stronger metric evidence."),
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
                    "structured_text": _main_analysis_json("Should not run provider."),
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


def test_run_analysis_persists_rendered_prompt_from_source_snapshot(tmp_path, monkeypatch):
    db = _create_session()
    try:
        monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
        get_settings.cache_clear()
        user = _create_user(db)
        document = _create_document(db, tmp_path, user)
        skill = _create_skill(
            db,
            source_uri=str(tmp_path / "missing-live-source"),
            source_entrypoint="skills/gate-challenger/SKILL.md",
            source_fingerprint="old-live-fingerprint",
        )
        skill.skill_source_id = uuid4()
        skill.runtime_mode = "snapshot_required"
        skill.prompt_text = "Stub prompt should not be used"
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

        source_snapshot_id = uuid4()
        snapshot_dir = tmp_path / "skill-snapshots" / str(source_snapshot_id)
        skill_file = snapshot_dir / "files" / "skills" / "gate-challenger" / "SKILL.md"
        reference_file = snapshot_dir / "files" / "skills" / "gate-challenger" / "references" / "rubric.md"
        reference_file.parent.mkdir(parents=True)
        skill_file.write_text("Snapshot Gate instructions", encoding="utf-8")
        reference_file.write_text("Snapshot reference rubric", encoding="utf-8")
        (snapshot_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "source_slug": "gate-challenger",
                    "resolved_revision": "abc123",
                    "source_fingerprint": "snapshot-fingerprint",
                    "files": [
                        {"path": "skills/gate-challenger/SKILL.md", "sha256": "skill-hash"},
                        {"path": "skills/gate-challenger/references/rubric.md", "sha256": "rubric-hash"},
                    ],
                }
            ),
            encoding="utf-8",
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
                "source_snapshot_id": str(source_snapshot_id),
                "source_snapshot_artifact_path": str(snapshot_dir),
                "skill_source_snapshot": {
                    "id": str(source_snapshot_id),
                    "artifact_path": str(snapshot_dir),
                    "source_fingerprint": "snapshot-fingerprint",
                },
                "mock_provider_result": {
                    "structured_text": _main_analysis_json("Needs stronger metric evidence."),
                    "raw_output": "raw provider text",
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "latency_ms": 30,
                },
            },
        )
        db.add(analysis)
        db.commit()

        run_analysis(str(analysis.id), db=db)

        db.refresh(analysis)
        assert analysis.status == RunStatus.COMPLETED.value
        assert analysis.run_parameters["prompt_fingerprint"]
        prompt_path = analysis.run_parameters["rendered_prompt_artifact_path"]
        rendered_prompt = Path(prompt_path).read_text(encoding="utf-8")
        assert "Snapshot Gate instructions" in rendered_prompt
        assert "Snapshot reference rubric" in rendered_prompt
        assert "Stub prompt should not be used" not in rendered_prompt
    finally:
        get_settings.cache_clear()
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


def _main_analysis_json(summary: str = "Needs evidence.") -> str:
    return json.dumps(
        {
            "verdict": "need_evidence",
            "summary": summary,
            "assessment_markdown": f"Оценка документа\nРекомендация: {summary}",
            "findings": [],
            "checks": [],
            "layer_1_markdown": "Layer 1\nL1-001 — Decision-critical blocker.",
            "layer_1": [
                {
                    "id": "L1-001",
                    "severity": "critical",
                    "title": "Decision-critical blocker",
                    "issue": "Mandatory readiness is not proven.",
                    "evidence": "The document does not close the required proof.",
                    "impact": "Committee cannot approve scale-up as-is.",
                    "recommendation": "Gate approval on proof.",
                }
            ],
            "layer_2_markdown": "Layer 2\nL2-001 — Atomic weak-link finding.",
            "layer_2": [
                {
                    "id": "L2-001",
                    "parent_layer_1_id": "L1-001",
                    "severity": "high",
                    "title": "Atomic weak-link finding",
                    "atomic_issue": "A key target is not evidenced.",
                    "evidence": "The mock document omits the proof.",
                    "risk": "The model may overstate readiness.",
                    "recommendation": "Add evidence before approval.",
                }
            ],
        }
    )


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
