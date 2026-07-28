from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import SessionLocal
from app.logging import worker_logger
from app.models.analysis import Analysis
from app.models.document import Document
from app.schemas.enums import DocumentParseStatus, RunStatus
from app.services.analysis_jobs import enqueue_run_analysis
from app.services.analyses import DOCUMENT_PARSE_DEPENDENCY_KEY


DeferredAnalysisEnqueue = Callable[[UUID], None]


def enqueue_ready_deferred_analyses(
    *,
    db: Session | None = None,
    document_id: UUID | None = None,
    enqueue: DeferredAnalysisEnqueue | None = None,
) -> int:
    owns_session = db is None
    session = db or SessionLocal()
    enqueue_analysis = enqueue or enqueue_run_analysis
    try:
        analyses = _ready_deferred_analyses(session=session, document_id=document_id)
        enqueued = 0
        for analysis, document in analyses:
            _mark_dependency_state(
                session=session,
                analysis=analysis,
                document=document,
                state="enqueueing",
            )
            try:
                enqueue_analysis(analysis.id)
            except Exception as exc:
                _mark_dependency_state(
                    session=session,
                    analysis=analysis,
                    document=document,
                    state="enqueue_failed",
                    error=f"{exc.__class__.__name__}: {exc}",
                )
                worker_logger.info(
                    "deferred_analysis_enqueue_failed",
                    extra={
                        "job_type": "parse_document",
                        "entity_id": str(document.id),
                        "analysis_id": str(analysis.id),
                        "status": "failed",
                        "error_class": exc.__class__.__name__,
                    },
                )
                continue

            _mark_dependency_state(
                session=session,
                analysis=analysis,
                document=document,
                state="enqueued",
            )
            enqueued += 1
            worker_logger.info(
                "deferred_analysis_enqueued",
                extra={
                    "job_type": "parse_document",
                    "entity_id": str(document.id),
                    "analysis_id": str(analysis.id),
                    "status": "queued",
                },
            )
        return enqueued
    finally:
        if owns_session:
            session.close()


def _ready_deferred_analyses(
    *,
    session: Session,
    document_id: UUID | None,
) -> list[tuple[Analysis, Document]]:
    statement = (
        select(Analysis, Document)
        .join(Document, Analysis.document_id == Document.id)
        .where(
            Analysis.status == RunStatus.QUEUED.value,
            Analysis.deleted_at.is_(None),
            Document.parse_status == DocumentParseStatus.COMPLETED.value,
        )
        .order_by(Analysis.created_at, Analysis.id)
    )
    if document_id is not None:
        statement = statement.where(Document.id == document_id)

    return [
        (analysis, document)
        for analysis, document in session.execute(statement).all()
        if _is_waiting_for_document_parse(analysis)
    ]


def _is_waiting_for_document_parse(analysis: Analysis) -> bool:
    dependency = (analysis.run_parameters or {}).get(DOCUMENT_PARSE_DEPENDENCY_KEY)
    return isinstance(dependency, dict) and dependency.get("state") != "enqueued"


def _mark_dependency_state(
    *,
    session: Session,
    analysis: Analysis,
    document: Document,
    state: str,
    error: str | None = None,
) -> None:
    parameters = dict(analysis.run_parameters or {})
    dependency = dict(parameters.get(DOCUMENT_PARSE_DEPENDENCY_KEY) or {})
    dependency.update(
        {
            "document_id": str(document.id),
            "state": state,
        }
    )
    if error:
        dependency["error"] = error
    else:
        dependency.pop("error", None)
    parameters[DOCUMENT_PARSE_DEPENDENCY_KEY] = dependency
    parameters["document_type"] = document.manual_document_type or document.detected_document_type
    analysis.run_parameters = parameters
    flag_modified(analysis, "run_parameters")
    session.commit()
