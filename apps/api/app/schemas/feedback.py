from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.enums import FeedbackUsefulness


class FeedbackCreate(BaseModel):
    usefulness: FeedbackUsefulness | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    verdict_correct: bool | None = None
    has_false_findings: bool | None = None
    has_missed_findings: bool | None = None
    comment: str | None = None
    can_use_for_benchmark: bool = False

    @model_validator(mode="after")
    def require_rating_or_usefulness(self) -> "FeedbackCreate":
        if self.rating is None and self.usefulness is None:
            raise ValueError("Either rating or usefulness is required")
        return self


class FeedbackRead(BaseModel):
    id: UUID
    user_id: UUID
    document_id: UUID
    analysis_id: UUID
    provider: str
    model: str
    skill_id: UUID
    skill_version: str
    rating: int | None
    usefulness: FeedbackUsefulness
    verdict_correct: bool | None
    has_false_findings: bool | None
    has_missed_findings: bool | None
    comment: str | None
    can_use_for_benchmark: bool
    processed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FeedbackListResponse(BaseModel):
    feedback: list[FeedbackRead]
