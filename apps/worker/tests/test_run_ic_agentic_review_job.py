from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.core.config import get_settings
from app.models.analysis import Analysis, AnalysisCheckRun, AnalysisCheckStep, AnalysisDetailRun
from app.models.base import utc_now
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.models.skill import Skill
from app.models.skill_source import SkillSourceSnapshot
from app.models.user import User
from app.schemas.enums import DocumentParseStatus, DocumentType, EntityStatus, Provider, Role, RunStatus, SkillSourceType, SkillType, UserStatus
from app.security.secrets import encrypt_secret
from ic_review.renderer import ROLE_ORDER
from ic_review.script_runner import ScriptPipelineResult, ScriptResult
from jobs import run_ic_agentic_review as job
from jobs.run_ic_agentic_review import run_ic_agentic_review


def test_completed_run_without_workbook_skips_spreadsheet_audit_and_persists_artifacts(tmp_path, monkeypatch):
    db = _create_session()
    calls: dict[str, object] = {}
    try:
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=False)
        _patch_script_pipeline(monkeypatch, calls, validation_text="validation ok\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        check_run = db.get(AnalysisCheckRun, records["check_run"].id)
        steps = db.execute(select(AnalysisCheckStep).order_by(AnalysisCheckStep.created_at)).scalars().all()

        assert check_run.status == RunStatus.COMPLETED.value
        assert check_run.current_stage == "completed"
        assert check_run.structured_output["spreadsheet_audit"]["status"] == "not_provided"
        assert check_run.structured_output["validation"] == {
            "status": "pass",
            "summary": "Validation passed with 0 failure(s) and 0 warning(s).",
            "warnings_count": 0,
            "failures_count": 0,
        }
        assert calls["workbook_path"] is None
        assert [step.step_name for step in steps] == [*list(ROLE_ORDER), "result_short_summary", "result_rationale"]
        role_steps = [step for step in steps if step.step_type == "role"]
        result_steps = [step for step in steps if step.step_type == "result_synthesis"]
        assert all(step.raw_output == f"raw {step.step_name}" for step in role_steps)
        assert {step.step_name for step in result_steps} == {"result_short_summary", "result_rationale"}
        assert all(step.prompt_artifact_path for step in result_steps)
        assert all(step.raw_output for step in result_steps)
        assert all(step.structured_output for step in result_steps)
        assert all(
            any(artifact.get("key") == "effective_run_parameters" for artifact in step.artifacts)
            for step in result_steps
        )
        assert check_run.run_parameters["synthesis_prompt_artifact_path"].endswith("/prompts/synthesis.txt")
        assert check_run.run_parameters["synthesis_prompt_fingerprint"]
        artifact_keys = {artifact["key"] for artifact in check_run.artifacts}
        assert "script:json_postprocess:stdout" in artifact_keys
        assert "script:pdf_generator:stdout" in artifact_keys
        assert "artifact:legacy_report_markdown" in artifact_keys
        assert "artifact:legacy_report_pdf" in artifact_keys
        assert "artifact:validation_report" in artifact_keys
        pdf_artifact = next(artifact for artifact in check_run.artifacts if artifact["key"] == "artifact:legacy_report_pdf")
        markdown_artifact = next(
            artifact for artifact in check_run.artifacts if artifact["key"] == "artifact:legacy_report_markdown"
        )
        assert pdf_artifact["visibility"] == "user"
        assert markdown_artifact["visibility"] == "user"
        db.refresh(records["analysis"])
        assert records["analysis"].structured_output["result"]["short_summary"] == _result_short_summary_text()
        assert records["analysis"].structured_output["result"]["short_summary_status"] == "completed"
        assert (
            records["analysis"].structured_output["result"]["short_summary_metadata"]["skill"]["name"]
            == "result_summary_synthesis"
        )
        assert records["analysis"].structured_output["result"]["short_summary_metadata"]["trace_step_id"]
        assert records["analysis"].structured_output["result"]["rationale_markdown"] == _result_rationale_markdown()
        assert records["analysis"].structured_output["result"]["rationale_items"] == _result_rationale_items()
        assert records["analysis"].structured_output["result"]["critical_risks"] == ["Hiring scale-up may precede proof."]
        assert records["analysis"].structured_output["result"]["data_gaps"] == ["No current A/B delta for uplift."]
        assert records["analysis"].structured_output["result"]["rationale_status"] == "completed"
        assert (
            records["analysis"].structured_output["result"]["rationale_metadata"]["skill"]["name"]
            == "result_rationale_synthesis"
        )
        assert records["analysis"].structured_output["result"]["rationale_metadata"]["trace_step_id"]
    finally:
        db.close()


def test_completed_run_persists_context_pack_and_avoids_full_document_repetition(tmp_path, monkeypatch):
    db = _create_session()
    calls: dict[str, object] = {}
    evidence = "Section 4: CAC payback is 19 months and gross margin is 31% in the base case."
    raw_tail = "FULL_RAW_DOCUMENT_SENTINEL " * 260
    try:
        records = _seed_run(
            db,
            tmp_path,
            monkeypatch=monkeypatch,
            workbook=False,
            parsed_document_text=f"{evidence}\n\n{raw_tail}",
        )
        _patch_script_pipeline(monkeypatch, calls, validation_text="validation ok\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        check_run = db.get(AnalysisCheckRun, records["check_run"].id)
        steps = db.execute(select(AnalysisCheckStep).order_by(AnalysisCheckStep.created_at)).scalars().all()
        context_pack_artifact = next(artifact for artifact in check_run.artifacts if artifact["key"] == "artifact:context_pack")
        context_pack = json.loads(Path(context_pack_artifact["path"]).read_text(encoding="utf-8"))
        first_role_prompt = Path(steps[0].prompt_artifact_path).read_text(encoding="utf-8")
        synthesis_prompt = Path(check_run.run_parameters["synthesis_prompt_artifact_path"]).read_text(encoding="utf-8")

        assert check_run.status == RunStatus.COMPLETED.value
        assert check_run.run_parameters["context_pack_fingerprint"]
        assert context_pack["source_stats"]["parsed_document_chars"] == len(f"{evidence}\n\n{raw_tail}")
        assert "CAC payback is 19 months" in json.dumps(context_pack, ensure_ascii=False)
        assert "FULL_RAW_DOCUMENT_SENTINEL" not in first_role_prompt
        assert "FULL_RAW_DOCUMENT_SENTINEL" not in synthesis_prompt
        assert len(first_role_prompt) < 12_000
    finally:
        db.close()


def test_completed_run_with_workbook_runs_formula_and_excel_audit(tmp_path, monkeypatch):
    db = _create_session()
    calls: dict[str, object] = {}
    try:
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=True)
        _patch_workbook_parser(monkeypatch)
        _patch_formula_auditor(monkeypatch, calls)
        _patch_script_pipeline(monkeypatch, calls, validation_text="validation ok\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        check_run = db.get(AnalysisCheckRun, records["check_run"].id)
        assert check_run.status == RunStatus.COMPLETED.value
        assert check_run.structured_output["spreadsheet_audit"]["status"] == "completed"
        assert check_run.structured_output["spreadsheet_audit"]["source_filename"] == "model.xlsx"
        assert calls["formula_workbook_path"] == records["workbook_path"]
        assert calls["workbook_path"] == records["workbook_path"]
        assert calls["formula_audit_json_path"] == records["formula_audit_path"]
        assert "formula_auditor" not in calls["pipeline_script_names"]
        artifact_keys = {artifact["key"] for artifact in check_run.artifacts}
        assert "artifact:formula_audit" in artifact_keys
        assert "script:excel_audit:stdout" in artifact_keys
    finally:
        db.close()


def test_requeued_run_reuses_completed_role_outputs_and_marks_stale_running_steps(tmp_path, monkeypatch):
    db = _create_session()
    calls: dict[str, object] = {}
    try:
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=False)
        check_run = records["check_run"]
        run_parameters = dict(check_run.run_parameters)
        role_mock_results = dict(run_parameters["role_mock_provider_results"])
        role_mock_results[ROLE_ORDER[0]] = {
            "structured_text": "first role should not be called again",
            "raw_output": "first role should not be called again",
            "latency_ms": 1,
        }
        run_parameters["role_mock_provider_results"] = role_mock_results
        check_run.run_parameters = run_parameters
        now = utc_now()
        completed_step = AnalysisCheckStep(
            check_run_id=check_run.id,
            step_type="role",
            step_name=ROLE_ORDER[0],
            status=RunStatus.COMPLETED.value,
            started_at=now,
            completed_at=now,
            raw_output="existing raw financial auditor",
            structured_output=_role_result(ROLE_ORDER[0]),
        )
        stale_step = AnalysisCheckStep(
            check_run_id=check_run.id,
            step_type="role",
            step_name=ROLE_ORDER[1],
            status=RunStatus.RUNNING.value,
            started_at=now,
        )
        db.add_all([completed_step, stale_step])
        db.commit()
        _patch_script_pipeline(monkeypatch, calls, validation_text="validation ok\n")

        run_ic_agentic_review(str(check_run.id), db=db)

        db.refresh(check_run)
        role_steps = (
            db.execute(
                select(AnalysisCheckStep)
                .where(AnalysisCheckStep.step_type == "role")
                .order_by(AnalysisCheckStep.created_at, AnalysisCheckStep.id)
            )
            .scalars()
            .all()
        )

        assert check_run.status == RunStatus.COMPLETED.value
        assert [step.step_name for step in role_steps].count(ROLE_ORDER[0]) == 1
        assert role_steps[0].raw_output == "existing raw financial auditor"
        product_steps = [step for step in role_steps if step.step_name == ROLE_ORDER[1]]
        assert [step.status for step in product_steps] == [RunStatus.FAILED.value, RunStatus.COMPLETED.value]
        assert product_steps[0].error_message == "interrupted_by_worker_restart"
        assert [step.step_name for step in role_steps if step.status == RunStatus.COMPLETED.value] == list(ROLE_ORDER)
    finally:
        db.close()


def test_synthesis_run_parameters_add_provider_timeouts_and_preserve_overrides():
    defaulted = job._synthesis_run_parameters({})
    overridden = job._synthesis_run_parameters(
        {"timeout_seconds": 240, "connect_timeout_seconds": 20, "max_retries": 1}
    )

    assert defaulted["timeout_seconds"] == 600
    assert defaulted["connect_timeout_seconds"] == 30
    assert defaulted["max_retries"] == 3
    assert defaulted["max_output_tokens"] == 12000
    assert defaulted["ic_review_step"] == "synthesis"
    assert overridden["timeout_seconds"] == 240
    assert overridden["connect_timeout_seconds"] == 20
    assert overridden["max_retries"] == 1


def test_provider_failure_after_role_three_preserves_first_three_raw_outputs_and_marks_failed(tmp_path, monkeypatch):
    db = _create_session()
    try:
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=False, failing_role=ROLE_ORDER[3])
        _patch_script_pipeline(monkeypatch, {}, validation_text="validation ok\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        check_run = db.get(AnalysisCheckRun, records["check_run"].id)
        steps = db.execute(select(AnalysisCheckStep).order_by(AnalysisCheckStep.created_at)).scalars().all()

        assert check_run.status == RunStatus.FAILED.value
        assert check_run.current_stage == f"failed:{ROLE_ORDER[3]}"
        assert "Expecting value" in check_run.error_message
        assert [step.step_name for step in steps] == list(ROLE_ORDER[:4])
        assert [step.status for step in steps[:3]] == [RunStatus.COMPLETED.value] * 3
        assert [step.raw_output for step in steps[:3]] == [f"raw {role}" for role in ROLE_ORDER[:3]]
        assert steps[3].status == RunStatus.FAILED.value
        assert steps[3].raw_output == "not json"
    finally:
        db.close()


def test_role_schema_failure_does_not_leak_provider_instance_to_run_error(tmp_path, monkeypatch):
    db = _create_session()
    secret_evidence = "SECRET_DOCUMENT_EVIDENCE_SHOULD_NOT_RENDER"
    try:
        invalid_role_payload = {
            **_role_result(ROLE_ORDER[3]),
            "role": secret_evidence,
        }
        records = _seed_run(
            db,
            tmp_path,
            monkeypatch=monkeypatch,
            workbook=False,
            invalid_role_payload=(ROLE_ORDER[3], invalid_role_payload),
        )
        _patch_script_pipeline(monkeypatch, {}, validation_text="validation ok\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        check_run = db.get(AnalysisCheckRun, records["check_run"].id)
        failed_step = db.execute(
            select(AnalysisCheckStep).where(AnalysisCheckStep.step_name == ROLE_ORDER[3]),
        ).scalar_one()

        assert check_run.status == RunStatus.FAILED.value
        assert check_run.error_message == "schema_validation_failed:enum"
        assert secret_evidence not in check_run.error_message
        assert failed_step.status == RunStatus.FAILED.value
        assert failed_step.error_message == "schema_validation_failed:enum"
        assert secret_evidence not in failed_step.error_message
        assert secret_evidence in (failed_step.raw_output or "")
    finally:
        db.close()


def test_parent_analysis_not_completed_fails_before_provider_or_scripts(tmp_path, monkeypatch):
    db = _create_session()
    calls: dict[str, object] = {}
    try:
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=False)
        records["analysis"].status = RunStatus.RUNNING.value
        db.commit()
        _patch_script_pipeline(monkeypatch, calls, validation_text="should not run\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        db.refresh(records["check_run"])
        assert records["check_run"].status == RunStatus.FAILED.value
        assert records["check_run"].error_message == "parent_analysis_not_completed"
        assert db.execute(select(AnalysisCheckStep)).scalars().all() == []
        assert "workbook_path" not in calls
    finally:
        db.close()


def test_cancelled_run_is_not_claimed_and_is_marked_cancelled(tmp_path, monkeypatch):
    db = _create_session()
    try:
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=False)
        check_run = records["check_run"]
        check_run.status = RunStatus.CANCELLED.value
        check_run.current_stage = None
        db.commit()

        run_ic_agentic_review(str(check_run.id), db=db)

        db.refresh(check_run)
        assert check_run.status == RunStatus.CANCELLED.value
        assert check_run.current_stage == "cancelled"
        assert check_run.completed_at is not None
        assert db.execute(select(AnalysisCheckStep)).scalars().all() == []
    finally:
        db.close()


def test_claim_queued_run_updates_only_queued_rows(tmp_path, monkeypatch):
    db = _create_session()
    try:
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=False)
        claimed = job._claim_queued_run(db, records["check_run"].id)

        assert claimed is not None
        assert claimed.status == RunStatus.RUNNING.value
        assert claimed.current_stage == "preparing_context"
        assert claimed.started_at is not None

        claimed.current_stage = "already-running"
        db.commit()
        duplicate = job._claim_queued_run(db, claimed.id)

        db.refresh(claimed)
        assert duplicate is None
        assert claimed.status == RunStatus.RUNNING.value
        assert claimed.current_stage == "already-running"
    finally:
        db.close()


@pytest.mark.parametrize("status", [RunStatus.RUNNING.value, RunStatus.COMPLETED.value, RunStatus.FAILED.value])
def test_duplicate_delivery_for_non_queued_run_does_not_rerun_or_mutate(tmp_path, monkeypatch, status):
    db = _create_session()
    try:
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=False)
        check_run = records["check_run"]
        check_run.status = status
        check_run.current_stage = f"existing:{status}"
        check_run.raw_output = "existing raw"
        db.commit()

        run_ic_agentic_review(str(check_run.id), db=db)

        db.refresh(check_run)
        assert check_run.status == status
        assert check_run.current_stage == f"existing:{status}"
        assert check_run.raw_output == "existing raw"
        assert db.execute(select(AnalysisCheckStep)).scalars().all() == []
    finally:
        db.close()


def test_unowned_workbook_path_is_rejected(tmp_path, monkeypatch):
    db = _create_session()
    try:
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=True)
        outside = tmp_path / "outside.xlsx"
        outside.write_bytes(b"xlsx")
        records["check_run"].uploaded_workbook_metadata = {
            **records["check_run"].uploaded_workbook_metadata,
            "storage_path": str(outside),
        }
        db.commit()

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        db.refresh(records["check_run"])
        assert records["check_run"].status == RunStatus.FAILED.value
        assert "workbook_storage_path_escapes_run_upload_dir" in records["check_run"].error_message
    finally:
        db.close()


def test_source_run_parameters_path_is_ignored_in_favor_of_snapshot_row(tmp_path, monkeypatch):
    db = _create_session()
    calls: dict[str, object] = {}
    try:
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=False)
        evil_snapshot = _write_snapshot(tmp_path, root_name="evil-storage")
        records["check_run"].run_parameters["source_snapshot_artifact_path"] = str(evil_snapshot)
        db.commit()
        from jobs import run_ic_agentic_review as job

        original_prepare = job.prepare_snapshot_workspace

        def capture_prepare_snapshot_workspace(**kwargs):
            calls["prepared_snapshot_dir"] = Path(kwargs["snapshot_dir"])
            return original_prepare(**kwargs)

        monkeypatch.setattr(job, "prepare_snapshot_workspace", capture_prepare_snapshot_workspace)
        _patch_script_pipeline(monkeypatch, calls, validation_text="validation ok\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        assert calls["prepared_snapshot_dir"] == records["snapshot_dir"]
        db.refresh(records["check_run"])
        assert records["check_run"].status == RunStatus.COMPLETED.value
    finally:
        db.close()


def test_formula_auditor_failure_marks_spreadsheet_audit_failed_and_preserves_logs(tmp_path, monkeypatch):
    db = _create_session()
    try:
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=True)
        _patch_workbook_parser(monkeypatch)
        _patch_formula_auditor(monkeypatch, {}, exit_code=2)
        _patch_script_pipeline(monkeypatch, {}, validation_text="should not run\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        db.refresh(records["check_run"])
        assert records["check_run"].status == RunStatus.FAILED.value
        assert records["check_run"].structured_output["spreadsheet_audit"]["status"] == "failed"
        artifact_keys = {artifact["key"] for artifact in records["check_run"].artifacts}
        assert "artifact:formula_audit" in artifact_keys
        assert "script:formula_auditor:stdout" in artifact_keys
        assert "script:formula_auditor:stderr" in artifact_keys
    finally:
        db.close()


def test_workbook_extraction_failure_marks_spreadsheet_audit_failed(tmp_path, monkeypatch):
    db = _create_session()
    calls: dict[str, object] = {}
    try:
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=True)

        from jobs import run_ic_agentic_review as job

        def fail_extract_workbook_snapshot(path):
            raise RuntimeError("workbook_parse_failed")

        monkeypatch.setattr(job, "extract_workbook_snapshot", fail_extract_workbook_snapshot)
        _patch_formula_auditor(monkeypatch, calls)
        _patch_script_pipeline(monkeypatch, calls, validation_text="should not run\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        db.refresh(records["check_run"])
        assert records["check_run"].status == RunStatus.FAILED.value
        assert records["check_run"].error_message == "workbook_parse_failed"
        assert records["check_run"].structured_output["spreadsheet_audit"]["status"] == "failed"
        assert "formula_workbook_path" not in calls
        assert "workbook_path" not in calls
    finally:
        db.close()


def test_excel_or_validation_failure_marks_spreadsheet_audit_failed(tmp_path, monkeypatch):
    db = _create_session()
    try:
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=True)
        _patch_workbook_parser(monkeypatch)
        _patch_formula_auditor(monkeypatch, {})
        _patch_script_pipeline(monkeypatch, {}, validation_text="[FAIL] excel issue\n", failed_script="excel_audit")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        db.refresh(records["check_run"])
        assert records["check_run"].status == RunStatus.FAILED.value
        assert records["check_run"].structured_output["spreadsheet_audit"]["status"] == "failed"
    finally:
        db.close()


def test_invalid_compact_synthesis_shape_fails_before_scripts(tmp_path, monkeypatch):
    db = _create_session()
    calls: dict[str, object] = {}
    try:
        records = _seed_run(
            db,
            tmp_path,
            monkeypatch=monkeypatch,
            workbook=False,
            synthesis_mock_provider_result={
                "structured_text": json.dumps({"compact_result": {"bad": True}, "legacy_report_json": _legacy_report()}),
                "raw_output": "invalid compact",
                "latency_ms": 1,
            },
        )
        _patch_script_pipeline(monkeypatch, calls, validation_text="should not run\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        db.refresh(records["check_run"])
        assert records["check_run"].status == RunStatus.FAILED.value
        assert "schema_validation_failed" in records["check_run"].error_message
        assert "workbook_path" not in calls
    finally:
        db.close()


def test_empty_legacy_sections_are_normalized_before_scripts(tmp_path, monkeypatch):
    db = _create_session()
    calls: dict[str, object] = {}
    try:
        legacy_report = {
            **_legacy_report(),
            "sections": {},
        }
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=False, legacy_report=legacy_report)
        _patch_script_pipeline(monkeypatch, calls, validation_text="validation ok\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        db.refresh(records["check_run"])
        assert records["check_run"].status == RunStatus.COMPLETED.value
        assert set(records["check_run"].legacy_output["sections"].keys()) == {f"section_{index}" for index in range(1, 11)}
        assert records["check_run"].legacy_output["sections"]["section_1"]["content"]
        assert "CONDITIONAL" in records["check_run"].legacy_output["sections"]["section_1"]["content"]
        assert calls["legacy_report_json_path"].is_file()
    finally:
        db.close()


def test_legacy_scenarios_list_is_normalized_for_original_scripts(tmp_path, monkeypatch):
    db = _create_session()
    calls: dict[str, object] = {}
    try:
        legacy_report = {
            **_legacy_report(),
            "scenarios": [],
        }
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=False, legacy_report=legacy_report)
        _patch_script_pipeline(monkeypatch, calls, validation_text="validation ok\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        db.refresh(records["check_run"])
        persisted_legacy = json.loads(calls["legacy_report_json_path"].read_text(encoding="utf-8"))
        assert records["check_run"].status == RunStatus.COMPLETED.value
        assert records["check_run"].legacy_output["scenarios"]
        assert persisted_legacy["scenarios"]
    finally:
        db.close()


def test_overlong_compact_strings_are_trimmed_before_validation(tmp_path, monkeypatch):
    db = _create_session()
    calls: dict[str, object] = {}
    try:
        compact_result = _compact_result(workbook=False)
        compact_result["role_summaries"][0]["summary"] = "x" * 650
        records = _seed_run(
            db,
            tmp_path,
            monkeypatch=monkeypatch,
            workbook=False,
            compact_result=compact_result,
        )
        _patch_script_pipeline(monkeypatch, calls, validation_text="validation ok\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        db.refresh(records["check_run"])
        assert records["check_run"].status == RunStatus.COMPLETED.value
        assert len(records["check_run"].structured_output["role_summaries"][0]["summary"]) == 500
        assert records["check_run"].raw_output is not None
    finally:
        db.close()


def test_synthesis_invalid_json_retries_once_without_rerunning_roles(tmp_path, monkeypatch):
    db = _create_session()
    calls: dict[str, object] = {}
    try:
        records = _seed_run(
            db,
            tmp_path,
            monkeypatch=monkeypatch,
            workbook=False,
            synthesis_mock_provider_result={
                "structured_text": '{"compact_result": {"executive_brief": "unterminated',
                "raw_output": "first invalid synthesis raw",
                "input_tokens": 101,
                "output_tokens": 202,
                "latency_ms": 303,
            },
            synthesis_json_retry_mock_provider_result={
                "structured_text": json.dumps(
                    {
                        "compact_result": _compact_result(workbook=False),
                        "legacy_report_json": _legacy_report(),
                    }
                ),
                "raw_output": "retry synthesis raw",
                "input_tokens": 111,
                "output_tokens": 222,
                "latency_ms": 333,
            },
        )
        _patch_script_pipeline(monkeypatch, calls, validation_text="validation ok\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        db.refresh(records["check_run"])
        steps = db.execute(select(AnalysisCheckStep).order_by(AnalysisCheckStep.created_at)).scalars().all()

        assert records["check_run"].status == RunStatus.COMPLETED.value
        assert records["check_run"].raw_output == "retry synthesis raw"
        assert records["check_run"].run_parameters["synthesis_json_retry"] == {
            "attempts": 2,
            "reason": "Unterminated string starting at",
            "retry_step": "synthesis:json_retry",
        }
        role_steps = [step for step in steps if step.step_type == "role"]
        assert [step.step_name for step in role_steps] == list(ROLE_ORDER)
        assert [step.status for step in role_steps] == [RunStatus.COMPLETED.value] * len(ROLE_ORDER)
    finally:
        db.close()


def test_malformed_legacy_wrapper_is_ignored_and_report_is_assembled_from_roles(tmp_path, monkeypatch):
    db = _create_session()
    calls: dict[str, object] = {}
    try:
        malformed_legacy = {
            **_legacy_report(),
            "formula_issues": {"not": "an array"},
        }
        records = _seed_run(db, tmp_path, monkeypatch=monkeypatch, workbook=False, legacy_report=malformed_legacy)
        _patch_script_pipeline(monkeypatch, calls, validation_text="should not run\n")

        run_ic_agentic_review(str(records["check_run"].id), db=db)

        db.refresh(records["check_run"])
        persisted_legacy = json.loads(calls["legacy_report_json_path"].read_text(encoding="utf-8"))
        assert records["check_run"].status == RunStatus.COMPLETED.value
        assert isinstance(persisted_legacy["formula_issues"], list)
        assert "Detailed full-report material" in persisted_legacy["sections"]["section_4"]["content"]
        assert "workbook_path" in calls
    finally:
        db.close()


def test_synthesis_wrapper_schema_hoists_compact_result_defs_for_provider_refs():
    review_schema = job._load_schema("contracts/schemas/ic-agentic-review-result.schema.json")

    wrapper_schema = job._synthesis_wrapper_schema(review_schema)

    root_defs = wrapper_schema.get("$defs") or {}
    unresolved_refs = sorted(
        ref
        for ref in _collect_schema_refs(wrapper_schema)
        if ref.startswith("#/$defs/") and ref.removeprefix("#/$defs/") not in root_defs
    )
    assert unresolved_refs == []
    assert "finding" in root_defs
    assert "finding" in review_schema["$defs"]


def test_legacy_kpis_are_pairs_for_original_excel_audit():
    compact_result = _compact_result(workbook=True)
    compact_result["key_numbers"] = [
        {"label": "NPV", "value": "12.3", "unit": "m RUB", "source": "model"},
        {"label": "IRR", "value": "24%", "unit": "", "source": ""},
    ]

    assert job._legacy_kpis_from_compact(compact_result) == [
        ["NPV", "12.3 m RUB | Source: model"],
        ["IRR", "24%"],
    ]


def _create_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _collect_schema_refs(node) -> list[str]:
    refs: list[str] = []
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            refs.append(ref)
        for value in node.values():
            refs.extend(_collect_schema_refs(value))
    elif isinstance(node, list):
        for item in node:
            refs.extend(_collect_schema_refs(item))
    return refs


def _seed_run(
    db,
    tmp_path: Path,
    *,
    monkeypatch,
    workbook: bool,
    failing_role: str | None = None,
    invalid_role_payload: tuple[str, dict] | None = None,
    legacy_report: dict | None = None,
    compact_result: dict | None = None,
    synthesis_mock_provider_result: dict | None = None,
    synthesis_json_retry_mock_provider_result: dict | None = None,
    parsed_document_text: str = "The document claims break-even by month six.",
) -> dict:
    storage_root = tmp_path / "storage"
    monkeypatch.setenv("STORAGE_ROOT", str(storage_root))
    get_settings.cache_clear()
    admin = User(
        id=uuid4(),
        login=f"admin-{uuid4()}",
        display_name="Admin",
        password_hash="hash",
        role=Role.ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    user = User(
        id=uuid4(),
        login=f"user-{uuid4()}",
        display_name="User",
        password_hash="hash",
        role=Role.USER.value,
        status=UserStatus.ACTIVE.value,
    )
    provider_key = ProviderKey(
        id=uuid4(),
        owner_id=admin.id,
        provider=Provider.OPENAI_COMPATIBLE.value,
        base_url="https://provider.invalid",
        default_model="gpt-test",
        available_models=["gpt-test"],
        encrypted_api_key=encrypt_secret("test-key"),
        api_key_fingerprint="openai_compatible:...-key",
    )
    document = Document(
        id=uuid4(),
        owner_id=user.id,
        title="Gate 3 Courier Expansion",
        original_filename="memo.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size_bytes=100,
        file_hash_sha256="0" * 64,
        storage_path=str(tmp_path / "memo.docx"),
        parse_status=DocumentParseStatus.COMPLETED.value,
        detected_document_type=DocumentType.GATE_3.value,
        document_type_confidence=None,
        parsed_text=parsed_document_text,
        status=EntityStatus.ACTIVE.value,
    )
    main_skill = Skill(
        id=uuid4(),
        name="gate2_challenger_main_analysis",
        description="Main analysis",
        version="baseline",
        skill_type=SkillType.MAIN_ANALYSIS.value,
        supported_document_types=[DocumentType.GATE_3.value],
        source_type=SkillSourceType.INLINE_PROMPT.value,
        prompt_text="prompt",
        result_schema_path="contracts/schemas/gate2-analysis-result.schema.json",
        runtime_mode="inline",
        status=EntityStatus.ACTIVE.value,
    )
    check_skill = Skill(
        id=uuid4(),
        name="ic_agentic_review",
        description="IC review",
        version="baseline",
        skill_type=SkillType.ANALYSIS_CHECK.value,
        supported_document_types=[DocumentType.GATE_3.value],
        source_type=SkillSourceType.LOCAL_SKILL_REPO.value,
        source_entrypoint=".claude/commands/invest-analysis.md",
        prompt_text="prompt",
        result_schema_path="contracts/schemas/ic-agentic-review-result.schema.json",
        runtime_mode="snapshot_required",
        status=EntityStatus.ACTIVE.value,
    )
    result_summary_skill = Skill(
        id=uuid4(),
        name="result_summary_synthesis",
        description="Result summary",
        version="baseline",
        skill_type=SkillType.RESULT_SUMMARY.value,
        supported_document_types=[DocumentType.GATE_3.value],
        source_type=SkillSourceType.INLINE_PROMPT.value,
        prompt_text="Combine Gate Challenger recommendations and IC Review executive brief.",
        result_schema_path="contracts/schemas/result-short-summary.schema.json",
        runtime_mode="inline",
        status=EntityStatus.ACTIVE.value,
    )
    result_rationale_skill = Skill(
        id=uuid4(),
        name="result_rationale_synthesis",
        description="Result rationale",
        version="baseline",
        skill_type=SkillType.RESULT_SUMMARY.value,
        supported_document_types=[DocumentType.GATE_3.value],
        source_type=SkillSourceType.INLINE_PROMPT.value,
        prompt_text="Combine Gate Challenger rationale and IC Review top findings.",
        result_schema_path="contracts/schemas/result-rationale.schema.json",
        runtime_mode="inline",
        status=EntityStatus.ACTIVE.value,
    )
    analysis = Analysis(
        id=uuid4(),
        document_id=document.id,
        user_id=user.id,
        skill_id=main_skill.id,
        skill_version=main_skill.version,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        verdict="need_evidence",
        summary="Unit economics proof is incomplete.",
        structured_output={
            "verdict": "need_evidence",
            "summary": "Needs proof.",
            "assessment_markdown": (
                "Оценка документа\n\n"
                "Почему оценка именно такая:\n"
                "- The case lacks proof for unit economics and rollout readiness.\n\n"
                "Рекомендация: request more evidence."
            ),
        },
        run_parameters={"output_language": "ru"},
    )
    detail_run = AnalysisDetailRun(
        id=uuid4(),
        analysis_id=analysis.id,
        status=RunStatus.COMPLETED.value,
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        structured_output={"layer_2": [{"id": "L2-1", "status": "fail"}]},
        raw_output="raw detail",
    )
    snapshot_dir = _write_snapshot(tmp_path)
    synthesis_result = synthesis_mock_provider_result or {
        "structured_text": json.dumps(
            {
                "compact_result": compact_result if compact_result is not None else _compact_result(workbook=workbook),
                "legacy_report_json": legacy_report if legacy_report is not None else _legacy_report(),
            }
        ),
        "raw_output": "raw synthesis output",
        "input_tokens": 101,
        "output_tokens": 202,
        "latency_ms": 303,
    }
    run_parameters = {
        "output_language": "ru",
        "source_snapshot_artifact_path": str(snapshot_dir),
        "role_mock_provider_results": _role_provider_results(
            failing_role=failing_role,
            invalid_role_payload=invalid_role_payload,
        ),
        "synthesis_mock_provider_result": synthesis_result,
        "result_summary_mock_provider_result": {
            "structured_text": json.dumps(
                {
                    "run_mode": "result_short_summary",
                    "short_summary": _result_short_summary_text(),
                }
            ),
            "raw_output": "raw result summary output",
            "input_tokens": 11,
            "output_tokens": 22,
            "latency_ms": 33,
        },
        "result_rationale_mock_provider_result": {
            "structured_text": json.dumps(
                {
                    "run_mode": "result_rationale",
                    "rationale_markdown": _result_rationale_markdown(),
                    "rationale_items": _result_rationale_items(),
                    "critical_risks": ["Hiring scale-up may precede proof."],
                    "data_gaps": ["No current A/B delta for uplift."],
                }
            ),
            "raw_output": "raw result rationale output",
            "input_tokens": 44,
            "output_tokens": 55,
            "latency_ms": 66,
        },
    }
    if synthesis_json_retry_mock_provider_result is not None:
        run_parameters["synthesis_json_retry_mock_provider_result"] = synthesis_json_retry_mock_provider_result
    check_run = AnalysisCheckRun(
        id=uuid4(),
        analysis_id=analysis.id,
        skill_id=check_skill.id,
        skill_version=check_skill.version,
        check_type="ic_agentic_review",
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.QUEUED.value,
        run_parameters=run_parameters,
        artifacts=[],
        uploaded_workbook_metadata={},
    )
    workbook_path = None
    if workbook:
        workbook_path = tmp_path / "storage" / "ic-review" / str(analysis.id) / str(check_run.id) / "uploads" / "sha-model.xlsx"
        workbook_path.parent.mkdir(parents=True)
        workbook_path.write_bytes(b"not a real workbook")
        check_run.uploaded_workbook_metadata = {
            "filename": "model.xlsx",
            "safe_original_filename": "model.xlsx",
            "storage_path": str(workbook_path),
            "size_bytes": workbook_path.stat().st_size,
            "sha256": "sha",
        }
    snapshot_row = SkillSourceSnapshot(
        id=uuid4(),
        skill_source_id=uuid4(),
        analysis_check_run_id=check_run.id,
        source_slug="ic-agentic-review",
        source_kind=SkillSourceType.LOCAL_SKILL_REPO.value,
        source_path="/source",
        requested_ref=None,
        resolved_revision="abc123",
        is_dirty=False,
        dirty_details={},
        snapshot_mode="test",
        source_fingerprint="fingerprint",
        file_manifest=[],
        artifact_path=str(snapshot_dir),
    )

    db.add_all([
        admin,
        user,
        provider_key,
        document,
        main_skill,
        check_skill,
        result_summary_skill,
        result_rationale_skill,
        analysis,
        detail_run,
        check_run,
        snapshot_row,
    ])
    db.commit()
    return {
        "analysis": analysis,
        "check_run": check_run,
        "snapshot_dir": snapshot_dir,
        "workbook_path": workbook_path,
        "formula_audit_path": tmp_path / "storage" / "ic-review" / str(analysis.id) / str(check_run.id) / "artifacts" / "formula_audit.json",
    }


def _write_snapshot(tmp_path: Path, *, root_name: str = "storage") -> Path:
    snapshot_dir = tmp_path / root_name / "skill-snapshots" / str(uuid4())
    files_dir = snapshot_dir / "files"
    manifest_files = [".claude/commands/invest-analysis.md"]
    manifest_files.extend(f".claude/agents/{role}.md" for role in ROLE_ORDER)
    manifest_files.extend(
        [
            "scripts/invest/formula_auditor.py",
            "scripts/invest/json_postprocess.py",
            "scripts/invest/pdf_generator.py",
            "scripts/invest/excel_audit.py",
            "scripts/invest/validate_report.py",
        ]
    )
    for relative_path in manifest_files:
        path = files_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"content for {relative_path}\n", encoding="utf-8")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "manifest.json").write_text(
        json.dumps({"files": [{"path": path} for path in manifest_files]}),
        encoding="utf-8",
    )
    return snapshot_dir


def _role_provider_results(
    *,
    failing_role: str | None,
    invalid_role_payload: tuple[str, dict] | None = None,
) -> dict[str, dict]:
    results = {}
    for role in ROLE_ORDER:
        if role == failing_role:
            results[role] = {
                "structured_text": "not json",
                "raw_output": "not json",
                "latency_ms": 1,
            }
            continue
        if invalid_role_payload is not None and role == invalid_role_payload[0]:
            results[role] = {
                "structured_text": json.dumps(invalid_role_payload[1]),
                "raw_output": json.dumps(invalid_role_payload[1]),
                "latency_ms": 1,
            }
            continue
        results[role] = {
            "structured_text": json.dumps(_role_result(role)),
            "raw_output": f"raw {role}",
            "input_tokens": 10,
            "output_tokens": 20,
            "latency_ms": 30,
        }
    return results


def _role_result(role: str) -> dict:
    return {
        "role": role,
        "section_keys": ["section_4"],
        "summary": f"Summary for {role}",
        "findings": [],
        "data_gaps": [],
        "numbers_used": [],
        "full_report_materials": _full_report_materials(role),
    }


def _full_report_materials(role: str) -> dict:
    return {
        "section_drafts": [
            {
                "section_key": "section_4",
                "title": "Financial model",
                "content": f"Detailed full-report material from {role}.",
                "evidence_ids": ["doc-001"],
            }
        ],
        "tables": [
            {
                "section_key": "section_4",
                "title": "P&L",
                "markdown": "| Metric | Value |\n|---|---|\n| EBITDA | unknown |",
            }
        ],
        "risks": [{"title": "Evidence gap", "detail": "Evidence remains incomplete.", "severity": "critical"}],
        "data_gaps": [{"title": "Metric proof", "detail": "Need measured metric proof."}],
        "recommendations": [{"title": "Keep gated", "detail": "Keep approval gated until evidence is provided."}],
        "scenarios": [{"title": "Base", "detail": "Base case depends on unverified assumptions."}],
        "primary_verify_notes": [f"{role} provides full-report source material."],
    }


def _compact_result(*, workbook: bool) -> dict:
    brief = (
        "IC conclusion: the investment case remains conditional because the document does not yet prove "
        "repeatable unit economics, defensible retention, or operational readiness at the claimed scale. "
        "The review finds a coherent opportunity narrative, but the decision should stay gated until the "
        "team provides cohort evidence, sensitivity ranges, owner-specific mitigations, and reconciled "
        "financial-model assumptions for the base and downside scenarios."
    )
    return {
        "run_mode": "ic_agentic_review_compact",
        "verdict": "CONDITIONAL",
        "executive_brief": brief,
        "confidence": 0.72,
        "top_findings": [
            {
                "title": "Unit economics proof gap",
                "severity": "critical",
                "summary": "The case depends on rollout economics that are not yet proven.",
                "evidence": "The IC review found missing cohort evidence and model assumptions.",
                "recommendation": "Keep the approval gated until proof and model reconciliation are complete.",
            }
        ],
        "key_numbers": [],
        "spreadsheet_audit": {
            "status": "completed" if workbook else "not_provided",
            "summary": "Workbook reviewed." if workbook else "No workbook was provided.",
            "formula_issues_count": 1 if workbook else 0,
            "critical_formula_issues_count": 0,
            "source_filename": "model.xlsx" if workbook else None,
        },
        "critical_risks": ["Hiring scale-up may precede proof."],
        "data_gaps": ["No current A/B delta for uplift."],
        "required_actions": [],
        "questions_for_team": [],
        "role_summaries": [
            {
                "role": role,
                "summary": (
                    f"{role} found that the case needs stronger evidence before approval, including "
                    "specific proof points tied to the document and the uploaded materials."
                ),
            }
            for role in ROLE_ORDER
        ],
        "validation": {
            "status": "not_run",
            "summary": "",
            "warnings_count": 0,
            "failures_count": 0,
        },
        "artifacts": [],
    }


def _result_short_summary_text() -> str:
    return (
        "Gate Challenger and IC Review converge on a conditional decision: the case has a coherent opportunity, "
        "but approval should wait until the team closes evidence gaps, validates unit economics, and documents "
        "risk mitigations needed for an IC-ready launch."
    )


def _result_rationale_markdown() -> str:
    return (
        "Оценка остается условной, потому что Gate Challenger уже фиксирует недостаточную доказанность "
        "unit economics и rollout readiness, а IC Review усиливает этот вывод: top finding показывает, что "
        "масштабирование зависит от еще не подтвержденных экономических допущений. Поэтому полный approval "
        "нельзя выдавать до закрытия cohort evidence, reconciled model assumptions и owner-specific mitigations."
    )


def _result_rationale_items() -> list[dict]:
    return [
        {
            "title": "Главный uplift не доказан текущей фактической дельтой.",
            "detail": "Gate Challenger and IC Review both point to missing uplift evidence.",
            "sources": ["gate_challenger", "ic_review"],
        }
    ]


def _legacy_report() -> dict:
    return {
        "meta": {"title": "Legacy IC report"},
        "sections": {f"section_{index}": {} for index in range(1, 11)},
        "scenarios": [],
        "formula_issues": [],
        "kpis": [],
        "risks_structured": [],
        "appendices": [],
    }


def _patch_workbook_parser(monkeypatch) -> None:
    from jobs import run_ic_agentic_review as job

    monkeypatch.setattr(
        job,
        "extract_workbook_snapshot",
        lambda path: {"format": "xlsx_bounded_snapshot_v1", "source_filename": "model.xlsx", "sheet_count": 1, "sheets": []},
    )


def _patch_formula_auditor(monkeypatch, calls: dict[str, object], *, exit_code: int = 0) -> None:
    from jobs import run_ic_agentic_review as job

    def fake_run_source_script(**kwargs):
        calls["formula_workbook_path"] = Path(kwargs["args"][2])
        output_path = Path(kwargs["artifact_paths"][0])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps({"formula_issues_count": 1, "critical_formula_issues_count": 0}), encoding="utf-8")
        log_dir = Path(kwargs["log_dir"])
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / "formula_auditor.stdout.txt"
        stderr_path = log_dir / "formula_auditor.stderr.txt"
        stdout_path.write_text("formula ok", encoding="utf-8")
        stderr_path.write_text("formula failed" if exit_code else "", encoding="utf-8")
        return ScriptResult(
            script_name="formula_auditor",
            args=[str(arg) for arg in kwargs["args"]],
            status="completed" if exit_code == 0 else "failed",
            exit_code=exit_code,
            elapsed_ms=1,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            artifact_paths=[str(output_path)],
        )

    monkeypatch.setattr(job, "run_source_script", fake_run_source_script)


def _patch_script_pipeline(monkeypatch, calls: dict[str, object], *, validation_text: str, failed_script: str | None = None) -> None:
    from jobs import run_ic_agentic_review as job

    def fake_pipeline(**kwargs):
        calls["workbook_path"] = Path(kwargs["workbook_path"]) if kwargs["workbook_path"] is not None else None
        calls["legacy_report_json_path"] = Path(kwargs["legacy_report_json_path"])
        calls["snapshot_workspace_root"] = Path(kwargs["snapshot_workspace_root"])
        calls["formula_audit_json_path"] = (
            Path(kwargs["formula_audit_json_path"]) if kwargs.get("formula_audit_json_path") is not None else None
        )
        run_dir = Path(kwargs["run_dir"])
        logs_dir = Path(kwargs["log_dir"])
        artifacts_dir = Path(kwargs["artifacts_dir"])
        logs_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        script_names = ["json_postprocess", "validate_report"]
        script_names.insert(1, "pdf_generator")
        if kwargs["workbook_path"] is not None:
            if kwargs.get("formula_audit_json_path") is None:
                script_names.insert(0, "formula_auditor")
            script_names.insert(-1, "excel_audit")
        calls["pipeline_script_names"] = script_names
        scripts = []
        for script_name in script_names:
            if "stage_callback" in kwargs and kwargs["stage_callback"] is not None:
                kwargs["stage_callback"](script_name)
            stdout_path = logs_dir / f"{script_name}.stdout.txt"
            stderr_path = logs_dir / f"{script_name}.stderr.txt"
            stdout_path.write_text(validation_text if script_name == "validate_report" else f"{script_name} stdout", encoding="utf-8")
            stderr_path.write_text("", encoding="utf-8")
            exit_code = 1 if script_name == failed_script else 0
            scripts.append(
                ScriptResult(
                    script_name=script_name,
                    args=[],
                    status="completed" if exit_code == 0 else "failed",
                    exit_code=exit_code,
                    elapsed_ms=1,
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    artifact_paths=[],
                )
            )
        validation_report = artifacts_dir / "validation_report.txt"
        validation_report.write_text(validation_text, encoding="utf-8")
        postprocessed = artifacts_dir / "postprocessed_legacy_report.json"
        postprocessed.write_text("{}", encoding="utf-8")
        legacy_markdown = artifacts_dir / "legacy_report.md"
        legacy_markdown.write_text("# legacy report", encoding="utf-8")
        legacy_pdf = artifacts_dir / "legacy_report.pdf"
        legacy_pdf.write_bytes(b"%PDF-1.4\n")
        artifacts = {
            "postprocessed_json": str(postprocessed),
            "legacy_report_markdown": str(legacy_markdown),
            "legacy_report_pdf": str(legacy_pdf),
            "validation_report": str(validation_report),
        }
        if kwargs["workbook_path"] is not None:
            formula = artifacts_dir / "formula_audit.json"
            formula.write_text("{}", encoding="utf-8")
            xlsx = artifacts_dir / "legacy_audit.xlsx"
            xlsx.write_text("xlsx", encoding="utf-8")
            artifacts.update({"formula_audit_json": str(formula), "legacy_audit_xlsx": str(xlsx)})
        assert str(run_dir) in str(validation_report)
        return ScriptPipelineResult(scripts=scripts, artifacts=artifacts)

    monkeypatch.setattr(job, "run_ic_review_script_pipeline", fake_pipeline)
