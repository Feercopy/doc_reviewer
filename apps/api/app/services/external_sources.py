import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.skill_source import SkillSource


class SourceUnavailableError(ValueError):
    pass


@dataclass(frozen=True)
class SourceHealth:
    source_path: Path
    resolved_revision: str | None
    is_dirty: bool
    dirty_details: dict[str, Any]


@dataclass(frozen=True)
class SourceManifest:
    source_path: Path
    files: list[dict[str, Any]]


def check_git_freshness(source: SkillSource, *, snapshot_mode: str) -> SourceHealth:
    source_path = _source_path(source)
    if not source_path.exists():
        raise SourceUnavailableError(f"source path does not exist: {source_path}")
    if source.source_kind != "local_git_repo":
        return SourceHealth(source_path=source_path, resolved_revision=None, is_dirty=False, dirty_details={})

    revision = _git(source_path, "rev-parse", "HEAD").strip()
    dirty_files = _git(source_path, "status", "--short").splitlines()
    is_dirty = bool(dirty_files)
    dirty_details = {"files": dirty_files} if dirty_files else {}
    if snapshot_mode == "production_latest" and is_dirty:
        raise SourceUnavailableError(f"source repo is dirty: {source.slug}")
    if snapshot_mode == "production_latest":
        upstream = _git_optional(source_path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if upstream:
            _git(source_path, "fetch")
            counts = _git(source_path, "rev-list", "--left-right", "--count", f"HEAD...{upstream.strip()}").split()
            if len(counts) == 2 and int(counts[1]) > 0:
                raise SourceUnavailableError(f"source repo is behind upstream: {source.slug}")
    return SourceHealth(
        source_path=source_path,
        resolved_revision=revision,
        is_dirty=is_dirty,
        dirty_details=dirty_details,
    )


def collect_source_manifest(source: SkillSource) -> SourceManifest:
    source_path = _source_path(source)
    if not source_path.exists():
        raise SourceUnavailableError(f"source path does not exist: {source_path}")

    files: list[Path] = []
    required_paths = source.required_paths or [source.entrypoint]
    for relative in required_paths:
        candidate = (source_path / relative).resolve()
        _assert_under_source(candidate, source_path)
        if not candidate.exists():
            raise SourceUnavailableError(f"required source path does not exist: {relative}")
        if candidate.is_file():
            files.append(candidate)
        else:
            files.extend(path for path in candidate.rglob("*") if path.is_file())

    manifest_files = []
    seen: set[str] = set()
    for path in sorted(files):
        relative_path = path.relative_to(source_path).as_posix()
        if relative_path in seen:
            continue
        seen.add(relative_path)
        manifest_files.append(
            {
                "path": relative_path,
                "sha256": _sha256(path.read_bytes()),
                "size": path.stat().st_size,
            }
        )
    return SourceManifest(source_path=source_path, files=manifest_files)


def fingerprint_manifest(manifest: SourceManifest) -> str:
    digest = hashlib.sha256()
    for item in manifest.files:
        digest.update(item["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(item["sha256"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item["size"]).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _source_path(source: SkillSource) -> Path:
    if not source.local_path:
        raise SourceUnavailableError(f"source local_path is not configured: {source.slug}")
    return Path(source.local_path).expanduser().resolve()


def _assert_under_source(path: Path, source_path: Path) -> None:
    if not path.is_relative_to(source_path):
        raise SourceUnavailableError(f"source required path escapes source root: {path}")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _git(cwd: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise SourceUnavailableError(f"git command failed: {' '.join(args)}") from exc
    return result.stdout


def _git_optional(cwd: Path, *args: str) -> str | None:
    try:
        return _git(cwd, *args)
    except SourceUnavailableError:
        return None
