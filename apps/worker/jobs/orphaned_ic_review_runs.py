from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from redis import Redis
from rq import Queue
from rq.job import Job
from rq.registry import StartedJobRegistry
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import SessionLocal
from app.logging import worker_logger
from app.models.analysis import AnalysisCheckRun, AnalysisCheckStep
from app.models.base import utc_now
from app.schemas.enums import RunStatus


ANALYSIS_QUEUE_NAME = "analysis"
IC_REVIEW_CHECK_TYPE = "ic_agentic_review"
RUN_IC_AGENTIC_REVIEW_JOB_PATH = "jobs.run_ic_agentic_review.run_ic_agentic_review"
ABANDONED_ERROR_MESSAGE = "worker_job_abandoned"
INTERRUPTED_STEP_ERROR_MESSAGE = "interrupted_by_worker_restart"


def cleanup_abandoned_ic_review_runs(*, connection: Redis, db: Session | None = None) -> int:
    """Fail IC Review runs left running after their RQ job disappeared."""
    active_run_ids = _active_ic_review_run_ids(connection=connection)
    owns_session = db is None
    session = db or SessionLocal()
    try:
        cleaned = mark_abandoned_ic_review_runs(session=session, active_run_ids=active_run_ids)
        if cleaned:
            worker_logger.info(
                "worker_abandoned_ic_review_runs_cleaned",
                extra={"job_type": "run_ic_agentic_review", "runs_cleaned": cleaned},
            )
        return cleaned
    finally:
        if owns_session:
            session.close()


def mark_abandoned_ic_review_runs(*, session: Session, active_run_ids: Iterable[UUID]) -> int:
    active_ids = set(active_run_ids)
    statement = select(AnalysisCheckRun).where(
        AnalysisCheckRun.check_type == IC_REVIEW_CHECK_TYPE,
        AnalysisCheckRun.status == RunStatus.RUNNING.value,
    )
    runs = [
        run
        for run in session.execute(statement).scalars().all()
        if run.id not in active_ids
    ]
    if not runs:
        return 0

    now = utc_now()
    run_ids = [run.id for run in runs]
    for run in runs:
        run.status = RunStatus.FAILED.value
        run.current_stage = "failed:abandoned"
        run.error_message = ABANDONED_ERROR_MESSAGE
        run.completed_at = now
        run_parameters = dict(run.run_parameters or {})
        run_parameters["abandoned_cleanup"] = {
            "status": "failed",
            "reason": ABANDONED_ERROR_MESSAGE,
            "cleaned_at": now.isoformat(),
        }
        run.run_parameters = run_parameters
        flag_modified(run, "run_parameters")

    steps = session.execute(
        select(AnalysisCheckStep).where(
            AnalysisCheckStep.check_run_id.in_(run_ids),
            AnalysisCheckStep.status == RunStatus.RUNNING.value,
        )
    ).scalars().all()
    for step in steps:
        step.status = RunStatus.FAILED.value
        step.error_message = INTERRUPTED_STEP_ERROR_MESSAGE
        step.completed_at = now

    session.commit()
    return len(runs)


def _active_ic_review_run_ids(*, connection: Redis) -> set[UUID]:
    queue = Queue(ANALYSIS_QUEUE_NAME, connection=connection)
    job_ids = [
        *queue.job_ids,
        *StartedJobRegistry(queue.name, connection=connection).get_job_ids(),
    ]
    run_ids: set[UUID] = set()
    for job_id in job_ids:
        try:
            job = Job.fetch(job_id, connection=connection)
        except Exception:
            continue
        run_id = _ic_review_run_id_from_job(job)
        if run_id is not None:
            run_ids.add(run_id)
    return run_ids


def _ic_review_run_id_from_job(job: Any) -> UUID | None:
    func_name = getattr(job, "func_name", None)
    if func_name != RUN_IC_AGENTIC_REVIEW_JOB_PATH:
        return None
    args = getattr(job, "args", ()) or ()
    if not args:
        return None
    try:
        return UUID(str(args[0]))
    except ValueError:
        return None
