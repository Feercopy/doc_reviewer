"""Revocable, read-only capability links for a single analysis."""

from base64 import urlsafe_b64encode
from hashlib import sha256
from hmac import compare_digest, new as new_hmac
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.analysis import Analysis, AnalysisCheckRun
from app.models.document import Document
from app.models.user import User
from app.schemas.enums import EntityStatus
from app.services.analyses import AnalysisNotFoundError, get_manageable_analysis_for_actor
from app.services.audit import record_audit
from app.services.ic_review import IC_REVIEW_CHECK_TYPE
from app.services.new_summaries import read_new_summary, with_display_stage, with_verified_source_totals


def _share_token(analysis: Analysis) -> str:
    material = f"analysis-share-v1:{analysis.id}:{analysis.public_share_nonce}".encode("utf-8")
    digest = new_hmac(get_settings().app_secret_key.encode("utf-8"), material, sha256).digest()
    return urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def create_analysis_share(*, db: Session, actor: User, analysis_id: UUID) -> str:
    analysis = get_manageable_analysis_for_actor(db=db, actor=actor, analysis_id=analysis_id)
    db.refresh(analysis, with_for_update=True)
    if not analysis.public_share_nonce:
        analysis.public_share_nonce = token_urlsafe(32)
        record_audit(db=db, actor_id=actor.id, action="analysis.share_created", entity_type="analysis", entity_id=analysis.id)
        db.commit()
    return _share_token(analysis)


def analysis_share_is_active(*, db: Session, actor: User, analysis_id: UUID) -> bool:
    analysis = get_manageable_analysis_for_actor(db=db, actor=actor, analysis_id=analysis_id)
    return bool(analysis.public_share_nonce)


def revoke_analysis_share(*, db: Session, actor: User, analysis_id: UUID) -> None:
    analysis = get_manageable_analysis_for_actor(db=db, actor=actor, analysis_id=analysis_id)
    db.refresh(analysis, with_for_update=True)
    if analysis.public_share_nonce is not None:
        analysis.public_share_nonce = None
        record_audit(db=db, actor_id=actor.id, action="analysis.share_revoked", entity_type="analysis", entity_id=analysis.id)
        db.commit()


def get_shared_analysis(*, db: Session, analysis_id: UUID, token: str | None) -> tuple[Analysis, Document]:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or analysis.deleted_at is not None or not analysis.public_share_nonce or not token or len(token) != 43:
        raise AnalysisNotFoundError("Analysis not found")
    if not compare_digest(token, _share_token(analysis)):
        raise AnalysisNotFoundError("Analysis not found")
    document = db.get(Document, analysis.document_id)
    if document is None or document.status != EntityStatus.ACTIVE.value:
        raise AnalysisNotFoundError("Analysis not found")
    return analysis, document


def read_shared_analysis(*, db: Session, analysis: Analysis, document: Document) -> dict:
    output = analysis.structured_output if isinstance(analysis.structured_output, dict) else {}
    product_markdown = next((output[key] for key in (
        "assessment_markdown", "native_markdown", "markdown", "output_markdown", "summary_markdown"
    ) if isinstance(output.get(key), str) and output[key].strip()), None)
    summary = with_display_stage(
        with_verified_source_totals(read_new_summary(analysis), document), document.display_stage
    )
    statement = (
        select(AnalysisCheckRun)
        .where(AnalysisCheckRun.analysis_id == analysis.id, AnalysisCheckRun.check_type == IC_REVIEW_CHECK_TYPE)
        .order_by(AnalysisCheckRun.created_at.desc(), AnalysisCheckRun.id.desc())
    )
    financial_run = db.execute(statement).scalars().first()
    financial_output = financial_run.structured_output if financial_run and financial_run.status == "completed" else None
    return {
        "id": analysis.id,
        "title": document.title,
        "status": analysis.status,
        "created_at": analysis.created_at,
        "product_markdown": product_markdown,
        "summary_ru": _public_summary(summary.ru.payload) if summary.ru.status == "completed" else None,
        "summary_en": _public_summary(summary.en.payload) if summary.en.status == "completed" else None,
        "financial": _public_financial(financial_output),
    }


def _public_summary(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    display_fields = (
        "schema_version", "language", "title", "stage", "context", "document_quality_percent",
        "required_elements", "required_details", "confirmed",
        "insufficiently_confirmed", "critical_problems", "other",
    )
    result = {key: value[key] for key in display_fields if key in value}
    traction = value.get("traction_summary")
    if isinstance(traction, dict):
        if isinstance(traction.get("tables"), list):
            result["traction_summary"] = {"tables": [
                _public_traction_table(table) for table in traction["tables"] if isinstance(table, dict)
            ]}
        else:
            result["traction_summary"] = _public_traction_table(traction)
    return result


def _public_traction_table(value: dict) -> dict:
    visible = {key: value[key] for key in ("metric", "cumulative", "metric_label", "periods") if key in value}
    rows = value.get("rows")
    if isinstance(rows, list):
        visible["rows"] = [
            {key: row[key] for key in ("label", "values", "mismatch_periods") if key in row}
            for row in rows if isinstance(row, dict)
        ]
    return visible


def _public_financial(value: object) -> dict | None:
    if not isinstance(value, dict) or value.get("run_mode") != "ic_agentic_review_compact":
        return None

    def strings(items: object) -> list[str]:
        return [item for item in items if isinstance(item, str)] if isinstance(items, list) else []

    findings = value.get("top_findings")
    numbers = value.get("key_numbers")
    audit = value.get("spreadsheet_audit")
    validation = value.get("validation")
    return {
        "executive_brief": value.get("executive_brief") if isinstance(value.get("executive_brief"), str) else "",
        "top_findings": [
            {key: item.get(key) for key in ("title", "severity", "summary", "evidence", "recommendation") if isinstance(item.get(key), str)}
            for item in findings if isinstance(item, dict)
        ] if isinstance(findings, list) else [],
        "key_numbers": [
            {key: item.get(key) for key in ("label", "value", "unit", "source") if isinstance(item.get(key), str)}
            for item in numbers if isinstance(item, dict)
        ] if isinstance(numbers, list) else [],
        "spreadsheet_audit": {
            key: audit.get(key) for key in ("status", "summary") if isinstance(audit.get(key), str)
        } if isinstance(audit, dict) else {},
        "validation": {
            key: validation.get(key) for key in ("status", "summary", "warnings_count", "failures_count")
            if isinstance(validation.get(key), (str, int))
        } if isinstance(validation, dict) else {},
        "critical_risks": strings(value.get("critical_risks")),
        "data_gaps": strings(value.get("data_gaps")),
        "required_actions": strings(value.get("required_actions")),
    }
