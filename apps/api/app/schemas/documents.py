from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.enums import DocumentParseStatus, DocumentType, EntityStatus


class DocumentRead(BaseModel):
    id: UUID
    owner_id: UUID
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
    parse_error: str | None
    status: EntityStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentsListResponse(BaseModel):
    documents: list[DocumentRead]
