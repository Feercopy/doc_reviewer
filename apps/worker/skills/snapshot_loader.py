import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SkillSourceSnapshotMaterial:
    artifact_path: Path
    manifest: dict[str, Any]
    files: dict[str, str]

    def read_text(self, relative_path: str) -> str | None:
        return self.files.get(relative_path)


@dataclass(frozen=True)
class RetrievalSnapshotMaterial:
    artifact_path: Path
    dossier: dict[str, Any]


def load_skill_source_snapshot(artifact_path: str) -> SkillSourceSnapshotMaterial:
    snapshot_dir = Path(artifact_path).expanduser().resolve()
    manifest_path = snapshot_dir / "manifest.json"
    files_dir = (snapshot_dir / "files").resolve()
    if not manifest_path.is_file() or not files_dir.is_dir():
        raise RuntimeError("source_snapshot_unavailable")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files: dict[str, str] = {}
    for item in manifest.get("files", []):
        relative_path = _safe_relative_path(str(item["path"]))
        file_path = (files_dir / relative_path).resolve()
        if not file_path.is_relative_to(files_dir) or not file_path.is_file():
            raise RuntimeError("source_snapshot_unavailable")
        files[relative_path.as_posix()] = file_path.read_text(encoding="utf-8", errors="replace")

    return SkillSourceSnapshotMaterial(
        artifact_path=snapshot_dir,
        manifest=manifest,
        files=files,
    )


def load_retrieval_snapshot(artifact_path: str) -> RetrievalSnapshotMaterial:
    snapshot_dir = Path(artifact_path).expanduser().resolve()
    dossier_path = snapshot_dir / "dossier.json"
    if not dossier_path.is_file():
        raise RuntimeError("retrieval_snapshot_unavailable")
    return RetrievalSnapshotMaterial(
        artifact_path=snapshot_dir,
        dossier=json.loads(dossier_path.read_text(encoding="utf-8")),
    )


def _safe_relative_path(path: str) -> Path:
    relative_path = Path(path)
    if relative_path.is_absolute() or any(part == ".." for part in relative_path.parts):
        raise RuntimeError("source_snapshot_unavailable")
    return relative_path
