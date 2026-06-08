from uuid import uuid4

from app.models.skill_source import RetrievalSnapshot, SkillSource, SkillSourceSnapshot
from app.services.skill_snapshots import create_skill_source_snapshot
from app.services.external_sources import (
    SourceUnavailableError,
    collect_source_manifest,
    check_git_freshness,
    fingerprint_manifest,
)
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
