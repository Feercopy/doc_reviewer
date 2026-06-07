from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.models.base import Base, TimestampMixin
from app.schemas.enums import EntityStatus


class Skill(TimestampMixin, Base):
    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("name", "version", "skill_type", name="uq_skills_name_version_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    skill_type: Mapped[str] = mapped_column(String, nullable=False)
    supported_document_types: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    source_entrypoint: Mapped[str | None] = mapped_column(String, nullable=True)
    source_revision: Mapped[str | None] = mapped_column(String, nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    source_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    result_schema_path: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default=EntityStatus.ACTIVE.value)
    author_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
