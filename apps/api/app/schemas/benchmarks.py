from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import Provider, RunStatus


class BenchmarkCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    etalon_ids: list[UUID] = Field(min_length=1)
    skill_id: UUID
    provider: Provider
    model: str = Field(min_length=1)
    judge_skill_id: UUID
    evaluation_mode: str = "layer_1_and_layer_2"
    run_parameters: dict = Field(default_factory=dict)


class BenchmarkRead(BaseModel):
    id: UUID
    name: str
    description: str
    etalon_ids: list[UUID]
    skill_id: UUID
    skill_version: str
    judge_skill_id: UUID
    provider: Provider
    model: str
    status: RunStatus
    started_by_id: UUID
    started_at: datetime | None
    completed_at: datetime | None
    overall_score: Decimal | None
    layer_1_score: Decimal | None
    layer_2_score: Decimal | None
    precision: Decimal | None
    recall: Decimal | None
    f1: Decimal | None
    missed_findings: list | None
    false_positives: list | None
    partial_matches: list | None
    judge_output: dict | None
    report: dict | None
    run_parameters: dict
    error_message: str | None

    model_config = ConfigDict(from_attributes=True)


class BenchmarksListResponse(BaseModel):
    benchmarks: list[BenchmarkRead]
