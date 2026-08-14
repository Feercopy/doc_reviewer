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
DEFAULT_GATE_CHALLENGER_MANAGED_REF = "3447f867987d8727cbbd16e8874c60f2b1ed07d0"
GATE_CHALLENGER_SKILL_VERSION = os.getenv("GATE_CHALLENGER_SKILL_VERSION", "stage-checklist-v2")
GATE_CHALLENGER_MANAGED_REPO_URL = os.getenv("GATE_CHALLENGER_MANAGED_REPO_URL")
GATE_CHALLENGER_MANAGED_REF = os.getenv(
    "GATE_CHALLENGER_MANAGED_REF", DEFAULT_GATE_CHALLENGER_MANAGED_REF
)
GATE2_BENCHMARK_DIR = Path(
    os.getenv("GATE2_BENCHMARK_DIR", str(GATE_CHALLENGER_SOURCE_PATH / "benchmark"))
)
DEVILS_ADVOCATE_SOURCE_PATH = Path(
    os.getenv("DEVILS_ADVOCATE_SOURCE_PATH", "/Users/iseremenko/Documents/Common GPTs/devils-advocate")
)
IC_AGENTIC_REVIEW_SOURCE_PATH = Path(
    os.getenv("IC_AGENTIC_REVIEW_SOURCE_PATH", "/Users/iseremenko/Documents/IC-Agentic-Review")
)
BENCHMARK_JUDGE_PROMPT_PATHS = (
    "LLM-as-a-judge для оценки.txt",
    "LLM-as-a-judge для оценки v2.txt",
)
RESULT_SUMMARY_SYNTHESIS_PROMPT = """You are the Result tab short-summary synthesis skill.

Combine two already-produced review sections into one concise decision summary:
1. Gate Challenger Recommendations.
2. IC Review Executive Summary / Executive brief.

Write only the final short summary. Do not introduce new facts, scores, or evidence.
Preserve the strictest decision posture when the two sources disagree.
Prefer clear business language for an investment/product defense committee.
"""
RESULT_RATIONALE_SYNTHESIS_PROMPT = """You are the Result tab rationale synthesis skill.

Combine Gate Challenger's "Почему оценка именно такая" rationale with IC Review Top findings.
Keep the output in the same business-review style and structure as Gate Challenger's rationale,
but enrich it with IC Review findings when they add evidence, risks, or data-quality constraints.
Do not introduce new facts, scores, or evidence. Return rationale_items with sources marked as
gate_challenger, ic_review, or both when both sources support the same subpoint. Return Critical
risks and Data gaps as separate lists.
"""
GATE_CHALLENGER_ENTRYPOINT = "skills/gate-challenger/SKILL.md"
DEVILS_ADVOCATE_ENTRYPOINT = "ic-voting-prompt.md"
IC_AGENTIC_REVIEW_ENTRYPOINT = ".claude/commands/invest-analysis.md"
GATE_CHALLENGER_SKILL_PATH = GATE_CHALLENGER_SOURCE_PATH / GATE_CHALLENGER_ENTRYPOINT
DEVILS_ADVOCATE_PATH = DEVILS_ADVOCATE_SOURCE_PATH / DEVILS_ADVOCATE_ENTRYPOINT
IC_AGENTIC_REVIEW_PATH = IC_AGENTIC_REVIEW_SOURCE_PATH / IC_AGENTIC_REVIEW_ENTRYPOINT
DEVILS_ADVOCATE_WIKI_PATH = DEVILS_ADVOCATE_SOURCE_PATH / "wiki-ic"
GATE_CHALLENGER_REQUIRED_PATHS = [
    GATE_CHALLENGER_ENTRYPOINT,
    "skills/gate-challenger/references",
    "skills/gate-challenger/references/progress-review-rubric.md",
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
IC_AGENTIC_REVIEW_REQUIRED_PATHS = [
    "CLAUDE.md",
    IC_AGENTIC_REVIEW_ENTRYPOINT,
    ".claude/agents/ic-financial-auditor.md",
    ".claude/agents/ic-product-analyst.md",
    ".claude/agents/ic-market-analyst.md",
    ".claude/agents/ic-web-researcher.md",
    ".claude/agents/ic-benchmark-valuation.md",
    ".claude/agents/ic-team-legal.md",
    ".claude/agents/ic-tech-dd.md",
    ".claude/agents/ic-risk-scenario.md",
    ".claude/agents/_common_rules.md",
    "scripts/invest/config.py",
    "scripts/invest/formula_auditor.py",
    "scripts/invest/json_postprocess.py",
    "scripts/invest/marker_parser.py",
    "scripts/invest/metrics_lookup.py",
    "scripts/invest/pdf_generator.py",
    "scripts/invest/excel_audit.py",
    "scripts/invest/validate_report.py",
    "scripts/invest/run_pipeline.py",
    "data/metrics_dictionary.json",
    "data/internal_codes",
    "fonts/DejaVuSans.ttf",
    "fonts/DejaVuSans-Bold.ttf",
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


def _git(path: Path, *args: str, timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        raise RuntimeError(
            f"managed Gate Challenger git command failed: {' '.join(args)}: {stderr.strip()}"
        ) from exc
    return result.stdout


def _ensure_git_checkout(path: Path, repo_url: str, ref: str) -> None:
    path = path.expanduser()
    if path.exists() and not path.is_dir():
        raise RuntimeError(f"managed Gate Challenger source path is not a directory: {path}")
    if path.exists() and any(path.iterdir()) and not (path / ".git").exists():
        raise RuntimeError(f"managed Gate Challenger source path is not a git checkout: {path}")

    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                ["git", "clone", repo_url, str(path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            stderr = getattr(exc, "stderr", "") or ""
            raise RuntimeError(f"managed Gate Challenger clone failed: {stderr.strip()}") from exc

    status = _git(path, "status", "--porcelain").strip()
    if status:
        raise RuntimeError(f"managed Gate Challenger source has local modifications: {path}")

    _git(path, "remote", "set-url", "origin", repo_url)
    _git(path, "fetch", "--prune", "--tags", "origin", timeout=180)
    if _is_commit_sha(ref):
        _git(path, "checkout", "--detach", ref)
    else:
        try:
            remote_branch = _git(
                path,
                "rev-parse",
                "--verify",
                f"refs/remotes/origin/{ref}^{{commit}}",
            ).strip()
        except RuntimeError:
            tagged_commit = _git(
                path,
                "rev-parse",
                "--verify",
                f"refs/tags/{ref}^{{commit}}",
            ).strip()
            _git(path, "checkout", "--detach", tagged_commit)
        else:
            _git(path, "checkout", "-B", ref, remote_branch)


def _is_commit_sha(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdefABCDEF" for char in value)


def _validate_required_source_paths(root: Path, required_paths: list[str]) -> None:
    root = root.resolve()
    for relative_path in required_paths:
        candidate = (root / relative_path).resolve()
        if not candidate.is_relative_to(root):
            raise RuntimeError(f"managed Gate Challenger required path escapes source root: {relative_path}")
        if not candidate.exists():
            raise RuntimeError(f"managed Gate Challenger required path is missing: {relative_path}")


def _refresh_managed_gate_challenger_source() -> None:
    if not GATE_CHALLENGER_MANAGED_REPO_URL:
        return
    _ensure_git_checkout(
        GATE_CHALLENGER_SOURCE_PATH,
        GATE_CHALLENGER_MANAGED_REPO_URL,
        GATE_CHALLENGER_MANAGED_REF,
    )
    _validate_required_source_paths(GATE_CHALLENGER_SOURCE_PATH, GATE_CHALLENGER_REQUIRED_PATHS)


def _read_prompt(path: Path, fallback: str) -> str:
    return path.read_text() if path.exists() and path.is_file() else fallback


def _benchmark_judge_prompt() -> tuple[str, dict]:
    fallback = "Compare analysis output with an etalon and calculate precision, recall, and F1."
    prompt_path = next(
        (
            GATE2_BENCHMARK_DIR / relative_path
            for relative_path in BENCHMARK_JUDGE_PROMPT_PATHS
            if (GATE2_BENCHMARK_DIR / relative_path).is_file()
        ),
        None,
    )
    if prompt_path is None:
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
    _refresh_managed_gate_challenger_source()

    gate_challenger_fingerprint = _fingerprint_path(GATE_CHALLENGER_SKILL_PATH)
    devils_fingerprint = _fingerprint_path(DEVILS_ADVOCATE_PATH)
    ic_agentic_review_fingerprint = _fingerprint_path(IC_AGENTIC_REVIEW_PATH)
    wiki_fingerprint = _fingerprint_path(DEVILS_ADVOCATE_WIKI_PATH)
    benchmark_judge_prompt, benchmark_judge_metadata = _benchmark_judge_prompt()
    gate_challenger_document_types = [item.value for item in GATE_CHALLENGER_DOCUMENT_TYPES]
    predefense_document_types = [*gate_challenger_document_types, DocumentType.UNKNOWN.value]
    gate_source = _upsert_skill_source(
        db,
        {
            "slug": "gate-challenger",
            "display_name": "Gate Challenger",
            "source_kind": "local_git_repo",
            "local_path": str(GATE_CHALLENGER_SOURCE_PATH),
            "repo_url": GATE_CHALLENGER_MANAGED_REPO_URL,
            "default_ref": GATE_CHALLENGER_MANAGED_REF if GATE_CHALLENGER_MANAGED_REPO_URL else "main",
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
    ic_agentic_review_source = _upsert_skill_source(
        db,
        {
            "slug": "ic-agentic-review",
            "display_name": "IC Agentic Review",
            "source_kind": "local_git_repo",
            "local_path": str(IC_AGENTIC_REVIEW_SOURCE_PATH),
            "repo_url": None,
            "default_ref": "main",
            "entrypoint": IC_AGENTIC_REVIEW_ENTRYPOINT,
            "required_paths": IC_AGENTIC_REVIEW_REQUIRED_PATHS,
            "update_policy": "require_latest",
            "status": EntityStatus.ACTIVE.value,
        },
    )

    skills = [
        {
            "name": "gate2_challenger_main_analysis",
            "description": "Gate Challenger main analysis skill snapshot source.",
            "version": GATE_CHALLENGER_SKILL_VERSION,
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
            "supported_document_types": predefense_document_types,
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
            "name": "ic_agentic_review",
            "description": "IC Agentic Review analysis check skill snapshot source.",
            "version": "baseline",
            "skill_type": SkillType.ANALYSIS_CHECK.value,
            "supported_document_types": gate_challenger_document_types,
            "source_type": SkillSourceType.LOCAL_SKILL_REPO.value,
            "skill_source_id": ic_agentic_review_source.id,
            "source_uri": str(IC_AGENTIC_REVIEW_PATH),
            "source_entrypoint": IC_AGENTIC_REVIEW_ENTRYPOINT,
            "source_revision": _git_revision(IC_AGENTIC_REVIEW_PATH),
            "source_fingerprint": ic_agentic_review_fingerprint,
            "source_metadata": {},
            "prompt_text": _read_prompt(
                IC_AGENTIC_REVIEW_PATH,
                "IC Agentic Review baseline analysis check prompt.",
            ),
            "result_schema_path": "contracts/schemas/ic-agentic-review-result.schema.json",
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
            "name": "result_summary_synthesis",
            "description": "Synthesizes Result tab Short Summary from Gate Challenger recommendations and IC Review executive brief.",
            "version": "baseline",
            "skill_type": SkillType.RESULT_SUMMARY.value,
            "supported_document_types": gate_challenger_document_types,
            "source_type": SkillSourceType.INLINE_PROMPT.value,
            "source_uri": None,
            "source_entrypoint": None,
            "source_revision": None,
            "source_fingerprint": None,
            "source_metadata": {"sources": ["gate_challenger_recommendations", "ic_review_executive_summary"]},
            "prompt_text": RESULT_SUMMARY_SYNTHESIS_PROMPT,
            "result_schema_path": "contracts/schemas/result-short-summary.schema.json",
            "runtime_mode": "inline",
            "status": EntityStatus.ACTIVE.value,
        },
        {
            "name": "result_rationale_synthesis",
            "description": "Synthesizes Result tab rationale from Gate Challenger rationale and IC Review top findings.",
            "version": "baseline",
            "skill_type": SkillType.RESULT_SUMMARY.value,
            "supported_document_types": gate_challenger_document_types,
            "source_type": SkillSourceType.INLINE_PROMPT.value,
            "source_uri": None,
            "source_entrypoint": None,
            "source_revision": None,
            "source_fingerprint": None,
            "source_metadata": {"sources": ["gate_challenger_rationale", "ic_review_top_findings", "critical_risks", "data_gaps"]},
            "prompt_text": RESULT_RATIONALE_SYNTHESIS_PROMPT,
            "result_schema_path": "contracts/schemas/result-rationale.schema.json",
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
    active_gate_skill = next(skill for skill in seeded if skill.name == "gate2_challenger_main_analysis")
    db.flush()
    superseded_gate_skills = db.scalars(
        select(Skill).where(
            Skill.name == active_gate_skill.name,
            Skill.skill_type == active_gate_skill.skill_type,
            Skill.id != active_gate_skill.id,
            Skill.status == EntityStatus.ACTIVE.value,
        )
    ).all()
    for skill in superseded_gate_skills:
        skill.status = EntityStatus.ARCHIVED.value
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
