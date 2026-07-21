from cryptography.fernet import InvalidToken

from app.models.audit_log import AuditLog
from app.models.provider_key import ProviderKey
from app.schemas.enums import Provider, Role
from app.security.secrets import decrypt_secret, encrypt_secret

from test_documents_upload import create_user, login


def test_admin_provider_key_roundtrip_includes_model_allowlist_and_is_masked(client, db_session):
    create_user(db_session, "admin", "secret", role=Role.ADMIN)
    login(client, "admin", "secret")

    save = client.put(
        f"/settings/provider-keys/{Provider.OPENAI_COMPATIBLE.value}",
        json={
            "api_key": "sk-test-SECRET1234",
            "base_url": "https://api.example.test/v1",
            "default_model": "openai/gpt-5.5",
            "available_models": ["openai/gpt-5.5", "google/gemini-3.5-flash"],
        },
    )

    assert save.status_code == 200
    payload = save.json()
    assert payload == {
        "provider": "openai_compatible",
        "base_url": "https://api.example.test/v1",
        "default_model": "openai/gpt-5.5",
        "available_models": ["openai/gpt-5.5", "google/gemini-3.5-flash"],
        "api_key_fingerprint": "openai_compatible:...1234",
        "has_key": True,
    }
    stored = db_session.query(ProviderKey).one()
    assert stored.encrypted_api_key != b"sk-test-SECRET1234"

    listing = client.get("/settings/provider-keys")
    assert listing.status_code == 200
    assert listing.json()["provider_keys"] == [payload]
    assert "SECRET" not in listing.text


def test_provider_key_management_requires_admin(client, db_session):
    create_user(db_session, "author", "secret")
    login(client, "author", "secret")

    response = client.put(
        f"/settings/provider-keys/{Provider.OPENAI_COMPATIBLE.value}",
        json={
            "api_key": "sk-test-SECRET1234",
            "base_url": "https://api.example.test/v1",
            "default_model": "openai/gpt-5.5",
            "available_models": ["openai/gpt-5.5"],
        },
    )
    listing = client.get("/settings/provider-keys")

    assert response.status_code == 403
    assert listing.status_code == 403


def test_admin_can_update_provider_key_model_settings_without_replacing_secret(client, db_session):
    create_user(db_session, "admin", "secret", role=Role.ADMIN)
    login(client, "admin", "secret")
    save = client.put(
        f"/settings/provider-keys/{Provider.OPENAI_COMPATIBLE.value}",
        json={
            "api_key": "sk-test-SECRET1234",
            "base_url": "https://api.example.test/v1",
            "default_model": "openai/gpt-5.5",
            "available_models": ["openai/gpt-5.5", "google/gemini-3.5-flash"],
        },
    )
    assert save.status_code == 200
    original = db_session.query(ProviderKey).one()
    encrypted_api_key = original.encrypted_api_key
    fingerprint = original.api_key_fingerprint

    response = client.patch(
        f"/settings/provider-keys/{Provider.OPENAI_COMPATIBLE.value}",
        json={
            "default_model": "google/gemini-3.5-flash",
            "available_models": ["google/gemini-3.5-flash", "openai/gpt-5.5"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "provider": "openai_compatible",
        "base_url": "https://api.example.test/v1",
        "default_model": "google/gemini-3.5-flash",
        "available_models": ["google/gemini-3.5-flash", "openai/gpt-5.5"],
        "api_key_fingerprint": "openai_compatible:...1234",
        "has_key": True,
    }
    db_session.refresh(original)
    assert original.encrypted_api_key == encrypted_api_key
    assert original.api_key_fingerprint == fingerprint
    assert original.base_url == "https://api.example.test/v1"
    assert db_session.query(AuditLog).filter_by(action="provider_key.updated").count() == 1


def test_provider_key_model_update_requires_saved_key(client, db_session):
    create_user(db_session, "admin", "secret", role=Role.ADMIN)
    login(client, "admin", "secret")

    response = client.patch(
        f"/settings/provider-keys/{Provider.ANTHROPIC_COMPATIBLE.value}",
        json={
            "default_model": "anthropic/claude-opus-4.7",
            "available_models": ["anthropic/claude-opus-4.7"],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Provider key is not configured"


def test_non_admin_can_read_shared_launch_model_options(client, db_session):
    admin = create_user(db_session, "admin", "secret", role=Role.ADMIN)
    create_user(db_session, "author", "secret")
    db_session.add(
        ProviderKey(
            owner_id=admin.id,
            provider=Provider.OPENAI_COMPATIBLE.value,
            base_url="https://api.example.test/v1",
            default_model="openai/gpt-5.5",
            available_models=["openai/gpt-5.5", "google/gemini-3.5-flash"],
            encrypted_api_key=encrypt_secret("sk-test-SECRET1234"),
            api_key_fingerprint="openai_compatible:...1234",
        )
    )
    db_session.commit()
    login(client, "author", "secret")

    response = client.get("/settings/provider-models")

    assert response.status_code == 200
    assert response.json() == {
        "provider_models": [
            {
                "provider": "openai_compatible",
                "default_model": "openai/gpt-5.5",
                "available_models": ["openai/gpt-5.5", "google/gemini-3.5-flash"],
                "has_key": True,
            }
        ]
    }
    assert "SECRET" not in response.text


def test_provider_key_delete_removes_row(client, db_session):
    create_user(db_session, "admin", "secret", role=Role.ADMIN)
    login(client, "admin", "secret")
    response = client.put(
        f"/settings/provider-keys/{Provider.ANTHROPIC_COMPATIBLE.value}",
        json={
            "api_key": "anthropic-secret",
            "default_model": "anthropic/claude-opus-4.7",
            "available_models": ["anthropic/claude-opus-4.7"],
        },
    )
    assert response.status_code == 200

    delete = client.delete(f"/settings/provider-keys/{Provider.ANTHROPIC_COMPATIBLE.value}")

    assert delete.status_code == 200
    assert delete.json() == {"status": "deleted"}
    assert db_session.query(ProviderKey).count() == 0


def test_provider_key_test_endpoint_checks_stored_key_without_exposing_plaintext(client, db_session):
    create_user(db_session, "admin", "secret", role=Role.ADMIN)
    login(client, "admin", "secret")
    save = client.put(
        f"/settings/provider-keys/{Provider.OPENAI_COMPATIBLE.value}",
        json={
            "api_key": "sk-test-CONNECTION1234",
            "base_url": "https://api.example.test/v1",
            "default_model": "openai/gpt-5.5",
            "available_models": ["openai/gpt-5.5"],
        },
    )
    assert save.status_code == 200

    response = client.post(f"/settings/provider-keys/{Provider.OPENAI_COMPATIBLE.value}/test")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "openai_compatible",
        "status": "ok",
        "message": "Provider key is configured and decryptable.",
        "default_model": "openai/gpt-5.5",
        "base_url": "https://api.example.test/v1",
    }
    assert "CONNECTION" not in response.text
    assert db_session.query(AuditLog).filter_by(action="provider_key.test").count() == 1


def test_provider_key_test_endpoint_requires_saved_key(client, db_session):
    create_user(db_session, "admin", "secret", role=Role.ADMIN)
    login(client, "admin", "secret")

    response = client.post(f"/settings/provider-keys/{Provider.ANTHROPIC_COMPATIBLE.value}/test")

    assert response.status_code == 404
    assert response.json()["detail"] == "Provider key is not configured"
    assert db_session.query(AuditLog).filter_by(action="provider_key.test_failure").count() == 1


def test_secret_encryption_roundtrip_and_wrong_key_rejection():
    encrypted = encrypt_secret("sk-secret", secret_key="correct-key")

    assert encrypted != b"sk-secret"
    assert decrypt_secret(encrypted, secret_key="correct-key") == "sk-secret"
    try:
        decrypt_secret(encrypted, secret_key="wrong-key")
    except InvalidToken:
        pass
    else:
        raise AssertionError("wrong key decrypted provider secret")
