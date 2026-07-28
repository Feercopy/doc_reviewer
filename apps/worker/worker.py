import sys
from collections.abc import Sequence

from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings
from jobs.deferred_analyses import enqueue_ready_deferred_analyses
from jobs.orphaned_ic_review_runs import cleanup_abandoned_ic_review_runs


QUEUE_NAMES = ["documents", "analysis", "benchmark"]


def selected_queue_names(args: Sequence[str]) -> list[str]:
    queue_names = list(dict.fromkeys(args)) if args else list(QUEUE_NAMES)
    unknown_names = [name for name in queue_names if name not in QUEUE_NAMES]
    if unknown_names:
        raise ValueError(f"Unknown worker queues: {', '.join(unknown_names)}")
    return queue_names


def main(args: Sequence[str] | None = None) -> None:
    queue_names = selected_queue_names(sys.argv[1:] if args is None else args)
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    queues = [Queue(name, connection=connection) for name in queue_names]
    worker = Worker(queues, connection=connection)
    worker.clean_registries()
    if "analysis" in queue_names:
        cleanup_abandoned_ic_review_runs(connection=connection)
    if "documents" in queue_names:
        enqueue_ready_deferred_analyses()
    worker.work()


if __name__ == "__main__":
    main()
