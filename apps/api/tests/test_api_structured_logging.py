import logging

from test_documents_upload import create_user, login


def test_api_request_logging_sets_request_id_and_actor_id(client, db_session, caplog):
    create_user(db_session, "author", "secret")
    login(client, "author", "secret")

    with caplog.at_level(logging.INFO, logger="gate_challenger.api"):
        response = client.get("/auth/me", headers={"X-Request-ID": "req-test-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-test-123"
    records = [record for record in caplog.records if record.name == "gate_challenger.api"]
    assert any(record.request_id == "req-test-123" for record in records)
    assert any(record.actor_id == str(response.json()["id"]) for record in records)
    assert "secret" not in caplog.text
