from __future__ import annotations

import re


_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(https?://[^)]+\)", re.IGNORECASE)
_SOURCE_LINK = re.compile(r"(?:3\s*sigma|tri\s*sigma|три\s*сигм|ссылка|\blink\b)", re.IGNORECASE)
_TRAILING_SOURCE = re.compile(
    r"(?:\s*\((?:3\s*sigma|tri\s*sigma|три\s*сигм|ссылка|link)[^)]*\)\s*)+$",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_BREAK_TAG = re.compile(r"(?:<br\s*/?>|&lt;br\s*/?&gt;)", re.IGNORECASE)
_SUMMARY_SUFFIX = re.compile(r"\s*[-–—]\s*AI Summary\s*$", re.IGNORECASE)
_TITLE_STAGE = (
    r"(?:gate\s*[1-4]|progress\s+review|stream\s+review(?:\s*#?\s*(?:1|2\+?))?"
    r"|ic\s+update\s+request|дозапрос\s+ресурс[а-яё]*)"
)
_TITLE_SHORT_LANGUAGE = r"(?:en|eng|ru|rus|рус)"
_TITLE_LANGUAGE = rf"(?:{_TITLE_SHORT_LANGUAGE}|english|russian|рус(?:ский|ская|ское|ские)|англ(?:ийский|ийская|ийское)?)"
_TITLE_ANNOTATION = rf"(?:{_TITLE_STAGE}|{_TITLE_LANGUAGE})"
_TITLE_ANNOTATION_GROUP = rf"{_TITLE_ANNOTATION}(?:\s*(?:and|и|&|,|/|\+)\s*{_TITLE_ANNOTATION})*"
_TRAILING_TITLE_ANNOTATION = re.compile(
    rf"(?:\s*[-–—_|:]\s*|\s*\()\s*{_TITLE_ANNOTATION_GROUP}\s*\)?\s*$"
    rf"|\s+(?:{_TITLE_STAGE}|{_TITLE_SHORT_LANGUAGE})\s*$",
    re.IGNORECASE,
)
_LEADING_TITLE_ANNOTATION = re.compile(
    rf"^\s*(?:{_TITLE_ANNOTATION_GROUP}\s*[-–—_|:]\s*|{_TITLE_STAGE}\s+)",
    re.IGNORECASE,
)


def clean_initiative_title(value: str) -> str:
    title = _BREAK_TAG.sub(" ", value).strip()
    if title.lower().startswith("ai summary "):
        title = title[len("AI Summary "):]
    title = _SUMMARY_SUFFIX.sub("", title)
    title = _MARKDOWN_LINK.sub(
        lambda match: "" if _SOURCE_LINK.search(match.group(1)) else match.group(1),
        title,
    )
    title = _URL.sub("", title)
    for _ in range(8):
        cleaned = _TRAILING_SOURCE.sub("", title)
        cleaned = _TRAILING_TITLE_ANNOTATION.sub("", cleaned)
        cleaned = _LEADING_TITLE_ANNOTATION.sub("", cleaned)
        if cleaned == title:
            break
        title = cleaned
    title = re.sub(r"\s+", " ", title).strip(" \t-–—,;:")
    if re.fullmatch(_TITLE_ANNOTATION_GROUP, title, flags=re.IGNORECASE):
        title = ""
    return title or "Untitled initiative"


def display_new_summary_title(value: str) -> str:
    return f"{clean_initiative_title(value)} - AI Summary"
