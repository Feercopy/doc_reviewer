from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.analysis import Analysis, AnalysisCheckRun
from app.schemas.analyses import SummaryLocalizationsRead, SummaryLocalizationVariantRead
from app.schemas.enums import RunStatus


SUMMARY_LOCALIZATIONS_KEY = "summary_localizations"
SUMMARY_LOCALIZATION_VERSION = 2
SUMMARY_GENERATION_MODE = "independent"
STALE_LOCALIZATION_AFTER = timedelta(minutes=30)


def latest_completed_ic_review(*, db: Session, analysis_id: UUID) -> AnalysisCheckRun | None:
    return db.execute(
        select(AnalysisCheckRun)
        .where(
            AnalysisCheckRun.analysis_id == analysis_id,
            AnalysisCheckRun.status == RunStatus.COMPLETED.value,
        )
        .order_by(AnalysisCheckRun.created_at.desc())
    ).scalars().first()


def request_summary_localizations(
    *,
    db: Session,
    analysis: Analysis,
    create_if_missing: bool = False,
) -> tuple[SummaryLocalizationsRead, bool]:
    analysis = db.execute(select(Analysis).where(Analysis.id == analysis.id).with_for_update()).scalar_one()
    check_run = latest_completed_ic_review(db=db, analysis_id=analysis.id)
    if analysis.status != RunStatus.COMPLETED.value or check_run is None:
        return read_summary_localizations(analysis), False

    revision = str(check_run.id)
    state = _state(analysis)
    should_enqueue = False
    is_independent_generation = (
        state.get("source_revision") == revision
        and state.get("version") == SUMMARY_LOCALIZATION_VERSION
        and state.get("generation_mode") == SUMMARY_GENERATION_MODE
    )
    if not is_independent_generation:
        if not create_if_missing:
            return _read_state(analysis.id, state), False
        state = _empty_state(revision)
        should_enqueue = True
    else:
        for language in ("ru", "en"):
            variant = state.get(language)
            if not isinstance(variant, dict) or variant.get("status") in {None, "failed"}:
                state[language] = _queued_variant()
                should_enqueue = True
            elif variant.get("status") in {"queued", "running"} and _is_stale(variant):
                state[language] = _queued_variant()
                should_enqueue = True
    if should_enqueue:
        _persist_state(analysis, state)
        db.commit()
    return _read_state(analysis.id, state), should_enqueue


def mark_summary_localizations_enqueue_failed(*, db: Session, analysis: Analysis, error_message: str) -> None:
    state = _state(analysis)
    for language in ("ru", "en"):
        variant = state.get(language)
        if isinstance(variant, dict) and variant.get("status") == "queued":
            state[language] = {**variant, "status": "failed", "error_message": error_message}
    _persist_state(analysis, state)
    db.commit()


def read_summary_localizations(analysis: Analysis) -> SummaryLocalizationsRead:
    return _read_state(analysis.id, _state(analysis))


def _state(analysis: Analysis) -> dict[str, Any]:
    output = analysis.structured_output or {}
    result = output.get("result") if isinstance(output, dict) else None
    state = result.get(SUMMARY_LOCALIZATIONS_KEY) if isinstance(result, dict) else None
    return dict(state) if isinstance(state, dict) else {}


def _empty_state(revision: str | None, *, status: str = "queued") -> dict[str, Any]:
    variant = _queued_variant() if status == "queued" else {"status": status, "payload": None, "error_message": None}
    return {
        "version": SUMMARY_LOCALIZATION_VERSION,
        "generation_mode": SUMMARY_GENERATION_MODE,
        "source_revision": revision,
        "ru": dict(variant),
        "en": dict(variant),
    }


def _queued_variant() -> dict[str, Any]:
    return {
        "status": "queued",
        "payload": None,
        "error_message": None,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }


def _is_stale(variant: dict[str, Any]) -> bool:
    raw_timestamp = variant.get("started_at") or variant.get("requested_at")
    if not isinstance(raw_timestamp, str):
        return True
    try:
        timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return True
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - timestamp > STALE_LOCALIZATION_AFTER


def _persist_state(analysis: Analysis, state: dict[str, Any]) -> None:
    output = dict(analysis.structured_output or {})
    result = dict(output.get("result") or {})
    result[SUMMARY_LOCALIZATIONS_KEY] = state
    output["result"] = result
    analysis.structured_output = output
    flag_modified(analysis, "structured_output")


def _read_state(analysis_id: UUID, state: dict[str, Any]) -> SummaryLocalizationsRead:
    available = (
        state.get("version") == SUMMARY_LOCALIZATION_VERSION
        and state.get("generation_mode") == SUMMARY_GENERATION_MODE
    )
    return SummaryLocalizationsRead(
        analysis_id=analysis_id,
        source_revision=state.get("source_revision"),
        generation_mode=state.get("generation_mode") if available else None,
        available=available,
        ru=_variant(state.get("ru") if available else None),
        en=_variant(state.get("en") if available else None),
    )


def _variant(value: Any) -> SummaryLocalizationVariantRead:
    item = value if isinstance(value, dict) else {}
    return SummaryLocalizationVariantRead(
        status=str(item.get("status") or "missing"),
        payload=item.get("payload") if isinstance(item.get("payload"), dict) else None,
        error_message=item.get("error_message") if isinstance(item.get("error_message"), str) else None,
        source_language=item.get("source_language") if isinstance(item.get("source_language"), str) else None,
        source_fingerprint=item.get("source_fingerprint") if isinstance(item.get("source_fingerprint"), str) else None,
    )
