from pathlib import Path

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from parsers.artifact import ParsedDocument, ParserInfo, ParseQuality, build_blocks_from_output, package_version


def parse_docx(path: Path) -> str:
    return parse_docx_document(path).plain_text


def parse_docx_document(path: Path) -> ParsedDocument:
    document = Document(path)
    block_inputs: list[dict[str, object]] = []
    table_count = 0

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            block_type = _paragraph_block_type(paragraph)
            block_inputs.append(
                {
                    "type": block_type,
                    "text": text,
                    "markdown": _paragraph_markdown(paragraph, text, block_type),
                    "metadata": {"style": paragraph.style.name if paragraph.style is not None else None},
                }
            )
        elif isinstance(child, CT_Tbl):
            table = Table(child, document)
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            if not any(any(cell for cell in row) for row in rows):
                continue
            table_count += 1
            text = "\n".join("\t".join(row) for row in rows)
            block_inputs.append(
                {
                    "type": "table",
                    "text": text,
                    "markdown": _table_markdown(rows),
                    "metadata": {"rows": len(rows), "columns": max((len(row) for row in rows), default=0)},
                }
            )

    plain_text, markdown, blocks = build_blocks_from_output(block_inputs)
    warnings = ["empty_text_extraction"] if not plain_text.strip() else []
    return ParsedDocument(
        plain_text=plain_text,
        markdown=markdown,
        blocks=blocks,
        parser=ParserInfo(name="python-docx", version=package_version("python-docx")),
        quality=ParseQuality(
            char_count=len(plain_text),
            block_count=len(blocks),
            table_count=table_count,
            warnings=warnings,
        ),
    )


def _paragraph_block_type(paragraph: Paragraph) -> str:
    style_name = paragraph.style.name.lower() if paragraph.style is not None else ""
    if style_name.startswith("heading"):
        return "heading"
    if style_name.startswith("list"):
        return "list_item"
    return "paragraph"


def _paragraph_markdown(paragraph: Paragraph, text: str, block_type: str) -> str:
    if block_type == "heading":
        style_name = paragraph.style.name if paragraph.style is not None else ""
        level = _heading_level(style_name)
        return f"{'#' * level} {text}"
    if block_type == "list_item":
        return f"- {text}"
    return text


def _heading_level(style_name: str) -> int:
    match = style_name.rsplit(" ", 1)
    if len(match) == 2 and match[1].isdigit():
        return min(max(int(match[1]), 1), 6)
    return 2


def _table_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""

    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    separator = ["---"] * width
    body = normalized[1:]
    lines = [
        "| " + " | ".join(_escape_table_cell(cell) for cell in header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    lines.extend("| " + " | ".join(_escape_table_cell(cell) for cell in row) + " |" for row in body)
    return "\n".join(lines)


def _escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")
