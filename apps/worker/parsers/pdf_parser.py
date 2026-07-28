from pathlib import Path

from pypdf import PdfReader

from parsers.artifact import ParsedDocument, ParserInfo, ParseQuality, build_blocks_from_output, package_version


def parse_pdf(path: Path) -> str:
    return parse_pdf_document(path).plain_text


def parse_pdf_document(path: Path) -> ParsedDocument:
    try:
        return _parse_pdf_with_pdfplumber(path)
    except Exception as exc:
        return _parse_pdf_with_pypdf(path, fallback_warning=f"pdfplumber_failed:{exc.__class__.__name__}")


def _parse_pdf_with_pdfplumber(path: Path) -> ParsedDocument:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber is not installed") from exc

    block_inputs: list[dict[str, object]] = []
    empty_pages: list[int] = []
    table_count = 0
    image_count = 0

    with pdfplumber.open(str(path)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            page_blocks = _pdfplumber_page_blocks(page, page_number=index)
            if not page_blocks:
                empty_pages.append(index)
                page_blocks = [
                    {
                        "type": "page",
                        "text": f"[Page {index}]",
                        "markdown": f"<!-- page {index} -->",
                        "page": index,
                        "metadata": {"extractor": "pdfplumber", "empty": True},
                    }
                ]
            table_count += sum(1 for block in page_blocks if block.get("type") == "table")
            image_count += sum(1 for block in page_blocks if block.get("type") == "image")
            block_inputs.extend(page_blocks)

        plain_text, markdown, blocks = build_blocks_from_output(block_inputs)
        warnings: list[str] = []
        if not plain_text.strip():
            warnings.append("empty_text_extraction")
        if empty_pages:
            warnings.append("empty_pages_detected")
        if image_count:
            warnings.append("image_placeholders_emitted")
        return ParsedDocument(
            plain_text=plain_text,
            markdown=markdown,
            blocks=blocks,
            parser=ParserInfo(
                name="pdfplumber",
                version=package_version("pdfplumber"),
                options={"fallback": "pypdf"},
            ),
            quality=ParseQuality(
                char_count=len(plain_text),
                block_count=len(blocks),
                page_count=len(pdf.pages),
                table_count=table_count,
                empty_pages=empty_pages,
                warnings=warnings,
            ),
        )


def _pdfplumber_page_blocks(page: object, *, page_number: int) -> list[dict[str, object]]:
    tables = list(page.find_tables() or [])
    table_boxes = [tuple(table.bbox) for table in tables if getattr(table, "bbox", None)]
    blocks: list[tuple[float, int, dict[str, object]]] = []

    text_lines = _extract_lines_outside_boxes(page, table_boxes)
    for order, line in enumerate(text_lines):
        text = line["text"].strip()
        if not text:
            continue
        blocks.append(
            (
                float(line["top"]),
                order,
                {
                    "type": "paragraph",
                    "text": text,
                    "markdown": text,
                    "page": page_number,
                    "metadata": {"extractor": "pdfplumber"},
                },
            )
        )

    for order, table in enumerate(tables, start=1):
        rows = _clean_table_rows(table.extract() or [])
        if not rows:
            continue
        markdown = _markdown_table(rows)
        blocks.append(
            (
                float(table.bbox[1]),
                10_000 + order,
                {
                    "type": "table",
                    "text": markdown,
                    "markdown": markdown,
                    "page": page_number,
                    "metadata": {
                        "extractor": "pdfplumber",
                        "bbox": [round(float(value), 2) for value in table.bbox],
                        "row_count": len(rows),
                        "column_count": max(len(row) for row in rows),
                    },
                },
            )
        )

    for order, image in enumerate(getattr(page, "images", []) or [], start=1):
        top = float(image.get("top") or image.get("y0") or 0)
        width = round(float(image.get("width") or 0), 2)
        height = round(float(image.get("height") or 0), 2)
        text = f"[Image on page {page_number}: {width:g} x {height:g}]"
        blocks.append(
            (
                top,
                20_000 + order,
                {
                    "type": "image",
                    "text": text,
                    "markdown": f"> {text}",
                    "page": page_number,
                    "metadata": {
                        "extractor": "pdfplumber",
                        "index": order,
                        "bbox": _image_bbox(image),
                        "width": width,
                        "height": height,
                    },
                },
            )
        )

    return [
        {
            "type": "page",
            "text": f"[Page {page_number}]",
            "markdown": f"<!-- page {page_number} -->",
            "page": page_number,
            "metadata": {"extractor": "pdfplumber"},
        },
        *[block for _, _, block in sorted(blocks, key=lambda item: (item[0], item[1]))],
    ]


def _extract_lines_outside_boxes(page: object, boxes: list[tuple[float, float, float, float]]) -> list[dict[str, object]]:
    words = []
    for word in page.extract_words(use_text_flow=False, keep_blank_chars=False) or []:
        x_center = (float(word["x0"]) + float(word["x1"])) / 2
        y_center = (float(word["top"]) + float(word["bottom"])) / 2
        if any(_point_in_box(x_center, y_center, box) for box in boxes):
            continue
        words.append(word)

    lines: list[dict[str, object]] = []
    for word in sorted(words, key=lambda item: (round(float(item["top"]), 1), float(item["x0"]))):
        top = float(word["top"])
        if lines and abs(float(lines[-1]["top"]) - top) <= 3:
            lines[-1]["words"].append(word)
            lines[-1]["top"] = min(float(lines[-1]["top"]), top)
            continue
        lines.append({"top": top, "words": [word]})

    return [
        {
            "top": line["top"],
            "text": " ".join(str(word["text"]) for word in sorted(line["words"], key=lambda item: float(item["x0"]))),
        }
        for line in lines
    ]


def _point_in_box(x: float, y: float, box: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = box
    return x0 <= x <= x1 and top <= y <= bottom


def _clean_table_rows(rows: list[list[object]]) -> list[list[str]]:
    cleaned: list[list[str]] = []
    for row in rows:
        values = [str(cell or "").replace("\n", "<br>").strip() for cell in row]
        if any(values):
            cleaned.append(values)
    return cleaned


def _markdown_table(rows: list[list[str]]) -> str:
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header, *body = normalized
    separator = ["---"] * width
    return "\n".join(_markdown_table_row(row) for row in [header, separator, *body])


def _markdown_table_row(row: list[str]) -> str:
    return "| " + " | ".join(_escape_table_cell(cell) for cell in row) + " |"


def _escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|")


def _image_bbox(image: dict[str, object]) -> list[float]:
    keys = ("x0", "top", "x1", "bottom")
    return [round(float(image.get(key) or 0), 2) for key in keys]


def _parse_pdf_with_pypdf(path: Path, *, fallback_warning: str | None = None) -> ParsedDocument:
    reader = PdfReader(str(path))
    block_inputs: list[dict[str, object]] = []
    empty_pages: list[int] = []

    for index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        stripped_text = page_text.strip()
        if not stripped_text:
            empty_pages.append(index)
        page_block_text = f"[Page {index}]\n{stripped_text}"
        block_inputs.append(
            {
                "type": "page",
                "text": page_block_text,
                "markdown": f"<!-- page {index} -->\n\n{stripped_text}",
                "page": index,
                "metadata": {"extractor": "pypdf"},
            }
        )

    plain_text, markdown, blocks = build_blocks_from_output(block_inputs)
    warnings: list[str] = []
    if not plain_text.strip():
        warnings.append("empty_text_extraction")
    if empty_pages:
        warnings.append("empty_pages_detected")
    if fallback_warning:
        warnings.append(fallback_warning)
    return ParsedDocument(
        plain_text=plain_text,
        markdown=markdown,
        blocks=blocks,
        parser=ParserInfo(name="pypdf", version=package_version("pypdf")),
        quality=ParseQuality(
            char_count=len(plain_text),
            block_count=len(blocks),
            page_count=len(reader.pages),
            empty_pages=empty_pages,
            warnings=warnings,
        ),
    )
