from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.logging import worker_logger
from app.models.analysis import Analysis, AnalysisCheckRun
from app.models.provider_key import ProviderKey
from app.schemas.enums import Provider
from app.security.secrets import decrypt_secret
from app.services.provider_keys import get_shared_provider_key, list_shared_provider_keys
from app.services.summary_localizations import latest_completed_ic_review
from skills.summary_localization import (
    LANGUAGES,
    mark_localization_failed,
    persist_native_summary,
    summary_payload_fingerprint,
    translate_and_persist_summary,
)


def run_summary_localizations(analysis_id: str, *, db: Session | None = None) -> None:
    owns_session = db is None
    session = db or SessionLocal()
    analysis_uuid = UUID(str(analysis_id))
    target_language: str | None = None
    try:
        analysis = session.get(Analysis, analysis_uuid)
        if analysis is None or analysis.deleted_at is not None:
            return
        check_run = latest_completed_ic_review(db=session, analysis_id=analysis.id)
        if check_run is None:
            return

        source_language, source_payload, source_fingerprint = persist_native_summary(
            session=session,
            analysis=analysis,
            check_run=check_run,
        )
        translation_provider: tuple[Provider, str, str | None, str | None] | None = None
        targets = ["ru", "en"] if source_language == "mixed" else [next(language for language in LANGUAGES if language != source_language)]
        for target_language in targets:
            state = ((analysis.structured_output or {}).get("result") or {}).get("summary_localizations") or {}
            target = state.get(target_language) or {}
            if target.get("status") == "completed" and target.get("source_fingerprint") == source_fingerprint:
                source_language = target_language
                source_payload = target["payload"]
                source_fingerprint = summary_payload_fingerprint(source_payload)
                continue
            if translation_provider is None:
                translation_provider = _resolve_translation_provider(session=session, check_run=check_run)
            provider, model, api_key, base_url = translation_provider
            translated_payload = translate_and_persist_summary(
                session=session,
                analysis=analysis,
                check_run=check_run,
                source_language=source_language,
                source_payload=source_payload,
                target_language=target_language,
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
            )
            source_language = target_language
            source_payload = translated_payload
            source_fingerprint = summary_payload_fingerprint(source_payload)
        worker_logger.info(
            "worker_job_completed",
            extra={"job_type": "run_summary_localizations", "entity_id": str(analysis_uuid), "status": "completed"},
        )
    except Exception as exc:
        current_analysis = session.get(Analysis, analysis_uuid)
        current_check_run = latest_completed_ic_review(db=session, analysis_id=analysis_uuid)
        if current_analysis is not None and current_check_run is not None:
            if target_language is None:
                source_language = "en" if (current_analysis.run_parameters or {}).get("output_language") == "en" else "ru"
                target_language = "ru" if source_language == "en" else "en"
            mark_localization_failed(
                session=session,
                analysis=current_analysis,
                check_run=current_check_run,
                language=target_language,
                error_message=str(exc),
            )
        worker_logger.info(
            "worker_job_failed",
            extra={
                "job_type": "run_summary_localizations",
                "entity_id": str(analysis_uuid),
                "status": "failed",
                "error_class": exc.__class__.__name__,
            },
        )
    finally:
        if owns_session:
            session.close()


def _resolve_translation_provider(
    *,
    session: Session,
    check_run: AnalysisCheckRun,
) -> tuple[Provider, str, str | None, str | None]:
    historical_provider = Provider(check_run.provider)
    if historical_provider == Provider.HERMES and get_settings().hermes_enabled:
        return historical_provider, check_run.model, None, None

    provider_key = get_shared_provider_key(db=session, provider=historical_provider)
    if provider_key is None:
        provider_key = _fallback_provider_key(session)
    if provider_key is None:
        raise RuntimeError("provider_key_missing")

    provider = Provider(provider_key.provider)
    model = _available_translation_model(
        provider_key=provider_key,
        historical_model=check_run.model if provider == historical_provider else None,
    )
    return (
        provider,
        model,
        decrypt_secret(provider_key.encrypted_api_key),
        provider_key.base_url,
    )


def _fallback_provider_key(session: Session) -> ProviderKey | None:
    provider_keys = list_shared_provider_keys(db=session)
    return next(
        (key for key in provider_keys if key.provider == Provider.OPENAI_COMPATIBLE.value),
        provider_keys[0] if provider_keys else None,
    )


def _available_translation_model(*, provider_key: ProviderKey, historical_model: str | None) -> str:
    available_models = provider_key.available_models or []
    if historical_model and historical_model in available_models:
        return historical_model
    return provider_key.default_model
