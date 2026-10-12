from __future__ import annotations

import re
from copy import deepcopy
from decimal import Decimal
from itertools import product
from typing import Any

from app.services.new_summary_source_tables import (
    VerifiedRevenueTotal,
    _number,
    clean_table_cell,
    verified_revenue_total,
)


_TOTAL_PERIOD = re.compile(r"\b(?:total|ttl|итого|всего)\b", re.IGNORECASE)
_YEAR = re.compile(r"\b20\d{2}\b")
_REVENUE_LABEL = re.compile(r"\b(?:revenue|выручк[а-я]*)\b", re.IGNORECASE)
_CUMULATIVE = re.compile(r"\b(?:cum(?:ulative)?|накоплен\w*)\b", re.IGNORECASE)
_PLAIN_REVENUE = re.compile(r"-?(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,]\d{1,2})?")
_AMBIGUOUS_GROUPING = re.compile(r"-?\d{1,3}(?:[,.]\d{3})+")
_GROUPED_DECIMAL_COMMA = re.compile(r"-?\d{1,3}(?:,\d{3})+\.\d+")
_GROUPED_DECIMAL_DOT = re.compile(r"-?\d{1,3}(?:\.\d{3})+,\d+")
_STRICT_TOTAL_POLICY = "same_table_annual_sum"
_VERIFIED_TOTAL_POLICY = "same_table_verified_total"


def _period_key(label: Any) -> tuple[int, int, int] | None:
    text = clean_table_cell(str(label)).upper()
    if _TOTAL_PERIOD.search(text):
        return None
    year = re.search(r"(?<!\d)(20\d{2})(?!\d)|CY\s*['’]?(\d{2})\b", text)
    if not year or "FY" in text:
        return None
    number = int(year.group(1) or f"20{year.group(2)}")
    quarter = re.search(r"Q\s*([1-4])|([1-4])\s*(?:Q|КВ)", text)
    half = re.search(r"H\s*([12])|([12])\s*(?:H|ПОЛУГОД|П\b)", text)
    if quarter:
        start = (int(quarter.group(1) or quarter.group(2)) - 1) * 3 + 1
        return number, start, start + 2
    if half:
        start = (int(half.group(1) or half.group(2)) - 1) * 6 + 1
        return number, start, start + 5
    if re.fullmatch(r"(?:20\d{2}(?:\s*Г(?:ОД)?\.?)?|CY\s*['’]?(?:20)?\d{2})", text):
        return number, 1, 12
    return None


def _period_label(key: tuple[int, int, int]) -> str:
    year, start, end = key
    if (start, end) == (1, 12):
        return str(year)
    return f"{'H' + str((start - 1) // 6 + 1) if end - start == 5 else 'Q' + str((start - 1) // 3 + 1)} {year}"


def _coverage(keys: list[tuple[int, int, int]]) -> set[tuple[int, int]]:
    return {(year, month) for year, start, end in keys for month in range(start, end + 1)}


def _total_matches_horizon(label: str, old: list[tuple[int, int, int]], new: list[tuple[int, int, int]]) -> bool:
    explicit = re.search(r"(20\d{2})\s*[-–—]\s*(20\d{2}|\d{2})(?!\d)", label)
    if explicit:
        first, last = int(explicit.group(1)), int(explicit.group(2))
        last = last + 2000 if last < 100 else last
        return _coverage(new) == {(year, month) for year in range(first, last + 1) for month in range(1, 13)}
    return _coverage(old) == _coverage(new)


def _align_periods(tables: list[dict[str, Any]], unavailable: str) -> None:
    """Select source columns together; never aggregate or relabel a partial year as a year."""
    if len(tables) != 2 or any(not isinstance(table, dict) for table in tables) or {table.get("metric") for table in tables} != {"revenue", "dtb"}:
        return
    dtb = next(table for table in tables if table.get("metric") == "dtb")
    revenue = next(table for table in tables if table.get("metric") == "revenue")
    revenue_keys = {_period_key(period) for period in revenue.get("periods", [])}
    dtb_keys = {_period_key(period) for period in dtb.get("periods", [])}
    # Explicit product rule: use DTB H2 as a labeled fallback, never as an unqualified full-year figure.
    for index, period in enumerate(dtb.get("periods", [])):
        key = _period_key(period)
        if key and key[1:] == (7, 12) and (key[0], 1, 12) in revenue_keys and (key[0], 1, 12) not in dtb_keys:
            dtb["periods"][index] = str(key[0])
            for row in dtb.get("rows") or []:
                if isinstance(row, dict) and isinstance(row.get("values"), list) and index < len(row["values"]):
                    row["values"][index] = f"{row['values'][index]} (H2 {key[0]})"
    parsed = [[(i, _period_key(p)) for i, p in enumerate(table.get("periods", [])) if not _TOTAL_PERIOD.search(str(p))] for table in tables]
    # Unknown labels must not silently disappear during a best-effort historical read.
    if any(not pairs or any(key is None for _, key in pairs) for pairs in parsed):
        return
    for table, pairs in zip(tables, parsed, strict=True):
        seen: dict[tuple[int, int, int], int] = {}
        for index, key in pairs:
            if key in seen and any(
                isinstance(row, dict) and isinstance(row.get("values"), list)
                and row["values"][index:index + 1] != row["values"][seen[key]:seen[key] + 1]
                for row in table.get("rows") or []
            ):
                return
            seen[key] = index
    keys = [{key for _, key in pairs} for pairs in parsed]
    common = keys[0] & keys[1]
    if not common:
        return
    first_common = min(common)
    overlap_end = min(max(values) for values in keys)
    granularities = {(start, end) for _, start, end in common}
    for table, pairs in zip(tables, parsed, strict=True):
        selected = sorted((key, i) for i, key in pairs if key in common or (
            key >= first_common and key > overlap_end and (key[1], key[2]) in granularities
        ))
        # Do not duplicate an equivalent source column such as CY26 and 2026.
        unique = dict(selected)
        selected = sorted(unique.items())
        total_index = next((i for i, p in enumerate(table["periods"]) if _TOTAL_PERIOD.search(str(p))), None)
        old_keys = [key for _, key in pairs]
        new_keys = [key for key, _ in selected]
        total_label = str(table["periods"][total_index]) if total_index is not None else "Total"
        keep_total = _total_matches_horizon(total_label, old_keys, new_keys)
        table["periods"] = [_period_label(key) for key in new_keys]
        table["periods"].append(f"Total {new_keys[0][0]}–{new_keys[-1][0]}" if not keep_total else total_label)
        for row in table.get("rows") or []:
            values = row.get("values")
            if not isinstance(values, list):
                continue
            total = values[total_index] if keep_total and total_index is not None and total_index < len(values) else unavailable
            row["values"] = [values[i] if i < len(values) else unavailable for _, i in selected] + [total]


def traction_row_label(table: dict[str, Any], row: dict[str, Any]) -> str:
    label = str(row.get("label") or "").strip()
    metric_label = str(table.get("metric_label") or "").strip()
    if _REVENUE_LABEL.search(label) or re.search(r"\bDTB\b", label, re.IGNORECASE):
        unit = metric_label.partition(",")[2].strip()
        if unit and unit not in label:
            return f"{label}, {unit}"
        return label
    if label.lower() in {"total incremental output uplifts", "итоговый инкрементальный прирост", ""}:
        return metric_label
    return f"{metric_label}: {label}" if metric_label else label


def _table_metric(table: dict[str, Any]) -> str | None:
    metric = table.get("metric")
    if metric in {"revenue", "dtb"}:
        return metric
    label = table.get("metric_label")
    if metric is None and isinstance(label, str) and _REVENUE_LABEL.search(label) and "dtb" not in label.lower():
        return "revenue"
    return None


def needs_verified_revenue_total(payload: dict[str, Any]) -> bool:
    if payload.get("schema_version") in {"new-summary-v7", "new-summary-v8"}:
        summary = payload.get("traction_summary")
        if not isinstance(summary, dict):
            return False
        if summary.get("total_source_policy") in {_STRICT_TOTAL_POLICY, _VERIFIED_TOTAL_POLICY}:
            return False
        periods = summary.get("periods")
        rows = summary.get("rows")
        if not isinstance(periods, list) or not isinstance(rows, list):
            return False
        index = next((i for i, period in enumerate(periods) if _TOTAL_PERIOD.search(str(period))), None)
        total_revenue = next((row for row in rows if isinstance(row, dict) and row.get("label") == "Total Revenue"), None)
        values = total_revenue.get("values") if isinstance(total_revenue, dict) else None
        return isinstance(values, list) and (index is None or index >= len(values) or _missing_total(values[index], include_dashes=payload.get("schema_version") == "new-summary-v8"))
    summary = payload.get("traction_summary")
    if not isinstance(summary, dict):
        return False
    tables = summary.get("tables") if isinstance(summary.get("tables"), list) else [summary]
    for table in tables:
        if not isinstance(table, dict) or _table_metric(table) != "revenue":
            continue
        periods = table.get("periods")
        if not isinstance(periods, list):
            continue
        index = next((i for i, period in enumerate(periods) if isinstance(period, str) and _TOTAL_PERIOD.search(period)), None)
        if index is None:
            return True
        if any(
            isinstance(row, dict)
            and isinstance(row.get("values"), list)
            and (index >= len(row["values"]) or _missing_total(row["values"][index]))
            for row in table.get("rows") or []
        ):
            return True
    return False


def with_traction_totals(
    payload: dict[str, Any], *, source_tables: list[dict[str, Any]] | None = None,
    source_blocks: list[dict[str, Any]] | None = None,
    strict_total_source: bool = False,
) -> dict[str, Any]:
    """Normalize display periods and Total cells; new reports may sum annual Revenue."""
    summary = payload.get("traction_summary")
    if not isinstance(summary, dict):
        return payload
    if payload.get("schema_version") in {"new-summary-v7", "new-summary-v8"}:
        updated = deepcopy(payload)
        table = updated["traction_summary"]
        if strict_total_source:
            table["total_source_policy"] = _VERIFIED_TOTAL_POLICY
        same_table_only = table.get("total_source_policy") == _STRICT_TOTAL_POLICY
        table["periods"] = [clean_table_cell(period) for period in table.get("periods", [])]
        for row in table.get("rows", []):
            if not isinstance(row, dict):
                continue
            row["label"] = clean_table_cell(row.get("label", ""))
            row["values"] = [display_traction_cell(value, payload.get("schema_version")) for value in row.get("values", [])]
        total_index = next((i for i, period in enumerate(table["periods"]) if _TOTAL_PERIOD.search(str(period))), None)
        if total_index is not None and source_blocks and not same_table_only:
            total_revenue = next((row for row in table.get("rows", []) if row.get("label") == "Total Revenue"), None)
            if isinstance(total_revenue, dict) and total_index < len(total_revenue["values"]) and _missing_total(total_revenue["values"][total_index], include_dashes=payload.get("schema_version") == "new-summary-v8"):
                verified = verified_revenue_total(table["periods"], total_revenue["values"], source_blocks)
                if verified:
                    total_revenue["values"][total_index] = verified.value
        total_changed = False
        if strict_total_source:
            total_changed = _verify_or_sum_revenue_total(table, total_index, source_tables or [])
        elif same_table_only:
            _fill_annual_total_revenue(table, total_index)
        if payload.get("schema_version") == "new-summary-v8":
            updated = apply_revenue_from_dtb_fallback(updated)
        if total_changed:
            _reconcile_total_revenue_mismatch(updated["traction_summary"], total_index)
        return updated
    tables = summary.get("tables") if isinstance(summary.get("tables"), list) else [summary]
    language = payload.get("language")
    absent = "отсутствуют данные в документе защиты" if language == "ru" else "no data in the defense document"
    unavailable = "невозможно извлечь данные" if language == "ru" else "could not extract data"
    updated = deepcopy(payload)
    updated_summary = updated["traction_summary"]
    updated_tables_source = updated_summary.get("tables") if isinstance(updated_summary.get("tables"), list) else [updated_summary]
    for table in updated_tables_source:
        if not isinstance(table, dict):
            continue
        if isinstance(table.get("metric_label"), str):
            table["metric_label"] = clean_table_cell(table["metric_label"])
        if isinstance(table.get("periods"), list):
            table["periods"] = [clean_table_cell(period) if isinstance(period, str) else period for period in table["periods"]]
        for row in table.get("rows") or []:
            if not isinstance(row, dict):
                continue
            if isinstance(row.get("label"), str):
                row["label"] = clean_table_cell(row["label"])
            if isinstance(row.get("values"), list):
                row["values"] = [clean_table_cell(value) if isinstance(value, str) else value for value in row["values"]]
    tables = updated_tables_source
    updated_tables = []
    for table in tables:
        if not isinstance(table, dict):
            updated_tables.append(table)
            continue
        periods = table.get("periods")
        rows = table.get("rows")
        if not isinstance(periods, list) or not periods or not isinstance(rows, list) or not rows:
            updated_tables.append(table)
            continue
        metric = _table_metric(table)
        total_index = next(
            (index for index, period in enumerate(periods)
             if isinstance(period, str) and _TOTAL_PERIOD.search(period)), None
        )
        source_periods_without_total = [
            period for period in periods if not isinstance(period, str) or not _TOTAL_PERIOD.search(period)
        ]
        matching_source = next(
            (
                source for source in source_tables or []
                if isinstance(source, dict)
                and source.get("metric") == metric
                and source.get("periods") in (periods, source_periods_without_total)
            ), None
        ) if metric in {"revenue", "dtb"} else None
        if total_index is not None:
            amended = deepcopy(table)
            if total_index != len(periods) - 1:
                total_period = amended["periods"].pop(total_index)
                amended["periods"].append(total_period)
            for row in amended["rows"]:
                values = row.get("values") if isinstance(row, dict) else None
                if not isinstance(values, list):
                    continue
                if total_index >= len(values):
                    values.extend([unavailable] * (total_index + 1 - len(values)))
                if _missing_total(values[total_index]):
                    verified = verified_revenue_total(periods, values, source_blocks or []) if metric == "revenue" else None
                    values[total_index] = verified.value if verified else (absent if matching_source is not None else unavailable)
                if total_index != len(periods) - 1:
                    total_value = values.pop(total_index)
                    values.append(total_value)
            updated_tables.append(amended)
            continue
        missing_reason = absent if matching_source is not None else unavailable
        years = [year for period in periods if isinstance(period, str) for year in _YEAR.findall(period)]
        label = f"Total {years[0]}–{years[-1]}" if len(years) > 1 else "Total"
        amended = deepcopy(table)
        amended["periods"].append(label)
        for row in amended["rows"]:
            if isinstance(row, dict) and isinstance(row.get("values"), list):
                verified = verified_revenue_total(periods, row["values"], source_blocks or []) if metric == "revenue" else None
                row["values"].append(verified.value if verified else missing_reason)
        updated_tables.append(amended)
    _align_periods(updated_tables, unavailable)
    for table in updated_tables:
        if not isinstance(table, dict) or _table_metric(table) != "dtb":
            continue
        total_index = next((i for i, p in enumerate(table.get("periods") or []) if _TOTAL_PERIOD.search(str(p))), None)
        if total_index is None:
            continue
        for row in table.get("rows") or []:
            if not isinstance(row, dict) or not isinstance(row.get("values"), list):
                continue
            cumulative = table.get("cumulative") is True or _CUMULATIVE.search(f"{table.get('metric_label', '')} {row.get('label', '')}")
            if cumulative and total_index < len(row["values"]):
                row["values"][total_index] = "—"
    updated["traction_summary"] = {**updated_summary, "tables": updated_tables} if "tables" in updated_summary else updated_tables[0]
    return updated


def _verify_or_sum_revenue_total(
    table: dict[str, Any], total_index: int | None, source_tables: list[dict[str, Any]],
) -> bool:
    """Do not persist a model-supplied Total unless its source row is verified."""
    periods = table.get("periods")
    rows = table.get("rows")
    if not isinstance(periods, list) or not isinstance(rows, list) or total_index != len(periods) - 1:
        return False
    row = next((item for item in rows if isinstance(item, dict) and item.get("label") == "Total Revenue"), None)
    values = row.get("values") if isinstance(row, dict) else None
    if not isinstance(values, list) or len(values) != len(periods):
        return False

    model_total = values[total_index]
    verified = _same_row_revenue_total(periods, values, source_tables)
    values[total_index] = "—"
    if verified is not None:
        values[total_index] = verified.value
        provenance: dict[str, Any] = {"method": "same_source_table"}
        if verified.source_block_id:
            provenance["source_block_id"] = verified.source_block_id
        if verified.source_page is not None:
            provenance["source_page"] = verified.source_page
    else:
        _fill_annual_total_revenue(table, total_index)
        provenance = {"method": "annual_sum" if values[total_index] != "—" else "unavailable"}
    table["total_revenue_provenance"] = provenance
    return values[total_index] != model_total


def _reconcile_total_revenue_mismatch(table: dict[str, Any], total_index: int | None) -> None:
    if total_index is None:
        return
    rows = {row.get("label"): row for row in table.get("rows", []) if isinstance(row, dict)}
    total_row = rows.get("Total Revenue")
    if not isinstance(total_row, dict):
        return
    markers = total_row.get("mismatch_periods")
    retained = [period for period in markers if not _TOTAL_PERIOD.search(str(period))] if isinstance(markers, list) else []
    components = (rows.get("Revenue from DTB"), rows.get("Revenue non-DTB"))
    values = [row.get("values", []) if isinstance(row, dict) else [] for row in (*components, total_row)]
    if all(total_index < len(row_values) for row_values in values):
        cells = [row_values[total_index] for row_values in values]
        if _proven_total_mismatch(cells):
            retained.append(table["periods"][total_index])
    if retained or isinstance(markers, list):
        total_row["mismatch_periods"] = retained


def _unambiguous_number(value: Any) -> Decimal | None:
    values = _possible_numbers(value)
    return next(iter(values)) if len(values) == 1 else None


def _normalized_number_syntax(value: Any) -> str:
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace("−", "-")
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    return text


def _grouped_separator(text: str) -> str | None:
    if not _AMBIGUOUS_GROUPING.fullmatch(text):
        return None
    separators = {char for char in text if char in ",."}
    return next(iter(separators)) if len(separators) == 1 else None


def _grouped_number(text: str) -> Decimal | None:
    separator = _grouped_separator(text)
    return _number(text.replace(separator, "")) if separator is not None else None


def _grouped_decimal_number(text: str) -> Decimal | None:
    if _GROUPED_DECIMAL_COMMA.fullmatch(text):
        return _number(text.replace(",", ""))
    if _GROUPED_DECIMAL_DOT.fullmatch(text):
        return _number(text.replace(".", "").replace(",", "."))
    return None


def _possible_numbers(value: Any) -> set[Decimal]:
    text = _normalized_number_syntax(value)
    grouped_decimal = _grouped_decimal_number(text)
    if grouped_decimal is not None:
        return {grouped_decimal}
    separator = _grouped_separator(text)
    if separator is None:
        number = _number(text)
        return {number} if number is not None else set()
    grouped = _grouped_number(text)
    if grouped is None:
        return set()
    if text.count(separator) > 1:
        return {grouped}
    decimal = _number(text)
    return {grouped, decimal} if decimal is not None else {grouped}


def _pinned_roles(texts: list[str]) -> dict[str, bool] | None:
    roles: dict[str, bool] = {}
    for text in texts:
        cell_roles: dict[str, bool] = {}
        separator = _grouped_separator(text)
        if separator is not None and text.count(separator) > 1:
            cell_roles[separator] = True
        if _GROUPED_DECIMAL_COMMA.fullmatch(text):
            cell_roles.update({",": True, ".": False})
        elif _GROUPED_DECIMAL_DOT.fullmatch(text):
            cell_roles.update({".": True, ",": False})
        elif separator is None and _number(text) is not None:
            for decimal_separator in ",.":
                if decimal_separator in text:
                    cell_roles[decimal_separator] = False
        if any(key in roles and roles[key] != role for key, role in cell_roles.items()):
            return None
        roles.update(cell_roles)
    return roles


def _numbers_with_roles(value: Any, roles: dict[str, bool]) -> set[Decimal]:
    text = _normalized_number_syntax(value)
    values = _possible_numbers(text)
    separator = _grouped_separator(text)
    if len(values) > 1 and separator in roles:
        number = _grouped_number(text) if roles[separator] else _number(text)
        return {number} if number is not None else set()
    return values


def _proven_total_mismatch(cells: list[Any]) -> bool:
    texts = [_normalized_number_syntax(cell) for cell in cells]
    possibilities = [_possible_numbers(text) for text in texts]
    if not all(possibilities):
        return False
    pinned_roles = _pinned_roles(texts)
    if pinned_roles is None:
        return False
    ambiguous_separators = sorted({
        separator for text, values in zip(texts, possibilities, strict=True)
        if len(values) > 1 and (separator := _grouped_separator(text)) is not None and separator not in pinned_roles
    })
    for choices in product((False, True), repeat=len(ambiguous_separators)):
        grouping_by_separator = dict(zip(ambiguous_separators, choices, strict=True))
        grouping_by_separator.update(pinned_roles)
        coherent = []
        for text, values in zip(texts, possibilities, strict=True):
            coherent.append(_numbers_with_roles(text, grouping_by_separator))
        if any(left + right == total for left in coherent[0] for right in coherent[1] for total in coherent[2]):
            return False
    return True


def _same_numeric_cell(displayed: Any, source: Any, roles: dict[str, bool]) -> bool:
    displayed_text = _normalized_number_syntax(displayed)
    source_text = _normalized_number_syntax(source)
    if displayed_text == source_text and _possible_numbers(source_text):
        return True
    displayed_numbers = _numbers_with_roles(displayed_text, roles)
    source_numbers = _numbers_with_roles(source_text, roles)
    return len(displayed_numbers) == len(source_numbers) == 1 and displayed_numbers == source_numbers


def _same_row_revenue_total(
    periods: list[str], values: list[str], source_tables: list[dict[str, Any]],
) -> VerifiedRevenueTotal | None:
    annual_keys = [_period_key(period) for period in periods[:-1]]
    if not annual_keys or any(key is None or key[1:] != (1, 12) for key in annual_keys):
        return None
    if any(not _possible_numbers(value) for value in values[:-1]):
        return None
    years = [key[0] for key in annual_keys if key is not None]
    if years != list(range(years[0], years[-1] + 1)):
        return None

    matches: list[tuple[VerifiedRevenueTotal, Decimal]] = []
    for source in source_tables:
        if not isinstance(source, dict) or source.get("metric") != "revenue":
            continue
        source_periods = source.get("periods")
        if not isinstance(source_periods, list):
            continue
        source_total_index = next((i for i, period in enumerate(source_periods) if _TOTAL_PERIOD.search(str(period))), None)
        if source_total_index is None:
            continue
        source_keys = [_period_key(period) for i, period in enumerate(source_periods) if i != source_total_index]
        if any(key is None or key[1:] != (1, 12) for key in source_keys):
            continue
        if not _total_matches_horizon(str(source_periods[source_total_index]), source_keys, annual_keys):
            continue
        columns = {key[0]: i for i, key in enumerate(_period_key(period) for period in source_periods) if key is not None}
        if len(columns) != len(source_keys) or any(year not in columns for year in years):
            continue
        for source_row in source.get("rows") or []:
            source_values = source_row.get("values") if isinstance(source_row, dict) else None
            if not isinstance(source_values, list) or source_total_index >= len(source_values):
                continue
            total_text = _normalized_number_syntax(source_values[source_total_index])
            source_cells = [source_values[columns[year]] for year in years if columns[year] < len(source_values)]
            if len(source_cells) != len(years):
                continue
            source_roles = _pinned_roles([_normalized_number_syntax(cell) for cell in [*source_cells, total_text]])
            if source_roles is None:
                continue
            separator = _grouped_separator(total_text)
            if separator is not None and len(_possible_numbers(total_text)) > 1 and separator not in source_roles:
                if not any(
                    year in columns and columns[year] < len(source_values)
                    and _source_grouping_separator(_normalized_number_syntax(source_values[columns[year]])) == separator
                    and (
                        len(_possible_numbers(source_values[columns[year]])) > 1
                        or _grouped_decimal_number(_normalized_number_syntax(source_values[columns[year]])) is not None
                        or _normalized_number_syntax(source_values[columns[year]]).count(separator) > 1
                    )
                    for year in years
                ) or any(
                    year not in columns or columns[year] >= len(source_values)
                    or not _compatible_with_grouped_row(source_values[columns[year]], separator)
                    for year in years
                ):
                    continue
                source_roles[separator] = True
            resolved_total = _numbers_with_roles(total_text, source_roles)
            total = next(iter(resolved_total)) if len(resolved_total) == 1 else None
            if total is None or any(
                columns[year] >= len(source_values)
                or not _same_numeric_cell(values[index], source_values[columns[year]], source_roles)
                for index, year in enumerate(years)
            ):
                continue
            matches.append((VerifiedRevenueTotal(
                value=str(source_values[source_total_index]).strip(),
                source_block_id=source.get("source_block_id") if isinstance(source.get("source_block_id"), str) else None,
                source_page=source.get("source_page") if isinstance(source.get("source_page"), int) else None,
            ), total))
    if not matches or len({number for _, number in matches}) != 1:
        return None
    return matches[0][0]


def _compatible_with_grouped_row(value: Any, separator: str) -> bool:
    text = _normalized_number_syntax(value)
    if _source_grouping_separator(text) == separator:
        return True
    number = _unambiguous_number(text)
    return number is not None and abs(number) < 1000


def _source_grouping_separator(text: str) -> str | None:
    if _GROUPED_DECIMAL_COMMA.fullmatch(text):
        return ","
    if _GROUPED_DECIMAL_DOT.fullmatch(text):
        return "."
    return _grouped_separator(text)


def _fill_annual_total_revenue(table: dict[str, Any], total_index: int | None) -> None:
    """Sum complete, unambiguous annual values only for a missing Total Revenue total."""
    periods = table.get("periods")
    rows = table.get("rows")
    if not isinstance(periods, list) or not isinstance(rows, list) or total_index != len(periods) - 1:
        return
    row = next((item for item in rows if isinstance(item, dict) and item.get("label") == "Total Revenue"), None)
    values = row.get("values") if isinstance(row, dict) else None
    if not isinstance(values, list) or len(values) != len(periods) or not _missing_total(values[total_index], include_dashes=True):
        return
    keys = [_period_key(period) for period in periods[:total_index]]
    if not keys or any(key is None or key[1:] != (1, 12) for key in keys):
        return
    years = [key[0] for key in keys if key is not None]
    if years != list(range(years[0], years[-1] + 1)):
        return
    annual_values = [str(value).strip() for value in values[:total_index]]
    if any(_PLAIN_REVENUE.fullmatch(value) is None for value in annual_values):
        return
    numbers = [_number(value) for value in annual_values]
    if any(number is None for number in numbers):
        return
    calculated = format(sum(numbers).normalize(), "f")
    if any("," in value for value in annual_values) and not any("." in value for value in annual_values):
        calculated = calculated.replace(".", ",")
    values[total_index] = calculated
    if _YEAR.search(str(periods[total_index])):
        periods[total_index] = f"Total {years[0]}–{years[-1]}"


def apply_revenue_from_dtb_fallback(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy sourced Total Revenue only where cumulative DTB supports attribution."""
    summary = payload.get("traction_summary")
    if not isinstance(summary, dict) or not isinstance(summary.get("rows"), list) or not isinstance(summary.get("periods"), list):
        return payload
    rows = {row.get("label"): row for row in summary["rows"] if isinstance(row, dict)}
    dtb = rows.get("DTB Uplift (Cumul)")
    from_dtb = rows.get("Revenue from DTB")
    non_dtb = rows.get("Revenue non-DTB")
    total = rows.get("Total Revenue")
    if not all(isinstance(row, dict) and isinstance(row.get("values"), list) for row in (dtb, from_dtb, non_dtb, total)):
        return payload

    def present(value: Any) -> bool:
        return display_traction_cell(value, "new-summary-v8") != "—"

    if any(present(value) for value in non_dtb["values"]):
        return payload
    period_indices = [index for index, period in enumerate(summary["periods"]) if not _TOTAL_PERIOD.search(str(period))]
    if not any(index < len(dtb["values"]) and present(dtb["values"][index]) for index in period_indices):
        return payload

    updated = deepcopy(payload)
    updated_rows = {row["label"]: row for row in updated["traction_summary"]["rows"]}
    target = updated_rows["Revenue from DTB"]["values"]
    for index in period_indices:
        if (
            index < len(target) and index < len(total["values"]) and index < len(dtb["values"])
            and present(total["values"][index]) and present(dtb["values"][index]) and not present(target[index])
        ):
            target[index] = total["values"][index]

    revenue_indices = [index for index in period_indices if index < len(total["values"]) and present(total["values"][index])]
    if revenue_indices and all(index < len(dtb["values"]) and present(dtb["values"][index]) for index in revenue_indices):
        for index, period in enumerate(summary["periods"]):
            if _TOTAL_PERIOD.search(str(period)) and index < len(target) and index < len(total["values"]):
                if present(total["values"][index]) and not present(target[index]):
                    target[index] = total["values"][index]
    return updated


def _missing_total(value: Any, *, include_dashes: bool = False) -> bool:
    text = str(value or "").strip().casefold()
    return not text or (include_dashes and text in {"-", "–", "—"}) or text in {
        "отсутствуют данные в документе защиты",
        "невозможно извлечь данные",
        "no data in the defense document",
        "could not extract data",
        "не смог получить данные",
        "нет данных в документе",
        "no data in the document",
    }


def display_traction_cell(value: Any, schema_version: str | None) -> str:
    text = clean_table_cell(str(value if value is not None else ""))
    if text in {"", "-", "–", "—"}:
        return "—"
    if schema_version == "new-summary-v8" and _missing_total(text):
        return "—"
    if schema_version == "new-summary-v8" and text.casefold() in {
        "значение не найдено в документе",
        "value not found in the document",
    }:
        return "—"
    return text
