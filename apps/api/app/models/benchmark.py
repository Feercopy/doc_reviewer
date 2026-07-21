from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.models.base import Base


class Benchmark(Base):
    __tablename__ = "benchmarks"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    etalon_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    skill_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("skills.id"), nullable=False)
    skill_version: Mapped[str] = mapped_column(String, nullable=False)
    judge_skill_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("skills.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_by_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    overall_score: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    layer_1_score: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    layer_2_score: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    precision: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    recall: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    f1: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    missed_findings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    false_positives: Mapped[list | None] = mapped_column(JSON, nullable=True)
    partial_matches: Mapped[list | None] = mapped_column(JSON, nullable=True)
    judge_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    run_parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
