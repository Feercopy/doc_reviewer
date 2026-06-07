import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.analysis import Analysis, PredictedCommentRun
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.models.skill import Skill
from app.models.base import utc_now
from app.schemas.enums import EntityStatus, Provider, RunStatus, SkillSourceType, SkillType
from app.security.secrets import decrypt_secret
from app.services.skill_sources import SkillSourceValidationError, refresh_skill_source_material
from app.services.skills import skill_source_snapshot
from jobs.run_predicted_comments import enqueue_run_predicted_comments
from providers.base import ProviderRunRequest
from providers.registry import get_provider_adapter
from results.schema_validation import parse_and_validate_json_output
from skills.prompt_renderer import render_prompt


def run_analysis(analysis_id: str, *, db: Session | None = None, enqueue_predicted_comments=None) -> None:
    owns_session = db is None
    session = db or SessionLocal()
    analysis_uuid = UUID(str(analysis_id))
    try:
        analysis = session.get(Analysis, analysis_uuid)
        if analysis is None:
            raise ValueError(f"Analysis {analysis_id} not found")
        analysis.status = RunStatus.RUNNING.value
        analysis.started_at = utc_now()
        analysis.error_message = None
        session.commit()

        document = session.get(Document, analysis.document_id)
        skill = session.get(Skill, analysis.skill_id)
        if document is None or skill is None:
            raise RuntimeError("analysis_context_missing")
        _validate_skill_source_available(skill=skill, snapshot=analysis.run_parameters.get("skill_source_snapshot"))

        provider = Provider(analysis.provider)
        provider_key = _get_provider_key(session, analysis, provider)
        if provider != Provider.HERMES and provider_key is None:
            raise RuntimeError("provider_key_missing")
        api_key = decrypt_secret(provider_key.encrypted_api_key) if provider_key else None

        schema = json.loads(_resolve_schema_path(skill.result_schema_path).read_text(encoding="utf-8"))
        request = ProviderRunRequest(
            provider=provider,
            model=analysis.model,
            api_key=api_key,
            base_url=provider_key.base_url if provider_key else None,
            prompt=render_prompt(document=document, skill=skill, response_schema=schema),
            response_schema=schema,
            run_parameters=analysis.run_parameters,
        )
        result = get_provider_adapter(provider, analysis.run_parameters).run(request)
        structured = parse_and_validate_json_output(
            structured_text=result.structured_text,
            schema_path=skill.result_schema_path,
        )

        analysis.structured_output = structured
        analysis.raw_output = result.raw_output
        analysis.verdict = structured.get("verdict")
        analysis.summary = structured.get("summary")
        analysis.input_tokens = result.input_tokens
        analysis.output_tokens = result.output_tokens
        analysis.latency_ms = result.latency_ms
        analysis.estimated_cost = result.estimated_cost
        analysis.status = RunStatus.COMPLETED.value
        analysis.completed_at = utc_now()
        session.commit()
        _create_and_enqueue_predicted_comments(
            session=session,
            analysis=analysis,
            document=document,
            enqueue=enqueue_predicted_comments or enqueue_run_predicted_comments,
        )
    except Exception as exc:
        session.rollback()
        failed = session.get(Analysis, analysis_uuid)
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


def _create_and_enqueue_predicted_comments(*, session: Session, analysis: Analysis, document: Document, enqueue) -> None:
    predicted_run_id = None
    try:
        skill = _resolve_predicted_comments_skill(session=session, document=document)
        if skill is None:
            return
        run_parameters = {
            "main_analysis_id": str(analysis.id),
            "main_analysis_skill_source_snapshot": analysis.run_parameters.get("skill_source_snapshot"),
            "document_type": document.manual_document_type or document.detected_document_type,
            "skill_source_snapshot": skill_source_snapshot(skill),
        }
        mock_result = analysis.run_parameters.get("predicted_comments_mock_provider_result")
        if mock_result is not None:
            run_parameters["mock_provider_result"] = mock_result
        predicted_run = PredictedCommentRun(
            analysis_id=analysis.id,
            skill_id=skill.id,
            skill_version=skill.version,
            provider=analysis.provider,
            model=analysis.model,
            status=RunStatus.QUEUED.value,
            run_parameters=run_parameters,
        )
        session.add(predicted_run)
        session.commit()
        predicted_run_id = predicted_run.id
        try:
            enqueue(predicted_run.id)
        except Exception as exc:
            existing_run = session.get(PredictedCommentRun, predicted_run_id)
            if existing_run is not None:
                existing_run.status = RunStatus.FAILED.value
                existing_run.error_message = f"predicted_comments_enqueue_failed:{exc}"
                existing_run.completed_at = utc_now()
                session.commit()
    except Exception as exc:
        session.rollback()
        if predicted_run_id is not None:
            existing_run = session.get(PredictedCommentRun, predicted_run_id)
            if existing_run is not None:
                existing_run.status = RunStatus.FAILED.value
                existing_run.error_message = f"predicted_comments_enqueue_failed:{exc}"
                existing_run.completed_at = utc_now()
                session.commit()
                return
        failed_run = PredictedCommentRun(
            analysis_id=analysis.id,
            skill_id=analysis.skill_id,
            skill_version=analysis.skill_version,
            provider=analysis.provider,
            model=analysis.model,
            status=RunStatus.FAILED.value,
            error_message=f"predicted_comments_enqueue_failed:{exc}",
            completed_at=utc_now(),
            run_parameters={"main_analysis_id": str(analysis.id)},
        )
        session.add(failed_run)
        session.commit()


def _resolve_predicted_comments_skill(*, session: Session, document: Document) -> Skill | None:
    document_type = document.manual_document_type or document.detected_document_type
    base_statement = select(Skill).where(
        Skill.status == EntityStatus.ACTIVE.value,
        Skill.skill_type == SkillType.PREDICTED_COMMENTS.value,
    )
    preferred = session.execute(
        base_statement.where(Skill.name == "devils_advocate_predefense").order_by(Skill.created_at.desc())
    ).scalars().first()
    if preferred and document_type in (preferred.supported_document_types or []):
        return preferred
    return session.execute(
        base_statement.where(Skill.name == "generic_predicted_comments_fallback").order_by(Skill.created_at.desc())
    ).scalars().first()
