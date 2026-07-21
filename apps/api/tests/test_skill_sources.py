from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.analysis import Analysis, AnalysisCheckRun, PredictedCommentRun
from app.models.document import Document
from app.models.skill import Skill
from app.models.skill_source import RetrievalSnapshot, SkillSource, SkillSourceSnapshot
from app.models.user import User
from app.schemas.enums import DocumentParseStatus, DocumentType, Provider, Role, RunStatus, SkillType, UserStatus
from app.security.passwords import hash_password
from app.services.skill_snapshots import create_skill_source_snapshot
from app.seeds.skills import IC_AGENTIC_REVIEW_REQUIRED_PATHS
from app.services.external_sources import (
    SourceUnavailableError,
    collect_source_manifest,
    check_git_freshness,
    fingerprint_manifest,
)
from app.services import external_sources
from app.storage.local import LocalDocumentStorage


def test_skill_source_snapshot_models_persist(db_session):
    source = SkillSource(
        slug="gate-challenger",
        display_name="Gate Challenger",
        source_kind="local_git_repo",
        local_path="/external/gate-challenger",
        repo_url=None,
        default_ref="main",
        entrypoint="skills/gate-challenger/SKILL.md",
        required_paths=["skills/gate-challenger/references"],
        update_policy="require_latest",
        status="active",
    )
    db_session.add(source)
    db_session.flush()

    source_snapshot = SkillSourceSnapshot(
        skill_source_id=source.id,
        analysis_id=uuid4(),
        predicted_comment_run_id=None,
        source_slug=source.slug,
        source_kind=source.source_kind,
        source_path=source.local_path,
        repo_url=source.repo_url,
        requested_ref="main",
        resolved_revision="abc123",
        is_dirty=False,
        dirty_details={},
        snapshot_mode="production_latest",
        source_fingerprint="fingerprint",
        file_manifest=[{"path": "skills/gate-challenger/SKILL.md", "sha256": "sha", "size": 10}],
        artifact_path="/storage/skill-snapshots/snapshot-id",
    )
    retrieval_snapshot = RetrievalSnapshot(
        predicted_comment_run_id=uuid4(),
        retrieval_mode="deterministic_topk",
        retrieval_version="lexical-v1",
        corpus_fingerprint="corpus",
        query_fingerprint="query",
        selected_items={"top_cases": []},
        artifact_path="/storage/retrieval-snapshots/retrieval-id",
    )
    db_session.add_all([source_snapshot, retrieval_snapshot])
    db_session.commit()

    assert db_session.query(SkillSource).filter_by(slug="gate-challenger").one().id == source.id
    assert db_session.query(SkillSourceSnapshot).one().source_fingerprint == "fingerprint"
    assert db_session.query(RetrievalSnapshot).one().retrieval_mode == "deterministic_topk"


def test_skill_source_snapshot_can_be_owned_by_analysis_check_run(db_session):
    analysis, predicted_comment_run, analysis_check_run, source = _create_snapshot_owner_rows(db_session)

    analysis_snapshot = _source_snapshot(source, analysis_id=analysis.id)
    predicted_comment_snapshot = _source_snapshot(source, predicted_comment_run_id=predicted_comment_run.id)
    analysis_check_snapshot = _source_snapshot(source, analysis_check_run_id=analysis_check_run.id)
    db_session.add_all([analysis_snapshot, predicted_comment_snapshot, analysis_check_snapshot])
    db_session.commit()

    assert db_session.query(SkillSourceSnapshot).filter_by(analysis_id=analysis.id).one().source_slug == source.slug
    assert (
        db_session.query(SkillSourceSnapshot).filter_by(predicted_comment_run_id=predicted_comment_run.id).one().source_slug
        == source.slug
    )
    assert (
        db_session.query(SkillSourceSnapshot).filter_by(analysis_check_run_id=analysis_check_run.id).one().source_slug
        == source.slug
    )


def test_skill_source_snapshot_rejects_multiple_owners(db_session):
    analysis, _predicted_comment_run, analysis_check_run, source = _create_snapshot_owner_rows(db_session)
    db_session.add(_source_snapshot(source, analysis_id=analysis.id, analysis_check_run_id=analysis_check_run.id))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_skill_source_snapshot_rejects_zero_owners(db_session):
    _analysis, _predicted_comment_run, _analysis_check_run, source = _create_snapshot_owner_rows(db_session)
    db_session.add(_source_snapshot(source))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_create_skill_source_snapshot_links_analysis_check_run(db_session, tmp_path):
    _analysis, _predicted_comment_run, analysis_check_run, source = _create_snapshot_owner_rows(db_session)
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "SKILL.md").write_text("Main prompt", encoding="utf-8")
    source.source_kind = "local_directory"
    source.local_path = str(source_root)
    source.default_ref = None
    source.entrypoint = "SKILL.md"
    source.required_paths = ["SKILL.md"]
    storage = LocalDocumentStorage(tmp_path / "storage")
    db_session.commit()

    snapshot = create_skill_source_snapshot(
        db=db_session,
        storage=storage,
        source=source,
        analysis_id=None,
        predicted_comment_run_id=None,
        analysis_check_run_id=analysis_check_run.id,
        snapshot_mode="pinned_revision",
    )

    assert snapshot.analysis_id is None
    assert snapshot.predicted_comment_run_id is None
    assert snapshot.analysis_check_run_id == analysis_check_run.id
    assert (tmp_path / "storage" / "skill-snapshots" / str(snapshot.id) / "files" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "Main prompt"


def _source_snapshot(
    source: SkillSource,
    *,
    analysis_id=None,
    predicted_comment_run_id=None,
    analysis_check_run_id=None,
) -> SkillSourceSnapshot:
    return SkillSourceSnapshot(
        skill_source_id=source.id,
        analysis_id=analysis_id,
        predicted_comment_run_id=predicted_comment_run_id,
        analysis_check_run_id=analysis_check_run_id,
        source_slug=source.slug,
        source_kind=source.source_kind,
        source_path=source.local_path,
        repo_url=source.repo_url,
        requested_ref="main",
        resolved_revision="abc123",
        is_dirty=False,
        dirty_details={},
        snapshot_mode="production_latest",
        source_fingerprint=f"fingerprint-{uuid4()}",
        file_manifest=[{"path": "SKILL.md", "sha256": "sha", "size": 10}],
        artifact_path=f"/storage/skill-snapshots/{uuid4()}",
    )


def _create_snapshot_owner_rows(db_session):
    user = User(
        login=f"author-{uuid4()}",
        display_name="Author",
        password_hash=hash_password("secret"),
        role=Role.USER.value,
        status=UserStatus.ACTIVE.value,
    )
    source = SkillSource(
        slug=f"source-{uuid4()}",
        display_name="Source",
        source_kind="local_git_repo",
        local_path="/external/source",
        repo_url=None,
        default_ref="main",
        entrypoint="SKILL.md",
        required_paths=["SKILL.md"],
        update_policy="require_latest",
        status="active",
    )
    skill = Skill(
        name=f"skill-{uuid4()}",
        description="Skill",
        version="2026-07-09",
        skill_type=SkillType.MAIN_ANALYSIS.value,
        supported_document_types=[DocumentType.GATE_3.value],
        source_type="local_skill_repo",
        prompt_text="prompt",
        result_schema_path="schema.json",
    )
    analysis_check_skill = Skill(
        name=f"analysis-check-{uuid4()}",
        description="Analysis check",
        version="2026-07-09",
        skill_type=SkillType.ANALYSIS_CHECK.value,
        supported_document_types=[DocumentType.GATE_3.value],
        source_type="local_skill_repo",
        prompt_text="prompt",
        result_schema_path="schema.json",
    )
    db_session.add_all([user, source, skill, analysis_check_skill])
    db_session.flush()
    document = Document(
        owner_id=user.id,
        title="Investment Defense",
        original_filename="gate.txt",
        mime_type="text/plain",
        file_size_bytes=42,
        file_hash_sha256="1" * 64,
        storage_path="/storage/gate.txt",
        parse_status=DocumentParseStatus.COMPLETED.value,
        detected_document_type=DocumentType.GATE_3.value,
        parsed_text="Completed Gate 3 defense text",
    )
    db_session.add(document)
    db_session.flush()
    analysis = Analysis(
        document_id=document.id,
        user_id=user.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="openai/gpt-5.5",
        status=RunStatus.COMPLETED.value,
        run_parameters={},
    )
    db_session.add(analysis)
    db_session.flush()
    predicted_comment_run = PredictedCommentRun(
        analysis_id=analysis.id,
        skill_id=skill.id,
        skill_version=skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="openai/gpt-5.5",
        status=RunStatus.COMPLETED.value,
        run_parameters={},
    )
    analysis_check_run = AnalysisCheckRun(
        analysis_id=analysis.id,
        skill_id=analysis_check_skill.id,
        skill_version=analysis_check_skill.version,
        check_type="ic_agentic_review",
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="openai/gpt-5.5",
        status=RunStatus.COMPLETED.value,
        current_stage="synthesis",
        run_parameters={},
        artifacts=[],
        uploaded_workbook_metadata={},
    )
    db_session.add_all([predicted_comment_run, analysis_check_run])
    db_session.commit()
    return analysis, predicted_comment_run, analysis_check_run, source


def test_external_source_missing_path_is_unavailable(tmp_path):
    source = SkillSource(
        slug="missing",
        display_name="Missing",
        source_kind="local_git_repo",
        local_path=str(tmp_path / "missing"),
        default_ref="main",
        entrypoint="SKILL.md",
        required_paths=["SKILL.md"],
        update_policy="require_latest",
        status="active",
    )

    try:
        check_git_freshness(source, snapshot_mode="production_latest")
    except SourceUnavailableError as exc:
        assert "source path does not exist" in str(exc)
    else:
        raise AssertionError("missing source should fail")


def test_collect_source_manifest_hashes_required_files(tmp_path):
    root = tmp_path / "source"
    references = root / "references"
    references.mkdir(parents=True)
    (root / "SKILL.md").write_text("Main prompt", encoding="utf-8")
    (references / "rubric.md").write_text("Rubric", encoding="utf-8")
    source = SkillSource(
        slug="source",
        display_name="Source",
        source_kind="local_directory",
        local_path=str(root),
        default_ref=None,
        entrypoint="SKILL.md",
        required_paths=["SKILL.md", "references"],
        update_policy="allow_pinned",
        status="active",
    )

    manifest = collect_source_manifest(source)

    assert [item["path"] for item in manifest.files] == ["SKILL.md", "references/rubric.md"]
    assert all(item["sha256"] for item in manifest.files)
    assert fingerprint_manifest(manifest)


def test_collect_source_manifest_includes_ic_agentic_review_prompts_and_scripts(tmp_path):
    root = tmp_path / "ic-agentic-review"
    for required_path in IC_AGENTIC_REVIEW_REQUIRED_PATHS:
        target = root / required_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if required_path == "data/internal_codes":
            target.mkdir(exist_ok=True)
            (target / "codes.json").write_text('{"code": "demo"}', encoding="utf-8")
        elif required_path.endswith(".ttf"):
            target.write_bytes(b"font")
        else:
            target.write_text(f"{required_path}\n", encoding="utf-8")

    source = SkillSource(
        slug="ic-agentic-review",
        display_name="IC Agentic Review",
        source_kind="local_directory",
        local_path=str(root),
        default_ref=None,
        entrypoint=".claude/commands/invest-analysis.md",
        required_paths=IC_AGENTIC_REVIEW_REQUIRED_PATHS,
        update_policy="allow_pinned",
        status="active",
    )

    manifest = collect_source_manifest(source)
    manifest_paths = {item["path"] for item in manifest.files}

    assert {
        ".claude/agents/ic-financial-auditor.md",
        ".claude/agents/ic-product-analyst.md",
        ".claude/agents/ic-market-analyst.md",
        ".claude/agents/ic-web-researcher.md",
        ".claude/agents/ic-benchmark-valuation.md",
        ".claude/agents/ic-team-legal.md",
        ".claude/agents/ic-tech-dd.md",
        ".claude/agents/ic-risk-scenario.md",
    }.issubset(manifest_paths)
    assert {
        "scripts/invest/config.py",
        "scripts/invest/formula_auditor.py",
        "scripts/invest/json_postprocess.py",
        "scripts/invest/marker_parser.py",
        "scripts/invest/metrics_lookup.py",
        "scripts/invest/pdf_generator.py",
        "scripts/invest/excel_audit.py",
        "scripts/invest/validate_report.py",
        "scripts/invest/run_pipeline.py",
    }.issubset(manifest_paths)
    assert "data/internal_codes/codes.json" in manifest_paths
    assert all(item["sha256"] for item in manifest.files)
    assert fingerprint_manifest(manifest)


def test_git_freshness_rejects_dirty_production_latest(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "SKILL.md").write_text("Main prompt", encoding="utf-8")
    _run_git(root, "init")
    _run_git(root, "config", "user.email", "test@example.com")
    _run_git(root, "config", "user.name", "Test")
    _run_git(root, "add", "SKILL.md")
    _run_git(root, "commit", "-m", "initial")
    (root / "SKILL.md").write_text("Changed prompt", encoding="utf-8")
    source = SkillSource(
        slug="source",
        display_name="Source",
        source_kind="local_git_repo",
        local_path=str(root),
        default_ref="main",
        entrypoint="SKILL.md",
        required_paths=["SKILL.md"],
        update_policy="require_latest",
        status="active",
    )

    try:
        check_git_freshness(source, snapshot_mode="production_latest")
    except SourceUnavailableError as exc:
        assert "source repo is dirty" in str(exc)
    else:
        raise AssertionError("dirty production source should fail")


def test_git_freshness_allows_dirty_intentional_local_run(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "SKILL.md").write_text("Main prompt", encoding="utf-8")
    _run_git(root, "init")
    _run_git(root, "config", "user.email", "test@example.com")
    _run_git(root, "config", "user.name", "Test")
    _run_git(root, "add", "SKILL.md")
    _run_git(root, "commit", "-m", "initial")
    (root / "SKILL.md").write_text("Changed prompt", encoding="utf-8")
    source = SkillSource(
        slug="source",
        display_name="Source",
        source_kind="local_git_repo",
        local_path=str(root),
        default_ref="main",
        entrypoint="SKILL.md",
        required_paths=["SKILL.md"],
        update_policy="require_latest",
        status="active",
    )

    health = check_git_freshness(source, snapshot_mode="intentional_local_run")

    assert health.resolved_revision
    assert health.is_dirty is True
    assert "SKILL.md" in health.dirty_details["files"][0]


def test_git_freshness_allows_development_snapshot_when_git_is_unavailable(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "SKILL.md").write_text("Main prompt", encoding="utf-8")
    source = SkillSource(
        slug="source",
        display_name="Source",
        source_kind="local_git_repo",
        local_path=str(root),
        default_ref="main",
        entrypoint="SKILL.md",
        required_paths=["SKILL.md"],
        update_policy="require_latest",
        status="active",
    )

    def unavailable_git(*args):
        raise SourceUnavailableError("git command failed: rev-parse HEAD")

    monkeypatch.setattr(external_sources, "_git", unavailable_git)

    health = check_git_freshness(source, snapshot_mode="development_current")

    assert health.resolved_revision is None
    assert health.is_dirty is False
    assert health.dirty_details == {"git_unavailable": True}


def test_git_freshness_allows_production_export_when_git_is_unavailable(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "SKILL.md").write_text("Main prompt", encoding="utf-8")
    source = SkillSource(
        slug="source",
        display_name="Source",
        source_kind="local_git_repo",
        local_path=str(root),
        default_ref="main",
        entrypoint="SKILL.md",
        required_paths=["SKILL.md"],
        update_policy="require_latest",
        status="active",
    )

    def unavailable_git(*args):
        raise SourceUnavailableError("git command failed: rev-parse HEAD")

    monkeypatch.setattr(external_sources, "_git", unavailable_git)

    health = check_git_freshness(source, snapshot_mode="production_export")

    assert health.resolved_revision is None
    assert health.is_dirty is False
    assert health.dirty_details == {"git_unavailable": True}


def test_create_skill_source_snapshot_writes_artifact_files(db_session, tmp_path):
    source_root = tmp_path / "source"
    (source_root / "references").mkdir(parents=True)
    (source_root / "SKILL.md").write_text("Main prompt", encoding="utf-8")
    (source_root / "references" / "rubric.md").write_text("Rubric", encoding="utf-8")
    storage = LocalDocumentStorage(tmp_path / "storage")
    source = SkillSource(
        slug="gate-challenger",
        display_name="Gate Challenger",
        source_kind="local_directory",
        local_path=str(source_root),
        default_ref=None,
        entrypoint="SKILL.md",
        required_paths=["SKILL.md", "references"],
        update_policy="allow_pinned",
        status="active",
    )
    db_session.add(source)
    db_session.commit()

    snapshot = create_skill_source_snapshot(
        db=db_session,
        storage=storage,
        source=source,
        analysis_id=uuid4(),
        predicted_comment_run_id=None,
        analysis_check_run_id=None,
        snapshot_mode="pinned_revision",
    )

    artifact_path = tmp_path / "storage" / "skill-snapshots" / str(snapshot.id)
    assert snapshot.source_fingerprint
    assert snapshot.artifact_path == str(artifact_path)
    assert (artifact_path / "manifest.json").is_file()
    assert (artifact_path / "files" / "SKILL.md").read_text(encoding="utf-8") == "Main prompt"
    assert (artifact_path / "files" / "references" / "rubric.md").read_text(encoding="utf-8") == "Rubric"


def test_save_skill_source_snapshot_rejects_escaping_manifest_paths(tmp_path):
    storage = LocalDocumentStorage(tmp_path / "storage")
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_file = source_root / "SKILL.md"
    source_file.write_text("Main prompt", encoding="utf-8")

    try:
        storage.save_skill_source_snapshot(
            snapshot_id=uuid4(),
            manifest={"files": [{"path": "../escape.md", "source_path": str(source_file)}]},
        )
    except ValueError as exc:
        assert "escapes STORAGE_ROOT" in str(exc)
    else:
        raise AssertionError("escaping manifest path should fail")


def _run_git(cwd, *args):
    import subprocess

    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
