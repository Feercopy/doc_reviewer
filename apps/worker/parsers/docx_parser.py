from pathlib import Path
import re
from xml.etree import ElementTree
from zipfile import ZipFile

from parsers.artifact import ParsedDocument, ParserInfo, ParseQuality, build_blocks_from_output


DOCX_MAIN_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
DOTX_MAIN_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"
NAMESPACES = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def parse_docx(path: Path) -> str:
    return parse_docx_document(path).plain_text


def parse_docx_document(path: Path) -> ParsedDocument:
    with ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml")
        relationships = _read_docx_relationships(archive)
        styles = _read_docx_styles(archive)
        numbering = _read_docx_numbering(archive)

    root = ElementTree.fromstring(document_xml)
    body = root.find("w:body", NAMESPACES)
    block_inputs: list[dict[str, object]] = []
    table_count = 0
    list_counters: dict[tuple[str, int], int] = {}

    if body is not None:
        for child in body:
            tag = _local_name(child.tag)
            if tag == "p":
                markdown = _paragraph_to_markdown(child, relationships, styles, numbering, list_counters)
                if not markdown:
                    continue
                block_inputs.append(
                    {
                        "type": _paragraph_block_type(child, styles, numbering),
                        "text": markdown,
                        "markdown": markdown,
                        "metadata": _paragraph_metadata(child, styles),
                    }
                )
            elif tag == "tbl":
                markdown = _table_to_markdown(child, relationships, styles, numbering)
                if not markdown:
                    continue
                table_count += 1
                rows, columns = _table_dimensions(child)
                block_inputs.append(
                    {
                        "type": "table",
                        "text": markdown,
                        "markdown": markdown,
                        "metadata": {"rows": rows, "columns": columns},
                    }
                )

    plain_text, markdown, blocks = build_blocks_from_output(block_inputs)
    warnings = ["empty_text_extraction"] if not plain_text.strip() else []
    return ParsedDocument(
        plain_text=plain_text,
        markdown=markdown,
        blocks=blocks,
        parser=ParserInfo(
            name="ooxml-docx",
            version=None,
            options={"source": "zipfile.ElementTree"},
        ),
        quality=ParseQuality(
            char_count=len(plain_text),
            block_count=len(blocks),
            table_count=table_count,
            warnings=warnings,
        ),
    )


def _read_docx_relationships(archive: ZipFile) -> dict[str, str]:
    xml = _read_optional_archive_member(archive, "word/_rels/document.xml.rels")
    if xml is None:
        return {}
    root = ElementTree.fromstring(xml)
    relationships: dict[str, str] = {}
    for relationship in root.findall("rel:Relationship", NAMESPACES):
        relationship_id = relationship.get("Id")
        target = relationship.get("Target")
        if relationship_id and target:
            relationships[relationship_id] = target
    return relationships


def _read_docx_styles(archive: ZipFile) -> dict[str, str]:
    xml = _read_optional_archive_member(archive, "word/styles.xml")
    if xml is None:
        return {}
    root = ElementTree.fromstring(xml)
    styles: dict[str, str] = {}
    for style in root.findall("w:style", NAMESPACES):
        style_id = _word_attr(style, "styleId")
        name = style.find("w:name", NAMESPACES)
        name_value = _word_attr(name, "val") if name is not None else None
        if style_id and name_value:
            styles[style_id] = name_value
    return styles


def _read_docx_numbering(archive: ZipFile) -> dict[str, dict[int, dict[str, int | str]]]:
    xml = _read_optional_archive_member(archive, "word/numbering.xml")
    if xml is None:
        return {}
    root = ElementTree.fromstring(xml)
    abstract_levels: dict[str, dict[int, dict[str, int | str]]] = {}
    for abstract_num in root.findall("w:abstractNum", NAMESPACES):
        abstract_id = _word_attr(abstract_num, "abstractNumId")
        if not abstract_id:
            continue
        levels: dict[int, dict[str, int | str]] = {}
        for level in abstract_num.findall("w:lvl", NAMESPACES):
            level_index = _int_or_default(_word_attr(level, "ilvl"), 0)
            num_format = level.find("w:numFmt", NAMESPACES)
            start = level.find("w:start", NAMESPACES)
            levels[level_index] = {
                "format": _word_attr(num_format, "val") if num_format is not None else "decimal",
                "start": _int_or_default(_word_attr(start, "val") if start is not None else None, 1),
            }
        abstract_levels[abstract_id] = levels

    numbering: dict[str, dict[int, dict[str, int | str]]] = {}
    for num in root.findall("w:num", NAMESPACES):
        num_id = _word_attr(num, "numId")
        abstract_id_node = num.find("w:abstractNumId", NAMESPACES)
        abstract_id = _word_attr(abstract_id_node, "val") if abstract_id_node is not None else None
        if not num_id or not abstract_id:
            continue
        levels = {level: values.copy() for level, values in abstract_levels.get(abstract_id, {}).items()}
        for override in num.findall("w:lvlOverride", NAMESPACES):
            level_index = _int_or_default(_word_attr(override, "ilvl"), 0)
            start_override = override.find("w:startOverride", NAMESPACES)
            if start_override is not None:
                levels.setdefault(level_index, {"format": "decimal", "start": 1})
                levels[level_index]["start"] = _int_or_default(_word_attr(start_override, "val"), 1)
        numbering[num_id] = levels
    return numbering


def _read_optional_archive_member(archive: ZipFile, name: str) -> bytes | None:
    try:
        return archive.read(name)
    except KeyError:
        return None


def _paragraph_to_markdown(
    paragraph: ElementTree.Element,
    relationships: dict[str, str],
    styles: dict[str, str],
    numbering: dict[str, dict[int, dict[str, int | str]]],
    list_counters: dict[tuple[str, int], int],
) -> str:
    text = _clean_inline_text(_inline_text(paragraph, relationships))
    if not text:
        return ""

    heading_level = _heading_level(paragraph, styles)
    if heading_level:
        return f"{'#' * heading_level} {text}"

    list_info = _paragraph_list_info(paragraph, numbering)
    if list_info is None:
        return text

    num_id, level, num_format, start = list_info
    indent = "  " * level
    if num_format in {"bullet", "none"}:
        return f"{indent}- {text}"

    for counter_key in list(list_counters):
        if counter_key[0] == num_id and counter_key[1] > level:
            del list_counters[counter_key]
    counter_key = (num_id, level)
    current = list_counters.get(counter_key, start - 1) + 1
    list_counters[counter_key] = current
    return f"{indent}{current}. {text}"


def _table_to_markdown(
    table: ElementTree.Element,
    relationships: dict[str, str],
    styles: dict[str, str],
    numbering: dict[str, dict[int, dict[str, int | str]]],
) -> str:
    rows: list[list[str]] = []
    for row in table.findall("w:tr", NAMESPACES):
        cells: list[str] = []
        for cell in row.findall("w:tc", NAMESPACES):
            cells.append(_table_cell_to_text(cell, relationships, styles, numbering))
            span = _table_cell_grid_span(cell)
            cells.extend("" for _ in range(max(0, span - 1)))
        if any(value for value in cells):
            rows.append(cells)
    if not rows:
        return ""

    column_count = max(len(row) for row in rows)
    rows = [row + [""] * (column_count - len(row)) for row in rows]
    headers = [value or f"Column {index + 1}" for index, value in enumerate(rows[0])]
    lines = [
        _format_markdown_table_row(headers),
        _format_markdown_table_row(["---"] * column_count),
    ]
    lines.extend(_format_markdown_table_row(row) for row in rows[1:])
    return "\n".join(lines)


def _table_cell_to_text(
    cell: ElementTree.Element,
    relationships: dict[str, str],
    styles: dict[str, str],
    numbering: dict[str, dict[int, dict[str, int | str]]],
) -> str:
    parts: list[str] = []
    list_counters: dict[tuple[str, int], int] = {}
    for child in cell:
        tag = _local_name(child.tag)
        if tag == "p":
            paragraph = _paragraph_to_markdown(child, relationships, styles, numbering, list_counters)
            if paragraph:
                parts.append(paragraph)
        elif tag == "tbl":
            nested_table = _table_to_markdown(child, relationships, styles, numbering)
            if nested_table:
                parts.append(nested_table)
    return "<br>".join(parts)


def _inline_text(node: ElementTree.Element, relationships: dict[str, str]) -> str:
    parts: list[str] = []
    for child in node:
        tag = _local_name(child.tag)
        if tag in {"pPr", "rPr"}:
            continue
        if tag == "t":
            parts.append(child.text or "")
        elif tag == "tab":
            parts.append(" ")
        elif tag in {"br", "cr"}:
            parts.append("\n")
        elif tag == "noBreakHyphen":
            parts.append("-")
        elif tag in {"softHyphen", "instrText", "delText"}:
            continue
        elif tag == "hyperlink":
            label = _clean_inline_text(_inline_text(child, relationships))
            relationship_id = child.get(f"{{{NAMESPACES['r']}}}id")
            target = relationships.get(relationship_id or "")
            if label and target:
                parts.append(f"[{_escape_markdown_link_label(label)}]({target})")
            else:
                parts.append(label)
        elif tag in {"del", "moveFrom"}:
            continue
        else:
            parts.append(_inline_text(child, relationships))
    return "".join(parts)


def _clean_inline_text(value: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line.replace("\u00a0", " ")).strip() for line in value.splitlines()]
    return "<br>".join(line for line in lines if line)


def _paragraph_block_type(
    paragraph: ElementTree.Element,
    styles: dict[str, str],
    numbering: dict[str, dict[int, dict[str, int | str]]],
) -> str:
    if _heading_level(paragraph, styles):
        return "heading"
    if _paragraph_list_info(paragraph, numbering) is not None:
        return "list_item"
    return "paragraph"


def _paragraph_metadata(paragraph: ElementTree.Element, styles: dict[str, str]) -> dict[str, str | None]:
    style = paragraph.find("w:pPr/w:pStyle", NAMESPACES)
    style_id = _word_attr(style, "val") if style is not None else None
    return {"style_id": style_id, "style": styles.get(style_id or "")}


def _heading_level(paragraph: ElementTree.Element, styles: dict[str, str]) -> int | None:
    style = paragraph.find("w:pPr/w:pStyle", NAMESPACES)
    style_id = _word_attr(style, "val") if style is not None else None
    candidates = [style_id or "", styles.get(style_id or "", "")]
    for candidate in candidates:
        normalized = re.sub(r"[\s_-]+", "", candidate).lower()
        match = re.search(r"(?:heading|заголовок)([1-6])", normalized)
        if match:
            return int(match.group(1))
    return None


def _paragraph_list_info(
    paragraph: ElementTree.Element,
    numbering: dict[str, dict[int, dict[str, int | str]]],
) -> tuple[str, int, str, int] | None:
    num_pr = paragraph.find("w:pPr/w:numPr", NAMESPACES)
    if num_pr is None:
        return None
    num_id_node = num_pr.find("w:numId", NAMESPACES)
    if num_id_node is None:
        return None
    num_id = _word_attr(num_id_node, "val")
    if not num_id:
        return None
    level_node = num_pr.find("w:ilvl", NAMESPACES)
    level = _int_or_default(_word_attr(level_node, "val") if level_node is not None else None, 0)
    level_info = numbering.get(num_id, {}).get(level, {"format": "decimal", "start": 1})
    num_format = str(level_info.get("format") or "decimal")
    start = _int_or_default(level_info.get("start"), 1)
    return num_id, level, num_format, start


def _table_dimensions(table: ElementTree.Element) -> tuple[int, int]:
    rows: list[list[str]] = []
    for row in table.findall("w:tr", NAMESPACES):
        cells: list[str] = []
        for cell in row.findall("w:tc", NAMESPACES):
            cells.append("")
            span = _table_cell_grid_span(cell)
            cells.extend("" for _ in range(max(0, span - 1)))
        if cells:
            rows.append(cells)
    return len(rows), max((len(row) for row in rows), default=0)


def _table_cell_grid_span(cell: ElementTree.Element) -> int:
    grid_span = cell.find("w:tcPr/w:gridSpan", NAMESPACES)
    return _int_or_default(_word_attr(grid_span, "val") if grid_span is not None else None, 1)


def _format_markdown_table_row(values: list[str]) -> str:
    return "| " + " | ".join(_escape_markdown_table_cell(value) for value in values) + " |"


def _escape_markdown_table_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", "<br>").strip()


def _escape_markdown_link_label(value: str) -> str:
    return value.replace("[", r"\[").replace("]", r"\]")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _word_attr(element: ElementTree.Element | None, name: str) -> str | None:
    if element is None:
        return None
    return element.get(f"{{{NAMESPACES['w']}}}{name}")


def _int_or_default(value: object, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
