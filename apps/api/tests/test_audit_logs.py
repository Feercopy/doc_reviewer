from app.models.audit_log import AuditLog
from app.services.audit import record_audit

from test_documents_upload import create_user


def test_record_audit_sanitizes_plaintext_secret_metadata(db_session):
    actor = create_user(db_session, "admin", "secret")

    audit = record_audit(
        db=db_session,
        actor_id=actor.id,
        action="provider_key.saved",
        entity_type="provider_key",
        entity_id=None,
        metadata={
            "provider": "openai_compatible",
            "api_key": "sk-live-secret",
            "password": "plaintext",
            "nested": {"token": "token-value", "safe": "kept"},
        },
    )
    db_session.commit()

    persisted = db_session.get(AuditLog, audit.id)
    assert persisted.action == "provider_key.saved"
    assert persisted.metadata_ == {
        "provider": "openai_compatible",
        "api_key": "[redacted]",
        "password": "[redacted]",
        "nested": {"token": "[redacted]", "safe": "kept"},
    }


def test_user_admin_routes_use_canonical_audit_actions(client, db_session):
    admin = create_user(db_session, "admin", "secret")
    admin.role = "admin"
    db_session.commit()
    response = client.post("/auth/login", json={"login": "admin", "password": "secret"})
    assert response.status_code == 200

    created = client.post(
        "/admin/users",
        json={
            "login": "analyst",
            "display_name": "Analyst",
            "password": "strong-secret",
            "role": "user",
            "status": "active",
        },
    )

    assert created.status_code == 201
    audit_actions = [row.action for row in db_session.query(AuditLog).order_by(AuditLog.created_at).all()]
    assert "user.created" in audit_actions
