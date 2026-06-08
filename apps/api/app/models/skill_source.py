from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.models.base import Base, TimestampMixin, utc_now


class SkillSource(TimestampMixin, Base):
    __tablename__ = "skill_sources"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    local_path: Mapped[str | None] = mapped_column(String, nullable=True)
    repo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    default_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    entrypoint: Mapped[str] = mapped_column(String, nullable=False)
    required_paths: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    update_policy: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)


class SkillSourceSnapshot(Base):
    __tablename__ = "skill_source_snapshots"
    __table_args__ = (
        CheckConstraint(
            "(analysis_id IS NOT NULL AND predicted_comment_run_id IS NULL) "
            "OR (analysis_id IS NULL AND predicted_comment_run_id IS NOT NULL)",
            name="ck_skill_source_snapshots_one_owner",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    skill_source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("skill_sources.id"), nullable=False)
    analysis_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("analyses.id"), nullable=True)
    predicted_comment_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("predicted_comment_runs.id"),
        nullable=True,
    )
    source_slug: Mapped[str] = mapped_column(String, nullable=False)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_path: Mapped[str | None] = mapped_column(String, nullable=True)
    repo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    requested_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_revision: Mapped[str | None] = mapped_column(String, nullable=True)
    is_dirty: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dirty_details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    snapshot_mode: Mapped[str] = mapped_column(String, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    file_manifest: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    artifact_path: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class RetrievalSnapshot(Base):
    __tablename__ = "retrieval_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    predicted_comment_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("predicted_comment_runs.id"),
        nullable=False,
    )
    retrieval_mode: Mapped[str] = mapped_column(String, nullable=False)
    retrieval_version: Mapped[str] = mapped_column(String, nullable=False)
    corpus_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    query_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    selected_items: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    artifact_path: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
