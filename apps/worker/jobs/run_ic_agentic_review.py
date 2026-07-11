from __future__ import annotations

import hashlib
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID

from jsonschema import ValidationError, validate
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.logging import worker_logger
from app.models.analysis import Analysis, AnalysisCheckRun, AnalysisDetailRun
from app.models.base import utc_now
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.models.skill import Skill
from app.models.skill_source import SkillSourceSnapshot
from app.schemas.enums import Provider, RunStatus
from app.security.secrets import decrypt_secret
from app.services.provider_keys import get_shared_provider_key
from app.storage.local import LocalDocumentStorage
from ic_review.context import build_ic_review_context
from ic_review.context_pack import build_ic_review_context_pack
from ic_review.errors import safe_ic_review_error_message
from ic_review.renderer import REVIEW_SCHEMA_PATH, ROLE_ORDER, render_synthesis_prompt
from ic_review.role_runner import apply_ic_review_provider_defaults, run_role_step, write_prompt_artifact
from ic_review.script_runner import (
    ScriptPipelineResult,
    ScriptResult,
    prepare_snapshot_workspace,
    run_ic_review_script_pipeline,
    run_source_script,
)
from ic_review.workbook_parser import extract_workbook_snapshot
from providers.base import ProviderRunRequest
from providers.registry import get_provider_adapter
from skills.snapshot_loader import load_skill_source_snapshot


SYNTHESIS_STEP_NAME = "synthesis"
LEGACY_REPORT_RELATIVE_PATH = "structured/legacy_report.json"


def run_ic_agentic_review(check_run_id: str, *, db: Session | None = None) -> None:
    owns_session = db is None
    session = db or SessionLocal()
    run_uuid = UUID(str(check_run_id))
    provider_raw_output: str | None = None
    provider_structured_text: str | None = None
    try:
        worker_logger.info(
            "worker_job_started",
            extra={"job_type": "run_ic_agentic_review", "entity_id": str(run_uuid), "status": "running"},
        )
        check_run = _claim_queued_run(session, run_uuid)
        if check_run is None:
            current_run = session.get(AnalysisCheckRun, run_uuid)
            worker_logger.info(
                "worker_job_duplicate_delivery_skipped",
                extra={
                    "job_type": "run_ic_agentic_review",
                    "entity_id": str(run_uuid),
                    "status": current_run.status if current_run is not None else "missing",
                },
            )
            return

        analysis = session.get(Analysis, check_run.analysis_id)
        if analysis is None:
            raise RuntimeError("ic_review_context_missing")
        if analysis.status != RunStatus.COMPLETED.value:
            raise RuntimeError("parent_analysis_not_completed")
        skill = session.get(Skill, check_run.skill_id)
        if skill is None:
            raise RuntimeError("ic_review_context_missing")
        document = session.get(Document, analysis.document_id)
        if document is None:
            raise RuntimeError("ic_review_document_missing")

        provider = Provider(check_run.provider)
        provider_key = _get_provider_key(session, provider)
        if provider != Provider.HERMES and provider_key is None:
            raise RuntimeError("provider_key_missing")
        api_key = decrypt_secret(provider_key.encrypted_api_key) if provider_key else None
        base_url = provider_key.base_url if provider_key else None

        source_snapshot_path = _source_snapshot_artifact_path(session=session, check_run=check_run)
        source_snapshot = load_skill_source_snapshot(str(source_snapshot_path))

        storage = LocalDocumentStorage(get_settings().storage_root)
        run_dir = storage.ic_review_run_dir(analysis_id=analysis.id, run_id=check_run.id)
        run_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir = _owned_child(run_dir, "artifacts")
        script_log_dir = _owned_child(run_dir, "scripts")
        structured_dir = _owned_child(run_dir, "structured")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        script_log_dir.mkdir(parents=True, exist_ok=True)
        structured_dir.mkdir(parents=True, exist_ok=True)

        snapshot_workspace_root = prepare_snapshot_workspace(snapshot_dir=source_snapshot_path, run_dir=run_dir)
        workbook_path = _workbook_path(check_run=check_run, run_dir=run_dir)
        workbook_snapshot: dict | None = None
        formula_audit_summary: dict | None = None
        formula_audit_json_path: Path | None = None
        if workbook_path is not None:
            try:
                workbook_snapshot = extract_workbook_snapshot(workbook_path)
                formula_audit_summary, formula_audit_json_path = _run_formula_auditor(
                    check_run=check_run,
                    run_dir=run_dir,
                    snapshot_workspace_root=snapshot_workspace_root,
                    workbook_path=workbook_path,
                    artifacts_dir=artifacts_dir,
                    script_log_dir=script_log_dir,
                )
            except Exception:
                _set_spreadsheet_audit_failed(check_run=check_run, workbook_path=workbook_path)
                flag_modified(check_run, "artifacts")
                session.commit()
                raise
            _set_spreadsheet_audit_completed(check_run=check_run, workbook_path=workbook_path, formula_audit=formula_audit_summary)
        else:
            _set_spreadsheet_audit_not_provided(check_run)
        session.commit()

        context = build_ic_review_context(
            document=document,
            analysis=analysis,
            main_analysis_detail_output=_latest_completed_detail_output(session=session, analysis_id=analysis.id),
            workbook_extraction_summary=workbook_snapshot,
            formula_auditor_summary=formula_audit_summary,
            output_language=(check_run.run_parameters or {}).get("output_language"),
        )
        context_pack = build_ic_review_context_pack(context)
        context_pack_path = _write_json_artifact(structured_dir / "context_pack.json", context_pack.to_dict())
        _add_artifact(
            check_run,
            key="artifact:context_pack",
            kind="other",
            path=context_pack_path,
            media_type="application/json",
        )
        run_parameters = dict(check_run.run_parameters or {})
        run_parameters["context_pack_artifact_path"] = str(context_pack_path)
        run_parameters["context_pack_fingerprint"] = hashlib.sha256(
            json.dumps(context_pack.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        check_run.run_parameters = run_parameters
        flag_modified(check_run, "artifacts")
        flag_modified(check_run, "run_parameters")
        session.commit()

        role_outputs: dict[str, dict] = {}
        for role in ROLE_ORDER:
            check_run.current_stage = f"role:{role}"
            session.commit()
            role_outputs[role] = run_role_step(
                session=session,
                check_run=check_run,
                analysis=analysis,
                role=role,
                context=context,
                context_pack=context_pack,
                source_snapshot=source_snapshot,
                api_key=api_key,
                base_url=base_url,
                storage=storage,
            )

        check_run = session.get(AnalysisCheckRun, run_uuid)
        if check_run is None:
            raise RuntimeError("ic_review_run_missing")
        check_run.current_stage = "synthesis"
        session.commit()

        review_schema = _load_schema(REVIEW_SCHEMA_PATH)
        synthesis_response_schema = _synthesis_wrapper_schema(review_schema)
        synthesis_prompt = render_synthesis_prompt(
            context=context,
            context_pack=context_pack,
            role_outputs=role_outputs,
            source_snapshot=source_snapshot,
            review_schema=review_schema,
        )
        synthesis_prompt_path = write_prompt_artifact(
            storage=storage,
            analysis_id=analysis.id,
            run_id=check_run.id,
            step_name=SYNTHESIS_STEP_NAME,
            prompt=synthesis_prompt,
        )
        run_parameters = dict(check_run.run_parameters or {})
        run_parameters["synthesis_prompt_artifact_path"] = str(synthesis_prompt_path)
        run_parameters["synthesis_prompt_fingerprint"] = hashlib.sha256(synthesis_prompt.encode("utf-8")).hexdigest()
        check_run.run_parameters = run_parameters
        flag_modified(check_run, "run_parameters")
        session.commit()

        synthesis_parameters = _synthesis_run_parameters(check_run.run_parameters or {})
        result = get_provider_adapter(provider, synthesis_parameters).run(
            ProviderRunRequest(
                provider=provider,
                model=check_run.model,
                api_key=api_key,
                base_url=base_url,
                prompt=synthesis_prompt,
                response_schema=synthesis_response_schema,
                run_parameters=synthesis_parameters,
            )
        )
        provider_raw_output = result.raw_output
        provider_structured_text = result.structured_text
        check_run.raw_output = result.raw_output or result.structured_text
        check_run.input_tokens = result.input_tokens
        check_run.output_tokens = result.output_tokens
        check_run.latency_ms = result.latency_ms
        check_run.estimated_cost = result.estimated_cost
        session.commit()

        compact_result, legacy_report_json = _parse_synthesis_wrapper(result.structured_text, review_schema)
        legacy_report_json = _normalize_legacy_report_json(legacy_report_json)
        _validate_legacy_report_json(legacy_report_json)
        compact_result = _with_spreadsheet_audit(
            compact_result=compact_result,
            check_run=check_run,
            workbook_path=workbook_path,
            formula_audit=formula_audit_summary,
        )
        validate(instance=compact_result, schema=review_schema)
        check_run.structured_output = compact_result
        check_run.legacy_output = legacy_report_json
        flag_modified(check_run, "structured_output")
        flag_modified(check_run, "legacy_output")
        legacy_report_json_path = _write_json_artifact(structured_dir / "legacy_report.json", legacy_report_json)
        _add_artifact(
            check_run,
            key="artifact:legacy_report_json",
            kind="legacy_report_json",
            path=legacy_report_json_path,
            media_type="application/json",
        )
        session.commit()

        check_run.current_stage = "postprocess"
        session.commit()
        pipeline_result = run_ic_review_script_pipeline(
            run_dir=run_dir,
            snapshot_workspace_root=snapshot_workspace_root,
            legacy_report_json_path=legacy_report_json_path,
            artifacts_dir=artifacts_dir,
            log_dir=script_log_dir,
            workbook_path=workbook_path,
            formula_audit_json_path=formula_audit_json_path,
            stage_callback=_script_stage_callback(session=session, check_run=check_run),
        )
        _persist_pipeline_artifacts(check_run=check_run, pipeline_result=pipeline_result)
        validation_summary = _validation_summary(pipeline_result)
        compact_with_validation = dict(check_run.structured_output or {})
        if workbook_path is not None and (not pipeline_result.succeeded or validation_summary["failures_count"] > 0):
            compact_with_validation["spreadsheet_audit"] = _spreadsheet_audit_failed_payload(
                check_run=check_run,
                workbook_path=workbook_path,
            )
        compact_with_validation["validation"] = validation_summary
        validate(instance=compact_with_validation, schema=review_schema)
        check_run.structured_output = compact_with_validation
        flag_modified(check_run, "structured_output")
        flag_modified(check_run, "artifacts")

        if not pipeline_result.succeeded or validation_summary["failures_count"] > 0:
            check_run.status = RunStatus.FAILED.value
            check_run.current_stage = "failed:validation"
            check_run.error_message = "ic_review_validation_failed"
        else:
            check_run.status = RunStatus.COMPLETED.value
            check_run.current_stage = "completed"
            check_run.error_message = None
        check_run.completed_at = utc_now()
        session.commit()

        worker_logger.info(
            "worker_job_completed",
            extra={"job_type": "run_ic_agentic_review", "entity_id": str(run_uuid), "status": check_run.status},
        )
    except Exception as exc:
        session.rollback()
        failed = session.get(AnalysisCheckRun, run_uuid)
        if failed is None:
            raise
        failed.status = RunStatus.FAILED.value
        if not failed.current_stage or not failed.current_stage.startswith("failed:"):
            failed.current_stage = _failed_stage(failed.current_stage)
        failed.error_message = safe_ic_review_error_message(exc)
        if provider_raw_output is not None and failed.raw_output is None:
            failed.raw_output = provider_raw_output or provider_structured_text
        failed.completed_at = utc_now()
        session.commit()
        worker_logger.info(
            "worker_job_failed",
            extra={
                "job_type": "run_ic_agentic_review",
                "entity_id": str(run_uuid),
                "status": "failed",
                "error_class": exc.__class__.__name__,
            },
        )
    finally:
        if owns_session:
            session.close()


def _get_provider_key(session: Session, provider: Provider) -> ProviderKey | None:
    return get_shared_provider_key(db=session, provider=provider)


def _claim_queued_run(session: Session, run_uuid: UUID) -> AnalysisCheckRun | None:
    started_at = utc_now()
    result = session.execute(
        update(AnalysisCheckRun)
        .where(
            AnalysisCheckRun.id == run_uuid,
            AnalysisCheckRun.status == RunStatus.QUEUED.value,
        )
        .values(
            status=RunStatus.RUNNING.value,
            current_stage="preparing_context",
            started_at=started_at,
            error_message=None,
        )
    )
    if result.rowcount == 1:
        session.commit()
        return session.get(AnalysisCheckRun, run_uuid)

    session.expire_all()
    current_run = session.get(AnalysisCheckRun, run_uuid)
    if current_run is None:
        raise ValueError(f"IC review run {run_uuid} not found")
    if current_run.status == RunStatus.CANCELLED.value:
        current_run.current_stage = "cancelled"
        if current_run.completed_at is None:
            current_run.completed_at = utc_now()
        session.commit()
    return None


def _source_snapshot_artifact_path(*, session: Session, check_run: AnalysisCheckRun) -> Path:
    run_parameters = check_run.run_parameters or {}
    statement = (
        select(SkillSourceSnapshot)
        .where(SkillSourceSnapshot.analysis_check_run_id == check_run.id)
        .order_by(SkillSourceSnapshot.created_at.desc())
    )
    snapshot_row = session.execute(statement).scalars().first()
    if snapshot_row is None or not snapshot_row.artifact_path:
        raise RuntimeError("source_snapshot_required")

    requested_snapshot_id = run_parameters.get("source_snapshot_id")
    if requested_snapshot_id is not None and str(requested_snapshot_id) != str(snapshot_row.id):
        raise RuntimeError("source_snapshot_id_mismatch")
    requested_fingerprint = run_parameters.get("source_fingerprint")
    if requested_fingerprint is not None and requested_fingerprint != snapshot_row.source_fingerprint:
        raise RuntimeError("source_snapshot_fingerprint_mismatch")

    storage_root = Path(get_settings().storage_root).expanduser().resolve()
    artifact_path = Path(str(snapshot_row.artifact_path)).expanduser().resolve()
    if not artifact_path.is_relative_to(storage_root):
        raise RuntimeError("source_snapshot_artifact_path_escapes_storage_root")
    if not artifact_path.is_dir():
        raise RuntimeError("source_snapshot_required")
    return artifact_path


def _workbook_path(*, check_run: AnalysisCheckRun, run_dir: Path) -> Path | None:
    metadata = check_run.uploaded_workbook_metadata or {}
    storage_path = metadata.get("storage_path")
    if not storage_path:
        return None
    workbook_path = Path(str(storage_path)).expanduser().resolve()
    upload_dir = (run_dir.expanduser().resolve() / "uploads").resolve()
    if not workbook_path.is_relative_to(upload_dir):
        raise RuntimeError("workbook_storage_path_escapes_run_upload_dir")
    if not workbook_path.is_file():
        raise RuntimeError("workbook_storage_path_missing")
    if workbook_path.suffix.lower() != ".xlsx":
        raise RuntimeError("workbook_storage_path_not_xlsx")
    return workbook_path


def _run_formula_auditor(
    *,
    check_run: AnalysisCheckRun,
    run_dir: Path,
    snapshot_workspace_root: Path,
    workbook_path: Path,
    artifacts_dir: Path,
    script_log_dir: Path,
) -> tuple[dict, Path]:
    formula_audit_path = artifacts_dir / "formula_audit.json"
    result = run_source_script(
        snapshot_workspace_root=snapshot_workspace_root,
        args=[
            sys.executable,
            "scripts/invest/formula_auditor.py",
            workbook_path,
            "--json",
            "--output",
            formula_audit_path,
        ],
        log_dir=script_log_dir,
        owner_root=run_dir,
        script_name="formula_auditor",
        artifact_paths=[formula_audit_path],
    )
    _persist_script_result(check_run=check_run, result=result)
    _add_artifact(
        check_run,
        key="artifact:formula_audit",
        kind="formula_audit",
        path=formula_audit_path,
        media_type="application/json",
    )
    if not result.succeeded:
        raise RuntimeError("formula_auditor_failed")
    if formula_audit_path.is_file():
        try:
            return json.loads(formula_audit_path.read_text(encoding="utf-8")), formula_audit_path
        except json.JSONDecodeError:
            return {"raw_formula_audit_path": str(formula_audit_path)}, formula_audit_path
    return {}, formula_audit_path


def _set_spreadsheet_audit_not_provided(check_run: AnalysisCheckRun) -> None:
    output = dict(check_run.structured_output or {})
    output["spreadsheet_audit"] = {
        "status": "not_provided",
        "summary": "No workbook was provided; spreadsheet audit scripts were skipped.",
        "formula_issues_count": 0,
        "critical_formula_issues_count": 0,
        "source_filename": None,
    }
    check_run.structured_output = output
    flag_modified(check_run, "structured_output")


def _set_spreadsheet_audit_completed(*, check_run: AnalysisCheckRun, workbook_path: Path, formula_audit: dict) -> None:
    output = dict(check_run.structured_output or {})
    output["spreadsheet_audit"] = {
        "status": "completed",
        "summary": "Workbook snapshot and formula audit completed.",
        "formula_issues_count": _int_value(formula_audit, "formula_issues_count", "issues_count"),
        "critical_formula_issues_count": _int_value(
            formula_audit,
            "critical_formula_issues_count",
            "critical_issues_count",
        ),
        "source_filename": _workbook_filename(check_run=check_run, fallback=workbook_path.name),
    }
    check_run.structured_output = output
    flag_modified(check_run, "structured_output")


def _set_spreadsheet_audit_failed(*, check_run: AnalysisCheckRun, workbook_path: Path) -> None:
    output = dict(check_run.structured_output or {})
    output["spreadsheet_audit"] = _spreadsheet_audit_failed_payload(check_run=check_run, workbook_path=workbook_path)
    check_run.structured_output = output
    flag_modified(check_run, "structured_output")


def _spreadsheet_audit_failed_payload(*, check_run: AnalysisCheckRun, workbook_path: Path) -> dict:
    return {
        "status": "failed",
        "summary": "Workbook audit failed; see script logs and validation artifacts.",
        "formula_issues_count": 0,
        "critical_formula_issues_count": 0,
        "source_filename": _workbook_filename(check_run=check_run, fallback=workbook_path.name),
    }


def _with_spreadsheet_audit(
    *,
    compact_result: dict,
    check_run: AnalysisCheckRun,
    workbook_path: Path | None,
    formula_audit: dict | None,
) -> dict:
    normalized = dict(compact_result)
    if workbook_path is None:
        normalized["spreadsheet_audit"] = {
            "status": "not_provided",
            "summary": "No workbook was provided; spreadsheet audit scripts were skipped.",
            "formula_issues_count": 0,
            "critical_formula_issues_count": 0,
            "source_filename": None,
        }
        return normalized

    formula_audit = formula_audit or {}
    existing = dict(normalized.get("spreadsheet_audit") or {})
    normalized["spreadsheet_audit"] = {
        "status": "completed",
        "summary": str(existing.get("summary") or "Workbook snapshot and formula audit completed.")[:700],
        "formula_issues_count": _int_value(formula_audit, "formula_issues_count", "issues_count"),
        "critical_formula_issues_count": _int_value(
            formula_audit,
            "critical_formula_issues_count",
            "critical_issues_count",
        ),
        "source_filename": _workbook_filename(check_run=check_run, fallback=workbook_path.name),
    }
    return normalized


def _synthesis_run_parameters(run_parameters: dict) -> dict:
    parameters = dict(run_parameters)
    if "synthesis_mock_provider_result" in parameters:
        parameters["mock_provider_result"] = parameters["synthesis_mock_provider_result"]
    apply_ic_review_provider_defaults(parameters)
    parameters["ic_review_step"] = SYNTHESIS_STEP_NAME
    return parameters


def _synthesis_wrapper_schema(review_schema: dict) -> dict:
    return {
        "title": "ICAgenticReviewSynthesisWrapper",
        "type": "object",
        "additionalProperties": False,
        "required": ["compact_result", "legacy_report_json"],
        "$defs": deepcopy(review_schema.get("$defs", {})),
        "properties": {
            "compact_result": deepcopy(review_schema),
            "legacy_report_json": {
                "type": "object",
                "additionalProperties": True,
                "required": [
                    "meta",
                    "sections",
                    "scenarios",
                    "formula_issues",
                    "kpis",
                    "risks_structured",
                    "appendices",
                ],
                "properties": {
                    "meta": {"type": "object"},
                    "sections": {
                        "type": "object",
                    },
                    "scenarios": {"type": "object"},
                    "formula_issues": {"type": "array"},
                    "kpis": {"type": "array"},
                    "risks_structured": {"type": "array"},
                    "appendices": {"type": "array"},
                },
            },
        },
    }


def _parse_synthesis_wrapper(structured_text: str, review_schema: dict) -> tuple[dict, dict]:
    payload = json.loads(_extract_json_text(structured_text))
    if not isinstance(payload, dict) or set(payload.keys()) != {"compact_result", "legacy_report_json"}:
        raise RuntimeError("invalid_synthesis_wrapper")
    compact_result = payload["compact_result"]
    legacy_report_json = payload["legacy_report_json"]
    if not isinstance(compact_result, dict) or not isinstance(legacy_report_json, dict):
        raise RuntimeError("invalid_synthesis_wrapper")
    compact_result = _normalize_schema_bounded_strings(compact_result, review_schema, review_schema)
    legacy_report_json = _normalize_legacy_report_json(legacy_report_json, compact_result=compact_result)
    normalized_payload = {
        "compact_result": compact_result,
        "legacy_report_json": legacy_report_json,
    }
    try:
        validate(instance=normalized_payload, schema=_synthesis_wrapper_schema(review_schema))
    except ValidationError as exc:
        raise RuntimeError(f"invalid_synthesis_wrapper:{safe_ic_review_error_message(exc)}") from exc
    return compact_result, legacy_report_json


def _normalize_schema_bounded_strings(value: Any, schema: dict, root_schema: dict) -> Any:
    resolved_schema = schema
    if "$ref" in resolved_schema:
        resolved = _resolve_local_schema_ref(str(resolved_schema["$ref"]), root_schema)
        if resolved is not None:
            resolved_schema = resolved

    for combinator in ("anyOf", "oneOf"):
        options = resolved_schema.get(combinator)
        if isinstance(options, list):
            for option in options:
                if isinstance(option, dict) and _schema_option_matches_value(option, value, root_schema):
                    return _normalize_schema_bounded_strings(value, option, root_schema)
            return value

    all_of = resolved_schema.get("allOf")
    if isinstance(all_of, list):
        normalized = value
        for option in all_of:
            if isinstance(option, dict):
                normalized = _normalize_schema_bounded_strings(normalized, option, root_schema)
        return normalized

    expected_type = resolved_schema.get("type")
    if expected_type == "string" and isinstance(value, str):
        max_length = resolved_schema.get("maxLength")
        if isinstance(max_length, int) and len(value) > max_length:
            return value[:max_length]
        return value

    if expected_type == "object" and isinstance(value, dict):
        properties = resolved_schema.get("properties")
        if not isinstance(properties, dict):
            return value
        normalized = dict(value)
        for key, child_schema in properties.items():
            if key in normalized and isinstance(child_schema, dict):
                normalized[key] = _normalize_schema_bounded_strings(normalized[key], child_schema, root_schema)
        return normalized

    if expected_type == "array" and isinstance(value, list):
        item_schema = resolved_schema.get("items")
        if isinstance(item_schema, dict):
            return [_normalize_schema_bounded_strings(item, item_schema, root_schema) for item in value]
        return value

    return value


def _schema_option_matches_value(schema: dict, value: Any, root_schema: dict) -> bool:
    if "$ref" in schema:
        resolved = _resolve_local_schema_ref(str(schema["$ref"]), root_schema)
        if resolved is not None:
            return _schema_option_matches_value(resolved, value, root_schema)

    expected_type = schema.get("type")
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "null":
        return value is None
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return True


def _resolve_local_schema_ref(ref: str, root_schema: dict) -> dict | None:
    if not ref.startswith("#/"):
        return None
    current: Any = root_schema
    for raw_part in ref.removeprefix("#/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current if isinstance(current, dict) else None


def _normalize_legacy_report_json(legacy_report_json: dict, *, compact_result: dict | None = None) -> dict:
    normalized = deepcopy(legacy_report_json)
    sections = normalized.get("sections")
    if isinstance(sections, dict):
        for index in range(1, 11):
            section_key = f"section_{index}"
            section = sections.setdefault(section_key, {})
            if compact_result is not None:
                sections[section_key] = _normalize_legacy_section(section, index=index, compact_result=compact_result)
    scenarios = normalized.get("scenarios")
    if isinstance(scenarios, list):
        normalized["scenarios"] = _normalize_legacy_scenarios(scenarios)
    elif not isinstance(scenarios, dict):
        normalized["scenarios"] = {}

    meta = normalized.get("meta")
    if isinstance(meta, dict) and compact_result is not None:
        meta.setdefault("verdict", compact_result.get("verdict") or "—")
    return normalized


def _normalize_legacy_section(section: object, *, index: int, compact_result: dict) -> dict:
    normalized = dict(section) if isinstance(section, dict) else {}
    normalized.setdefault("tables", [])
    normalized.setdefault("subsections", [])
    normalized.setdefault("callouts", [])
    content = normalized.get("content")
    if not isinstance(content, str) or not content.strip():
        normalized["content"] = _legacy_section_fallback_content(index=index, compact_result=compact_result)
    return normalized


def _legacy_section_fallback_content(*, index: int, compact_result: dict) -> str:
    title = _legacy_section_title(index)
    verdict = str(compact_result.get("verdict") or "UNKNOWN")
    confidence = compact_result.get("confidence")
    executive_brief = str(compact_result.get("executive_brief") or "No executive brief was provided.")
    role_summaries = _legacy_role_summary_lines(compact_result)
    selected_roles = role_summaries[max(0, index - 2) : max(0, index - 2) + 2] or role_summaries[:2]
    findings = _legacy_finding_lines(compact_result)
    numbers = _legacy_key_number_lines(compact_result)
    risks = _legacy_text_list_lines(compact_result, "critical_risks")
    gaps = _legacy_text_list_lines(compact_result, "data_gaps")
    actions = _legacy_text_list_lines(compact_result, "required_actions")
    questions = _legacy_text_list_lines(compact_result, "questions_for_team")
    spreadsheet = compact_result.get("spreadsheet_audit") if isinstance(compact_result.get("spreadsheet_audit"), dict) else {}

    section_focus = {
        1: ["Executive brief", executive_brief, "Top findings", *findings],
        2: ["Product and investment context", executive_brief, *selected_roles],
        3: ["Market and benchmark signals", *findings, *numbers],
        4: ["Financial model and spreadsheet audit", str(spreadsheet.get("summary") or "No workbook audit summary."), *numbers],
        5: ["Team, legal, and operating readiness", *selected_roles],
        6: ["Scenario and sensitivity notes", *numbers, *risks],
        7: ["Critical risks", *risks, *selected_roles],
        8: ["Data gaps", *gaps, *questions],
        9: ["Required actions", *actions, *questions],
        10: ["IC recommendation", executive_brief, *actions, *risks],
    }.get(index, [executive_brief])

    lines = [
        f"{title}.",
        f"Verdict: {verdict}. Confidence: {confidence}.",
        *[line for line in section_focus if line],
        "Selected role evidence",
        *selected_roles,
    ]
    content = "\n".join(str(line) for line in lines if str(line).strip())
    while len(content) < 900:
        content = f"{content}\n\nSupporting compact evidence:\n{executive_brief}"
    return content[:1800]


def _legacy_section_title(index: int) -> str:
    titles = {
        1: "Section 1: Executive Summary",
        2: "Section 2: Project And Product Context",
        3: "Section 3: Market And Benchmark Review",
        4: "Section 4: Financial Model Review",
        5: "Section 5: Team, Legal, And Operations",
        6: "Section 6: Scenarios And Sensitivities",
        7: "Section 7: Risk Map",
        8: "Section 8: Data Gaps",
        9: "Section 9: Required Actions",
        10: "Section 10: IC Recommendation",
    }
    return titles.get(index, f"Section {index}")


def _legacy_role_summary_lines(compact_result: dict) -> list[str]:
    role_summaries = compact_result.get("role_summaries")
    if not isinstance(role_summaries, list):
        return []
    lines = []
    for item in role_summaries:
        if isinstance(item, dict):
            role = item.get("role") or "role"
            summary = item.get("summary") or ""
            if summary:
                lines.append(f"- {role}: {summary}")
    return lines


def _legacy_finding_lines(compact_result: dict) -> list[str]:
    findings = compact_result.get("top_findings")
    if not isinstance(findings, list):
        return []
    lines = []
    for item in findings:
        if isinstance(item, dict):
            title = item.get("title") or "Finding"
            summary = item.get("summary") or item.get("evidence") or ""
            recommendation = item.get("recommendation") or ""
            lines.append(f"- {title}: {summary} {recommendation}".strip())
    return lines


def _legacy_key_number_lines(compact_result: dict) -> list[str]:
    key_numbers = compact_result.get("key_numbers")
    if not isinstance(key_numbers, list):
        return []
    lines = []
    for item in key_numbers:
        if isinstance(item, dict):
            label = item.get("label") or "Metric"
            value = item.get("value") or "—"
            unit = item.get("unit") or ""
            source = item.get("source") or ""
            lines.append(f"- {label}: {value} {unit}. Source: {source}".strip())
    return lines


def _legacy_text_list_lines(compact_result: dict, key: str) -> list[str]:
    values = compact_result.get(key)
    if not isinstance(values, list):
        return []
    return [f"- {value}" for value in values if isinstance(value, str) and value.strip()]


def _normalize_legacy_scenarios(scenarios: list) -> dict:
    normalized: dict[str, dict] = {}
    for index, item in enumerate(scenarios, start=1):
        if not isinstance(item, dict):
            continue
        scenario_key = _legacy_scenario_key(item, fallback=f"scenario_{index}")
        normalized[scenario_key] = dict(item)
    return normalized


def _legacy_scenario_key(item: dict, *, fallback: str) -> str:
    for key in ("key", "id", "scenario", "name", "title"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            slug = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower()).strip("_")
            if slug:
                return slug
    return fallback


def _validate_legacy_report_json(legacy_report_json: dict) -> None:
    required_root_keys = {
        "meta",
        "sections",
        "scenarios",
        "formula_issues",
        "kpis",
        "risks_structured",
        "appendices",
    }
    errors: list[str] = []
    if not isinstance(legacy_report_json, dict):
        raise RuntimeError("invalid_legacy_report_json:root")

    missing = sorted(required_root_keys.difference(legacy_report_json))
    errors.extend(missing)
    if not isinstance(legacy_report_json.get("meta"), dict):
        errors.append("meta:type")
    sections = legacy_report_json.get("sections")
    if not isinstance(sections, dict):
        errors.append("sections:type")
        missing_sections = [f"section_{index}" for index in range(1, 11)]
    else:
        missing_sections = [f"section_{index}" for index in range(1, 11) if f"section_{index}" not in sections]
    errors.extend(missing_sections)
    if not isinstance(legacy_report_json.get("scenarios"), dict):
        errors.append("scenarios:type")
    for key in ("formula_issues", "kpis", "risks_structured", "appendices"):
        if not isinstance(legacy_report_json.get(key), list):
            errors.append(f"{key}:type")
    if errors:
        detail = ",".join(errors)
        raise RuntimeError(f"invalid_legacy_report_json:{detail}")


def _extract_json_text(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else value


def _load_schema(schema_path: str) -> dict:
    return json.loads((Path(__file__).resolve().parents[3] / schema_path).read_text(encoding="utf-8"))


def _latest_completed_detail_output(*, session: Session, analysis_id: UUID) -> dict | None:
    statement = (
        select(AnalysisDetailRun)
        .where(
            AnalysisDetailRun.analysis_id == analysis_id,
            AnalysisDetailRun.status == RunStatus.COMPLETED.value,
        )
        .order_by(AnalysisDetailRun.created_at.desc())
    )
    detail_run = session.execute(statement).scalars().first()
    if detail_run is None:
        return None
    return detail_run.structured_output


def _script_stage_callback(*, session: Session, check_run: AnalysisCheckRun):
    def callback(script_name: str) -> None:
        if script_name == "json_postprocess":
            check_run.current_stage = "postprocess"
        elif script_name == "excel_audit":
            check_run.current_stage = "legacy_artifacts"
        elif script_name == "validate_report":
            check_run.current_stage = "validation"
        else:
            return
        session.commit()

    return callback


def _write_json_artifact(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _persist_pipeline_artifacts(*, check_run: AnalysisCheckRun, pipeline_result: ScriptPipelineResult) -> None:
    for script_result in pipeline_result.scripts:
        _persist_script_result(check_run=check_run, result=script_result)
    for name, artifact_path in pipeline_result.artifacts.items():
        path = Path(artifact_path)
        _add_artifact(
            check_run,
            key=f"artifact:{name}",
            kind=_artifact_kind(name),
            path=path,
            media_type=_media_type(path),
        )


def _persist_script_result(*, check_run: AnalysisCheckRun, result: ScriptResult) -> None:
    stdout_path = Path(result.stdout_path)
    stderr_path = Path(result.stderr_path)
    _add_artifact(
        check_run,
        key=f"script:{result.script_name}:stdout",
        kind="script_log",
        path=stdout_path,
        media_type="text/plain",
    )
    _add_artifact(
        check_run,
        key=f"script:{result.script_name}:stderr",
        kind="script_log",
        path=stderr_path,
        media_type="text/plain",
    )


def _validation_summary(pipeline_result: ScriptPipelineResult) -> dict:
    validation_path = pipeline_result.artifacts.get("validation_report")
    text = Path(validation_path).read_text(encoding="utf-8") if validation_path and Path(validation_path).is_file() else ""
    failures_count = len(re.findall(r"^\s*\[FAIL\]", text, flags=re.MULTILINE))
    warnings_count = len(re.findall(r"^\s*\[!\]", text, flags=re.MULTILINE))
    if failures_count > 0 or not pipeline_result.succeeded:
        status = "fail"
    elif warnings_count > 0:
        status = "warn"
    else:
        status = "pass"
    summary_status = {"pass": "passed", "warn": "warned", "fail": "failed"}[status]
    return {
        "status": status,
        "summary": f"Validation {summary_status} with {failures_count} failure(s) and {warnings_count} warning(s).",
        "warnings_count": warnings_count,
        "failures_count": failures_count,
    }


def _add_artifact(
    check_run: AnalysisCheckRun,
    *,
    key: str,
    kind: str,
    path: Path,
    media_type: str | None,
) -> None:
    artifacts = list(check_run.artifacts or [])
    artifacts = [artifact for artifact in artifacts if artifact.get("key") != key]
    record = {
        "key": key,
        "kind": kind,
        "filename": path.name,
        "path": str(path),
    }
    if media_type:
        record["media_type"] = media_type
    artifacts.append(record)
    check_run.artifacts = artifacts
    flag_modified(check_run, "artifacts")


def _artifact_kind(name: str) -> str:
    if name == "formula_audit_json":
        return "formula_audit"
    if name == "postprocessed_json":
        return "legacy_report_json"
    if name == "legacy_report_text":
        return "legacy_report_text"
    if name == "legacy_audit_xlsx":
        return "legacy_audit_xlsx"
    if name == "validation_report":
        return "validation_report"
    return "other"


def _media_type(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix == ".txt":
        return "text/plain"
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return None


def _owned_child(parent: Path, child: str) -> Path:
    root = parent.expanduser().resolve()
    path = (root / child).resolve()
    if not path.is_relative_to(root):
        raise RuntimeError("ic_review_artifact_path_escapes_run_dir")
    return path


def _int_value(payload: dict, *keys: str) -> int:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int):
            return max(0, value)
        if isinstance(value, float):
            return max(0, int(value))
    issues = payload.get("issues")
    if isinstance(issues, list):
        return len(issues)
    return 0


def _workbook_filename(*, check_run: AnalysisCheckRun, fallback: str) -> str:
    metadata = check_run.uploaded_workbook_metadata or {}
    return str(metadata.get("safe_original_filename") or metadata.get("filename") or fallback)


def _failed_stage(current_stage: str | None) -> str:
    if current_stage and current_stage.startswith("role:"):
        return "failed:" + current_stage.removeprefix("role:")
    if current_stage:
        return f"failed:{current_stage}"
    return "failed"
