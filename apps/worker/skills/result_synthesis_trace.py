from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.analysis import AnalysisCheckRun, AnalysisCheckStep
from app.models.base import utc_now
from app.models.skill import Skill
from app.schemas.enums import RunStatus
from app.storage.local import LocalDocumentStorage


def start_result_synthesis_step(
    *,
    session: Session,
    check_run: AnalysisCheckRun,
    step_name: str,
    prompt: str,
    run_parameters: dict[str, Any],
    skill: Skill | None,
    fallback_skill_metadata: dict[str, Any],
) -> AnalysisCheckStep:
    step = AnalysisCheckStep(
        check_run_id=check_run.id,
        step_type="result_synthesis",
        step_name=step_name,
        status=RunStatus.RUNNING.value,
        started_at=utc_now(),
    )
    session.add(step)
    session.flush()

    storage = LocalDocumentStorage(get_settings().storage_root)
    prompt_path = storage.save_rendered_prompt(analysis_id=step.id, prompt=prompt)
    step.prompt_artifact_path = str(prompt_path)
    step.prompt_fingerprint = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    step.artifacts = [
        {
            "key": "effective_run_parameters",
            "kind": "metadata",
            "run_parameters": dict(run_parameters),
        },
        {
            "key": "skill",
            "kind": "metadata",
            "skill": _step_skill_metadata(skill=skill, fallback=fallback_skill_metadata),
        },
    ]
    session.commit()
    return step


def complete_result_synthesis_step(
    *,
    session: Session,
    step: AnalysisCheckStep,
    raw_output: str | None,
    structured_output: dict[str, Any],
    input_tokens: int | None,
    output_tokens: int | None,
    latency_ms: int | None,
    estimated_cost,
) -> None:
    step.raw_output = raw_output
    step.structured_output = structured_output
    step.input_tokens = input_tokens
    step.output_tokens = output_tokens
    step.latency_ms = latency_ms
    step.estimated_cost = estimated_cost
    step.status = RunStatus.COMPLETED.value
    step.completed_at = utc_now()
    session.commit()


def fail_result_synthesis_step(
    *,
    session: Session,
    step: AnalysisCheckStep,
    error_message: str,
    raw_output: str | None,
) -> None:
    failed_step = session.get(AnalysisCheckStep, step.id)
    if failed_step is None:
        return
    failed_step.raw_output = failed_step.raw_output or raw_output
    failed_step.status = RunStatus.FAILED.value
    failed_step.error_message = error_message
    failed_step.completed_at = utc_now()
    session.commit()


def _step_skill_metadata(*, skill: Skill | None, fallback: dict[str, Any]) -> dict[str, Any]:
    if skill is None:
        return dict(fallback)
    return {
        "id": str(skill.id),
        "name": skill.name,
        "version": skill.version,
        "skill_type": skill.skill_type,
        "source_type": skill.source_type,
        "result_schema_path": skill.result_schema_path,
    }
