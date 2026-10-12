from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from skills.traction_tables import _block_rows, _incremental_rows, display_traction_tables, source_traction_tables
from app.services.new_summary_source_tables import verified_revenue_total


@pytest.mark.parametrize("section", ["CoS", "COGS", "Cost of Sales", "Себестоимость", "Operating expenses", "Total costs uplift"])
def test_revenue_candidates_exclude_expense_section_even_with_revenue_in_name(section):
    rows = [
        ["Increment P&L, mR", "2026", "2027", "2026-27 total"],
        ["Revenue uplift", "10", "20", "30"],
        [section, "(4)", "(8)", "(12)"],
        ["Subsidies", "(1)", "(2)", "(3)"],
        ["Partner revenue", "(3)", "(6)", "(9)"],
        ["Total partner revenue", "(3)", "(6)", "(9)"],
    ]
    candidates = _incremental_rows(rows)
    assert len(candidates) == 1
    assert candidates[0][1]["rows"] == [{"label": "Revenue uplift", "values": ["10", "20", "30"]}]


def test_genuine_partner_revenue_and_negative_uplift_are_not_excluded():
    rows = [
        ["Increment P&L, mR", "2026", "2027", "Total"],
        ["Partner revenue", "(10)", "20", "10"],
        ["CoS", "1", "2", "3"],
        ["Partner revenue", "1", "2", "3"],
        ["Gross profit", "(11)", "18", "7"],
        ["Revenue", "", "", ""],
        ["Partner revenue uplift", "5", "6", "11"],
    ]
    candidates = _incremental_rows(rows)
    assert [table["rows"][0]["values"] for _, table in candidates] == [["(10)", "20", "10"], ["5", "6", "11"]]


def test_cost_context_survives_repeated_header_but_not_a_different_table():
    rows = [
        ["Increment P&L", "2026", "2027", "Total"],
        ["CoS", "1", "2", "3"],
        ["Increment P&L", "2026", "2027", "Total"],
        ["Partner revenue", "1", "2", "3"],
        ["Incremental revenue", "2026", "2027", "Total"],
        ["Partner revenue", "10", "20", "30"],
    ]
    candidates = _incremental_rows(rows)
    assert len(candidates) == 1
    assert candidates[0][1]["rows"][0]["values"] == ["10", "20", "30"]


def test_source_tables_do_not_merge_cos_into_revenue_and_keep_dtb(monkeypatch):
    from copy import deepcopy
    import skills.traction_tables as extraction

    blocks = [{"id": "pnl", "page": 4, "metadata": {"rows": [
        ["Increment P&L, mR", "2026", "2027", "Total"],
        ["Revenue uplift", "10", "20", "30"],
        ["CoS", "(1)", "(2)", "(3)"],
        ["Partner revenue", "(1)", "(2)", "(3)"],
    ]}}, {"id": "dtb", "page": 3, "metadata": {"rows": [
        ["DTB cumulative, %", "2026", "2027", "Total"],
        ["DTB cumulative", "1%", "3%", ""],
    ]}}]
    original = deepcopy(blocks)
    monkeypatch.setattr(extraction, "verified_table_blocks", lambda document: blocks)
    tables = source_traction_tables(SimpleNamespace())
    assert [table["metric"] for table in tables] == ["revenue", "dtb"]
    assert tables[0]["rows"] == [{"label": "Revenue uplift", "values": ["10", "20", "30"]}]
    assert tables[0]["source_block_id"] == "pnl"
    assert tables[1]["rows"][0]["values"][:2] == ["1%", "3%"]
    for language in ("ru", "en"):
        assert len(display_traction_tables(tables, language=language)["tables"][0]["rows"]) == 1
    assert blocks == original


def test_incremental_revenue_uses_full_source_horizon_and_excludes_tobe():
    rows = [
        ["Increment P&L, mR", "2026", "2027", "2028", "2029", "2030", "2031", "", "2026-31 total"],
        ["Revenue", "86", "379", "626", "817", "936", "1 012", "", "3 857"],
        ["ToBe P&L, mR", "2026", "2027", "2028", "2029", "2030", "2031", "", "2026-31 total"],
        ["Revenue", "298", "573", "824", "1 031", "1 168", "1 249", "", "5 144"],
    ]
    candidates = _incremental_rows(rows)
    assert len(candidates) == 1
    _score, table = candidates[0]
    assert table["periods"] == ["2026", "2027", "2028", "2029", "2030", "2031", "2026-31 total"]
    assert table["rows"][0]["values"] == ["86", "379", "626", "817", "936", "1 012", "3 857"]


def test_dtb_and_revenue_keep_independent_periods():
    revenue = _incremental_rows([
        ["Incremental revenue, mR", "2026", "2027", "2026-27 total"],
        ["Revenue", "10", "20", "30"],
    ])[0][1]
    dtb = _incremental_rows([
        ["Incremental DTB, %", "CY26", "CY27", "CY28", "Total"],
        ["DTB", "1%", "2%", "3%", "2%"],
    ])[0][1]
    rendered = display_traction_tables([revenue, dtb], language="ru")
    assert [table["metric"] for table in rendered["tables"]] == ["revenue", "dtb"]
    assert len(rendered["tables"][0]["periods"]) == 3
    assert len(rendered["tables"][1]["periods"]) == 4
    assert rendered["tables"][1]["rows"][0]["values"] == ["1%", "2%", "3%", "2%"]


def test_source_table_blank_cell_is_explained_without_changing_real_values():
    table = _incremental_rows([
        ["Incremental revenue, mR", "2026", "2027", "Total"],
        ["Revenue", "10", "", "30"],
    ])[0][1]
    assert display_traction_tables([table], language="ru")["tables"][0]["rows"][0]["values"] == [
        "10", "Нет данных в документе", "30",
    ]
    assert display_traction_tables([table], language="en")["tables"][0]["rows"][0]["values"] == [
        "10", "No data in the document", "30",
    ]


def test_source_total_blank_is_reported_as_missing_not_summed():
    table = _incremental_rows([
        ["Incremental revenue, mR", "2026", "2027", "Total"],
        ["Revenue", "10", "20", ""],
    ])[0][1]
    assert display_traction_tables([table], language="ru")["tables"][0]["rows"][0]["values"][-1] == (
        "отсутствуют данные в документе защиты"
    )


def test_legacy_markdown_table_rows_are_read_without_reparse():
    block = {
        "markdown": "| Increment P&L, mR | 2026 | 2027 | 2026-27 total |\n"
        "| --- | --- | --- | --- |\n"
        "| Revenue | 1 | 2 | 3 |",
        "metadata": {"extractor": "pdfplumber"},
    }
    assert _incremental_rows(_block_rows(block))[0][1]["rows"][0]["values"] == ["1", "2", "3"]


def test_parsed_table_break_markers_do_not_leak_into_total_header_or_values():
    block = {"metadata": {"rows": [
        ["Increment P&L, mR", "2026", "2027", "2026-27<br>total"],
        ["Revenue", "10", "20", "30<br/>"],
    ]}}
    table = _incremental_rows(_block_rows(block))[0][1]
    assert table["periods"] == ["2026", "2027", "2026-27 total"]
    assert table["rows"][0]["values"] == ["10", "20", "30"]


def test_previous_scenario_is_not_used_as_current_incremental_data():
    assert _incremental_rows([
        ["Diff vs IC 25, mR", "2026", "2027", "Total"],
        ["Revenue", "-1", "-2", "-3"],
    ]) == []


def test_same_metric_prefers_source_table_with_explicit_total():
    without_total = _incremental_rows([
        ["Incremental revenue", "2026", "2027"],
        ["Revenue", "10", "20"],
    ])[0]
    with_total = _incremental_rows([
        ["Incremental revenue", "2026", "2027", "Total"],
        ["Revenue", "10", "20", "30"],
    ])[0]
    assert with_total[0] > without_total[0]


def test_source_tables_use_matching_owned_artifact_and_ignore_stale_parse(tmp_path, monkeypatch):
    import app.core.config as config

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(storage_root=tmp_path))
    document = SimpleNamespace(
        owner_id=uuid4(), document_id=uuid4(), parsed_text="Parsed source", file_hash_sha256="a" * 64
    )
    document.id = document.document_id
    parsed_dir = tmp_path / "documents" / str(document.owner_id) / str(document.id) / "parsed"
    parsed_dir.mkdir(parents=True)
    artifact = {
        "source": {"sha256": document.file_hash_sha256},
        "outputs": {"plain_text_sha256": hashlib.sha256(document.parsed_text.encode()).hexdigest()},
        "blocks": [{
            "id": "b0014", "type": "table", "page": 14,
            "metadata": {"rows": [
                ["Increment P&L, mR", "2026", "2027", "2026-27 total"],
                ["Revenue", "86", "379", "465"],
            ]},
        }],
    }
    (parsed_dir / "structured.json").write_text(json.dumps(artifact))
    tables = source_traction_tables(document)
    assert tables[0]["source_page"] == 14
    assert tables[0]["rows"][0]["values"] == ["86", "379", "465"]
    document.file_hash_sha256 = "b" * 64
    assert source_traction_tables(document) == []


def test_source_traction_tables_never_borrows_total_from_tobe(tmp_path, monkeypatch):
    import app.core.config as config

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(storage_root=tmp_path))
    document = SimpleNamespace(
        owner_id=uuid4(), id=uuid4(), parsed_text="Parsed source", file_hash_sha256="a" * 64
    )
    parsed_dir = tmp_path / "documents" / str(document.owner_id) / str(document.id) / "parsed"
    parsed_dir.mkdir(parents=True)
    incremental = {
        "id": "b0082", "type": "table", "metadata": {"rows": [
            ["Increment P&L, mR", "H2 2026", "2026", "2027", "2028", "2029", "2030"],
            ["Revenue", "41", "41", "235", "1 797", "2 995", "4 250"],
        ]},
    }
    tobe = {
        "id": "b0089", "type": "table", "metadata": {"rows": [
            ["ToBe P&L, mR", "2025", "2026", "2027", "2028", "2029", "2030", "2026-30 total"],
            ["Revenue", "-", "41", "235", "1 797", "2 995", "4 250", "9 318"],
        ]},
    }
    artifact = {
        "source": {"sha256": document.file_hash_sha256},
        "outputs": {"plain_text_sha256": hashlib.sha256(document.parsed_text.encode()).hexdigest()},
        "blocks": [incremental, tobe],
    }
    (parsed_dir / "structured.json").write_text(json.dumps(artifact))
    revenue = source_traction_tables(document)[0]
    assert revenue["metric"] == "revenue"
    assert revenue["periods"][-1] == "2030"
    assert revenue["rows"][0]["values"][-1] == "4 250"
    assert revenue["source_block_id"] == "b0082"

    tobe["metadata"]["rows"][1][3] = "236"
    (parsed_dir / "structured.json").write_text(json.dumps(artifact))
    assert source_traction_tables(document)[0]["periods"][-1] == "2030"


def test_financial_model_revenue_beats_conflicting_incremental_table(tmp_path, monkeypatch):
    import app.core.config as config

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(storage_root=tmp_path))
    document = SimpleNamespace(owner_id=uuid4(), id=uuid4(), parsed_text="Parsed source", file_hash_sha256="a" * 64)
    parsed_dir = tmp_path / "documents" / str(document.owner_id) / str(document.id) / "parsed"
    parsed_dir.mkdir(parents=True)
    artifact = {
        "source": {"sha256": document.file_hash_sha256},
        "outputs": {"plain_text_sha256": hashlib.sha256(document.parsed_text.encode()).hexdigest()},
        "blocks": [
            {"id": "old", "type": "table", "metadata": {"rows": [
                ["Increment P&L", "2027", "2028", "Total"], ["Revenue", "10", "20", "30"],
            ]}},
            {"id": "current", "type": "table", "metadata": {"rows": [
                ["Financial Model", "2027", "2028", "Total"],
                ["Revenue", "12", "22", "34"],
                ["CoS", "", "", ""], ["Partner revenue", "2", "3", "5"],
            ]}},
        ],
    }
    (parsed_dir / "structured.json").write_text(json.dumps(artifact))

    revenue = source_traction_tables(document)[0]
    assert revenue["source_block_id"] == "current"
    assert revenue["rows"][0]["values"] == ["12", "22", "34"]
    assert all(row["label"] != "Partner revenue" for row in revenue["rows"])


def test_verified_revenue_total_rejects_wrong_horizon_or_ambiguous_totals():
    periods = ["2026", "2027"]
    values = ["10", "20"]
    block = {"id": "faq", "metadata": {"rows": [
        ["ToBe P&L", "2026", "2027", "2026-28 total"],
        ["Revenue", "10", "20", "30"],
    ]}}
    assert verified_revenue_total(periods, values, [block]) is None
    block["metadata"]["rows"][0][-1] = "2026-27 total"
    assert verified_revenue_total(periods, values, [block]).value == "30"
    other = {"id": "alternative", "metadata": {"rows": [
        ["ToBe P&L", "2026", "2027", "2026-27 total"],
        ["Revenue", "10", "20", "31"],
    ]}}
    assert verified_revenue_total(periods, values, [block, other]) is None
