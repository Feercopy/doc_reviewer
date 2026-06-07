import json
from pathlib import Path
from uuid import UUID

from redis import Redis
from rq import Queue
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.analysis import Analysis, PredictedCommentRun
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.models.skill import Skill
from app.models.base import utc_now
from app.schemas.enums import Provider, RunStatus, SkillSourceType
from app.security.secrets import decrypt_secret
from app.services.skill_sources import SkillSourceValidationError, refresh_skill_source_material
from providers.base import ProviderRunRequest
from providers.registry import get_provider_adapter
from results.schema_validation import parse_and_validate_json_output
from skills.devils_advocate_renderer import render_devils_advocate_prompt
from skills.prompt_renderer import render_prompt


ANALYSIS_QUEUE_NAME = "analysis"
RUN_PREDICTED_COMMENTS_JOB_PATH = "jobs.run_predicted_comments.run_predicted_comments"


def enqueue_run_predicted_comments(predicted_comment_run_id: UUID) -> None:
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    queue = Queue(ANALYSIS_QUEUE_NAME, connection=connection)
    queue.enqueue_call(
        func=RUN_PREDICTED_COMMENTS_JOB_PATH,
        args=(str(predicted_comment_run_id),),
        timeout=1800,
        result_ttl=3600,
    )


def run_predicted_comments(predicted_comment_run_id: str, *, db: Session | None = None) -> None:
    owns_session = db is None
    session = db or SessionLocal()
    run_uuid = UUID(str(predicted_comment_run_id))
    try:
        predicted_run = session.get(PredictedCommentRun, run_uuid)
        if predicted_run is None:
            raise ValueError(f"Predicted comment run {predicted_comment_run_id} not found")
        predicted_run.status = RunStatus.RUNNING.value
        predicted_run.started_at = utc_now()
        predicted_run.error_message = None
        session.commit()

        analysis = session.get(Analysis, predicted_run.analysis_id)
        skill = session.get(Skill, predicted_run.skill_id)
        if analysis is None or skill is None:
            raise RuntimeError("predicted_comments_context_missing")
        document = session.get(Document, analysis.document_id)
        if document is None:
            raise RuntimeError("predicted_comments_document_missing")
        _validate_skill_source_available(skill=skill, snapshot=predicted_run.run_parameters.get("skill_source_snapshot"))

        provider = Provider(predicted_run.provider)
        provider_key = _get_provider_key(session, analysis, provider)
        if provider != Provider.HERMES and provider_key is None:
            raise RuntimeError("provider_key_missing")
        api_key = decrypt_secret(provider_key.encrypted_api_key) if provider_key else None

        schema = json.loads(_resolve_schema_path(skill.result_schema_path).read_text(encoding="utf-8"))
        prompt = (
            render_devils_advocate_prompt(document=document, analysis=analysis, skill=skill, response_schema=schema)
            if skill.name == "devils_advocate_predefense"
            else render_prompt(document=document, skill=skill, response_schema=schema)
        )
        request = ProviderRunRequest(
            provider=provider,
            model=predicted_run.model,
            api_key=api_key,
            base_url=provider_key.base_url if provider_key else None,
            prompt=prompt,
            response_schema=schema,
            run_parameters=predicted_run.run_parameters,
        )
        result = get_provider_adapter(provider, predicted_run.run_parameters).run(request)
        structured = parse_and_validate_json_output(
            structured_text=result.structured_text,
            schema_path=skill.result_schema_path,
        )

        predicted_run.structured_output = structured
        predicted_run.raw_output = result.raw_output
        predicted_run.input_tokens = result.input_tokens
        predicted_run.output_tokens = result.output_tokens
        predicted_run.latency_ms = result.latency_ms
        predicted_run.estimated_cost = result.estimated_cost
        predicted_run.status = RunStatus.COMPLETED.value
        predicted_run.completed_at = utc_now()
        session.commit()
    except Exception as exc:
        session.rollback()
        failed = session.get(PredictedCommentRun, run_uuid)
        if failed is None:
            raise
        failed.status = RunStatus.FAILED.value
        failed.error_message = str(exc)
        failed.completed_at = utc_now()
        session.commit()
    finally:
        if owns_session:
            session.close()


def _get_provider_key(session: Session, analysis: Analysis, provider: Provider) -> ProviderKey | None:
    statement = select(ProviderKey).where(
        ProviderKey.owner_id == analysis.user_id,
        ProviderKey.provider == provider.value,
    )
    return session.execute(statement).scalar_one_or_none()


def _resolve_schema_path(schema_path: str) -> Path:
    return Path(__file__).resolve().parents[3] / schema_path


def _validate_skill_source_available(*, skill: Skill, snapshot: dict | None) -> None:
    if not snapshot:
        return
    source_type = snapshot.get("source_type") or skill.source_type
    if source_type == SkillSourceType.INLINE_PROMPT.value:
        return
    expected_fingerprint = snapshot.get("source_fingerprint")
    if not expected_fingerprint:
        return
    try:
        material = refresh_skill_source_material(skill)
    except SkillSourceValidationError as exc:
        raise RuntimeError("skill_source_unavailable") from exc
    if material.source_fingerprint != expected_fingerprint:
        raise RuntimeError("skill_source_unavailable")
