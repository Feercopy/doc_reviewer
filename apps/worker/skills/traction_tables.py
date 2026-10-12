from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.services.new_summary_source_tables import (
    _number as source_number,
    block_rows as _block_rows,
    expense_row_indices,
    verified_table_blocks,
)
from app.services.new_summary_traction import _period_key

if TYPE_CHECKING:
    from app.models.document import Document


_PERIOD = re.compile(r"(?:^|\b)(?:20\d{2}|CY\s*['’]?\d{2}|Q[1-4])(?:\b|$)", re.IGNORECASE)
_TOTAL = re.compile(r"\b(?:total|ttl|итого|всего)\b", re.IGNORECASE)
_INCREMENT = re.compile(r"\b(?:increment(?:al)?|incr\.?|uplift|прирост|инкремент)\b", re.IGNORECASE)
_EXCLUDED = re.compile(r"\b(?:tobe|to.be|baseline|before|previous|prior|diff|delta|разниц|до\s+изменен)\b", re.IGNORECASE)
_METRICS = {"revenue": re.compile(r"\b(?:revenue|выручк[а-я]*)\b", re.IGNORECASE), "dtb": re.compile(r"\bDTB\b", re.IGNORECASE)}
_CUMULATIVE = re.compile(r"\b(?:cum(?:mul(?:ative)?|ulative)?|накоплен\w*)\b", re.IGNORECASE)
_FINANCIAL_MODEL = re.compile(r"(?:financial\s+model|финансов\w*\s+модел\w*)", re.IGNORECASE)


def source_traction_tables(document: Document) -> list[dict[str, Any]]:
    """Read only the parsed artifact owned by this document; never infer missing figures."""
    blocks = verified_table_blocks(document)
    best: dict[str, tuple[int, dict[str, Any]]] = {}
    for block in blocks:
        rows = _block_rows(block)
        if not rows:
            continue
        candidates = [(score, table) for score, table in _incremental_rows(rows) if table["metric"] != "dtb"]
        candidates.extend(_cumulative_dtb_rows(rows))
        for score, table in candidates:
            metric = table["metric"]
            candidate = {
                **table,
                "source_page": block.get("page"),
                "source_block_id": block.get("id"),
            }
            if metric not in best or score > best[metric][0]:
                best[metric] = (score, candidate)
            elif score == best[metric][0]:
                selected = best[metric][1]
                if selected["source_block_id"] == block.get("id") and selected["periods"] == table["periods"]:
                    for row in table["rows"]:
                        if row not in selected["rows"]:
                            selected["rows"].append(row)
    return [best[metric][1] for metric in ("revenue", "dtb") if metric in best]


def _incremental_rows(rows: list[list[str]]) -> list[tuple[int, dict[str, Any]]]:
    found: list[tuple[int, dict[str, Any]]] = []
    active_header: list[str] = []
    active_context = ""
    expense_indices = expense_row_indices(rows)
    for row_index, row in enumerate(rows):
        if not row:
            continue
        first = row[0].strip()
        if not first:
            continue
        period_cells = [i for i, cell in enumerate(row[1:], 1) if _PERIOD.search(cell) or _TOTAL.search(cell)]
        if len(period_cells) >= 2:
            active_header = row
            active_context = first
            continue
        if not active_header or _EXCLUDED.search(active_context):
            continue
        context_incremental = bool(_INCREMENT.search(active_context))
        row_incremental = bool(_INCREMENT.search(first))
        financial_revenue = bool(_FINANCIAL_MODEL.search(active_context) and _METRICS["revenue"].search(first))
        if not (context_incremental or row_incremental or financial_revenue):
            continue
        if _EXCLUDED.search(first):
            continue
        metric = next((name for name, pattern in _METRICS.items() if pattern.search(first)), None)
        if metric is None:
            metric = next((name for name, pattern in _METRICS.items() if pattern.search(active_context)), None)
            if metric is None or not _TOTAL.search(first):
                continue
        if metric == "revenue" and row_index in expense_indices:
            continue
        indices = [i for i, cell in enumerate(active_header[1:], 1) if _PERIOD.search(cell) or _TOTAL.search(cell)]
        if len(indices) < 2:
            continue
        values = [row[i].strip() if i < len(row) else "" for i in indices]
        if not any(values):
            continue
        periods = [active_header[i].strip() for i in indices]
        score = 10 if context_incremental else 5
        if financial_revenue:
            score += 20
            if re.fullmatch(r"(?:total\s+)?revenue|выручка", first, re.IGNORECASE):
                score += 5
        if _TOTAL.search(first):
            score += 3
        if any(_TOTAL.search(period) for period in periods):
            score += 2
        if "p&l" in active_context.lower():
            score += 3
        if re.search(r"20\d{2}\s*[-–]\s*(?:20)?\d{2}\s*(?:total|ttl)", " ".join(periods), re.IGNORECASE):
            score += 1
        found.append((score, {
            "metric": metric,
            **({"cumulative": True} if metric == "dtb" and re.search(r"\b(?:cum(?:ulative)?|накоплен\w*)\b", f"{active_context} {first}", re.IGNORECASE) else {}),
            "metric_label": metric.upper() if metric == "dtb" else "Revenue",
            "unit": _unit(active_context, first),
            "periods": periods,
            "rows": [{
                "label": "Total incremental output uplifts" if _TOTAL.search(first) or first.lower() in {"revenue", "dtb"} else first,
                "values": values,
            }],
        }))
    return found


def _cumulative_dtb_rows(rows: list[list[str]]) -> list[tuple[int, dict[str, Any]]]:
    """Classify source rows, never calculate displayed DTB or mix table/scenario rows."""
    groups: list[tuple[list[str], list[list[str]]]] = []
    for row in rows:
        if len(row) < 2:
            continue
        if sum(bool(_PERIOD.search(cell) or _TOTAL.search(cell)) for cell in row[1:]) >= 2:
            groups.append((row, []))
        elif groups:
            groups[-1][1].append(row)
    found = []
    for header, body in groups:
        if _EXCLUDED.search(header[0]):
            continue
        indices = [i for i, value in enumerate(header[1:], 1) if _PERIOD.search(value) or _TOTAL.search(value)]
        dtb_rows = [row for row in body if _METRICS["dtb"].search(row[0]) and not _EXCLUDED.search(row[0])]
        incremental = [row for row in dtb_rows if _INCREMENT.search(row[0]) and not _CUMULATIVE.search(row[0])]
        for row in dtb_rows:
            explicit = bool(_CUMULATIVE.search(row[0]) or (_CUMULATIVE.search(header[0]) and not _INCREMENT.search(row[0])))
            if _INCREMENT.search(row[0]) and not explicit:
                continue
            # A generic DTB row is eligible only within an unambiguous matching table.
            inferred = not explicit and not _INCREMENT.search(header[0]) and len(incremental) == 1 and _dtb_recurrence(header, row, incremental[0])
            if not (explicit or inferred):
                continue
            periods = [header[i] for i in indices]
            values = [row[i] if i < len(row) else "" for i in indices]
            score = (30 if explicit else 25) + (3 if _TOTAL.search(row[0]) else 0)
            label = row[0] if _CUMULATIVE.search(row[0]) else f"{row[0]} (cummul)"
            found.append((score, {
                "metric": "dtb", "metric_label": "DTB (cummul)", "cumulative": True,
                "cumulative_basis": "explicit" if explicit else "verified_recurrence",
                "unit": _unit(header[0], row[0]), "periods": periods,
                "rows": [{"label": label, "values": values}],
            }))
    return found


def _dtb_recurrence(header: list[str], cumulative: list[str], incremental: list[str]) -> bool:
    def metric_key(label: str) -> str:
        return " ".join(re.findall(r"\w+|%", _TOTAL.sub("", _INCREMENT.sub("", label)).casefold()))
    if metric_key(cumulative[0]) != metric_key(incremental[0]):
        return False
    if _unit(header[0], cumulative[0]) != _unit(header[0], incremental[0]):
        return False
    periods = [(index, _period_key(label)) for index, label in enumerate(header[1:], 1) if not _TOTAL.search(label)]
    if any(key is None for _, key in periods):
        return False
    # Prefer full years; never add overlapping annual/half-year/quarter cells.
    for width in (12, 6, 3):
        comparable = [(i, key) for i, key in periods if key and key[2] - key[1] + 1 == width]
        if len(comparable) < 2:
            continue
        for (previous, prev_key), (current, key) in zip(comparable, comparable[1:]):
            if key[0] * 12 + key[1] != prev_key[0] * 12 + prev_key[2] + 1:
                return False
            if max(previous, current) >= len(cumulative) or current >= len(incremental):
                return False
            cells = [cumulative[previous], cumulative[current], incremental[current]]
            if len({value.strip().endswith("%") for value in cells}) != 1:
                return False
            numbers = [source_number(value.strip().removesuffix("%")) for value in cells]
            if any(number is None for number in numbers) or numbers[0] + numbers[2] != numbers[1]:
                return False
        return True
    return False


def _unit(context: str, label: str) -> str:
    text = f"{context} {label}"
    if re.search(r"\b(?:mR|млн\s*₽)\b", text, re.IGNORECASE):
        return "млн ₽"
    if "%" in text:
        return "%"
    return ""


def display_traction_tables(source_tables: list[dict[str, Any]], *, language: str) -> dict[str, Any]:
    tables: list[dict[str, Any]] = []
    for source in source_tables:
        metric = source["metric"]
        unit = source.get("unit") or ""
        name = "DTB" if metric == "dtb" else ("Выручка" if language == "ru" else "Revenue")
        cumulative = metric == "dtb" and source.get("cumulative") is True
        metric_label = f"{name} (cummul)" if cumulative else f"{name} (инкр.)" if language == "ru" else f"{name} (incr)"
        if unit:
            metric_label += f", {unit if language == 'ru' else ('mR' if unit == 'млн ₽' else unit)}"
        tables.append({
            "metric": metric,
            **({"cumulative": True} if source.get("cumulative") is True else {}),
            "metric_label": metric_label,
            "periods": source["periods"],
            "rows": [{
                "label": (
                    "Итоговый инкрементальный прирост" if language == "ru" else "Total incremental output uplifts"
                ) if row["label"] == "Total incremental output uplifts" else row["label"],
                "values": [
                    _display_source_cell(value, source["periods"][index], language=language)
                    for index, value in enumerate(row["values"])
                ],
            } for row in source["rows"]],
        })
    return {"tables": tables}


def _display_source_cell(value: str, period: str, *, language: str) -> str:
    if value:
        return value
    if _TOTAL.search(period):
        return "отсутствуют данные в документе защиты" if language == "ru" else "no data in the defense document"
    return "Нет данных в документе" if language == "ru" else "No data in the document"
