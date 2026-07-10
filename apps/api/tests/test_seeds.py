import hashlib

from app.models.user import User
from app.models.skill_source import SkillSource
from app.schemas.enums import DocumentType, Role, SkillSourceType, SkillType, UserStatus
from app.seeds.admin import ensure_admin_user
from app.seeds import skills as skill_seeds
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

    assert len(first_seed) == 6
    assert len(second_seed) == 6
    assert {skill.name for skill in second_seed} == {
        "gate2_challenger_main_analysis",
        "devils_advocate_predefense",
        "ic_agentic_review",
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
    ic_review_skill = next(skill for skill in skills if skill.name == "ic_agentic_review")

    sources = {source.slug: source for source in db_session.query(SkillSource).all()}

    assert set(sources) == {"gate-challenger", "devils-advocate", "ic-agentic-review"}
    assert gate_skill.skill_source_id == sources["gate-challenger"].id
    assert devils_skill.skill_source_id == sources["devils-advocate"].id
    assert ic_review_skill.skill_source_id == sources["ic-agentic-review"].id
    assert sources["gate-challenger"].entrypoint == "skills/gate-challenger/SKILL.md"
    assert "wiki-ic/cases" in sources["devils-advocate"].required_paths
    assert sources["ic-agentic-review"].local_path == "/Users/iseremenko/Documents/IC-Agentic-Review"
    assert sources["ic-agentic-review"].entrypoint == ".claude/commands/invest-analysis.md"
    assert ".claude/agents/ic-financial-auditor.md" in sources["ic-agentic-review"].required_paths
    assert "scripts/invest/run_pipeline.py" in sources["ic-agentic-review"].required_paths


def test_seeded_ic_agentic_review_skill_matches_source_contract(db_session):
    skills = seed_baseline_skills(db_session)

    ic_review_skill = next(skill for skill in skills if skill.name == "ic_agentic_review")

    assert ic_review_skill.version == "baseline"
    assert ic_review_skill.skill_type == SkillType.ANALYSIS_CHECK.value
    assert ic_review_skill.supported_document_types == [
        DocumentType.GATE_2.value,
        DocumentType.STREAM_REVIEW_1.value,
        DocumentType.STREAM_REVIEW_2_PLUS.value,
        DocumentType.GATE_3.value,
    ]
    assert ic_review_skill.source_type == SkillSourceType.LOCAL_SKILL_REPO.value
    assert ic_review_skill.source_uri.endswith("/.claude/commands/invest-analysis.md")
    assert ic_review_skill.source_entrypoint == ".claude/commands/invest-analysis.md"
    assert ic_review_skill.result_schema_path == "contracts/schemas/ic-agentic-review-result.schema.json"
    assert ic_review_skill.runtime_mode == "snapshot_required"


def test_seeded_benchmark_judge_uses_gate2_v2_prompt_when_available(db_session, tmp_path, monkeypatch):
    benchmark_dir = tmp_path / "benchmark"
    benchmark_dir.mkdir()
    prompt_path = benchmark_dir / "LLM-as-a-judge для оценки v2.txt"
    prompt_text = "Ты — строгий LLM-as-a-judge v2."
    prompt_path.write_text(prompt_text, encoding="utf-8")
    monkeypatch.setattr(skill_seeds, "GATE2_BENCHMARK_DIR", benchmark_dir, raising=False)

    skills = seed_baseline_skills(db_session)

    judge = next(skill for skill in skills if skill.name == "benchmark_judge")
    assert judge.prompt_text == prompt_text
    assert judge.source_metadata["prompt_source_path"] == str(prompt_path)
    assert judge.source_metadata["prompt_sha256"] == hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
