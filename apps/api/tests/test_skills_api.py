from pathlib import Path
from uuid import UUID

from app.models.audit_log import AuditLog
from app.models.skill import Skill
from app.schemas.enums import EntityStatus, Role
from app.seeds.skills import seed_baseline_skills
from app.services.skill_sources import CONTRACTS_SCHEMAS_ROOT, _find_repo_root

from test_documents_upload import create_user, login


def test_skill_source_schema_root_resolves_to_existing_contracts():
    assert (CONTRACTS_SCHEMAS_ROOT / "main-analysis-result.schema.json").is_file()


def test_find_repo_root_does_not_require_fixed_parent_depth(tmp_path):
    packaged_file = tmp_path / "app" / "services" / "skill_sources.py"
    packaged_file.parent.mkdir(parents=True)
    packaged_file.write_text("# packaged layout", encoding="utf-8")

    assert _find_repo_root(packaged_file) == Path.cwd()


def test_authenticated_user_can_list_active_skills(client, db_session):
    create_user(db_session, "author", "secret")
    seed_baseline_skills(db_session)
    login(client, "author", "secret")

    response = client.get("/skills")

    assert response.status_code == 200
    names = {skill["name"] for skill in response.json()["skills"]}
    assert "gate2_challenger_main_analysis" in names
    assert "devils_advocate_predefense" in names
    gate2 = next(skill for skill in response.json()["skills"] if skill["name"] == "gate2_challenger_main_analysis")
    assert gate2["source_snapshot"]["source_uri"]
    assert gate2["result_schema_path"] == "contracts/schemas/main-analysis-result.schema.json"


def test_non_admin_cannot_create_skill_version(client, db_session, tmp_path):
    create_user(db_session, "author", "secret")
    login(client, "author", "secret")
    source = tmp_path / "SKILL.md"
    source.write_text("Analyze Gate 2 with strict evidence checks.", encoding="utf-8")

    response = client.post(
        "/admin/skills",
        json={
            "name": "custom_gate2",
            "description": "Custom Gate 2 main analysis.",
            "version": "v1",
            "skill_type": "main_analysis",
            "supported_document_types": ["gate_2"],
            "source_type": "local_skill_repo",
            "source_uri": str(tmp_path),
            "source_entrypoint": "SKILL.md",
            "prompt_text": "fallback prompt",
            "result_schema_path": "contracts/schemas/main-analysis-result.schema.json",
        },
    )

    assert response.status_code == 403


def test_admin_can_create_archive_and_read_skill_version(client, db_session, tmp_path):
    create_user(db_session, "admin", "secret", Role.ADMIN)
    login(client, "admin", "secret")
    source = tmp_path / "SKILL.md"
    source.write_text("Analyze Gate 2 with strict evidence checks.", encoding="utf-8")

    create_response = client.post(
        "/admin/skills",
        json={
            "name": "custom_gate2",
            "description": "Custom Gate 2 main analysis.",
            "version": "v1",
            "skill_type": "main_analysis",
            "supported_document_types": ["gate_2"],
            "source_type": "local_skill_repo",
            "source_uri": str(tmp_path),
            "source_entrypoint": "SKILL.md",
            "prompt_text": "fallback prompt",
            "result_schema_path": "contracts/schemas/main-analysis-result.schema.json",
            "source_metadata": {"entrypoint_label": "fixture"},
        },
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["name"] == "custom_gate2"
    assert payload["source_snapshot"]["source_fingerprint"]
    assert payload["source_snapshot"]["source_revision"] is None
    skill = db_session.get(Skill, UUID(payload["id"]))
    assert skill.prompt_text == "Analyze Gate 2 with strict evidence checks."

    list_response = client.get("/skills")
    assert list_response.status_code == 200
    assert "custom_gate2" in {item["name"] for item in list_response.json()["skills"]}

    archive_response = client.post(f"/admin/skills/{payload['id']}/archive")

    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == "archived"
    assert db_session.get(Skill, UUID(payload["id"])).status == EntityStatus.ARCHIVED.value
    assert "custom_gate2" not in {item["name"] for item in client.get("/skills").json()["skills"]}

    direct_read = client.get(f"/skills/{payload['id']}")
    assert direct_read.status_code == 200
    assert direct_read.json()["status"] == "archived"
    assert {row.action for row in db_session.query(AuditLog).all()} >= {"skill.created", "skill.archived"}


def test_admin_refresh_source_updates_prompt_and_fingerprint(client, db_session, tmp_path):
    create_user(db_session, "admin", "secret", Role.ADMIN)
    login(client, "admin", "secret")
    source = tmp_path / "SKILL.md"
    source.write_text("Initial Gate 2 instructions.", encoding="utf-8")
    create_response = client.post(
        "/admin/skills",
        json={
            "name": "refreshable_gate2",
            "description": "Refreshable Gate 2 main analysis.",
            "version": "v1",
            "skill_type": "main_analysis",
            "supported_document_types": ["gate_2"],
            "source_type": "local_skill_repo",
            "source_uri": str(tmp_path),
            "source_entrypoint": "SKILL.md",
            "prompt_text": "fallback prompt",
            "result_schema_path": "contracts/schemas/main-analysis-result.schema.json",
        },
    )
    assert create_response.status_code == 201
    original_fingerprint = create_response.json()["source_snapshot"]["source_fingerprint"]
    skill_id = create_response.json()["id"]

    source.write_text("Updated Gate 2 instructions with stronger source checks.", encoding="utf-8")
    refresh_response = client.post(f"/admin/skills/{skill_id}/refresh-source")

    assert refresh_response.status_code == 200
    refreshed = refresh_response.json()
    assert refreshed["source_snapshot"]["source_fingerprint"] != original_fingerprint
    skill = db_session.get(Skill, UUID(skill_id))
    assert skill.prompt_text == "Updated Gate 2 instructions with stronger source checks."
    assert db_session.query(AuditLog).filter_by(action="skill.source_refreshed").count() == 1


def test_admin_create_skill_rejects_schema_outside_contracts(client, db_session, tmp_path):
    create_user(db_session, "admin", "secret", Role.ADMIN)
    login(client, "admin", "secret")

    response = client.post(
        "/admin/skills",
        json={
            "name": "bad_schema_skill",
            "description": "Bad schema path.",
            "version": "v1",
            "skill_type": "main_analysis",
            "supported_document_types": ["gate_2"],
            "source_type": "inline_prompt",
            "prompt_text": "Analyze",
            "result_schema_path": "../secret.json",
        },
    )

    assert response.status_code == 400
    assert "contracts/schemas" in response.json()["detail"]
