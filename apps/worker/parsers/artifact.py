from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re


PARSE_ARTIFACT_SCHEMA_VERSION = "document_parse_artifact.v1"
PARSER_ADAPTER_VERSION = "gate_challenger_parser.v1"


@dataclass(frozen=True)
class ParserInfo:
    name: str
    version: str | None = None
    adapter_version: str = PARSER_ADAPTER_VERSION
    options: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "adapter_version": self.adapter_version,
            "options": self.options,
        }


@dataclass(frozen=True)
class ParseBlock:
    id: str
    type: str
    text: str
    markdown: str
    page: int | None
    text_span: dict[str, int]
    hash: str
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "type": self.type,
            "text": self.text,
            "markdown": self.markdown,
            "page": self.page,
            "text_span": self.text_span,
            "hash": self.hash,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ParseQuality:
    char_count: int
    block_count: int
    page_count: int | None = None
    table_count: int = 0
    empty_pages: list[int] = field(default_factory=list)
    ocr_used: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "char_count": self.char_count,
            "block_count": self.block_count,
            "page_count": self.page_count,
            "table_count": self.table_count,
            "empty_pages": self.empty_pages,
            "ocr_used": self.ocr_used,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class ParsedDocument:
    plain_text: str
    markdown: str
    blocks: list[ParseBlock]
    parser: ParserInfo
    quality: ParseQuality

    def to_artifact(
        self,
        *,
        source_filename: str,
        source_mime_type: str,
        source_sha256: str,
        source_size_bytes: int,
    ) -> dict[str, object]:
        return {
            "schema_version": PARSE_ARTIFACT_SCHEMA_VERSION,
            "source": {
                "filename": source_filename,
                "mime_type": source_mime_type,
                "sha256": source_sha256,
                "size_bytes": source_size_bytes,
            },
            "parser": self.parser.to_dict(),
            "outputs": {
                "plain_text": self.plain_text,
                "markdown": self.markdown,
                "plain_text_sha256": _text_hash(self.plain_text),
                "markdown_sha256": _text_hash(self.markdown),
            },
            "blocks": [block.to_dict() for block in self.blocks],
            "quality": self.quality.to_dict(),
        }


def package_version(package_name: str) -> str | None:
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None


def build_blocks_from_output(
    block_inputs: list[dict[str, object]],
    *,
    plain_text: str | None = None,
    markdown: str | None = None,
) -> tuple[str, str, list[ParseBlock]]:
    plain_parts = [str(item.get("text") or "") for item in block_inputs]
    markdown_parts = [str(item.get("markdown") or item.get("text") or "") for item in block_inputs]
    plain_output = plain_text if plain_text is not None else "\n\n".join(part for part in plain_parts if part)
    markdown_output = markdown if markdown is not None else "\n\n".join(part for part in markdown_parts if part)

    blocks: list[ParseBlock] = []
    cursor = 0
    for index, item in enumerate(block_inputs, start=1):
        text = str(item.get("text") or "")
        if not text:
            continue
        start = plain_output.find(text, cursor)
        if start < 0:
            start = plain_output.find(text)
        if start < 0:
            start = cursor
        end = start + len(text)
        cursor = end
        blocks.append(
            ParseBlock(
                id=f"b{index:04d}",
                type=str(item.get("type") or "paragraph"),
                text=text,
                markdown=str(item.get("markdown") or text),
                page=item.get("page") if isinstance(item.get("page"), int) else None,
                text_span={"start": start, "end": end},
                hash=_text_hash(text),
                metadata=dict(item.get("metadata") or {}),
            )
        )

    return plain_output, markdown_output, blocks


def parsed_document_from_text(text: str, *, parser_name: str, source_path: Path) -> ParsedDocument:
    block_inputs: list[dict[str, object]] = []
    for match in re.finditer(r"\S(?:.*?)(?=\n\s*\n|\Z)", text, flags=re.DOTALL):
        block_text = match.group(0).strip()
        if not block_text:
            continue
        block_type = "heading" if source_path.suffix.lower() == ".md" and block_text.startswith("#") else "paragraph"
        block_inputs.append({"type": block_type, "text": block_text, "markdown": block_text})

    _, _, blocks = build_blocks_from_output(block_inputs, plain_text=text, markdown=text)
    warnings = ["empty_text_extraction"] if not text.strip() else []
    return ParsedDocument(
        plain_text=text,
        markdown=text,
        blocks=blocks,
        parser=ParserInfo(name=parser_name, version=None),
        quality=ParseQuality(char_count=len(text), block_count=len(blocks), warnings=warnings),
    )


def _text_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()
