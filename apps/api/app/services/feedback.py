from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authz.policies import can_manage_benchmarks
from app.models.base import utc_now
from app.models.feedback import Feedback
from app.models.user import User
from app.schemas.enums import FeedbackUsefulness
from app.schemas.feedback import FeedbackCreate
from app.services.analyses import AnalysisNotFoundError, get_analysis_for_actor
from app.services.audit import record_audit


class FeedbackNotFoundError(ValueError):
    pass


class FeedbackForbiddenError(ValueError):
    pass


def create_feedback(*, db: Session, actor: User, analysis_id: UUID, payload: FeedbackCreate) -> Feedback:
    try:
        analysis = get_analysis_for_actor(db=db, actor=actor, analysis_id=analysis_id)
    except AnalysisNotFoundError as exc:
        raise FeedbackNotFoundError("Analysis not found") from exc

    usefulness = _usefulness_from_rating(payload.rating) if payload.rating is not None else payload.usefulness
    if usefulness is None:
        raise FeedbackNotFoundError("Feedback usefulness not found")

    feedback = Feedback(
        user_id=actor.id,
        document_id=analysis.document_id,
        analysis_id=analysis.id,
        provider=analysis.provider,
        model=analysis.model,
        skill_id=analysis.skill_id,
        skill_version=analysis.skill_version,
        rating=payload.rating,
        usefulness=usefulness.value,
        verdict_correct=payload.verdict_correct,
        has_false_findings=payload.has_false_findings,
        has_missed_findings=payload.has_missed_findings,
        comment=payload.comment,
        can_use_for_benchmark=payload.can_use_for_benchmark,
    )
    db.add(feedback)
    record_audit(
        db=db,
        actor_id=actor.id,
        action="feedback.created",
        entity_type="feedback",
        entity_id=feedback.id,
        metadata={"analysis_id": str(analysis.id), "document_id": str(analysis.document_id)},
    )
    db.commit()
    db.refresh(feedback)
    return feedback


def _usefulness_from_rating(rating: int) -> FeedbackUsefulness:
    if rating <= 2:
        return FeedbackUsefulness.USELESS
    if rating == 3:
        return FeedbackUsefulness.PARTIALLY_USEFUL
    return FeedbackUsefulness.USEFUL


def list_feedback_for_admin(*, db: Session, actor: User) -> list[Feedback]:
    if not can_manage_benchmarks(actor):
        raise FeedbackForbiddenError("Admin access required")
    statement = select(Feedback).order_by(Feedback.created_at.desc())
    return list(db.execute(statement).scalars().all())


def mark_feedback_processed(*, db: Session, actor: User, feedback_id: UUID) -> Feedback:
    if not can_manage_benchmarks(actor):
        raise FeedbackForbiddenError("Admin access required")
    feedback = db.get(Feedback, feedback_id)
    if feedback is None:
        raise FeedbackNotFoundError("Feedback not found")
    feedback.processed_at = utc_now()
    record_audit(
        db=db,
        actor_id=actor.id,
        action="feedback.processed",
        entity_type="feedback",
        entity_id=feedback.id,
        metadata={"analysis_id": str(feedback.analysis_id), "user_id": str(feedback.user_id)},
    )
    db.commit()
    db.refresh(feedback)
    return feedback
