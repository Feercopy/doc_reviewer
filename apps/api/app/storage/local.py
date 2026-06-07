from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import UUID
import hashlib
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

    def parsed_artifact_path(self, *, owner_id: UUID, document_id: UUID) -> Path:
        return self._ensure_under_root(
            self.storage_root / "documents" / str(owner_id) / str(document_id) / "parsed" / "parsed.txt"
        )

    def _ensure_under_root(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.storage_root):
            raise ValueError("Storage path escapes STORAGE_ROOT")
        return resolved
