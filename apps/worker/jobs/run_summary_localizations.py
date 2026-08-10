from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.logging import worker_logger
from app.models.analysis import Analysis
from app.schemas.enums import Provider
from app.security.secrets import decrypt_secret
from app.services.provider_keys import get_shared_provider_key
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
        provider = Provider(check_run.provider)
        provider_key = None
        api_key = None
        base_url = None
        targets = ["ru", "en"] if source_language == "mixed" else [next(language for language in LANGUAGES if language != source_language)]
        for target_language in targets:
            state = ((analysis.structured_output or {}).get("result") or {}).get("summary_localizations") or {}
            target = state.get(target_language) or {}
            if target.get("status") == "completed" and target.get("source_fingerprint") == source_fingerprint:
                source_language = target_language
                source_payload = target["payload"]
                source_fingerprint = summary_payload_fingerprint(source_payload)
                continue
            if provider_key is None and provider != Provider.HERMES:
                provider_key = get_shared_provider_key(db=session, provider=provider)
                if provider_key is None:
                    raise RuntimeError("provider_key_missing")
                api_key = decrypt_secret(provider_key.encrypted_api_key)
                base_url = provider_key.base_url
            translated_payload = translate_and_persist_summary(
                session=session,
                analysis=analysis,
                check_run=check_run,
                source_language=source_language,
                source_payload=source_payload,
                target_language=target_language,
                provider=provider,
                model=check_run.model,
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
