from pathlib import Path

from parsers.artifact import ParsedDocument, parsed_document_from_text


def parse_text(path: Path) -> str:
    return parse_text_document(path).plain_text


def parse_text_document(path: Path) -> ParsedDocument:
    return parsed_document_from_text(
        path.read_text(encoding="utf-8", errors="replace"),
        parser_name="utf8_text",
        source_path=path,
    )
