from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.enums import CheckStatus, DocumentType, EtalonSource, EtalonStatus, Severity, Verdict


class EtalonEvidence(BaseModel):
    quote: str = Field(min_length=1)
    location: str = Field(min_length=1)


class EtalonLayer1Item(BaseModel):
    id: str = Field(min_length=1)
    dimension: str = Field(min_length=1)
    status: CheckStatus
    severity: Severity
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence: list[EtalonEvidence] = Field(default_factory=list)
    recommendation: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)


class EtalonLayer2Item(BaseModel):
    id: str = Field(min_length=1)
    parent_layer_1_id: str = Field(min_length=1)
    check: str = Field(min_length=1)
    status: CheckStatus
    severity: Severity
    finding: str = Field(min_length=1)
    evidence: list[EtalonEvidence] = Field(default_factory=list)
    expected_fix: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)


class EtalonPayload(BaseModel):
    expected_verdict: Verdict
    layer_1: list[EtalonLayer1Item] = Field(default_factory=list)
    layer_2: list[EtalonLayer2Item] = Field(default_factory=list)
    key_findings: list[str] = Field(default_factory=list)
    forbidden_false_findings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_layer_2_parents(self) -> "EtalonPayload":
        layer_1_ids = {item.id for item in self.layer_1}
        orphan_ids = sorted({item.parent_layer_1_id for item in self.layer_2 if item.parent_layer_1_id not in layer_1_ids})
        if orphan_ids:
            raise ValueError(f"Layer 2 parent_layer_1_id values do not exist in Layer 1: {', '.join(orphan_ids)}")
        return self


class EtalonDraftCreate(BaseModel):
    status: EtalonStatus = EtalonStatus.DRAFT


class Gate2BenchmarkImportRequest(BaseModel):
    benchmark_dir: str | None = None
    activate: bool = False


class EtalonUpdate(BaseModel):
    expected_verdict: Verdict | None = None
    layer_1: list[EtalonLayer1Item] | None = None
    layer_2: list[EtalonLayer2Item] | None = None
    key_findings: list[str] | None = None
    forbidden_false_findings: list[str] | None = None
    real_defense_status: str | None = None
    defense_comments: str | None = None
    raw_file_visible_to_all: bool | None = None


class EtalonRead(BaseModel):
    id: UUID
    document_id: UUID
    author_id: UUID
    source: EtalonSource
    document_type: DocumentType
    real_defense_status: str | None
    defense_comments: str | None
    expected_verdict: Verdict
    layer_1: list[EtalonLayer1Item]
    layer_2: list[EtalonLayer2Item]
    key_findings: list[str]
    forbidden_false_findings: list[str]
    source_metadata: dict
    status: EtalonStatus
    version: int
    raw_file_visible_to_all: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EtalonsListResponse(BaseModel):
    etalons: list[EtalonRead]


class Gate2BenchmarkImportResponse(BaseModel):
    imported_count: int
    skipped_count: int
    updated_count: int = 0
    unmatched_count: int = 0
    parse_enqueued_count: int
    etalons: list[EtalonRead]
