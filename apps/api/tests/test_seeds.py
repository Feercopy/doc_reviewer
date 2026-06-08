from app.models.user import User
from app.models.skill_source import SkillSource
from app.schemas.enums import DocumentType, Role, UserStatus
from app.seeds.admin import ensure_admin_user
from app.seeds.skills import seed_baseline_skills
from app.security.passwords import verify_password


def test_ensure_admin_user_creates_and_updates_admin(db_session):
    user = ensure_admin_user(db_session, "admin", "first-password")

    assert user.login == "admin"
    assert user.role == Role.ADMIN.value
    assert user.status == UserStatus.ACTIVE.value
    assert verify_password("first-password", user.password_hash)

    updated = ensure_admin_user(db_session, "admin", "second-password", "Root Admin")

    assert updated.id == user.id
    assert updated.display_name == "Root Admin"
    assert verify_password("second-password", updated.password_hash)
    assert db_session.query(User).count() == 1


def test_seed_baseline_skills_is_idempotent(db_session):
    first_seed = seed_baseline_skills(db_session)
    second_seed = seed_baseline_skills(db_session)

    assert len(first_seed) == 5
    assert len(second_seed) == 5
    assert {skill.name for skill in second_seed} == {
        "gate2_challenger_main_analysis",
        "devils_advocate_predefense",
        "generic_predicted_comments_fallback",
        "benchmark_judge",
        "document_classifier",
    }


def test_seeded_gate_challenger_skill_matches_supported_document_types(db_session):
    skills = seed_baseline_skills(db_session)
    main_skill = next(skill for skill in skills if skill.name == "gate2_challenger_main_analysis")

    assert main_skill.source_uri.endswith("/skills/gate-challenger/SKILL.md")
    assert main_skill.skill_source_id is not None
    assert main_skill.supported_document_types == [
        DocumentType.GATE_2.value,
        DocumentType.STREAM_REVIEW_1.value,
        DocumentType.STREAM_REVIEW_2_PLUS.value,
        DocumentType.GATE_3.value,
    ]


def test_seed_baseline_skills_creates_external_source_registry(db_session):
    skills = seed_baseline_skills(db_session)
    gate_skill = next(skill for skill in skills if skill.name == "gate2_challenger_main_analysis")
    devils_skill = next(skill for skill in skills if skill.name == "devils_advocate_predefense")

    sources = {source.slug: source for source in db_session.query(SkillSource).all()}

    assert set(sources) == {"gate-challenger", "devils-advocate"}
    assert gate_skill.skill_source_id == sources["gate-challenger"].id
    assert devils_skill.skill_source_id == sources["devils-advocate"].id
    assert sources["gate-challenger"].entrypoint == "skills/gate-challenger/SKILL.md"
    assert "wiki-ic/cases" in sources["devils-advocate"].required_paths
