from collections.abc import Callable
from uuid import UUID

from redis import Redis
from rq import Queue

from app.core.config import get_settings


ANALYSIS_QUEUE_NAME = "analysis"
RUN_ANALYSIS_JOB_PATH = "jobs.run_analysis.run_analysis"
RUN_ANALYSIS_DETAILS_JOB_PATH = "jobs.run_analysis_details.run_analysis_details"
RUN_IC_AGENTIC_REVIEW_JOB_PATH = "jobs.run_ic_agentic_review.run_ic_agentic_review"
RUN_SUMMARY_LOCALIZATIONS_JOB_PATH = "jobs.run_summary_localizations.run_summary_localizations"
IC_AGENTIC_REVIEW_JOB_TIMEOUT_SECONDS = 7200
SUMMARY_LOCALIZATIONS_JOB_TIMEOUT_SECONDS = 7200

RunAnalysisEnqueue = Callable[[UUID], None]
RunAnalysisDetailsEnqueue = Callable[[UUID], None]
RunIcAgenticReviewEnqueue = Callable[[UUID], None]
RunSummaryLocalizationsEnqueue = Callable[[UUID], None]


def enqueue_run_analysis(analysis_id: UUID) -> None:
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    queue = Queue(ANALYSIS_QUEUE_NAME, connection=connection)
    queue.enqueue_call(func=RUN_ANALYSIS_JOB_PATH, args=(str(analysis_id),), timeout=1800, result_ttl=3600)


def enqueue_run_analysis_details(detail_run_id: UUID) -> None:
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    queue = Queue(ANALYSIS_QUEUE_NAME, connection=connection)
    queue.enqueue_call(func=RUN_ANALYSIS_DETAILS_JOB_PATH, args=(str(detail_run_id),), timeout=1800, result_ttl=3600)


def enqueue_run_ic_agentic_review(check_run_id: UUID) -> None:
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    queue = Queue(ANALYSIS_QUEUE_NAME, connection=connection)
    queue.enqueue_call(
        func=RUN_IC_AGENTIC_REVIEW_JOB_PATH,
        args=(str(check_run_id),),
        timeout=IC_AGENTIC_REVIEW_JOB_TIMEOUT_SECONDS,
        result_ttl=3600,
    )


def enqueue_run_summary_localizations(analysis_id: UUID) -> None:
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    queue = Queue(ANALYSIS_QUEUE_NAME, connection=connection)
    job_id = f"summary-localizations-{analysis_id}"
    existing = queue.fetch_job(job_id)
    if existing is not None:
        status = existing.get_status(refresh=True)
        status_value = getattr(status, "value", status)
        if str(status_value).lower() in {"queued", "started", "deferred", "scheduled"}:
            return
    queue.enqueue_call(
        func=RUN_SUMMARY_LOCALIZATIONS_JOB_PATH,
        args=(str(analysis_id),),
        job_id=job_id,
        timeout=SUMMARY_LOCALIZATIONS_JOB_TIMEOUT_SECONDS,
        result_ttl=3600,
    )
