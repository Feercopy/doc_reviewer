from pathlib import Path

from pypdf import PdfReader


def parse_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages: list[str] = []

    for index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        pages.append(f"[Page {index}]\n{page_text.strip()}")

    return "\n\n".join(pages)
