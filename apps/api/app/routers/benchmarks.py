from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_current_user
from app.models.benchmark import Benchmark
from app.models.user import User
from app.schemas.benchmarks import BenchmarkCreate, BenchmarkRead, BenchmarksListResponse
from app.services.benchmark_jobs import RunBenchmarkEnqueue, enqueue_run_benchmark
from app.services.benchmarks import (
    BenchmarkForbiddenError,
    BenchmarkNotFoundError,
    BenchmarkPreconditionError,
    cancel_benchmark,
    create_benchmark,
    get_benchmark_for_actor,
    list_benchmarks_for_actor,
)

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


def get_run_benchmark_enqueue() -> RunBenchmarkEnqueue:
    return enqueue_run_benchmark


@router.get("", response_model=BenchmarksListResponse)
def list_benchmarks(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> BenchmarksListResponse:
    try:
        return BenchmarksListResponse(benchmarks=list_benchmarks_for_actor(db=db, actor=current_user))
    except BenchmarkForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("", response_model=BenchmarkRead, status_code=status.HTTP_201_CREATED)
def post_benchmark(
    payload: BenchmarkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
    enqueue: RunBenchmarkEnqueue = Depends(get_run_benchmark_enqueue),
) -> Benchmark:
    try:
        benchmark = create_benchmark(db=db, actor=current_user, payload=payload)
    except BenchmarkForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except BenchmarkPreconditionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    enqueue(benchmark.id)
    return benchmark


@router.get("/{benchmark_id}", response_model=BenchmarkRead)
def get_benchmark(
    benchmark_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Benchmark:
    try:
        return get_benchmark_for_actor(db=db, actor=current_user, benchmark_id=benchmark_id)
    except BenchmarkForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except BenchmarkNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benchmark not found") from exc


@router.get("/{benchmark_id}/report")
def get_benchmark_report(
    benchmark_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> dict:
    benchmark = get_benchmark(benchmark_id=benchmark_id, db=db, current_user=current_user)
    return benchmark.report or {}


@router.post("/{benchmark_id}/cancel", response_model=BenchmarkRead)
def post_cancel_benchmark(
    benchmark_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Benchmark:
    try:
        return cancel_benchmark(db=db, actor=current_user, benchmark_id=benchmark_id)
    except BenchmarkForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except BenchmarkNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benchmark not found") from exc
    except BenchmarkPreconditionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
