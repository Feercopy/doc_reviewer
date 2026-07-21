from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.enums import (
    DocumentParseStatus,
    DocumentRole,
    DocumentType,
    EntityStatus,
    EtalonSource,
    EtalonStatus,
    FeedbackUsefulness,
    Provider,
    RunStatus,
    Verdict,
)


class AdminDocumentRead(BaseModel):
    id: UUID
    owner_id: UUID
    linked_fin_summary_document_id: UUID | None
    owner_login: str
    title: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    file_hash_sha256: str
    parse_status: DocumentParseStatus
    detected_document_type: DocumentType
    manual_document_type: DocumentType | None
    document_role: DocumentRole
    document_type_confidence: Decimal | None
    parse_error: str | None
    status: EntityStatus
    parsed_text_available: bool
    created_at: datetime
    updated_at: datetime


class AdminDocumentsListResponse(BaseModel):
    documents: list[AdminDocumentRead]


class AdminAnalysisRead(BaseModel):
    id: UUID
    document_id: UUID
    document_title: str
    user_id: UUID
    user_login: str
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


class AdminAnalysesListResponse(BaseModel):
    analyses: list[AdminAnalysisRead]


class AdminEtalonRead(BaseModel):
    id: UUID
    document_id: UUID
    document_title: str
    author_id: UUID
    author_login: str
    source: EtalonSource
    document_type: DocumentType
    expected_verdict: Verdict
    layer_1_count: int
    layer_2_count: int
    status: EtalonStatus
    version: int
    raw_file_visible_to_all: bool
    created_at: datetime
    updated_at: datetime


class AdminEtalonsListResponse(BaseModel):
    etalons: list[AdminEtalonRead]


class AdminBenchmarkRead(BaseModel):
    id: UUID
    name: str
    description: str
    etalon_ids: list
    skill_id: UUID
    skill_version: str
    skill_name: str
    judge_skill_id: UUID
    judge_skill_name: str
    provider: Provider
    model: str
    status: RunStatus
    started_by_id: UUID
    started_by_login: str
    started_at: datetime | None
    completed_at: datetime | None
    overall_score: Decimal | None
    layer_1_score: Decimal | None
    layer_2_score: Decimal | None
    precision: Decimal | None
    recall: Decimal | None
    f1: Decimal | None
    run_parameters: dict
    error_message: str | None


class AdminBenchmarksListResponse(BaseModel):
    benchmarks: list[AdminBenchmarkRead]


class AdminFeedbackRead(BaseModel):
    id: UUID
    user_id: UUID
    user_login: str
    document_id: UUID
    document_title: str
    analysis_id: UUID
    analysis_verdict: str | None
    provider: str
    model: str
    skill_id: UUID
    skill_version: str
    rating: int | None
    usefulness: FeedbackUsefulness
    verdict_correct: bool | None
    has_false_findings: bool | None
    has_missed_findings: bool | None
    comment: str | None
    can_use_for_benchmark: bool
    processed_at: datetime | None
    created_at: datetime


class AdminFeedbackSummary(BaseModel):
    total_count: int
    scored_count: int
    average_rating: float | None
    usefulness_counts: dict[str, int]
    incorrect_verdict_count: int
    false_findings_count: int
    missed_findings_count: int
    benchmark_candidate_count: int
    unprocessed_count: int
    low_rating_count: int
    legacy_count: int


class AdminFeedbackListResponse(BaseModel):
    feedback: list[AdminFeedbackRead]
    summary: AdminFeedbackSummary
