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


def test_enqueue_summary_localizations_uses_rq_safe_dedup_job_id(monkeypatch):
    calls: list[dict] = []

    class FakeRedis:
        @staticmethod
        def from_url(url):
            return f"redis:{url}"

    class FakeQueue:
        def __init__(self, name, connection):
            self.name = name
            self.connection = connection

        def fetch_job(self, job_id):
            return None

        def enqueue_call(self, **kwargs):
            calls.append({"queue": self.name, "connection": self.connection, **kwargs})

    monkeypatch.setattr(analysis_jobs, "Redis", FakeRedis)
    monkeypatch.setattr(analysis_jobs, "Queue", FakeQueue)

    analysis_id = uuid4()
    analysis_jobs.enqueue_run_summary_localizations(analysis_id)

    assert calls == [
        {
            "queue": analysis_jobs.ANALYSIS_QUEUE_NAME,
            "connection": "redis:redis://redis:6379/0",
            "func": analysis_jobs.RUN_SUMMARY_LOCALIZATIONS_JOB_PATH,
            "args": (str(analysis_id),),
            "job_id": f"summary-localizations-{analysis_id}",
            "timeout": analysis_jobs.SUMMARY_LOCALIZATIONS_JOB_TIMEOUT_SECONDS,
            "result_ttl": 3600,
        }
    ]
    assert ":" not in calls[0]["job_id"]
    assert analysis_jobs.SUMMARY_LOCALIZATIONS_JOB_TIMEOUT_SECONDS == 7200


def test_enqueue_summary_localizations_skips_active_duplicate(monkeypatch):
    calls: list[dict] = []

    class FakeRedis:
        @staticmethod
        def from_url(url):
            return f"redis:{url}"

    class FakeJob:
        def get_status(self, *, refresh):
            return "queued"

    class FakeQueue:
        def __init__(self, name, connection):
            self.name = name
            self.connection = connection

        def fetch_job(self, job_id):
            return FakeJob()

        def enqueue_call(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(analysis_jobs, "Redis", FakeRedis)
    monkeypatch.setattr(analysis_jobs, "Queue", FakeQueue)

    analysis_jobs.enqueue_run_summary_localizations(uuid4())

    assert calls == []
