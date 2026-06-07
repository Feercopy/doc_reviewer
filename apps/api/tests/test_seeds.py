from app.models.user import User
from app.schemas.enums import Role, UserStatus
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
