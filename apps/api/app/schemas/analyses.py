from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.enums import DocumentType, Provider, RunStatus


class AnalysisCreate(BaseModel):
    provider: Provider
    model: str
    skill_id: UUID | None = None
    document_type_override: DocumentType | None = None
    run_parameters: dict = Field(default_factory=dict)


class AnalysisRead(BaseModel):
    id: UUID
    document_id: UUID
    user_id: UUID
    skill_id: UUID
    skill_name: str
    skill_version: str
    provider: Provider
    model: str
    status: RunStatus
    verdict: str | None
    summary: str | None
    structured_output: dict | None
    raw_output: str | None
    error_message: str | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost: Decimal | None
    run_parameters: dict
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    predicted_comment_run: "PredictedCommentRunRead | None" = None


class AnalysesListResponse(BaseModel):
    analyses: list[AnalysisRead]


class PredictedCommentRunRead(BaseModel):
    id: UUID
    analysis_id: UUID
    skill_id: UUID
    skill_name: str
    skill_version: str
    provider: Provider
    model: str
    status: RunStatus
    structured_output: dict | None
    raw_output: str | None
    error_message: str | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost: Decimal | None
    run_parameters: dict
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
