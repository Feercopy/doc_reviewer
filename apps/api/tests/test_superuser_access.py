from uuid import UUID

from app.core.config import get_settings
from app.models.analysis import Analysis
from app.models.provider_key import ProviderKey
from app.models.skill_source import SkillSource
from app.models.superuser_owner_access import SuperuserOwnerAccess
from app.schemas.enums import Provider, Role, RunStatus
from app.security.secrets import encrypt_secret

from test_document_access import _case
from test_analyses_api import _new_summary_payload
from test_documents_upload import create_user, enqueued_parse_jobs, login, storage_root


def _switch(client, user):
    client.post("/auth/logout")
    login(client, user.login, "secret")


def test_owner_scope_is_dynamic_revocable_and_not_transitive(client, db_session, storage_root, enqueued_parse_jobs):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    owner = create_user(db_session, "owner", "secret")
    other = create_user(db_session, "other", "secret")
    superuser = create_user(db_session, "super", "secret", Role.SUPERUSER)
    document, analysis = _case(client, db_session, owner)
    analysis.structured_output = {"result": {"new_summary": {
        "version": 2,
        "generation_mode": "new_summary_skill",
        "ru": {"status": "completed", "payload": _new_summary_payload(language="ru")},
        "en": {"status": "completed", "payload": _new_summary_payload(language="en")},
    }}}
    analysis.raw_output = "internal model details"
    db_session.commit()
    _switch(client, other)
    unrelated, unrelated_analysis = _case(client, db_session, other)

    _switch(client, admin)
    grant = client.post("/admin/documents/access/batch", json={
        "items": [{"analysis_id": str(unrelated_analysis.id), "logins": [owner.login]}]
    })
    assert grant.status_code == 200
    assert client.get(f"/admin/users/{superuser.id}/owner-scope").json() == {"owner_ids": []}
    scope_url = f"/admin/users/{superuser.id}/owner-scope"
    assert client.put(scope_url, json={"owner_ids": [str(owner.id)]}).status_code == 200

    _switch(client, superuser)
    assert {row["id"] for row in client.get("/documents").json()["documents"]} == {str(document.id)}
    assert client.get(f"/documents/{document.id}").status_code == 200
    assert client.get(f"/documents/{document.id}/raw").content == b"Gate 2 MVP metrics"
    analysis_response = client.get(f"/analyses/{analysis.id}")
    assert analysis_response.status_code == 200
    assert analysis_response.json()["raw_output"] is None
    assert client.get(f"/documents/{document.id}/analyses/statuses").status_code == 200
    assert client.get(f"/analyses/{analysis.id}/new-summary/export/pdf").content.startswith(b"%PDF")
    assert client.get(f"/analyses/{analysis.id}/new-summary/export/docx").content.startswith(b"PK")
    assert client.get(f"/documents/{unrelated.id}").status_code == 404
    assert client.get(f"/analyses/{unrelated_analysis.id}").status_code == 404
    assert client.get("/admin/users").status_code == 403
    assert client.get(scope_url).status_code == 403
    assert client.put(scope_url, json={"owner_ids": []}).status_code == 403
    assert client.get("/settings/provider-keys").status_code == 403
    assert client.delete(f"/documents/{document.id}").status_code == 404
    assert client.delete(f"/analyses/{analysis.id}").status_code == 404
    assert client.patch(f"/documents/{document.id}/title", json={"title": "No"}).status_code == 404
    assert client.post(f"/documents/{document.id}/reparse").status_code == 404
    assert client.post(f"/analyses/{analysis.id}/ic-review-runs", data={"provider": "hermes", "model": "x"}).status_code == 404

    _switch(client, owner)
    future, future_analysis = _case(client, db_session, owner)
    _switch(client, superuser)
    assert {row["id"] for row in client.get("/documents").json()["documents"]} == {str(document.id), str(future.id)}
    assert client.get(f"/analyses/{future_analysis.id}").status_code == 200

    _switch(client, admin)
    assert client.put(scope_url, json={"owner_ids": []}).status_code == 200
    _switch(client, superuser)
    assert client.get("/documents").json()["documents"] == []
    assert client.get(f"/documents/{document.id}/raw").status_code == 404
    assert client.get(f"/analyses/{future_analysis.id}").status_code == 404


def test_owner_scope_validation_and_role_downgrade(client, db_session):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    owner = create_user(db_session, "owner", "secret")
    superuser = create_user(db_session, "super", "secret", Role.SUPERUSER)
    ordinary = create_user(db_session, "ordinary", "secret")
    login(client, admin.login, "secret")
    scope_url = f"/admin/users/{superuser.id}/owner-scope"
    assert client.put(scope_url, json={"owner_ids": [str(owner.id)]}).status_code == 200
    assert client.put(scope_url, json={"owner_ids": [str(owner.id), str(ordinary.id), str(superuser.id)]}).status_code == 422
    assert client.get(scope_url).json() == {"owner_ids": [str(owner.id)]}
    assert client.put(scope_url, json={"owner_ids": [str(owner.id), "00000000-0000-0000-0000-000000000001"]}).status_code == 422
    assert client.get(scope_url).json() == {"owner_ids": [str(owner.id)]}
    assert client.put(f"/admin/users/{ordinary.id}/owner-scope", json={"owner_ids": []}).status_code == 404
    assert client.patch(f"/admin/users/{superuser.id}", json={"role": "user"}).status_code == 200
    assert db_session.get(SuperuserOwnerAccess, (superuser.id, owner.id)) is None
    assert client.get(scope_url).status_code == 404


def test_superuser_can_launch_new_full_analysis_but_not_delete_it(client, db_session, storage_root, enqueued_parse_jobs, tmp_path):
    from app.main import app
    from app.routers import analyses as analyses_router

    enqueued = []
    app.dependency_overrides[analyses_router.get_run_analysis_enqueue] = lambda: lambda analysis_id: enqueued.append(analysis_id)
    try:
        source_root = tmp_path / "gate-source"
        (source_root / "references").mkdir(parents=True)
        (source_root / "SKILL.md").write_text("Gate prompt", encoding="utf-8")
        (source_root / "references" / "rubric.md").write_text("Rubric", encoding="utf-8")
        admin = create_user(db_session, "admin", "secret", Role.ADMIN)
        owner = create_user(db_session, "owner", "secret")
        superuser = create_user(db_session, "super", "secret", Role.SUPERUSER)
        viewer = create_user(db_session, "viewer", "secret")
        document, _ = _case(client, db_session, owner)
        source = db_session.query(SkillSource).filter_by(slug="gate-challenger").one()
        source.source_kind = "local_directory"
        source.local_path = str(source_root)
        source.entrypoint = "SKILL.md"
        source.required_paths = ["SKILL.md", "references"]
        db_session.add(ProviderKey(
            owner_id=admin.id,
            provider=Provider.OPENAI_COMPATIBLE.value,
            base_url=None,
            default_model="openai/gpt-5.5",
            available_models=["openai/gpt-5.5"],
            encrypted_api_key=encrypt_secret("sk-test"),
            api_key_fingerprint="openai_compatible:...test",
        ))
        db_session.commit()
        _switch(client, admin)
        assert client.put(f"/admin/users/{superuser.id}/owner-scope", json={"owner_ids": [str(owner.id)]}).status_code == 200
        _switch(client, viewer)
        denied = client.post(f"/documents/{document.id}/analyses", json={"provider": "openai_compatible", "model": "openai/gpt-5.5"})
        assert denied.status_code == 404
        _switch(client, superuser)
        created = client.post(f"/documents/{document.id}/analyses", json={
            "provider": "openai_compatible", "model": "openai/gpt-5.5",
            "run_parameters": {"launched_by_superuser": False},
        })
        assert created.status_code == 201, created.text
        analysis = db_session.get(Analysis, UUID(created.json()["id"]))
        assert analysis.user_id == superuser.id
        assert analysis.document_id == document.id
        assert analysis.run_parameters["launched_by_superuser"] is True
        assert enqueued == [analysis.id]
        assert client.delete(f"/analyses/{analysis.id}").status_code == 404
        assert client.post(f"/analyses/{analysis.id}/cancel").status_code == 404
        assert client.post(f"/analyses/{analysis.id}/new-summary").status_code == 404
        analysis.status = RunStatus.COMPLETED.value
        db_session.commit()
        _switch(client, owner)
        assert client.delete(f"/analyses/{analysis.id}").status_code == 204
    finally:
        get_settings.cache_clear()
        app.dependency_overrides.pop(analyses_router.get_run_analysis_enqueue, None)
