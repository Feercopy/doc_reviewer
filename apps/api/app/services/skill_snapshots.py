from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.skill_source import SkillSource, SkillSourceSnapshot
from app.services.external_sources import check_git_freshness, collect_source_manifest, fingerprint_manifest
from app.storage.local import LocalDocumentStorage


def create_skill_source_snapshot(
    *,
    db: Session,
    storage: LocalDocumentStorage,
    source: SkillSource,
    analysis_id: UUID | None,
    predicted_comment_run_id: UUID | None,
    snapshot_mode: str,
) -> SkillSourceSnapshot:
    health = check_git_freshness(source, snapshot_mode=snapshot_mode)
    manifest = collect_source_manifest(source)
    source_fingerprint = fingerprint_manifest(manifest)
    snapshot_id = uuid4()
    manifest_payload = {
        "source_slug": source.slug,
        "source_kind": source.source_kind,
        "source_path": str(health.source_path),
        "resolved_revision": health.resolved_revision,
        "snapshot_mode": snapshot_mode,
        "source_fingerprint": source_fingerprint,
        "files": [
            {
                **item,
                "source_path": str(manifest.source_path / item["path"]),
            }
            for item in manifest.files
        ],
    }
    artifact_path = storage.save_skill_source_snapshot(snapshot_id=snapshot_id, manifest=manifest_payload)
    snapshot = SkillSourceSnapshot(
        id=snapshot_id,
        skill_source_id=source.id,
        analysis_id=analysis_id,
        predicted_comment_run_id=predicted_comment_run_id,
        source_slug=source.slug,
        source_kind=source.source_kind,
        source_path=str(health.source_path),
        repo_url=source.repo_url,
        requested_ref=source.default_ref,
        resolved_revision=health.resolved_revision,
        is_dirty=health.is_dirty,
        dirty_details=health.dirty_details,
        snapshot_mode=snapshot_mode,
        source_fingerprint=source_fingerprint,
        file_manifest=manifest.files,
        artifact_path=str(artifact_path),
    )
    db.add(snapshot)
    db.flush()
    return snapshot
