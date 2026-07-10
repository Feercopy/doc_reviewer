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


class SourceTrace(BaseModel):
    source_snapshot_id: UUID | None = None
    source_slug: str | None = None
    source_revision: str | None = None
    source_fingerprint: str | None = None
    snapshot_mode: str | None = None
    is_dirty: bool | None = None
    prompt_fingerprint: str | None = None
    rendered_prompt_artifact_path: str | None = None


class RetrievalTrace(BaseModel):
    retrieval_snapshot_id: UUID | None = None
    retrieval_mode: str | None = None
    retrieval_version: str | None = None
    corpus_fingerprint: str | None = None
    query_fingerprint: str | None = None
    prompt_fingerprint: str | None = None
    rendered_prompt_artifact_path: str | None = None


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
    source_trace: SourceTrace | None = None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    predicted_comment_run: "PredictedCommentRunRead | None" = None
    detail_run: "AnalysisDetailRunRead | None" = None
    ic_review_run: "AnalysisCheckRunRead | None" = None


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
    source_trace: SourceTrace | None = None
    retrieval_trace: RetrievalTrace | None = None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class AnalysisDetailRunRead(BaseModel):
    id: UUID
    analysis_id: UUID
    status: RunStatus
    provider: Provider
    model: str
    previous_response_id: str | None
    response_id: str | None
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


class AnalysisCheckStepRead(BaseModel):
    id: UUID
    check_run_id: UUID
    step_type: str
    step_name: str
    status: RunStatus
    prompt_fingerprint: str | None
    prompt_artifact_path: str | None = None
    raw_output: str | None
    structured_output: dict | None
    error_message: str | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost: Decimal | None
    artifacts: list[dict]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class AnalysisCheckRunRead(BaseModel):
    id: UUID
    analysis_id: UUID
    skill_id: UUID
    skill_name: str
    skill_version: str
    check_type: str
    provider: Provider
    model: str
    status: RunStatus
    current_stage: str | None
    structured_output: dict | None
    legacy_output: dict | None
    raw_output: str | None
    error_message: str | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost: Decimal | None
    run_parameters: dict
    uploaded_workbook_metadata: dict
    artifacts: list[dict]
    source_trace: SourceTrace | None = None
    steps: list[AnalysisCheckStepRead] = Field(default_factory=list)
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class AnalysisCheckRunsListResponse(BaseModel):
    runs: list[AnalysisCheckRunRead]
