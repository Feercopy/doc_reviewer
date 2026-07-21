from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import re

from parsers.artifact import ParsedDocument, ParserInfo, ParseQuality, build_blocks_from_output, package_version


DOCLING_SUPPORTED_EXTENSIONS = {".docx", ".pdf"}


class DoclingParserUnavailableError(RuntimeError):
    pass


def is_docling_available() -> bool:
    if find_spec("docling") is None:
        return False
    return find_spec("docling.document_converter") is not None


def parse_docling_document(path: Path) -> ParsedDocument:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise DoclingParserUnavailableError("Docling is not installed") from exc

    try:
        converter = DocumentConverter()
        converted = converter.convert(source=path)
    except Exception as exc:
        raise DoclingParserUnavailableError("Docling conversion failed") from exc
    markdown = _export_markdown(converted.document)
    block_inputs = _markdown_block_inputs(markdown)
    plain_text, markdown_output, blocks = build_blocks_from_output(
        block_inputs,
        plain_text=markdown,
        markdown=markdown,
    )
    warnings = ["empty_text_extraction"] if not plain_text.strip() else []
    return ParsedDocument(
        plain_text=plain_text,
        markdown=markdown_output,
        blocks=blocks,
        parser=ParserInfo(
            name="docling",
            version=package_version("docling"),
            options={"source": "docling.document_converter.DocumentConverter"},
        ),
        quality=ParseQuality(
            char_count=len(plain_text),
            block_count=len(blocks),
            table_count=_count_markdown_tables(markdown),
            warnings=warnings,
        ),
    )


def _export_markdown(document: object) -> str:
    export_to_markdown = getattr(document, "export_to_markdown", None)
    if callable(export_to_markdown):
        return str(export_to_markdown())

    try:
        from docling_core.transforms.serializer.markdown import MarkdownDocSerializer
    except ImportError as exc:
        raise DoclingParserUnavailableError("Docling markdown serializer is not installed") from exc

    serialized = MarkdownDocSerializer(doc=document).serialize()
    return str(serialized.text)


def _markdown_block_inputs(markdown: str) -> list[dict[str, object]]:
    block_inputs: list[dict[str, object]] = []
    for match in re.finditer(r"\S(?:.*?)(?=\n\s*\n|\Z)", markdown, flags=re.DOTALL):
        text = match.group(0).strip()
        if not text:
            continue
        block_inputs.append({"type": _markdown_block_type(text), "text": text, "markdown": text})
    return block_inputs


def _markdown_block_type(text: str) -> str:
    if text.startswith("#"):
        return "heading"
    if _is_markdown_table(text):
        return "table"
    if text.startswith(("- ", "* ")):
        return "list_item"
    return "paragraph"


def _is_markdown_table(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return len(lines) >= 2 and lines[0].startswith("|") and re.match(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", lines[1]) is not None


def _count_markdown_tables(markdown: str) -> int:
    return sum(1 for block in _markdown_block_inputs(markdown) if block["type"] == "table")
