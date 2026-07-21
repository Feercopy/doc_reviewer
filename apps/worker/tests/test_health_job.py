from jobs.health import health_job


def test_health_job_returns_ok():
    assert health_job() == {"status": "ok"}
