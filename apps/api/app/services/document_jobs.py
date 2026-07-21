from collections.abc import Callable
from uuid import UUID

from redis import Redis
from rq import Queue

from app.core.config import get_settings


DOCUMENTS_QUEUE_NAME = "documents"
PARSE_DOCUMENT_JOB_PATH = "jobs.parse_document.parse_document"

ParseDocumentEnqueue = Callable[[UUID], None]


def enqueue_parse_document(document_id: UUID) -> None:
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    queue = Queue(DOCUMENTS_QUEUE_NAME, connection=connection)
    queue.enqueue_call(
        func=PARSE_DOCUMENT_JOB_PATH,
        args=(str(document_id),),
        timeout=600,
        result_ttl=3600,
    )
