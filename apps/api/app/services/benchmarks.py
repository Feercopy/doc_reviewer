from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authz.policies import can_manage_benchmarks
from app.models.benchmark import Benchmark
from app.models.etalon import Etalon
from app.models.skill import Skill
from app.models.user import User
from app.schemas.benchmarks import BenchmarkCreate
from app.schemas.enums import EntityStatus, EtalonStatus, Provider, RunStatus, SkillType
from app.services.provider_keys import get_provider_key
from app.services.skills import skill_source_snapshot


class BenchmarkForbiddenError(ValueError):
    pass


class BenchmarkNotFoundError(ValueError):
    pass


class BenchmarkPreconditionError(ValueError):
    pass


def list_benchmarks_for_actor(*, db: Session, actor: User) -> list[Benchmark]:
    _require_benchmark_manager(actor)
    statement = select(Benchmark).order_by(Benchmark.started_at.desc().nullslast(), Benchmark.name)
    return list(db.execute(statement).scalars().all())


def get_benchmark_for_actor(*, db: Session, actor: User, benchmark_id: UUID) -> Benchmark:
    _require_benchmark_manager(actor)
    benchmark = db.get(Benchmark, benchmark_id)
    if benchmark is None:
        raise BenchmarkNotFoundError("Benchmark not found")
    return benchmark


def create_benchmark(*, db: Session, actor: User, payload: BenchmarkCreate) -> Benchmark:
    _require_benchmark_manager(actor)
    etalons = _resolve_active_etalons(db=db, etalon_ids=payload.etalon_ids)
    skill = _resolve_skill(db=db, skill_id=payload.skill_id, skill_type=SkillType.MAIN_ANALYSIS)
    judge_skill = _resolve_skill(db=db, skill_id=payload.judge_skill_id, skill_type=SkillType.BENCHMARK_JUDGE)
    if _requires_provider_key(payload.provider, payload.run_parameters) and get_provider_key(
        db=db,
        owner_id=actor.id,
        provider=payload.provider,
    ) is None:
        raise BenchmarkPreconditionError("Provider key is not configured")

    run_parameters = dict(payload.run_parameters)
    run_parameters["evaluation_mode"] = payload.evaluation_mode
    run_parameters["skill_source_snapshot"] = skill_source_snapshot(skill)
    run_parameters["judge_skill_source_snapshot"] = skill_source_snapshot(judge_skill)

    benchmark = Benchmark(
        name=payload.name,
        description=payload.description,
        etalon_ids=[str(item.id) for item in etalons],
        skill_id=skill.id,
        skill_version=skill.version,
        judge_skill_id=judge_skill.id,
        provider=payload.provider.value,
        model=payload.model,
        status=RunStatus.QUEUED.value,
        started_by_id=actor.id,
        run_parameters=run_parameters,
    )
    db.add(benchmark)
    db.commit()
    db.refresh(benchmark)
    return benchmark


def cancel_benchmark(*, db: Session, actor: User, benchmark_id: UUID) -> Benchmark:
    benchmark = get_benchmark_for_actor(db=db, actor=actor, benchmark_id=benchmark_id)
    if benchmark.status not in {RunStatus.QUEUED.value, RunStatus.RUNNING.value}:
        raise BenchmarkPreconditionError("Only queued or running benchmarks can be cancelled")
    benchmark.status = RunStatus.CANCELLED.value
    db.commit()
    db.refresh(benchmark)
    return benchmark


def _resolve_active_etalons(*, db: Session, etalon_ids: list[UUID]) -> list[Etalon]:
    etalons = []
    for etalon_id in etalon_ids:
        etalon = db.get(Etalon, etalon_id)
        if etalon is None or etalon.status != EtalonStatus.ACTIVE.value:
            raise BenchmarkPreconditionError("Benchmarks can only run over active etalons")
        etalons.append(etalon)
    return etalons


def _resolve_skill(*, db: Session, skill_id: UUID, skill_type: SkillType) -> Skill:
    skill = db.get(Skill, skill_id)
    if skill is None or skill.status != EntityStatus.ACTIVE.value or skill.skill_type != skill_type.value:
        raise BenchmarkPreconditionError(f"Selected {skill_type.value} skill is not available")
    return skill


def _requires_provider_key(provider: Provider, run_parameters: dict) -> bool:
    return provider != Provider.HERMES and "mock_provider_result" not in run_parameters


def _require_benchmark_manager(actor: User) -> None:
    if not can_manage_benchmarks(actor):
        raise BenchmarkForbiddenError("Admin access required")
