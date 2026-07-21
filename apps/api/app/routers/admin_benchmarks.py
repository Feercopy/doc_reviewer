from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_admin
from app.models.benchmark import Benchmark
from app.models.skill import Skill
from app.models.user import User
from app.schemas.admin import AdminBenchmarkRead, AdminBenchmarksListResponse
from app.schemas.enums import Provider, RunStatus

router = APIRouter(prefix="/admin/benchmarks", tags=["admin-benchmarks"])


@router.get("", response_model=AdminBenchmarksListResponse)
def list_admin_benchmarks(
    status: RunStatus | None = None,
    provider: Provider | None = None,
    model: str | None = None,
    skill_id: UUID | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminBenchmarksListResponse:
    judge_skill = Skill.__table__.alias("judge_skill")
    statement = (
        select(Benchmark, User, Skill, judge_skill.c.name)
        .join(User, User.id == Benchmark.started_by_id)
        .join(Skill, Skill.id == Benchmark.skill_id)
        .join(judge_skill, judge_skill.c.id == Benchmark.judge_skill_id)
    )
    if status is not None:
        statement = statement.where(Benchmark.status == status.value)
    if provider is not None:
        statement = statement.where(Benchmark.provider == provider.value)
    if model is not None:
        statement = statement.where(Benchmark.model == model)
    if skill_id is not None:
        statement = statement.where(Benchmark.skill_id == skill_id)
    statement = statement.order_by(Benchmark.started_at.desc().nullslast(), Benchmark.name)
    return AdminBenchmarksListResponse(
        benchmarks=[
            _read_benchmark(benchmark, user, skill, judge_skill_name)
            for benchmark, user, skill, judge_skill_name in db.execute(statement).all()
        ]
    )


def _read_benchmark(benchmark: Benchmark, user: User, skill: Skill, judge_skill_name: str) -> AdminBenchmarkRead:
    return AdminBenchmarkRead(
        id=benchmark.id,
        name=benchmark.name,
        description=benchmark.description,
        etalon_ids=benchmark.etalon_ids,
        skill_id=benchmark.skill_id,
        skill_version=benchmark.skill_version,
        skill_name=skill.name,
        judge_skill_id=benchmark.judge_skill_id,
        judge_skill_name=judge_skill_name,
        provider=benchmark.provider,
        model=benchmark.model,
        status=benchmark.status,
        started_by_id=benchmark.started_by_id,
        started_by_login=user.login,
        started_at=benchmark.started_at,
        completed_at=benchmark.completed_at,
        overall_score=benchmark.overall_score,
        layer_1_score=benchmark.layer_1_score,
        layer_2_score=benchmark.layer_2_score,
        precision=benchmark.precision,
        recall=benchmark.recall,
        f1=benchmark.f1,
        run_parameters=benchmark.run_parameters,
        error_message=benchmark.error_message,
    )
