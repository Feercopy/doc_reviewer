from pathlib import Path

from parsers.docx_parser import parse_docx
from parsers.pdf_parser import parse_pdf
from parsers.text_parser import parse_text


class UnsupportedParserFileTypeError(ValueError):
    pass


def parse_file(path: Path | str) -> str:
    document_path = Path(path)
    extension = document_path.suffix.lower()

    if extension in {".txt", ".md"}:
        return parse_text(document_path)
    if extension in {".docx", ".dotx"}:
        return parse_docx(document_path)
    if extension == ".pdf":
        return parse_pdf(document_path)

    raise UnsupportedParserFileTypeError(f"Unsupported parser file type: {extension or '<none>'}")


__all__ = ["UnsupportedParserFileTypeError", "parse_file"]
