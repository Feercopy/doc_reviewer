from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings
from jobs.orphaned_ic_review_runs import cleanup_abandoned_ic_review_runs


QUEUE_NAMES = ["documents", "analysis", "benchmark"]


def main() -> None:
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    queues = [Queue(name, connection=connection) for name in QUEUE_NAMES]
    worker = Worker(queues, connection=connection)
    worker.clean_registries()
    cleanup_abandoned_ic_review_runs(connection=connection)
    worker.work()


if __name__ == "__main__":
    main()
