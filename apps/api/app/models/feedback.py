from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.models.base import Base, utc_now


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    analysis_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("analyses.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    skill_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("skills.id"), nullable=False)
    skill_version: Mapped[str] = mapped_column(String, nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usefulness: Mapped[str] = mapped_column(String, nullable=False)
    verdict_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_false_findings: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_missed_findings: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    can_use_for_benchmark: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
