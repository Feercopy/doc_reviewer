def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_localhost_and_loopback_frontend_origins(client):
    for origin in (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3100",
        "http://127.0.0.1:3100",
    ):
        response = client.options(
            "/auth/login",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_allows_configured_production_frontend_origin(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://avi-ix-devbox04:3000")
    get_settings.cache_clear()

    try:
        with TestClient(create_app()) as test_client:
            response = test_client.options(
                "/auth/login",
                headers={
                    "Origin": "http://avi-ix-devbox04:3000",
                    "Access-Control-Request-Method": "POST",
                },
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://avi-ix-devbox04:3000"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_allows_private_network_preflight_for_configured_origin(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "http://iseremenko.ru")
    get_settings.cache_clear()

    try:
        with TestClient(create_app()) as test_client:
            response = test_client.options(
                "/auth/login",
                headers={
                    "Origin": "http://iseremenko.ru",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                    "Access-Control-Request-Private-Network": "true",
                },
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://iseremenko.ru"
    assert response.headers["access-control-allow-private-network"] == "true"
