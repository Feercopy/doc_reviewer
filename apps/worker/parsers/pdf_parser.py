from pathlib import Path

from pypdf import PdfReader

from parsers.artifact import ParsedDocument, ParserInfo, ParseQuality, build_blocks_from_output, package_version


def parse_pdf(path: Path) -> str:
    return parse_pdf_document(path).plain_text


def parse_pdf_document(path: Path) -> ParsedDocument:
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
