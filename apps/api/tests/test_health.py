def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_localhost_and_loopback_frontend_origins(client):
    for origin in ("http://localhost:3000", "http://127.0.0.1:3000"):
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
