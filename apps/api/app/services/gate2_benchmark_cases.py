from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import hashlib
import re

from app.schemas.enums import CheckStatus, Severity, Verdict
from app.schemas.etalons import EtalonPayload


SUPPORTED_ORIGINAL_SUFFIXES = {".md", ".txt", ".docx", ".dotx"}
SUPPORTED_ETALON_SUFFIXES = {".md", ".txt", ".csv"}
STOP_TOKENS = {"bench", "benchmark", "normalized", "etalon", "эталон"}


@dataclass(frozen=True)
class Gate2BenchmarkCase:
    name: str
    benchmark_dir: Path
    original_path: Path
    etalon_path: Path
    etalon_markdown_path: Path | None

    @property
    def original_sha256(self) -> str:
        return _sha256_file(self.original_path)

    @property
    def etalon_sha256(self) -> str:
        return _sha256_file(self.etalon_path)

    @property
    def etalon_markdown_sha256(self) -> str | None:
        return _sha256_file(self.etalon_markdown_path) if self.etalon_markdown_path else None


@dataclass(frozen=True)
class Gate2EtalonParseResult:
    expected_verdict: str
    layer_1: list[dict]
    layer_2: list[dict]
    key_findings: list[str]
    input_doc_url: str | None
    row_count: int


def discover_gate2_benchmark_cases(benchmark_dir: Path) -> list[Gate2BenchmarkCase]:
    benchmark_dir = Path(benchmark_dir)
    original_dir = benchmark_dir / "original"
    if not original_dir.exists():
        raise FileNotFoundError(f"Original documents directory does not exist: {original_dir}")

    csv_etalons = _collect_etalon_files(benchmark_dir / "Эталоны" / "csv_by_document")
    fallback_etalons = _collect_etalon_files(benchmark_dir / "Эталоны" / "normalized")
    if not fallback_etalons:
        fallback_etalons = _collect_etalon_files(benchmark_dir / "Эталоны")
    markdown_etalons = [path for path in _collect_etalon_files(benchmark_dir / "Эталоны") if path.suffix.lower() in {".md", ".txt"}]

    original_files = sorted(
        path
        for path in original_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_ORIGINAL_SUFFIXES
    )
    cases = []
    for original_path in original_files:
        original_tokens = _tokens(original_path.stem)
        etalon_path = _best_etalon_match(original_tokens, csv_etalons) or _best_etalon_match(
            original_tokens, fallback_etalons
        )
        if etalon_path is None:
            continue
        markdown_path = _best_etalon_match(original_tokens, markdown_etalons)
        cases.append(
            Gate2BenchmarkCase(
                name=_case_name(original_path.stem),
                benchmark_dir=benchmark_dir,
                original_path=original_path,
                etalon_path=etalon_path,
                etalon_markdown_path=markdown_path,
            )
        )
    return sorted(cases, key=lambda case: case.name)


def parse_gate2_etalon_csv(path: Path) -> Gate2EtalonParseResult:
    rows = _read_csv_rows(path)
    verdict = Verdict.UNKNOWN.value
    input_doc_url = None
    dimension_status: dict[str, str] = {}
    layer_1_items: dict[tuple[str, str], dict[str, str]] = {}
    layer_2_items: dict[tuple[str, str], dict[str, str]] = {}
    layer_2_block_status: dict[str, str] = {}

    for row in rows:
        section = row.get("section", "").strip()
        block = row.get("block", "").strip()
        item_type = row.get("item_type", "").strip()
        item_id = row.get("item_id", "").strip()
        field = row.get("field", "").strip()
        value = row.get("value", "").strip()
        status = row.get("status", "").strip()

        if section == "metadata" and field == "url":
            input_doc_url = value or None
        elif section == "Layer 1" and block == "verdict" and field == "value":
            verdict = _verdict_value(value)
        elif section == "Layer 1" and item_type == "dimension" and field == "status":
            dimension_status[block] = _status_value(value or status)
        elif section == "Layer 1" and item_type == "issue" and item_id and field:
            layer_1_items.setdefault((block, item_id), {})[field] = value
        elif section == "Layer 2" and item_type == "atomic_check_block" and field == "status":
            layer_2_block_status[block] = _status_value(value or status)
        elif section == "Layer 2" and item_type == "atomic_check" and item_id and field:
            layer_2_items.setdefault((block, item_id), {})[field] = value

    layer_1 = _layer_1_from_csv_items(layer_1_items=layer_1_items, dimension_status=dimension_status)
    layer_2 = _layer_2_from_csv_items(
        layer_2_items=layer_2_items,
        layer_1=layer_1,
        block_status=layer_2_block_status,
    )
    return Gate2EtalonParseResult(
        expected_verdict=verdict,
        layer_1=layer_1,
        layer_2=layer_2,
        key_findings=[item["title"] for item in layer_1],
        input_doc_url=input_doc_url,
        row_count=len(rows),
    )


def gate2_case_to_etalon_payload(case: Gate2BenchmarkCase) -> EtalonPayload:
    parsed = parse_gate2_etalon_csv(case.etalon_path)
    return EtalonPayload.model_validate(
        {
            "expected_verdict": parsed.expected_verdict,
            "layer_1": parsed.layer_1,
            "layer_2": parsed.layer_2,
            "key_findings": parsed.key_findings,
            "forbidden_false_findings": [],
        }
    )


def gate2_case_source_metadata(case: Gate2BenchmarkCase, parsed: Gate2EtalonParseResult) -> dict:
    metadata = {
        "source_kind": "gate2_benchmark",
        "case_name": case.name,
        "benchmark_dir": str(case.benchmark_dir),
        "original_path": _relative_to(case.original_path, case.benchmark_dir),
        "original_sha256": case.original_sha256,
        "etalon_csv_path": _relative_to(case.etalon_path, case.benchmark_dir),
        "etalon_csv_sha256": case.etalon_sha256,
        "input_doc_url": parsed.input_doc_url,
        "csv_rows": parsed.row_count,
    }
    if case.etalon_markdown_path:
        metadata["etalon_markdown_path"] = _relative_to(case.etalon_markdown_path, case.benchmark_dir)
        metadata["etalon_markdown_sha256"] = case.etalon_markdown_sha256
    return metadata


def _layer_1_from_csv_items(*, layer_1_items: dict[tuple[str, str], dict[str, str]], dimension_status: dict[str, str]) -> list[dict]:
    items = []
    for (block, item_id), fields in sorted(layer_1_items.items(), key=lambda item: (_slug(item[0][0]), _natural_key(item[0][1]))):
        issue = fields.get("issue", "").strip()
        evidence = fields.get("evidence", "").strip()
        if not issue:
            continue
        items.append(
            {
                "id": f"L1-{_slug(block)}-{_slug(item_id)}",
                "dimension": block,
                "status": dimension_status.get(block, CheckStatus.PARTIAL.value),
                "severity": _severity_value(fields.get("severity")),
                "title": issue,
                "summary": issue,
                "evidence": [
                    {
                        "quote": evidence or issue,
                        "location": f"Gate2 benchmark etalon: Layer 1 / {block}",
                    }
                ],
                "recommendation": "",
                "confidence": None,
            }
        )
    return items


def _layer_2_from_csv_items(*, layer_2_items: dict[tuple[str, str], dict[str, str]], layer_1: list[dict], block_status: dict[str, str]) -> list[dict]:
    parent_by_block: dict[str, str] = {}
    for item in layer_1:
        parent_by_block.setdefault(str(item["dimension"]), str(item["id"]))

    items = []
    for (block, item_id), fields in sorted(layer_2_items.items(), key=lambda item: (_slug(item[0][0]), _natural_key(item[0][1]))):
        issue = fields.get("issue", "").strip()
        question = fields.get("question", "").strip()
        evidence = fields.get("evidence", "").strip()
        if not issue and not question:
            continue
        status = _status_from_answer(fields.get("answer")) or block_status.get(block, CheckStatus.PARTIAL.value)
        items.append(
            {
                "id": f"L2-{_slug(block)}-{_slug(item_id)}",
                "parent_layer_1_id": parent_by_block.get(block) or _synthetic_parent(block, layer_1, parent_by_block),
                "check": question or issue,
                "status": status,
                "severity": _severity_from_status(status),
                "finding": issue or question,
                "evidence": [
                    {
                        "quote": evidence or issue or question,
                        "location": f"Gate2 benchmark etalon: Layer 2 / {block}",
                    }
                ],
                "expected_fix": "",
                "confidence": None,
            }
        )
    return items


def _synthetic_parent(block: str, layer_1: list[dict], parent_by_block: dict[str, str]) -> str:
    parent_id = f"L1-{_slug(block)}-synthetic"
    parent_by_block[block] = parent_id
    layer_1.append(
        {
            "id": parent_id,
            "dimension": block,
            "status": CheckStatus.PARTIAL.value,
            "severity": Severity.MEDIUM.value,
            "title": f"{block} benchmark issue",
            "summary": f"{block} benchmark issue",
            "evidence": [{"quote": f"{block} benchmark issue", "location": f"Gate2 benchmark etalon: Layer 1 / {block}"}],
            "recommendation": "",
            "confidence": None,
        }
    )
    return parent_id


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as source:
        return [dict(row) for row in csv.DictReader(source)]


def _collect_etalon_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_ETALON_SUFFIXES
    )


def _best_etalon_match(original_tokens: set[str], etalon_files: list[Path]) -> Path | None:
    best_path = None
    best_score = 0.0
    for etalon_path in etalon_files:
        etalon_tokens = _tokens(etalon_path.stem)
        overlap = original_tokens & etalon_tokens
        if not overlap:
            continue
        score = len(overlap) / len(original_tokens | etalon_tokens)
        if score > best_score:
            best_path = etalon_path
            best_score = score
    return best_path


def _case_name(value: str) -> str:
    return "-".join(_ordered_tokens(value))


def _tokens(value: str) -> set[str]:
    return set(_ordered_tokens(value))


def _ordered_tokens(value: str) -> list[str]:
    raw_tokens = re.findall(r"[A-Za-zА-Яа-я0-9]+", value.lower())
    return [token for token in raw_tokens if token not in STOP_TOKENS]


def _slug(value: str) -> str:
    tokens = _ordered_tokens(value)
    return "-".join(tokens) if tokens else "item"


def _natural_key(value: str) -> tuple[int, str]:
    return (int(value), value) if value.isdigit() else (10**9, value)


def _verdict_value(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    candidate = candidate.replace("-", "_").replace(" ", "_")
    if candidate in {item.value for item in Verdict}:
        return candidate
    return Verdict.UNKNOWN.value


def _status_value(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    candidate = candidate.replace("-", "_").replace(" ", "_")
    return candidate if candidate in {item.value for item in CheckStatus} else CheckStatus.PARTIAL.value


def _status_from_answer(value: str | None) -> str | None:
    candidate = (value or "").strip().upper()
    if candidate == "YES":
        return CheckStatus.PASS.value
    if candidate == "PARTIAL":
        return CheckStatus.PARTIAL.value
    if candidate == "NO":
        return CheckStatus.FAIL.value
    return None


def _severity_value(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    return candidate if candidate in {item.value for item in Severity} else Severity.MEDIUM.value


def _severity_from_status(status: str) -> str:
    if status == CheckStatus.FAIL.value:
        return Severity.HIGH.value
    if status == CheckStatus.PARTIAL.value:
        return Severity.MEDIUM.value
    return Severity.LOW.value


def _relative_to(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
