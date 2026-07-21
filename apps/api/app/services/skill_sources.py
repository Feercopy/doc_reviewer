import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.schemas.enums import SkillSourceType


def _find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__).resolve()).resolve()
    search_from = current if current.is_dir() else current.parent
    for candidate in (search_from, *search_from.parents):
        if (candidate / "contracts" / "schemas").is_dir():
            return candidate
    return Path.cwd()


REPO_ROOT = _find_repo_root()
CONTRACTS_SCHEMAS_ROOT = REPO_ROOT / "contracts" / "schemas"


class SkillSourceValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SkillSourceMaterial:
    prompt_text: str
    source_revision: str | None
    source_fingerprint: str | None
    source_metadata: dict


def validate_result_schema_path(result_schema_path: str) -> None:
    candidate = (REPO_ROOT / result_schema_path).resolve()
    schema_root = CONTRACTS_SCHEMAS_ROOT.resolve()
    if not candidate.is_relative_to(schema_root):
        raise SkillSourceValidationError("result_schema_path must point under contracts/schemas")
    if not candidate.is_file():
        raise SkillSourceValidationError("result_schema_path does not exist")


def resolve_skill_source_material(
    *,
    source_type: SkillSourceType,
    source_uri: str | None,
    source_entrypoint: str | None,
    prompt_text: str,
    source_metadata: dict | None,
) -> SkillSourceMaterial:
    metadata = dict(source_metadata or {})
    if source_type == SkillSourceType.INLINE_PROMPT:
        return SkillSourceMaterial(
            prompt_text=prompt_text,
            source_revision=None,
            source_fingerprint=_fingerprint_inline_prompt(prompt_text),
            source_metadata=metadata,
        )

    entrypoint_path = _resolve_entrypoint_path(source_uri=source_uri, source_entrypoint=source_entrypoint)
    material_paths = [entrypoint_path]

    if source_type == SkillSourceType.LOCAL_KNOWLEDGE_BASE:
        wiki_path_value = metadata.get("wiki_path")
        if wiki_path_value:
            wiki_path = Path(wiki_path_value).expanduser()
            if not wiki_path.exists() or not wiki_path.is_dir():
                raise SkillSourceValidationError("source_metadata.wiki_path must point to an existing directory")
            metadata["wiki_fingerprint"] = _fingerprint_path(wiki_path)
            material_paths.extend(_selected_wiki_paths(wiki_path=wiki_path, metadata=metadata))

    return SkillSourceMaterial(
        prompt_text=entrypoint_path.read_text(encoding="utf-8"),
        source_revision=_git_revision(entrypoint_path),
        source_fingerprint=_fingerprint_paths(material_paths),
        source_metadata=metadata,
    )


def refresh_skill_source_material(skill) -> SkillSourceMaterial:
    return resolve_skill_source_material(
        source_type=SkillSourceType(skill.source_type),
        source_uri=skill.source_uri,
        source_entrypoint=skill.source_entrypoint,
        prompt_text=skill.prompt_text,
        source_metadata=skill.source_metadata,
    )


def _resolve_entrypoint_path(*, source_uri: str | None, source_entrypoint: str | None) -> Path:
    if not source_uri:
        raise SkillSourceValidationError("source_uri is required for local skill sources")

    source_path = Path(source_uri).expanduser()
    if source_path.is_file():
        entrypoint_path = source_path
    elif source_path.is_dir() and source_entrypoint:
        entrypoint_path = source_path / source_entrypoint
    else:
        raise SkillSourceValidationError("source_uri must be a file or a directory with source_entrypoint")

    if not entrypoint_path.exists() or not entrypoint_path.is_file():
        raise SkillSourceValidationError("source entrypoint does not exist")
    return entrypoint_path


def _selected_wiki_paths(*, wiki_path: Path, metadata: dict) -> list[Path]:
    candidates = [
        wiki_path / "schema.md",
        wiki_path / "meta" / "output-format.md",
    ]
    for page in metadata.get("selected_wiki_pages") or []:
        candidates.append(wiki_path / page)
    return [path for path in candidates if path.exists() and path.is_file()]


def _fingerprint_inline_prompt(prompt_text: str) -> str:
    digest = hashlib.sha256()
    digest.update(b"inline_prompt\0")
    digest.update(prompt_text.encode("utf-8"))
    return digest.hexdigest()


def _fingerprint_path(path: Path) -> str:
    if path.is_file():
        return _fingerprint_paths([path])
    paths = sorted(child for child in path.rglob("*") if child.is_file())
    return _fingerprint_paths(paths)


def _fingerprint_paths(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _git_revision(path: Path) -> str | None:
    target = path if path.is_dir() else path.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout.strip()
