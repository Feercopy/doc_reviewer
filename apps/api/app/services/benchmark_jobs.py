from collections.abc import Callable
from uuid import UUID

from redis import Redis
from rq import Queue

from app.core.config import get_settings


BENCHMARK_QUEUE_NAME = "benchmark"
RUN_BENCHMARK_JOB_PATH = "jobs.run_benchmark.run_benchmark"
RunBenchmarkEnqueue = Callable[[UUID], None]


def enqueue_run_benchmark(benchmark_id: UUID) -> None:
    settings = get_settings()
    queue = Queue(BENCHMARK_QUEUE_NAME, connection=Redis.from_url(settings.redis_url))
    queue.enqueue_call(func=RUN_BENCHMARK_JOB_PATH, args=(str(benchmark_id),), timeout=3600, result_ttl=3600)
