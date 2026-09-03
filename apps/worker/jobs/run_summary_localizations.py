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
from app.services.new_summaries import (
    NEW_SUMMARY_GENERATION_MODE,
    NEW_SUMMARY_VERSION,
    mark_new_summary_failed,
)
from app.services.summary_localizations import (
    SUMMARY_GENERATION_MODE,
    SUMMARY_LOCALIZATION_VERSION,
    latest_completed_ic_review,
)
from skills.summary_localization import (
    LANGUAGES,
    build_summary_generation_source,
    generate_and_persist_summary_variant,
    mark_localization_failed,
    summary_payload_fingerprint,
)
from skills.new_summary_generation import (
    LANGUAGES as NEW_SUMMARY_LANGUAGES,
    build_new_summary_source,
    generate_and_persist_new_summary_report,
    new_summary_source_fingerprint,
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
        state = ((analysis.structured_output or {}).get("result") or {}).get("summary_localizations") or {}
        new_summary_state = ((analysis.structured_output or {}).get("result") or {}).get("new_summary") or {}
        summary_requested = (
            state.get("version") == SUMMARY_LOCALIZATION_VERSION
            and state.get("generation_mode") == SUMMARY_GENERATION_MODE
            and state.get("source_revision") == str(check_run.id)
        )
        new_summary_requested = (
            new_summary_state.get("version") == NEW_SUMMARY_VERSION
            and new_summary_state.get("generation_mode") == NEW_SUMMARY_GENERATION_MODE
            and new_summary_state.get("source_revision") == str(check_run.id)
        )
        if not summary_requested and not new_summary_requested:
            worker_logger.info(
                "summary_generation_skipped",
                extra={
                    "job_type": "run_summary_localizations",
                    "entity_id": str(analysis_uuid),
                    "status": "skipped",
                    "reason": "independent_generation_not_requested",
                },
            )
            return

        runnable_statuses = {"queued", "running"}
        summary_runnable = summary_requested and any(
            (state.get(language) or {}).get("status") in runnable_statuses for language in LANGUAGES
        )
        new_summary_runnable = new_summary_requested and any(
            (new_summary_state.get(language) or {}).get("status") in runnable_statuses
            for language in NEW_SUMMARY_LANGUAGES
        )
        if not summary_runnable and not new_summary_runnable:
            worker_logger.info(
                "summary_generation_skipped",
                extra={
                    "job_type": "run_summary_localizations",
                    "entity_id": str(analysis_uuid),
                    "status": "skipped",
                    "reason": "localizations_not_queued",
                },
            )
            return

        generation_provider: tuple[Provider, str, str | None, str | None] | None = None
        failed_languages: list[str] = []
        if summary_runnable:
            source_payload = build_summary_generation_source(
                analysis=analysis,
                check_run=check_run,
            )
            source_fingerprint = summary_payload_fingerprint(source_payload)
            for target_language in LANGUAGES:
                state = ((analysis.structured_output or {}).get("result") or {}).get("summary_localizations") or {}
                target = state.get(target_language) or {}
                if target.get("status") == "completed" and target.get("source_fingerprint") == source_fingerprint:
                    continue
                if target.get("status") not in runnable_statuses:
                    continue
                if generation_provider is None:
                    generation_provider = _resolve_summary_provider(session=session, check_run=check_run)
                provider, model, api_key, base_url = generation_provider
                try:
                    generate_and_persist_summary_variant(
                        session=session,
                        analysis=analysis,
                        check_run=check_run,
                        source_payload=source_payload,
                        target_language=target_language,
                        provider=provider,
                        model=model,
                        api_key=api_key,
                        base_url=base_url,
                    )
                except Exception as exc:
                    mark_localization_failed(
                        session=session,
                        analysis=analysis,
                        check_run=check_run,
                        language=target_language,
                        error_message=str(exc),
                    )
                    failed_languages.append(f"summary_localization:{target_language}")
        if new_summary_runnable:
            try:
                new_summary_source = build_new_summary_source(
                    session=session,
                    analysis=analysis,
                    check_run=check_run,
                )
                new_summary_fingerprint = new_summary_source_fingerprint(new_summary_source)
            except Exception as exc:
                for target_language in NEW_SUMMARY_LANGUAGES:
                    mark_new_summary_failed(
                        analysis=analysis,
                        revision=str(check_run.id),
                        language=target_language,
                        error_message=str(exc),
                    )
                session.commit()
                failed_languages.extend(f"new_summary:{language}" for language in NEW_SUMMARY_LANGUAGES)
            else:
                needs_new_summary = False
                for target_language in NEW_SUMMARY_LANGUAGES:
                    new_summary_state = ((analysis.structured_output or {}).get("result") or {}).get("new_summary") or {}
                    target = new_summary_state.get(target_language) or {}
                    if target.get("status") == "completed" and target.get("source_fingerprint") == new_summary_fingerprint:
                        continue
                    if target.get("status") in runnable_statuses:
                        needs_new_summary = True
                if needs_new_summary:
                    if generation_provider is None:
                        generation_provider = _resolve_summary_provider(session=session, check_run=check_run)
                    provider, model, api_key, base_url = generation_provider
                    try:
                        generate_and_persist_new_summary_report(
                            session=session,
                            analysis=analysis,
                            check_run=check_run,
                            source_payload=new_summary_source,
                            provider=provider,
                            model=model,
                            api_key=api_key,
                            base_url=base_url,
                        )
                    except Exception as exc:
                        for target_language in NEW_SUMMARY_LANGUAGES:
                            mark_new_summary_failed(
                                analysis=analysis,
                                revision=str(check_run.id),
                                language=target_language,
                                error_message=str(exc),
                            )
                        session.commit()
                        failed_languages.extend(f"new_summary:{language}" for language in NEW_SUMMARY_LANGUAGES)
        worker_logger.info(
            "worker_job_completed",
            extra={
                "job_type": "run_summary_localizations",
                "entity_id": str(analysis_uuid),
                "status": "partial" if failed_languages else "completed",
                "failed_languages": failed_languages,
            },
        )
    except Exception as exc:
        current_analysis = session.get(Analysis, analysis_uuid)
        current_check_run = latest_completed_ic_review(db=session, analysis_id=analysis_uuid)
        if current_analysis is not None and current_check_run is not None:
            state = ((current_analysis.structured_output or {}).get("result") or {}).get("summary_localizations") or {}
            for language in LANGUAGES:
                if (state.get(language) or {}).get("status") != "completed":
                    mark_localization_failed(
                        session=session,
                        analysis=current_analysis,
                        check_run=current_check_run,
                        language=language,
                        error_message=str(exc),
                    )
            new_summary_state = ((current_analysis.structured_output or {}).get("result") or {}).get("new_summary") or {}
            for language in NEW_SUMMARY_LANGUAGES:
                if (new_summary_state.get(language) or {}).get("status") != "completed":
                    mark_new_summary_failed(
                        analysis=current_analysis,
                        revision=str(current_check_run.id),
                        language=language,
                        error_message=str(exc),
                    )
            session.commit()
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


def _resolve_summary_provider(
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
    model = _available_summary_model(
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


def _available_summary_model(*, provider_key: ProviderKey, historical_model: str | None) -> str:
    available_models = provider_key.available_models or []
    if historical_model and historical_model in available_models:
        return historical_model
    return provider_key.default_model
