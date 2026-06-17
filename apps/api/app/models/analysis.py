from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.models.base import Base, utc_now


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (
        Index("ix_analyses_document_created_at", "document_id", "created_at"),
        Index("ix_analyses_user_created_at", "user_id", "created_at"),
        Index("ix_analyses_provider_model", "provider", "model"),
        Index("ix_analyses_skill_version", "skill_id", "skill_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    skill_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("skills.id"), nullable=False)
    skill_version: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    run_parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PredictedCommentRun(Base):
    __tablename__ = "predicted_comment_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    analysis_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("analyses.id"), nullable=False)
    skill_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("skills.id"), nullable=False)
    skill_version: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    structured_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    run_parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnalysisDetailRun(Base):
    __tablename__ = "analysis_detail_runs"
    __table_args__ = (
        Index("ix_analysis_detail_runs_analysis_created_at", "analysis_id", "created_at"),
        Index("ix_analysis_detail_runs_status_created_at", "status", "created_at"),
        Index("ix_analysis_detail_runs_provider_model", "provider", "model"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    analysis_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("analyses.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    previous_response_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    run_parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
