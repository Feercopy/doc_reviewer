from types import SimpleNamespace
from uuid import uuid4

from app.authz.policies import (
    can_delete_analysis,
    can_manage_benchmarks,
    can_manage_skills,
    can_manage_users,
    can_publish_etalon,
    can_read_analysis,
    can_read_document,
    can_read_document_raw,
    can_read_raw_output,
)
from app.schemas.enums import Role


def actor(role: Role, actor_id=None):
    return SimpleNamespace(id=actor_id or uuid4(), role=role.value)


def test_document_owner_and_admin_can_read_document():
    owner_id = uuid4()
    owner = actor(Role.USER, owner_id)
    other = actor(Role.USER)
    admin = actor(Role.ADMIN)
    document = SimpleNamespace(owner_id=owner_id)

    assert can_read_document(owner, document)
    assert not can_read_document(other, document)
    assert can_read_document(admin, document)


def test_raw_document_access_respects_owner_admin_and_public_etalon():
    owner_id = uuid4()
    owner = actor(Role.USER, owner_id)
    other = actor(Role.USER)
    admin = actor(Role.ADMIN)
    document = SimpleNamespace(owner_id=owner_id)
    private_etalon = SimpleNamespace(raw_file_visible_to_all=False)
    public_etalon = SimpleNamespace(raw_file_visible_to_all=True)

    assert can_read_document_raw(owner, document)
    assert can_read_document_raw(admin, document)
    assert not can_read_document_raw(other, document, private_etalon)
    assert can_read_document_raw(other, document, public_etalon)


def test_analysis_read_access_follows_document_access_and_delete_access_stays_run_scoped():
    owner_id = uuid4()
    runner_id = uuid4()
    owner = actor(Role.USER, owner_id)
    runner = actor(Role.USER, runner_id)
    other = actor(Role.USER)
    admin = actor(Role.ADMIN)
    document = SimpleNamespace(owner_id=owner_id)
    analysis = SimpleNamespace(user_id=runner_id)

    assert can_read_analysis(owner, analysis, document)
    assert not can_read_analysis(other, analysis, document)
    assert can_read_analysis(admin, analysis, document)
    assert not can_delete_analysis(owner, analysis)
    assert can_delete_analysis(runner, analysis)
    assert can_delete_analysis(admin, analysis)
    assert can_read_raw_output(admin, analysis)
    assert not can_read_raw_output(owner, analysis)


def test_role_capabilities_match_policy_matrix():
    user = actor(Role.USER)
    annotator = actor(Role.ANNOTATOR)
    admin = actor(Role.ADMIN)

    assert not can_publish_etalon(user)
    assert can_publish_etalon(annotator)
    assert can_publish_etalon(admin)

    assert not can_manage_users(user)
    assert not can_manage_users(annotator)
    assert can_manage_users(admin)

    assert not can_manage_skills(user)
    assert not can_manage_skills(annotator)
    assert can_manage_skills(admin)

    assert not can_manage_benchmarks(user)
    assert not can_manage_benchmarks(annotator)
    assert can_manage_benchmarks(admin)
