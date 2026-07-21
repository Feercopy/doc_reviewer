from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_admin
from app.models.analysis import Analysis
from app.models.document import Document
from app.models.feedback import Feedback
from app.models.user import User
from app.schemas.admin import AdminFeedbackListResponse, AdminFeedbackRead, AdminFeedbackSummary
from app.schemas.enums import FeedbackUsefulness
from app.schemas.feedback import FeedbackRead
from app.services.feedback import FeedbackNotFoundError, mark_feedback_processed

router = APIRouter(prefix="/admin/feedback", tags=["admin-feedback"])


@router.get("", response_model=AdminFeedbackListResponse)
def list_admin_feedback(
    provider: str | None = None,
    model: str | None = None,
    skill_id: UUID | None = None,
    user_id: UUID | None = None,
    verdict: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    processed_state: Literal["all", "processed", "unprocessed"] | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminFeedbackListResponse:
    statement = (
        select(Feedback, User, Document, Analysis)
        .join(User, User.id == Feedback.user_id)
        .join(Document, Document.id == Feedback.document_id)
        .join(Analysis, Analysis.id == Feedback.analysis_id)
    )
    if provider is not None:
        statement = statement.where(Feedback.provider == provider)
    if model is not None:
        statement = statement.where(Feedback.model == model)
    if skill_id is not None:
        statement = statement.where(Feedback.skill_id == skill_id)
    if user_id is not None:
        statement = statement.where(Feedback.user_id == user_id)
    if verdict is not None:
        statement = statement.where(Analysis.verdict == verdict)
    if date_from is not None:
        statement = statement.where(Feedback.created_at >= _start_of_day(date_from))
    if date_to is not None:
        statement = statement.where(Feedback.created_at < _start_of_day(date_to + timedelta(days=1)))
    if processed_state == "processed":
        statement = statement.where(Feedback.processed_at.is_not(None))
    if processed_state == "unprocessed":
        statement = statement.where(Feedback.processed_at.is_(None))
    statement = statement.order_by(Feedback.created_at.desc())
    rows = db.execute(statement).all()
    feedback = [_read_feedback(feedback, user, document, analysis) for feedback, user, document, analysis in rows]
    return AdminFeedbackListResponse(
        feedback=feedback,
        summary=_summary(feedback),
    )


@router.patch("/{feedback_id}/processed", response_model=FeedbackRead)
def patch_feedback_processed(
    feedback_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> Feedback:
    try:
        feedback = mark_feedback_processed(db=db, actor=admin, feedback_id=feedback_id)
    except FeedbackNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found") from exc
    return feedback


def _read_feedback(feedback: Feedback, user: User, document: Document, analysis: Analysis) -> AdminFeedbackRead:
    return AdminFeedbackRead(
        id=feedback.id,
        user_id=feedback.user_id,
        user_login=user.login,
        document_id=feedback.document_id,
        document_title=document.title,
        analysis_id=feedback.analysis_id,
        analysis_verdict=analysis.verdict,
        provider=feedback.provider,
        model=feedback.model,
        skill_id=feedback.skill_id,
        skill_version=feedback.skill_version,
        rating=feedback.rating,
        usefulness=feedback.usefulness,
        verdict_correct=feedback.verdict_correct,
        has_false_findings=feedback.has_false_findings,
        has_missed_findings=feedback.has_missed_findings,
        comment=feedback.comment,
        can_use_for_benchmark=feedback.can_use_for_benchmark,
        processed_at=feedback.processed_at,
        created_at=feedback.created_at,
    )


def _summary(feedback: list[AdminFeedbackRead]) -> AdminFeedbackSummary:
    ratings = [item.rating for item in feedback if item.rating is not None]
    usefulness_counts = {item.value: 0 for item in FeedbackUsefulness}
    for item in feedback:
        usefulness_counts[item.usefulness.value] += 1
    average_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
    return AdminFeedbackSummary(
        total_count=len(feedback),
        scored_count=len(ratings),
        average_rating=average_rating,
        usefulness_counts=usefulness_counts,
        incorrect_verdict_count=sum(1 for item in feedback if item.verdict_correct is False),
        false_findings_count=sum(1 for item in feedback if item.has_false_findings is True),
        missed_findings_count=sum(1 for item in feedback if item.has_missed_findings is True),
        benchmark_candidate_count=sum(1 for item in feedback if item.can_use_for_benchmark),
        unprocessed_count=sum(1 for item in feedback if item.processed_at is None),
        low_rating_count=sum(1 for item in feedback if item.rating is not None and item.rating <= 2),
        legacy_count=sum(1 for item in feedback if item.rating is None),
    )


def _start_of_day(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)
