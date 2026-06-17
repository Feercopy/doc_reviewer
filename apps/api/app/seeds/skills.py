import hashlib
import os
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.skill import Skill
from app.models.skill_source import SkillSource
from app.schemas.enums import GATE_CHALLENGER_DOCUMENT_TYPES, DocumentType, EntityStatus, SkillSourceType, SkillType

GATE_CHALLENGER_SOURCE_PATH = Path(
    os.getenv("GATE_CHALLENGER_SOURCE_PATH", "/Users/iseremenko/Projects/Gate2-challenger")
)
GATE2_BENCHMARK_DIR = Path(
    os.getenv("GATE2_BENCHMARK_DIR", str(GATE_CHALLENGER_SOURCE_PATH / "benchmark"))
)
DEVILS_ADVOCATE_SOURCE_PATH = Path(
    os.getenv("DEVILS_ADVOCATE_SOURCE_PATH", "/Users/iseremenko/Documents/Common GPTs/devils-advocate")
)
BENCHMARK_JUDGE_V2_PROMPT_PATH = "LLM-as-a-judge для оценки v2.txt"
GATE_CHALLENGER_ENTRYPOINT = "skills/gate-challenger/SKILL.md"
DEVILS_ADVOCATE_ENTRYPOINT = "ic-voting-prompt.md"
GATE_CHALLENGER_SKILL_PATH = GATE_CHALLENGER_SOURCE_PATH / GATE_CHALLENGER_ENTRYPOINT
DEVILS_ADVOCATE_PATH = DEVILS_ADVOCATE_SOURCE_PATH / DEVILS_ADVOCATE_ENTRYPOINT
DEVILS_ADVOCATE_WIKI_PATH = DEVILS_ADVOCATE_SOURCE_PATH / "wiki-ic"
GATE_CHALLENGER_REQUIRED_PATHS = [
    GATE_CHALLENGER_ENTRYPOINT,
    "skills/gate-challenger/references",
]
DEVILS_ADVOCATE_REQUIRED_PATHS = [
    DEVILS_ADVOCATE_ENTRYPOINT,
    "workflow-ic-cases.md",
    "wiki-ic/CLAUDE.md",
    "wiki-ic/schema.md",
    "wiki-ic/meta/output-format.md",
    "wiki-ic/cases",
    "wiki-ic/patterns",
    "wiki-ic/heuristics",
    "wiki-ic/domains",
    "wiki-ic/personas",
    "wiki-ic/eval",
]


def _fingerprint_path(path: Path) -> str | None:
    if not path.exists():
        return None

    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
    else:
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            digest.update(str(child.relative_to(path)).encode("utf-8"))
            digest.update(child.read_bytes())
    return digest.hexdigest()


def _git_revision(path: Path) -> str | None:
    target = path if path.is_dir() else path.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout.strip()


def _read_prompt(path: Path, fallback: str) -> str:
    return path.read_text() if path.exists() and path.is_file() else fallback


def _benchmark_judge_prompt() -> tuple[str, dict]:
    prompt_path = GATE2_BENCHMARK_DIR / BENCHMARK_JUDGE_V2_PROMPT_PATH
    fallback = "Compare analysis output with an etalon and calculate precision, recall, and F1."
    if not prompt_path.exists() or not prompt_path.is_file():
        return fallback, {"fallback": True}
    prompt_text = prompt_path.read_text(encoding="utf-8")
    return prompt_text, {
        "prompt_source_path": str(prompt_path),
        "prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        "judge_policy": "gate2_llm_as_judge_v2",
    }


def _upsert_skill(db: Session, values: dict) -> Skill:
    skill = db.execute(
        select(Skill).where(
            Skill.name == values["name"],
            Skill.version == values["version"],
            Skill.skill_type == values["skill_type"],
        )
    ).scalar_one_or_none()
    if skill is None:
        skill = Skill(**values)
        db.add(skill)
    else:
        for key, value in values.items():
            setattr(skill, key, value)
    return skill


def _upsert_skill_source(db: Session, values: dict) -> SkillSource:
    source = db.execute(select(SkillSource).where(SkillSource.slug == values["slug"])).scalar_one_or_none()
    if source is None:
        source = SkillSource(**values)
        db.add(source)
        db.flush()
    else:
        for key, value in values.items():
            setattr(source, key, value)
    return source


def seed_baseline_skills(db: Session) -> list[Skill]:
    gate_challenger_fingerprint = _fingerprint_path(GATE_CHALLENGER_SKILL_PATH)
    devils_fingerprint = _fingerprint_path(DEVILS_ADVOCATE_PATH)
    wiki_fingerprint = _fingerprint_path(DEVILS_ADVOCATE_WIKI_PATH)
    benchmark_judge_prompt, benchmark_judge_metadata = _benchmark_judge_prompt()
    gate_challenger_document_types = [item.value for item in GATE_CHALLENGER_DOCUMENT_TYPES]
    gate_source = _upsert_skill_source(
        db,
        {
            "slug": "gate-challenger",
            "display_name": "Gate Challenger",
            "source_kind": "local_git_repo",
            "local_path": str(GATE_CHALLENGER_SOURCE_PATH),
            "repo_url": None,
            "default_ref": "main",
            "entrypoint": GATE_CHALLENGER_ENTRYPOINT,
            "required_paths": GATE_CHALLENGER_REQUIRED_PATHS,
            "update_policy": "require_latest",
            "status": EntityStatus.ACTIVE.value,
        },
    )
    devils_source = _upsert_skill_source(
        db,
        {
            "slug": "devils-advocate",
            "display_name": "Devil's Advocate",
            "source_kind": "local_git_repo",
            "local_path": str(DEVILS_ADVOCATE_SOURCE_PATH),
            "repo_url": None,
            "default_ref": "main",
            "entrypoint": DEVILS_ADVOCATE_ENTRYPOINT,
            "required_paths": DEVILS_ADVOCATE_REQUIRED_PATHS,
            "update_policy": "require_latest",
            "status": EntityStatus.ACTIVE.value,
        },
    )

    skills = [
        {
            "name": "gate2_challenger_main_analysis",
            "description": "Gate Challenger main analysis skill snapshot source.",
            "version": "baseline",
            "skill_type": SkillType.MAIN_ANALYSIS.value,
            "supported_document_types": gate_challenger_document_types,
            "source_type": SkillSourceType.LOCAL_SKILL_REPO.value,
            "skill_source_id": gate_source.id,
            "source_uri": str(GATE_CHALLENGER_SKILL_PATH),
            "source_entrypoint": "SKILL.md",
            "source_revision": _git_revision(GATE_CHALLENGER_SKILL_PATH),
            "source_fingerprint": gate_challenger_fingerprint,
            "source_metadata": {},
            "prompt_text": _read_prompt(
                GATE_CHALLENGER_SKILL_PATH,
                "Gate Challenger main analysis baseline prompt.",
            ),
            "result_schema_path": "contracts/schemas/main-analysis-result.schema.json",
            "runtime_mode": "snapshot_required",
            "status": EntityStatus.ACTIVE.value,
        },
        {
            "name": "devils_advocate_predefense",
            "description": "Devil's Advocate pre-defense comments skill snapshot source.",
            "version": "baseline",
            "skill_type": SkillType.PREDICTED_COMMENTS.value,
            "supported_document_types": gate_challenger_document_types,
            "source_type": SkillSourceType.LOCAL_KNOWLEDGE_BASE.value,
            "skill_source_id": devils_source.id,
            "source_uri": str(DEVILS_ADVOCATE_PATH),
            "source_entrypoint": "ic-voting-prompt.md",
            "source_revision": _git_revision(DEVILS_ADVOCATE_PATH),
            "source_fingerprint": devils_fingerprint,
            "source_metadata": {"wiki_path": str(DEVILS_ADVOCATE_WIKI_PATH), "wiki_fingerprint": wiki_fingerprint},
            "prompt_text": _read_prompt(DEVILS_ADVOCATE_PATH, "Devil's Advocate pre-defense baseline prompt."),
            "result_schema_path": "contracts/schemas/devils-advocate-result.schema.json",
            "runtime_mode": "snapshot_required",
            "status": EntityStatus.ACTIVE.value,
        },
        {
            "name": "generic_predicted_comments_fallback",
            "description": "Fallback predicted committee comments prompt.",
            "version": "baseline",
            "skill_type": SkillType.PREDICTED_COMMENTS.value,
            "supported_document_types": [DocumentType.UNKNOWN.value],
            "source_type": SkillSourceType.INLINE_PROMPT.value,
            "source_uri": None,
            "source_entrypoint": None,
            "source_revision": None,
            "source_fingerprint": None,
            "source_metadata": {},
            "prompt_text": "Predict likely committee questions with cited anchors.",
            "result_schema_path": "contracts/schemas/predicted-comments-result.schema.json",
            "runtime_mode": "inline",
            "status": EntityStatus.ACTIVE.value,
        },
        {
            "name": "benchmark_judge",
            "description": "Baseline benchmark judge prompt.",
            "version": "baseline",
            "skill_type": SkillType.BENCHMARK_JUDGE.value,
            "supported_document_types": [DocumentType.UNKNOWN.value],
            "source_type": SkillSourceType.INLINE_PROMPT.value,
            "source_uri": None,
            "source_entrypoint": None,
            "source_revision": None,
            "source_fingerprint": None,
            "source_metadata": benchmark_judge_metadata,
            "prompt_text": benchmark_judge_prompt,
            "result_schema_path": "contracts/schemas/benchmark-judge-result.schema.json",
            "runtime_mode": "inline",
            "status": EntityStatus.ACTIVE.value,
        },
        {
            "name": "document_classifier",
            "description": "Baseline document type classifier prompt.",
            "version": "baseline",
            "skill_type": SkillType.DOCUMENT_CLASSIFIER.value,
            "supported_document_types": [*gate_challenger_document_types, DocumentType.UNKNOWN.value],
            "source_type": SkillSourceType.INLINE_PROMPT.value,
            "source_uri": None,
            "source_entrypoint": None,
            "source_revision": None,
            "source_fingerprint": None,
            "source_metadata": {},
            "prompt_text": "Classify the document into the supported Gate Challenger document type enum.",
            "result_schema_path": "contracts/schemas/main-analysis-result.schema.json",
            "runtime_mode": "inline",
            "status": EntityStatus.ACTIVE.value,
        },
    ]

    seeded = [_upsert_skill(db, values) for values in skills]
    db.commit()
    return seeded


def main() -> None:
    db = SessionLocal()
    try:
        seeded = seed_baseline_skills(db)
        print(f"baseline skills ready: {len(seeded)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
