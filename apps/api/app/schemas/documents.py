from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.enums import DocumentParseStatus, DocumentRole, DocumentType, EntityStatus


class DocumentTypePatch(BaseModel):
    manual_document_type: DocumentType | None


class DocumentTitlePatch(BaseModel):
    title: str = Field(min_length=1, max_length=256)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Document title cannot be empty")
        return normalized


class LinkedDocumentRead(BaseModel):
    id: UUID
    title: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    parse_status: DocumentParseStatus
    parse_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentRead(BaseModel):
    id: UUID
    owner_id: UUID
    linked_fin_summary_document_id: UUID | None
    title: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    file_hash_sha256: str
    parse_status: DocumentParseStatus
    detected_document_type: DocumentType
    document_type_confidence: Decimal | None
    document_type_explanation: str | None
    manual_document_type: DocumentType | None
    document_role: DocumentRole
    parse_error: str | None
    status: EntityStatus
    linked_fin_summary_document: LinkedDocumentRead | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentsListResponse(BaseModel):
    documents: list[DocumentRead]
