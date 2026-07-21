from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.models.base import Base, TimestampMixin
from app.schemas.enums import DocumentParseStatus, DocumentRole, DocumentType, EntityStatus


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_owner_created_at", "owner_id", "created_at"),
        Index("ix_documents_file_hash_sha256", "file_hash_sha256"),
        Index("ix_documents_detected_document_type", "detected_document_type"),
        Index("ix_documents_document_role", "document_role"),
        Index("ix_documents_linked_fin_summary_document_id", "linked_fin_summary_document_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    linked_fin_summary_document_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_hash_sha256: Mapped[str] = mapped_column(String, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    parse_status: Mapped[str] = mapped_column(String, nullable=False, default=DocumentParseStatus.QUEUED.value)
    detected_document_type: Mapped[str] = mapped_column(String, nullable=False, default=DocumentType.UNKNOWN.value)
    document_type_confidence: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    document_type_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_document_type: Mapped[str | None] = mapped_column(String, nullable=True)
    document_role: Mapped[str] = mapped_column(String, nullable=False, default=DocumentRole.PRIMARY.value)
    parsed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default=EntityStatus.ACTIVE.value)
    linked_fin_summary_document: Mapped["Document | None"] = relationship(
        "Document",
        remote_side=[id],
        foreign_keys=[linked_fin_summary_document_id],
        post_update=True,
    )
