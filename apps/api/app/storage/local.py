from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import UUID
import hashlib
import json
import re
import unicodedata


CHUNK_SIZE_BYTES = 1024 * 1024


class StoredFileTooLargeError(ValueError):
    pass


@dataclass(frozen=True)
class StoredFile:
    path: Path
    sha256: str
    size_bytes: int
    safe_original_filename: str


def safe_filename(filename: str | None) -> str:
    original_name = Path(filename or "").name
    normalized = unicodedata.normalize("NFKD", original_name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_name).strip("._")
    return cleaned[:180] or "upload"


class LocalDocumentStorage:
    def __init__(self, storage_root: Path) -> None:
        self.storage_root = storage_root.expanduser().resolve()

    def save_raw_file(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
        original_filename: str | None,
        source: BinaryIO,
        max_size_bytes: int,
    ) -> StoredFile:
        safe_original_filename = safe_filename(original_filename)
        raw_dir = self._ensure_under_root(
            self.storage_root / "documents" / str(owner_id) / str(document_id) / "raw"
        )
        raw_dir.mkdir(parents=True, exist_ok=True)

        temp_path = self._ensure_under_root(raw_dir / f".{document_id}.uploading")
        digest = hashlib.sha256()
        size_bytes = 0

        try:
            with temp_path.open("wb") as target:
                while chunk := source.read(CHUNK_SIZE_BYTES):
                    size_bytes += len(chunk)
                    if size_bytes > max_size_bytes:
                        raise StoredFileTooLargeError("File exceeds maximum upload size")
                    digest.update(chunk)
                    target.write(chunk)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        sha256 = digest.hexdigest()
        final_path = self._ensure_under_root(raw_dir / f"{sha256}-{safe_original_filename}")
        temp_path.replace(final_path)
        return StoredFile(
            path=final_path,
            sha256=sha256,
            size_bytes=size_bytes,
            safe_original_filename=safe_original_filename,
        )

    def save_parsed_artifact(self, *, owner_id: UUID, document_id: UUID, parsed_text: str) -> Path:
        parsed_path = self.parsed_artifact_path(owner_id=owner_id, document_id=document_id)
        parsed_path.parent.mkdir(parents=True, exist_ok=True)
        parsed_path.write_text(parsed_text, encoding="utf-8")
        return parsed_path

    def save_parsed_artifacts(
        self,
        *,
        owner_id: UUID,
        document_id: UUID,
        parsed_text: str,
        parsed_markdown: str | None = None,
        structured_artifact: dict | None = None,
        quality_report: dict | None = None,
    ) -> dict[str, Path]:
        parsed_dir = self.parsed_artifact_dir(owner_id=owner_id, document_id=document_id)
        parsed_dir.mkdir(parents=True, exist_ok=True)

        artifacts = {
            "parsed_text": self._ensure_under_root(parsed_dir / "parsed.txt"),
        }
        artifacts["parsed_text"].write_text(parsed_text, encoding="utf-8")

        if parsed_markdown is not None:
            artifacts["parsed_markdown"] = self._ensure_under_root(parsed_dir / "parsed.md")
            artifacts["parsed_markdown"].write_text(parsed_markdown, encoding="utf-8")
        if structured_artifact is not None:
            artifacts["structured"] = self._ensure_under_root(parsed_dir / "structured.json")
            artifacts["structured"].write_text(
                json.dumps(structured_artifact, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if quality_report is not None:
            artifacts["quality"] = self._ensure_under_root(parsed_dir / "quality.json")
            artifacts["quality"].write_text(
                json.dumps(quality_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return artifacts

    def parsed_artifact_path(self, *, owner_id: UUID, document_id: UUID) -> Path:
        return self._ensure_under_root(self.parsed_artifact_dir(owner_id=owner_id, document_id=document_id) / "parsed.txt")

    def parsed_artifact_dir(self, *, owner_id: UUID, document_id: UUID) -> Path:
        return self._ensure_under_root(self.storage_root / "documents" / str(owner_id) / str(document_id) / "parsed")

    def save_rendered_prompt(self, *, analysis_id: UUID, prompt: str) -> Path:
        prompt_path = self._ensure_under_root(self.storage_root / "rendered-prompts" / str(analysis_id) / "prompt.txt")
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        return prompt_path

    def save_skill_source_snapshot(self, *, snapshot_id: UUID, manifest: dict) -> Path:
        snapshot_dir = self._ensure_under_root(self.storage_root / "skill-snapshots" / str(snapshot_id))
        files_dir = self._ensure_under_root(snapshot_dir / "files")
        files_dir.mkdir(parents=True, exist_ok=True)

        for item in manifest.get("files", []):
            relative_path = self._safe_relative_path(item["path"])
            source_path = Path(item["source_path"])
            target_path = self._ensure_under_root(files_dir / relative_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(source_path.read_bytes())

        manifest_path = self._ensure_under_root(snapshot_dir / "manifest.json")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return snapshot_dir

    def save_retrieval_snapshot(
        self,
        *,
        snapshot_id: UUID,
        dossier: dict,
        source_snapshot_artifact_path: str,
    ) -> Path:
        snapshot_dir = self._ensure_under_root(self.storage_root / "retrieval-snapshots" / str(snapshot_id))
        selected_dir = self._ensure_under_root(snapshot_dir / "selected")
        selected_dir.mkdir(parents=True, exist_ok=True)
        source_files_dir = Path(source_snapshot_artifact_path).expanduser().resolve() / "files"

        evidence_paths = [
            section.get("path")
            for section in (dossier.get("evidence_packet") or {}).get("sections", [])
            if section.get("path")
        ]
        for path in [*dossier.get("selected_paths", []), *evidence_paths]:
            relative_path = self._safe_relative_path(path)
            source_path = (source_files_dir / relative_path).resolve()
            if not source_path.is_relative_to(source_files_dir) or not source_path.is_file():
                continue
            target_path = self._ensure_under_root(selected_dir / relative_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(source_path.read_bytes())

        dossier_path = self._ensure_under_root(snapshot_dir / "dossier.json")
        dossier_path.write_text(json.dumps(dossier, ensure_ascii=False, indent=2), encoding="utf-8")
        evidence_markdown = (dossier.get("evidence_packet") or {}).get("markdown")
        if evidence_markdown:
            evidence_path = self._ensure_under_root(snapshot_dir / "evidence_packet.md")
            evidence_path.write_text(str(evidence_markdown), encoding="utf-8")
        return snapshot_dir

    def _ensure_under_root(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.storage_root):
            raise ValueError("Storage path escapes STORAGE_ROOT")
        return resolved

    def _safe_relative_path(self, path: str) -> Path:
        relative = Path(path)
        if relative.is_absolute() or any(part == ".." for part in relative.parts):
            raise ValueError("Storage path escapes STORAGE_ROOT")
        return relative
