from pathlib import Path

from parsers import docling_parser
from parsers.artifact import ParsedDocument
from parsers.docx_parser import parse_docx, parse_docx_document
from parsers.pdf_parser import parse_pdf, parse_pdf_document
from parsers.text_parser import parse_text, parse_text_document


class UnsupportedParserFileTypeError(ValueError):
    pass


def parse_file(path: Path | str) -> str:
    return parse_file_to_document(path).plain_text


def parse_file_to_document(path: Path | str) -> ParsedDocument:
    document_path = Path(path)
    extension = document_path.suffix.lower()

    if extension in {".txt", ".md"}:
        return parse_text_document(document_path)
    if extension == ".docx":
        if docling_parser.is_docling_available():
            try:
                return docling_parser.parse_docling_document(document_path)
            except docling_parser.DoclingParserUnavailableError:
                pass
        return parse_docx_document(document_path)
    if extension == ".pdf":
        if docling_parser.is_docling_available():
            try:
                return docling_parser.parse_docling_document(document_path)
            except docling_parser.DoclingParserUnavailableError:
                pass
        return parse_pdf_document(document_path)

    raise UnsupportedParserFileTypeError(f"Unsupported parser file type: {extension or '<none>'}")


__all__ = ["ParsedDocument", "UnsupportedParserFileTypeError", "parse_file", "parse_file_to_document"]
