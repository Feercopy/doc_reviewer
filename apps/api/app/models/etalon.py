from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.models.base import Base, TimestampMixin
from app.schemas.enums import EtalonStatus


class Etalon(TimestampMixin, Base):
    __tablename__ = "etalons"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    author_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    document_type: Mapped[str] = mapped_column(String, nullable=False)
    real_defense_status: Mapped[str | None] = mapped_column(String, nullable=True)
    defense_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_verdict: Mapped[str] = mapped_column(String, nullable=False)
    layer_1: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    layer_2: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    key_findings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    forbidden_false_findings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default=EtalonStatus.DRAFT.value)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    raw_file_visible_to_all: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
