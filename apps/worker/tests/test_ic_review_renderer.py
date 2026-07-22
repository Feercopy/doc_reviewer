from __future__ import annotations

from dataclasses import dataclass
import json
from uuid import uuid4

import pytest
from jsonschema import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.analysis import Analysis, AnalysisCheckRun, AnalysisCheckStep
from app.schemas.enums import Provider, RunStatus
from app.storage.local import LocalDocumentStorage
from ic_review.context import ICReviewContext
from ic_review.context_pack import build_ic_review_context_pack
from ic_review.renderer import ROLE_ORDER, render_role_prompt, render_synthesis_prompt
from ic_review.role_runner import run_role_step, _role_run_parameters


@dataclass(frozen=True)
class SnapshotStub:
    files: dict[str, str]

    def read_text(self, relative_path: str) -> str | None:
        return self.files.get(relative_path)


def _snapshot() -> SnapshotStub:
    files = {
        ".claude/commands/invest-analysis.md": "Synthesize the IC investment analysis.",
    }
    for role in ROLE_ORDER:
        files[f".claude/agents/{role}.md"] = f"Original instructions for {role}."
    return SnapshotStub(files)


def _context(*, workbook: bool = False) -> ICReviewContext:
    return ICReviewContext(
        document_title="Gate 3: Courier Expansion",
        document_type="gate_3",
        parsed_document_text="The document claims break-even by month six.",
        main_analysis_verdict="need_evidence",
        main_analysis_summary="Unit economics proof is incomplete.",
        main_analysis_structured_output={"verdict": "need_evidence", "summary": "Needs proof."},
        main_analysis_detail_output={"layer_2": [{"id": "L2-1", "status": "fail"}]},
        workbook_extraction_summary={"sheet_count": 2, "sheets": [{"name": "P&L"}]} if workbook else None,
        formula_auditor_summary={"critical_formula_issues_count": 1} if workbook else None,
        output_language="ru",
    )


def test_all_eight_role_prompt_names_can_be_loaded_from_snapshot():
    snapshot = _snapshot()

    prompts = [
        render_role_prompt(role=role, context=_context(), source_snapshot=snapshot)
        for role in ROLE_ORDER
    ]

    assert list(ROLE_ORDER) == [
        "ic-financial-auditor",
        "ic-product-analyst",
        "ic-market-analyst",
        "ic-web-researcher",
        "ic-benchmark-valuation",
        "ic-team-legal",
        "ic-tech-dd",
        "ic-risk-scenario",
    ]
    for role, prompt in zip(ROLE_ORDER, prompts, strict=True):
        assert f"Original instructions for {role}." in prompt


def test_role_prompt_includes_main_analysis_verdict_and_compact_schema_name():
    prompt = render_role_prompt(
        role="ic-product-analyst",
        context=_context(),
        source_snapshot=_snapshot(),
    )

    assert "need_evidence" in prompt
    assert "ic-agentic-role-result.schema.json" in prompt
    assert "Return only JSON" in prompt
    assert "full_report_materials" in prompt


def test_role_prompt_includes_workbook_context_only_when_workbook_exists():
    prompt_without_workbook = render_role_prompt(
        role="ic-financial-auditor",
        context=_context(workbook=False),
        source_snapshot=_snapshot(),
    )
    prompt_with_workbook = render_role_prompt(
        role="ic-financial-auditor",
        context=_context(workbook=True),
        source_snapshot=_snapshot(),
    )

    assert '"workbook_context": null' in prompt_without_workbook
    assert "critical_formula_issues_count" not in prompt_without_workbook
    assert "workbook_context" in prompt_with_workbook
    assert "## Workbook Context" not in prompt_with_workbook
    assert "critical_formula_issues_count" in prompt_with_workbook


def test_role_prompt_compacts_large_workbook_context():
    rows = [
        {
            "row_number": row_number,
            "cells": [
                {
                    "address": f"{chr(65 + column_index)}{row_number}",
                    "column": column_index + 1,
                    "formula": f"=SUM(A{row_number}:B{row_number})" if column_index % 7 == 0 else None,
                    "value": f"cell_text_{row_number}_{column_index}_" + ("x" * 80),
                }
                for column_index in range(30)
            ],
        }
        for row_number in range(1, 81)
    ]
    workbook = {
        "format": "xlsx_bounded_snapshot_v1",
        "source_filename": "large-model.xlsx",
        "sheet_count": 4,
        "sheets": [
            {
                "name": f"Sheet {index}",
                "dimensions": {"max_row": 180, "max_column": 60},
                "rows_truncated": True,
                "columns_truncated": True,
                "rows": rows,
            }
            for index in range(4)
        ],
    }
    context = ICReviewContext(
        document_title="Gate 3: Courier Expansion",
        document_type="gate_3",
        parsed_document_text="CAC payback needs proof.",
        main_analysis_verdict="need_evidence",
        main_analysis_summary="Unit economics proof is incomplete.",
        main_analysis_structured_output={"verdict": "need_evidence"},
        main_analysis_detail_output=None,
        workbook_extraction_summary=workbook,
        formula_auditor_summary={"critical_formula_issues_count": 2, "issues": [{"cell": "P&L!B12"}]},
        output_language="ru",
    )

    prompt = render_role_prompt(
        role="ic-financial-auditor",
        context=context,
        source_snapshot=_snapshot(),
    )

    assert len(prompt) < 90_000
    assert "large-model.xlsx" in prompt
    assert "## Workbook Context" not in prompt
    assert prompt.count("workbook_context") == 1


def test_context_pack_keeps_traceable_evidence_without_repeating_full_document():
    filler = "Generic rollout background without investment evidence. " * 180
    financial_evidence = "Section 4: CAC payback is 19 months, gross margin is 31%, and burn rises in the downside case."
    tech_evidence = "Section 8: API reliability has no SLA, integration monitoring is manual, and data lineage is missing."
    context = ICReviewContext(
        document_title="Gate 3: Courier Expansion",
        document_type="gate_3",
        parsed_document_text="\n\n".join([filler, financial_evidence, filler, tech_evidence, filler]),
        main_analysis_verdict="need_evidence",
        main_analysis_summary="Unit economics proof is incomplete.",
        main_analysis_structured_output={"verdict": "need_evidence", "top_findings": [{"title": "CAC payback"}]},
        main_analysis_detail_output={"layer_2": [{"id": "L2-1", "status": "fail", "evidence": financial_evidence}]},
        workbook_extraction_summary={"sheet_count": 1, "sheets": [{"name": "P&L", "max_row": 40}]},
        formula_auditor_summary={"critical_formula_issues_count": 1, "issues": [{"cell": "P&L!B12"}]},
        output_language="ru",
    )

    pack = build_ic_review_context_pack(context)
    financial_context = pack.for_role("ic-financial-auditor")
    tech_context = pack.for_role("ic-tech-dd")
    packed_text = json.dumps(financial_context, ensure_ascii=False)

    assert pack.source_stats["parsed_document_chars"] == len(context.parsed_document_text)
    assert len(packed_text) < len(context.parsed_document_text) * 0.65
    assert "CAC payback is 19 months" in packed_text
    assert "evidence_id" in packed_text
    assert "critical_formula_issues_count" in packed_text
    assert "API reliability has no SLA" in json.dumps(tech_context, ensure_ascii=False)
    assert context.parsed_document_text not in packed_text


def test_role_and_synthesis_prompts_use_context_pack_instead_of_full_document_text():
    long_tail = "FULL_RAW_DOCUMENT_SENTINEL " * 220
    evidence = "Revenue retention is not proven by cohorts, but CAC payback is stated as 19 months."
    context = ICReviewContext(
        document_title="Gate 3: Courier Expansion",
        document_type="gate_3",
        parsed_document_text=f"{evidence}\n\n{long_tail}",
        main_analysis_verdict="need_evidence",
        main_analysis_summary="Unit economics proof is incomplete.",
        main_analysis_structured_output={"verdict": "need_evidence"},
        main_analysis_detail_output=None,
        output_language="ru",
    )
    role_outputs = {role: _role_result(role) for role in ROLE_ORDER}
    pack = build_ic_review_context_pack(context)

    role_prompt = render_role_prompt(
        role="ic-financial-auditor",
        context=context,
        context_pack=pack,
        source_snapshot=_snapshot(),
    )
    synthesis_prompt = render_synthesis_prompt(
        context=context,
        context_pack=pack,
        role_outputs=role_outputs,
        source_snapshot=_snapshot(),
    )

    assert "## Context Pack" in role_prompt
    assert "Revenue retention is not proven" in role_prompt
    assert "FULL_RAW_DOCUMENT_SENTINEL" not in role_prompt
    assert "FULL_RAW_DOCUMENT_SENTINEL" not in synthesis_prompt
    assert "parsed_document_text" not in synthesis_prompt


def test_synthesis_prompt_includes_all_eight_role_outputs_and_compact_schema_name():
    role_outputs = {
        role: {
            "role": role,
            "section_keys": ["section_4"],
            "summary": f"Summary for {role}",
            "findings": [],
            "data_gaps": [],
            "numbers_used": [],
            "full_report_materials": _full_report_materials(role),
        }
        for role in ROLE_ORDER
    }

    prompt = render_synthesis_prompt(
        context=_context(),
        role_outputs=role_outputs,
        source_snapshot=_snapshot(),
    )

    for role in ROLE_ORDER:
        assert role in prompt
        assert f"Summary for {role}" in prompt
    assert "ic-agentic-review-result.schema.json" in prompt
    assert "worker will assemble the full PDF/Markdown report" in prompt
    assert "do not return the full report here" in prompt
    assert "full_report_materials" in prompt
    assert "Russian" in prompt


def test_synthesis_prompt_requires_all_eight_role_outputs():
    role_outputs = {
        role: _role_result(role)
        for role in ROLE_ORDER
        if role != "ic-risk-scenario"
    }

    with pytest.raises(ValueError, match="missing_role_outputs:ic-risk-scenario"):
        render_synthesis_prompt(
            context=_context(),
            role_outputs=role_outputs,
            source_snapshot=_snapshot(),
        )


def test_render_role_prompt_rejects_unknown_role():
    with pytest.raises(ValueError, match="unsupported_ic_role"):
        render_role_prompt(role="not-a-role", context=_context(), source_snapshot=_snapshot())


def test_run_role_step_persists_prompt_raw_structured_and_metadata(tmp_path):
    db = _create_session()
    try:
        analysis = _analysis()
        role_result = _role_result("ic-product-analyst")
        check_run = _check_run(
            analysis_id=analysis.id,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": json.dumps(role_result),
                    "raw_output": "raw role output",
                    "input_tokens": 12,
                    "output_tokens": 34,
                    "latency_ms": 56,
                }
            },
        )
        db.add_all([analysis, check_run])
        db.commit()

        structured = run_role_step(
            session=db,
            check_run=check_run,
            analysis=analysis,
            role="ic-product-analyst",
            context=_context(),
            source_snapshot=_snapshot(),
            storage=LocalDocumentStorage(tmp_path / "storage"),
        )

        step = db.execute(select(AnalysisCheckStep)).scalar_one()
        prompt_path = tmp_path / "storage" / "ic-review" / str(analysis.id) / str(check_run.id) / "prompts" / "ic-product-analyst.txt"
        assert structured == role_result
        assert step.status == RunStatus.COMPLETED.value
        assert step.raw_output == "raw role output"
        assert step.structured_output == role_result
        assert step.input_tokens == 12
        assert step.output_tokens == 34
        assert step.latency_ms == 56
        assert step.prompt_fingerprint
        assert step.prompt_artifact_path == str(prompt_path)
        assert prompt_path.read_text(encoding="utf-8")
    finally:
        db.close()


def test_run_role_step_trims_overlong_schema_bounded_strings_before_validation(tmp_path):
    db = _create_session()
    try:
        analysis = _analysis()
        role_result = {
            **_role_result("ic-tech-dd"),
            "summary": "x" * 1565,
        }
        raw_output = json.dumps(role_result)
        check_run = _check_run(
            analysis_id=analysis.id,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": raw_output,
                    "raw_output": raw_output,
                    "input_tokens": 17,
                    "output_tokens": 19,
                    "latency_ms": 23,
                }
            },
        )
        db.add_all([analysis, check_run])
        db.commit()

        structured = run_role_step(
            session=db,
            check_run=check_run,
            analysis=analysis,
            role="ic-tech-dd",
            context=_context(),
            source_snapshot=_snapshot(),
            storage=LocalDocumentStorage(tmp_path / "storage"),
        )

        step = db.execute(select(AnalysisCheckStep)).scalar_one()
        assert step.status == RunStatus.COMPLETED.value
        assert len(structured["summary"]) == 1500
        assert len(step.structured_output["summary"]) == 1500
        assert step.raw_output == raw_output
        assert len(json.loads(step.raw_output)["summary"]) == 1565
        assert step.input_tokens == 17
        assert step.output_tokens == 19
    finally:
        db.close()


def test_role_run_parameters_add_provider_timeouts_and_preserve_overrides():
    defaulted = _role_run_parameters(
        base_parameters={},
        role="ic-product-analyst",
        overrides=None,
    )
    overridden = _role_run_parameters(
        base_parameters={"timeout_seconds": 120, "connect_timeout_seconds": 15, "max_retries": 1},
        role="ic-product-analyst",
        overrides={"timeout_seconds": 240},
    )

    assert defaulted["timeout_seconds"] == 600
    assert defaulted["connect_timeout_seconds"] == 30
    assert defaulted["max_retries"] == 3
    assert defaulted["max_output_tokens"] == 32000
    assert defaulted["ic_review_role"] == "ic-product-analyst"
    assert overridden["timeout_seconds"] == 240
    assert overridden["connect_timeout_seconds"] == 15
    assert overridden["max_retries"] == 1


def test_run_role_step_marks_prompt_render_failure_failed(tmp_path):
    db = _create_session()
    try:
        analysis = _analysis()
        check_run = _check_run(analysis_id=analysis.id, run_parameters={})
        db.add_all([analysis, check_run])
        db.commit()

        with pytest.raises(ValueError, match="unsupported_ic_role"):
            run_role_step(
                session=db,
                check_run=check_run,
                analysis=analysis,
                role="not-a-role",
                context=_context(),
                source_snapshot=_snapshot(),
                storage=LocalDocumentStorage(tmp_path / "storage"),
            )

        step = db.execute(select(AnalysisCheckStep)).scalar_one()
        db.refresh(check_run)
        assert step.status == RunStatus.FAILED.value
        assert "unsupported_ic_role" in step.error_message
        assert step.raw_output is None
        assert step.completed_at is not None
        assert check_run.status == RunStatus.FAILED.value
        assert check_run.current_stage == "failed:not-a-role"
        assert "unsupported_ic_role" in check_run.error_message
        assert check_run.completed_at is not None
    finally:
        db.close()


def test_run_role_step_role_mock_overrides_global_mock(tmp_path):
    db = _create_session()
    try:
        analysis = _analysis()
        role_result = _role_result("ic-product-analyst")
        check_run = _check_run(
            analysis_id=analysis.id,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": "global mock should not be used",
                    "raw_output": "global raw",
                    "latency_ms": 1,
                },
                "role_mock_provider_results": {
                    "ic-product-analyst": {
                        "structured_text": json.dumps(role_result),
                        "raw_output": "role raw",
                        "latency_ms": 2,
                    }
                },
            },
        )
        db.add_all([analysis, check_run])
        db.commit()

        structured = run_role_step(
            session=db,
            check_run=check_run,
            analysis=analysis,
            role="ic-product-analyst",
            context=_context(),
            source_snapshot=_snapshot(),
            storage=LocalDocumentStorage(tmp_path / "storage"),
        )

        step = db.execute(select(AnalysisCheckStep)).scalar_one()
        assert structured == role_result
        assert step.status == RunStatus.COMPLETED.value
        assert step.raw_output == "role raw"
        assert step.latency_ms == 2
    finally:
        db.close()


def test_run_role_step_retries_invalid_json_once(tmp_path):
    db = _create_session()
    try:
        analysis = _analysis()
        role_result = _role_result("ic-financial-auditor")
        check_run = _check_run(
            analysis_id=analysis.id,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": '{"role": "ic-financial-auditor", "summary": "unterminated',
                    "raw_output": "first invalid role raw",
                    "input_tokens": 101,
                    "output_tokens": 12000,
                    "latency_ms": 303,
                },
                "role_json_retry_mock_provider_results": {
                    "ic-financial-auditor": {
                        "structured_text": json.dumps(role_result),
                        "raw_output": "retry role raw",
                        "input_tokens": 111,
                        "output_tokens": 222,
                        "latency_ms": 333,
                    }
                },
            },
        )
        db.add_all([analysis, check_run])
        db.commit()

        structured = run_role_step(
            session=db,
            check_run=check_run,
            analysis=analysis,
            role="ic-financial-auditor",
            context=_context(workbook=True),
            source_snapshot=_snapshot(),
            storage=LocalDocumentStorage(tmp_path / "storage"),
        )

        step = db.execute(select(AnalysisCheckStep)).scalar_one()
        assert structured == role_result
        assert step.status == RunStatus.COMPLETED.value
        assert step.raw_output == "retry role raw"
        assert step.input_tokens == 111
        assert step.output_tokens == 222
        assert step.latency_ms == 333
        assert step.artifacts == [
            {
                "key": "role_json_retry",
                "kind": "metadata",
                "attempts": 2,
                "reason": "Unterminated string starting at",
                "retry_step": "ic-financial-auditor:json_retry",
            }
        ]
    finally:
        db.close()


def test_run_role_step_marks_run_failed_and_preserves_structured_text_when_schema_validation_fails(tmp_path):
    db = _create_session()
    try:
        analysis = _analysis()
        check_run = _check_run(
            analysis_id=analysis.id,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": "not json from provider",
                    "raw_output": "",
                    "input_tokens": 5,
                    "output_tokens": 7,
                    "latency_ms": 11,
                }
            },
        )
        db.add_all([analysis, check_run])
        db.commit()

        with pytest.raises(json.JSONDecodeError):
            run_role_step(
                session=db,
                check_run=check_run,
                analysis=analysis,
                role="ic-product-analyst",
                context=_context(),
                source_snapshot=_snapshot(),
                storage=LocalDocumentStorage(tmp_path / "storage"),
            )

        step = db.execute(select(AnalysisCheckStep)).scalar_one()
        db.refresh(check_run)
        assert step.status == RunStatus.FAILED.value
        assert step.raw_output == "not json from provider"
        assert step.input_tokens == 5
        assert step.output_tokens == 7
        assert step.latency_ms == 11
        assert "Expecting value" in step.error_message
        assert step.completed_at is not None
        assert check_run.status == RunStatus.FAILED.value
        assert check_run.current_stage == "failed:ic-product-analyst"
        assert "Expecting value" in check_run.error_message
        assert check_run.completed_at is not None
    finally:
        db.close()


def test_run_role_step_schema_validation_error_does_not_leak_provider_instance(tmp_path):
    db = _create_session()
    secret_evidence = "SECRET_DOCUMENT_EVIDENCE_SHOULD_NOT_RENDER"
    try:
        analysis = _analysis()
        invalid_role_result = {
            **_role_result("ic-product-analyst"),
            "role": secret_evidence,
        }
        check_run = _check_run(
            analysis_id=analysis.id,
            run_parameters={
                "mock_provider_result": {
                    "structured_text": json.dumps(invalid_role_result),
                    "raw_output": json.dumps(invalid_role_result),
                    "input_tokens": 5,
                    "output_tokens": 7,
                    "latency_ms": 11,
                }
            },
        )
        db.add_all([analysis, check_run])
        db.commit()

        with pytest.raises(ValidationError):
            run_role_step(
                session=db,
                check_run=check_run,
                analysis=analysis,
                role="ic-product-analyst",
                context=_context(),
                source_snapshot=_snapshot(),
                storage=LocalDocumentStorage(tmp_path / "storage"),
            )

        step = db.execute(select(AnalysisCheckStep)).scalar_one()
        db.refresh(check_run)
        assert step.status == RunStatus.FAILED.value
        assert step.error_message == "schema_validation_failed:enum"
        assert secret_evidence not in step.error_message
        assert check_run.status == RunStatus.FAILED.value
        assert check_run.error_message == "schema_validation_failed:enum"
        assert secret_evidence not in check_run.error_message
        assert secret_evidence in (step.raw_output or "")
    finally:
        db.close()


def _create_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _analysis() -> Analysis:
    return Analysis(
        id=uuid4(),
        document_id=uuid4(),
        user_id=uuid4(),
        skill_id=uuid4(),
        skill_version="baseline",
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Needs proof.",
        structured_output={"verdict": "need_evidence"},
        run_parameters={},
    )


def _check_run(*, analysis_id, run_parameters: dict) -> AnalysisCheckRun:
    return AnalysisCheckRun(
        id=uuid4(),
        analysis_id=analysis_id,
        skill_id=uuid4(),
        skill_version="baseline",
        check_type="ic_agentic_review",
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.RUNNING.value,
        current_stage="role:ic-product-analyst",
        run_parameters=run_parameters,
        artifacts=[],
        uploaded_workbook_metadata={},
    )


def _role_result(role: str) -> dict:
    return {
        "role": role,
        "section_keys": ["section_5"],
        "summary": "Product evidence is incomplete.",
        "findings": [
            {
                "title": "Missing cohort proof",
                "severity": "data_gap",
                "evidence": "Main analysis asks for cohort retention.",
                "recommendation": "Provide cohort table.",
            }
        ],
        "data_gaps": ["Retention cohort by segment"],
        "numbers_used": [{"label": "Retention", "value": "unknown", "source": "Gate Challenger"}],
        "full_report_materials": _full_report_materials(role),
    }


def _full_report_materials(role: str) -> dict:
    return {
        "section_drafts": [
            {
                "section_key": "section_5",
                "title": "Product metrics",
                "content": f"Detailed report material for {role}. Cohort proof is incomplete.",
                "evidence_ids": ["doc-001"],
            }
        ],
        "tables": [
            {
                "section_key": "section_5",
                "title": "Metrics",
                "markdown": "| Metric | Value |\n|---|---|\n| Retention | unknown |",
            }
        ],
        "risks": [{"title": "Missing cohort proof", "detail": "Retention cohorts are absent.", "severity": "data_gap"}],
        "data_gaps": [{"title": "Retention cohort", "detail": "Need retention cohort by segment."}],
        "recommendations": [{"title": "Provide cohort table", "detail": "Add cohort table before IC decision."}],
        "scenarios": [{"title": "Base", "detail": "Base case remains unverified until retention data is provided."}],
        "primary_verify_notes": [f"{role} provides detailed source material."],
    }
