from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_current_user
from app.models.feedback import Feedback
from app.models.user import User
from app.schemas.feedback import FeedbackCreate, FeedbackRead
from app.services.feedback import (
    FeedbackNotFoundError,
    create_feedback,
)

router = APIRouter(tags=["feedback"])


@router.post("/analyses/{analysis_id}/feedback", response_model=FeedbackRead, status_code=status.HTTP_201_CREATED)
def post_feedback(
    analysis_id: UUID,
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Feedback:
    try:
        return create_feedback(db=db, actor=current_user, analysis_id=analysis_id, payload=payload)
    except FeedbackNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found") from exc

