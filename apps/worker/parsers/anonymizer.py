from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlparse
import ipaddress
import json
import re
from typing import Any, Iterable

from parsers.artifact import ParseBlock, ParsedDocument, ParserInfo, ParseQuality


SANITIZER_VERSION = "strict-local-pii.v1"

PLACEHOLDER_PREFIXES = {
    "email": "EMAIL",
    "phone": "PHONE",
    "bank_details": "BANK_DETAILS",
    "name": "PERSON",
    "address": "ADDRESS",
    "ip": "IP",
    "link": "LINK",
    "identifier": "IDENTIFIER",
}

_PROTECTED = re.compile(
    r"\[(?:"
    r"email|phone|bank_details|name|address|ip|link|identifier|номер|почта|ссылка|"
    r"EMAIL|PHONE|BANK_DETAILS|PERSON|ADDRESS|IP|LINK|IDENTIFIER"
    r")(?:_[0-9]{3})?[^\]]*\]",
    re.I,
)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63})+(?![\w.-])", re.I)
_URL = re.compile(r"https?://[^\s<>\]]+", re.I)
_IP_TOKEN = re.compile(
    r"(?<![\w:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f:.]{1,39}(?![\w:])|"
    r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)",
    re.I,
)
_DIGIT_RUN = re.compile(r"(?<!\d)(?:\+?\d[\d ()\-]{7,28}\d)(?!\d)")
_BANK_LABEL = re.compile(
    r"(?i)\b(?:карта|card|сч[её]т|р/?с|к/?с|бик|инн|кпп|корр(?:еспондентский)?\s+сч[её]т|iban)\b"
    r"\s*[:№#-]?\s*([A-Z]{0,2}\d(?:[\d -]{6,32}\d))"
)
_NAME_LABEL = re.compile(
    r"(?i)\b(?:"
    r"фио|ф\.\s*и\.\s*о\.|имя|получатель|владелец|клиент|контактное\s+лицо|меня\s+зовут|"
    r"автор(?:\s+комментария)?|комментатор|подготовил|подготовила|создал|создала|ответственный|ревьюер"
    r")\s*[:—-]?\s*"
    r"([А-ЯЁа-яё][а-яё-]{1,40}(?:[ \t]+[А-ЯЁа-яё][а-яё-]{1,40}){0,2})"
)
_LATIN_NAME_LABEL = re.compile(
    r"(?i)\b(?:"
    r"author|comment author|commenter|prepared by|created by|owner|responsible|reviewer|contact person|client"
    r")\s*[:—-]?\s*"
    r"([A-Z][a-z-]{1,40}(?:[ \t]+[A-Z][a-z-]{1,40}){0,2})"
)
_COMMENT_BY_LATIN_NAME = re.compile(r"(?i)\bcomment\s+\d+\s+by\s+([A-Z][a-z-]{1,40}(?:[ \t]+[A-Z][a-z-]{1,40}){1,2})")
_FULL_NAME = re.compile(
    r"(?<![А-Яа-яЁё-])([А-ЯЁ][а-яё-]{1,40}\s+[А-ЯЁ][а-яё-]{1,40}\s+[А-ЯЁ][а-яё-]{1,40})(?![А-Яа-яЁё-])"
)
_TWO_PART_NAME = re.compile(r"(?<![А-Яа-яЁё-])([А-ЯЁ][а-яё-]{1,40}\s+[А-ЯЁ][а-яё-]{1,40})(?![А-Яа-яЁё-])")
_PATRONYMIC_NAME = re.compile(
    r"(?i)(?<![А-Яа-яЁё-])([а-яё-]{2,40}\s+[а-яё-]{2,40}\s+[а-яё-]{2,35}"
    r"(?:ович|евич|ич|овна|евна|ична))(?![А-Яа-яЁё-])"
)
_SIGNATURE_NAME = re.compile(r"(?im)(?:^|\n)\s*(?:с\s+уважением[,!]?\s*)?([А-ЯЁ][а-яё-]{1,40}\s+[А-ЯЁ][а-яё-]{1,40})\s*(?:$|\n)")
_ADDRESS = re.compile(
    r"(?i)(?<!\w)(?:(?:россия|рф)\s*,?\s*)?(?:г(?:ород)?\.?\s*[А-ЯЁ][А-Яа-яЁё .-]{1,50},?\s*)?"
    r"(?:ул(?:ица)?\.?|просп(?:ект)?\.?|пр-т|пер(?:еулок)?\.?|шоссе|наб(?:ережная)?\.?|бульвар|б-р)\s+"
    r"[А-ЯЁ0-9][А-Яа-яЁё0-9 .'-]{1,70}(?:,?\s*(?:д(?:ом)?\.?|влад(?:ение)?\.?|стр(?:оение)?\.?)\s*\d+[А-Яа-я]?)?"
    r"(?:,?\s*(?:кв(?:артира)?\.?|оф(?:ис)?\.?)\s*\d+[А-Яа-я]?)?"
)
_POSTAL_ADDRESS = re.compile(r"(?i)(?<!\d)\d{6}\s*,\s*(?:россия|рф|г\.|город|обл\.|область|край)\b[^\n;]{3,120}")
_ADDRESS_LABEL = re.compile(r"(?i)\b(?:адрес(?:\s+(?:проживания|регистрации|доставки))?|почтовый\s+адрес)\s*[:—-]\s*([^\n;]{3,160})")
_CITY_ADDRESS = re.compile(
    r"(?i)(?:г\.|город)\s*[А-ЯЁ][А-Яа-яЁё .-]{1,50},?\s*(?:д\.|дом)\s*\d+[А-Яа-я]?(?:,?\s*(?:кв\.|квартира)\s*\d+)?"
)
_LONG_IDENTIFIER = re.compile(r"(?<!\w)(?=[A-Za-z0-9_-]{24,}\b)(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]+(?!\w)")
_BROKEN_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{4,}\[(?:PHONE|BANK_DETAILS|phone|bank_details)(?:_[0-9]{3})?\][A-Za-z0-9_-]{4,}", re.I)

_NON_PERSON_TOKENS = {
    "analysis",
    "challenger",
    "comment",
    "document",
    "gate",
    "layer",
    "progress",
    "review",
    "stream",
    "strategy",
    "summary",
    "contact",
    "defense",
    "economics",
    "fit",
    "investment",
    "market",
    "metric",
    "north",
    "product",
    "rate",
    "sales",
    "star",
    "unit",
    "гейт",
    "документ",
    "комментарий",
    "обзор",
    "ревью",
}
_NON_PERSON_PHRASES = {
    "gate challenger",
    "gate review",
    "investment defense",
    "progress review",
    "stream review",
    "strategy review",
    "avito sales",
    "contact rate",
    "customer experience",
    "north star",
    "north star metric",
    "product market fit",
    "unit economics",
}
_NAME_METADATA_KEYS = {
    "author",
    "comment_author",
    "commenter",
    "created_by",
    "owner",
    "prepared_by",
    "responsible",
    "reviewer",
}
_LATIN_PERSON_VALUE = re.compile(r"^[A-Z][a-z-]{1,40}(?:\s+[A-Z][a-z-]{1,40}){1,2}$")
_CYRILLIC_PERSON_VALUE = re.compile(r"^[А-ЯЁ][а-яё-]{1,40}(?:\s+[А-ЯЁ][а-яё-]{1,40}){1,2}$")
_TITLE_LATIN_NAME_PREFIX = re.compile(
    r"(?<![A-Za-z-])([A-Z][a-z-]{1,40}(?:\s+[A-Z][a-z-]{1,40}){1,2})"
    r"(?=\s*(?:[-_:]|Gate\b|Гейт\b|$))"
)


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    kind: str
    priority: int


@dataclass(frozen=True)
class AnonymizationReport:
    person_replacements: int
    email_replacements: int
    phone_replacements: int
    bank_details_replacements: int = 0
    address_replacements: int = 0
    ip_replacements: int = 0
    link_replacements: int = 0
    identifier_replacements: int = 0
    residuals: dict[str, int] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "sanitizer_version": SANITIZER_VERSION,
            "config_hash": config_hash(),
            "person_replacements": self.person_replacements,
            "email_replacements": self.email_replacements,
            "phone_replacements": self.phone_replacements,
            "bank_details_replacements": self.bank_details_replacements,
            "address_replacements": self.address_replacements,
            "ip_replacements": self.ip_replacements,
            "link_replacements": self.link_replacements,
            "identifier_replacements": self.identifier_replacements,
            "residuals": self.residuals or {},
        }


class PiiResidueError(ValueError):
    def __init__(self, residuals: dict[str, int]) -> None:
        super().__init__("personal_data_residue_detected")
        self.residuals = residuals


class PersonalDataAnonymizer:
    def __init__(self) -> None:
        self._placeholders: dict[str, dict[str, str]] = {kind: {} for kind in PLACEHOLDER_PREFIXES}
        self._name_aliases: dict[str, str] = {}
        self._replacement_counts: dict[str, int] = {}
        self._residuals: dict[str, int] = {}

    def anonymize_document(self, document: ParsedDocument) -> tuple[ParsedDocument, AnonymizationReport]:
        self._collect_name_aliases_from_text(document.plain_text)
        self._collect_name_aliases_from_text(document.markdown)
        for block in document.blocks:
            self._collect_name_aliases_from_text(block.text)
            self._collect_name_aliases_from_text(block.markdown)
            self._collect_name_aliases_from_value(block.metadata)

        anonymized_plain_text = self.anonymize_text(document.plain_text)
        anonymized_markdown = self.anonymize_text(document.markdown)
        anonymized_blocks: list[ParseBlock] = []
        for block in document.blocks:
            anonymized_block_text = self.anonymize_text(block.text)
            anonymized_blocks.append(
                ParseBlock(
                    id=block.id,
                    type=block.type,
                    text=anonymized_block_text,
                    markdown=self.anonymize_text(block.markdown),
                    page=block.page,
                    text_span=block.text_span,
                    hash=_text_hash(anonymized_block_text),
                    metadata=self.anonymize_value(block.metadata),
                )
            )
        self._assert_no_residue(anonymized_plain_text)
        self._assert_no_residue(anonymized_markdown)
        anonymized_document = ParsedDocument(
            plain_text=anonymized_plain_text,
            markdown=anonymized_markdown,
            blocks=anonymized_blocks,
            parser=ParserInfo(
                name=document.parser.name,
                version=document.parser.version,
                adapter_version=document.parser.adapter_version,
                options={
                    **document.parser.options,
                    "anonymization": {
                        "enabled": True,
                        "strategy": "strict_local_pii_rules",
                        "version": SANITIZER_VERSION,
                        "config_hash": config_hash(),
                    },
                },
            ),
            quality=ParseQuality(
                char_count=len(anonymized_plain_text),
                block_count=document.quality.block_count,
                page_count=document.quality.page_count,
                table_count=document.quality.table_count,
                empty_pages=document.quality.empty_pages,
                ocr_used=document.quality.ocr_used,
                warnings=[*document.quality.warnings, "personal_data_anonymized"],
            ),
        )
        return anonymized_document, self.report()

    def anonymize_source_filename(self, filename: str) -> str:
        suffix = ""
        if "." in filename:
            suffix = "." + filename.rsplit(".", 1)[-1]
        return f"anonymized-document{suffix}"

    def anonymize_text(self, text: str) -> str:
        if not text:
            return text
        spans = self._detect_spans_with_aliases(text)
        result = text
        result = self._anonymize_spans(result, spans)
        self._assert_no_residue(result)
        return result

    def anonymize_title(self, title: str) -> str:
        if not title:
            return title
        spans = self._detect_spans_with_aliases(title)
        protected = _protected_ranges(title)
        for match in _TITLE_LATIN_NAME_PREFIX.finditer(title):
            name = match.group(1)
            if not _is_non_person_name(name) and not _is_protected(*match.span(1), protected):
                spans.append(Span(match.start(1), match.end(1), "name", 58))
        result = self._anonymize_spans(title, _accept_spans(spans))
        self._assert_no_residue(result)
        return result

    def _anonymize_spans(self, text: str, spans: Iterable[Span]) -> str:
        result = text
        for span in reversed(spans):
            value = result[span.start : span.end]
            result = result[: span.start] + self._placeholder_for(span.kind, value) + result[span.end :]
        return result

    def anonymize_value(self, value: Any, current_key: str | None = None) -> Any:
        if isinstance(value, str):
            if _is_name_metadata_key(current_key) and _looks_like_person_value(value):
                return self._placeholder_for("name", value)
            return self.anonymize_text(value)
        if isinstance(value, list):
            return [self.anonymize_value(item, current_key=current_key) for item in value]
        if isinstance(value, dict):
            return {key: self.anonymize_value(item, current_key=key) for key, item in value.items()}
        return value

    def report(self) -> AnonymizationReport:
        return AnonymizationReport(
            person_replacements=self._replacement_counts.get("name", 0),
            email_replacements=self._replacement_counts.get("email", 0),
            phone_replacements=self._replacement_counts.get("phone", 0),
            bank_details_replacements=self._replacement_counts.get("bank_details", 0),
            address_replacements=self._replacement_counts.get("address", 0),
            ip_replacements=self._replacement_counts.get("ip", 0),
            link_replacements=self._replacement_counts.get("link", 0),
            identifier_replacements=self._replacement_counts.get("identifier", 0),
            residuals=dict(self._residuals),
        )

    def _detect_spans_with_aliases(self, text: str) -> list[Span]:
        spans = detect_spans(text)
        protected = _protected_ranges(text)
        for alias in sorted(self._name_aliases, key=len, reverse=True):
            if _is_non_person_name(alias):
                continue
            for match in re.finditer(rf"(?<![\w\[]){re.escape(alias)}(?![\w\]])", text):
                if not _is_protected(*match.span(), protected):
                    spans.append(Span(match.start(), match.end(), "name", 45))
        return _accept_spans(spans)

    def _collect_name_aliases_from_value(self, value: Any, current_key: str | None = None) -> None:
        if isinstance(value, str):
            if _is_name_metadata_key(current_key) and _looks_like_person_value(value):
                self._register_name_aliases(value)
            else:
                self._collect_name_aliases_from_text(value)
        elif isinstance(value, list):
            for item in value:
                self._collect_name_aliases_from_value(item, current_key=current_key)
        elif isinstance(value, dict):
            for key, item in value.items():
                self._collect_name_aliases_from_value(item, current_key=key)

    def _collect_name_aliases_from_text(self, text: str) -> None:
        if not text:
            return
        for span in detect_spans(text):
            if span.kind != "name":
                continue
            self._register_name_aliases(text[span.start : span.end])

    def _register_name_aliases(self, name: str) -> None:
        cleaned_name = " ".join(name.split())
        if not cleaned_name or _is_non_person_name(cleaned_name):
            return
        placeholder = self._placeholders["name"].get(cleaned_name)
        if placeholder is None:
            placeholder = self._next_placeholder("name")
            self._placeholders["name"][cleaned_name] = placeholder
        for alias in {cleaned_name, *cleaned_name.split()}:
            if len(alias) >= 3 and not _is_non_person_name(alias):
                self._name_aliases.setdefault(alias, placeholder)

    def _placeholder_for(self, kind: str, value: str) -> str:
        if kind == "name":
            self._register_name_aliases(value)
            placeholder = self._name_aliases.get(value) or self._placeholders["name"].get(" ".join(value.split()))
            if placeholder is None:
                placeholder = self._placeholder_by_value(kind, value)
        else:
            placeholder = self._placeholder_by_value(kind, value)
        self._replacement_counts[kind] = self._replacement_counts.get(kind, 0) + 1
        return placeholder

    def _placeholder_by_value(self, kind: str, value: str) -> str:
        normalized = " ".join(value.split()) if kind in {"name", "address"} else value
        if kind == "link":
            return self._placeholders[kind].setdefault(normalized, self._next_link_placeholder(value))
        if kind == "identifier":
            return self._placeholders[kind].setdefault(normalized, self._next_identifier_placeholder(value))
        return self._placeholders[kind].setdefault(normalized, self._next_placeholder(kind))

    def _next_placeholder(self, kind: str) -> str:
        return f"[{PLACEHOLDER_PREFIXES[kind]}_{len(set(self._placeholders[kind].values())) + 1:03d}]"

    def _next_link_placeholder(self, value: str) -> str:
        label = _link_label(value)
        count = sum(1 for placeholder in set(self._placeholders["link"].values()) if placeholder.startswith(f"[LINK_{label}_"))
        return f"[LINK_{label}_{count + 1:03d}]"

    def _next_identifier_placeholder(self, value: str) -> str:
        label = _identifier_label(value)
        count = sum(
            1
            for placeholder in set(self._placeholders["identifier"].values())
            if placeholder.startswith(f"[IDENTIFIER_{label}_")
        )
        return f"[IDENTIFIER_{label}_{count + 1:03d}]"

    def _assert_no_residue(self, text: str) -> None:
        residuals = residual_counts(text)
        if not residuals:
            return
        for kind, count in residuals.items():
            self._residuals[kind] = self._residuals.get(kind, 0) + count
        raise PiiResidueError(residuals)


def detect_spans(text: str) -> list[Span]:
    protected = _protected_ranges(text)
    spans: list[Span] = []

    def add(match: re.Match[str], kind: str, priority: int, group: int = 0) -> None:
        start, end = match.span(group)
        if start >= 0 and not _is_protected(start, end, protected):
            spans.append(Span(start, end, kind, priority))

    for match in _EMAIL.finditer(text):
        add(match, "email", 100)

    for match in _URL.finditer(text):
        add(match, "link", 125)

    for match in _IP_TOKEN.finditer(text):
        token = match.group(0).strip("[](){}<>,.;")
        try:
            ipaddress.ip_address(token)
        except ValueError:
            continue
        offset = match.group(0).find(token)
        start = match.start() + offset
        end = start + len(token)
        if not _is_protected(start, end, protected):
            spans.append(Span(start, end, "ip", 95))

    for match in _BANK_LABEL.finditer(text):
        add(match, "bank_details", 110, 1)

    for match in _DIGIT_RUN.finditer(text):
        raw = match.group(0)
        digits = _digits(raw)
        if len(digits) == 20 or (13 <= len(digits) <= 19 and _luhn(digits)):
            add(match, "bank_details", 110)
            continue
        compact = re.sub(r"\D", "", raw)
        if 10 <= len(compact) <= 15:
            add(match, "phone", 80)

    for pattern in (_ADDRESS, _POSTAL_ADDRESS, _CITY_ADDRESS):
        for match in pattern.finditer(text):
            add(match, "address", 70)
    for match in _ADDRESS_LABEL.finditer(text):
        add(match, "address", 72, 1)

    for match in _NAME_LABEL.finditer(text):
        if not _is_non_person_name(match.group(1)):
            add(match, "name", 60, 1)
    for match in _LATIN_NAME_LABEL.finditer(text):
        if not _is_non_person_name(match.group(1)):
            add(match, "name", 60, 1)
    for match in _COMMENT_BY_LATIN_NAME.finditer(text):
        if not _is_non_person_name(match.group(1)):
            add(match, "name", 60, 1)
    for match in _FULL_NAME.finditer(text):
        if not _is_non_person_name(match.group(1)):
            add(match, "name", 55, 1)
    for match in _TWO_PART_NAME.finditer(text):
        if not _is_non_person_name(match.group(1)):
            add(match, "name", 52, 1)
    for match in _PATRONYMIC_NAME.finditer(text):
        if not _is_non_person_name(match.group(1)):
            add(match, "name", 54, 1)
    for match in _SIGNATURE_NAME.finditer(text):
        if not _is_non_person_name(match.group(1)):
            add(match, "name", 50, 1)
    # A complete opaque identifier wins over phone/card-looking substrings inside it.
    for match in _LONG_IDENTIFIER.finditer(text):
        add(match, "identifier", 120)

    return _accept_spans(spans)


def residual_counts(text: str) -> dict[str, int]:
    protected = _protected_ranges(text)
    counts: dict[str, int] = {}

    def count(kind: str) -> None:
        counts[kind] = counts.get(kind, 0) + 1

    for match in _EMAIL.finditer(text):
        if not _is_protected(*match.span(), protected):
            count("email")
    for match in _URL.finditer(text):
        if not _is_protected(*match.span(), protected):
            count("link")
    for match in _IP_TOKEN.finditer(text):
        token = match.group(0).strip("[](){}<>,.;")
        try:
            ipaddress.ip_address(token)
        except ValueError:
            continue
        if not _is_protected(*match.span(), protected):
            count("ip")
    for match in _DIGIT_RUN.finditer(text):
        if _is_protected(*match.span(), protected):
            continue
        digits = _digits(match.group(0))
        if len(digits) == 20 or (13 <= len(digits) <= 19 and _luhn(digits)):
            count("bank_details")
        elif 10 <= len(digits) <= 15:
            count("phone")
    for match in _LONG_IDENTIFIER.finditer(text):
        if not _is_protected(*match.span(), protected):
            count("identifier")
    for _match in _BROKEN_IDENTIFIER.finditer(text):
        count("identifier")
    for kind, pattern in (
        ("bank_details", _BANK_LABEL),
        ("name", _NAME_LABEL),
        ("name", _LATIN_NAME_LABEL),
        ("name", _COMMENT_BY_LATIN_NAME),
        ("name", _TWO_PART_NAME),
        ("name", _PATRONYMIC_NAME),
        ("address", _ADDRESS),
        ("address", _POSTAL_ADDRESS),
        ("address", _CITY_ADDRESS),
        ("address", _ADDRESS_LABEL),
    ):
        for match in pattern.finditer(text):
            span = match.span(1) if kind in {"bank_details", "name"} or pattern is _ADDRESS_LABEL else match.span()
            if not _is_protected(*span, protected) and not (kind == "name" and _is_non_person_name(match.group(1))):
                count(kind)
    return counts


def config_hash() -> str:
    material = json.dumps(
        {
            "version": SANITIZER_VERSION,
            "placeholder_prefixes": PLACEHOLDER_PREFIXES,
            "patterns": [
                pattern.pattern
                for pattern in (
                    _PROTECTED,
                    _EMAIL,
                    _URL,
                    _IP_TOKEN,
                    _DIGIT_RUN,
                    _BANK_LABEL,
                    _NAME_LABEL,
                    _LATIN_NAME_LABEL,
                    _COMMENT_BY_LATIN_NAME,
                    _TITLE_LATIN_NAME_PREFIX,
                    _FULL_NAME,
                    _TWO_PART_NAME,
                    _PATRONYMIC_NAME,
                    _SIGNATURE_NAME,
                    _ADDRESS,
                    _POSTAL_ADDRESS,
                    _ADDRESS_LABEL,
                    _CITY_ADDRESS,
                    _LONG_IDENTIFIER,
                    _BROKEN_IDENTIFIER,
                )
            ],
        },
        sort_keys=True,
    ).encode()
    return sha256(material).hexdigest()


def _accept_spans(spans: Iterable[Span]) -> list[Span]:
    accepted: list[Span] = []
    for candidate in sorted(spans, key=lambda span: (-span.priority, span.start, -(span.end - span.start))):
        if any(candidate.start < other.end and candidate.end > other.start for other in accepted):
            continue
        accepted.append(candidate)
    return sorted(accepted, key=lambda span: span.start)


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _luhn(value: str) -> bool:
    digits = [int(ch) for ch in value]
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _protected_ranges(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in _PROTECTED.finditer(text)]


def _is_protected(start: int, end: int, protected: Iterable[tuple[int, int]]) -> bool:
    return any(start < right and end > left for left, right in protected)


def _is_non_person_name(value: str) -> bool:
    cleaned = " ".join(value.split()).casefold()
    tokens = [token.casefold() for token in cleaned.split()]
    return cleaned in _NON_PERSON_PHRASES or any(token in _NON_PERSON_TOKENS for token in tokens)


def _is_name_metadata_key(key: str | None) -> bool:
    if not key:
        return False
    normalized = key.strip().casefold().replace("-", "_").replace(" ", "_")
    return normalized in _NAME_METADATA_KEYS or normalized.endswith("_author")


def _looks_like_person_value(value: str) -> bool:
    cleaned = " ".join(value.split())
    if _is_non_person_name(cleaned):
        return False
    return bool(_LATIN_PERSON_VALUE.match(cleaned) or _CYRILLIC_PERSON_VALUE.match(cleaned))


def _link_label(value: str) -> str:
    hostname = (urlparse(value).hostname or "").casefold()
    if "figma" in hostname:
        return "FIGMA"
    if any(token in hostname for token in ("metabase", "superset", "tableau", "grafana", "dashboard")):
        return "DASHBOARD"
    if any(token in hostname for token in ("confluence", "wiki", "notion")):
        return "DOC"
    return "URL"


def _identifier_label(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized.startswith(("exp-", "experiment-", "ab-")):
        return "EXPERIMENT"
    if normalized.startswith(("usr-", "user-", "account-", "acct-")):
        return "ACCOUNT"
    return "OPAQUE"


def _text_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()
