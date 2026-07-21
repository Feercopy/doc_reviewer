from uuid import uuid4

from app.services import analysis_jobs


def test_enqueue_ic_review_uses_extended_timeout(monkeypatch):
    calls: list[dict] = []

    class FakeRedis:
        @staticmethod
        def from_url(url):
            return f"redis:{url}"

    class FakeQueue:
        def __init__(self, name, connection):
            self.name = name
            self.connection = connection

        def enqueue_call(self, **kwargs):
            calls.append({"queue": self.name, "connection": self.connection, **kwargs})

    monkeypatch.setattr(analysis_jobs, "Redis", FakeRedis)
    monkeypatch.setattr(analysis_jobs, "Queue", FakeQueue)

    check_run_id = uuid4()
    analysis_jobs.enqueue_run_ic_agentic_review(check_run_id)

    assert calls == [
        {
            "queue": analysis_jobs.ANALYSIS_QUEUE_NAME,
            "connection": "redis:redis://redis:6379/0",
            "func": analysis_jobs.RUN_IC_AGENTIC_REVIEW_JOB_PATH,
            "args": (str(check_run_id),),
            "timeout": analysis_jobs.IC_AGENTIC_REVIEW_JOB_TIMEOUT_SECONDS,
            "result_ttl": 3600,
        }
    ]
    assert analysis_jobs.IC_AGENTIC_REVIEW_JOB_TIMEOUT_SECONDS == 7200
