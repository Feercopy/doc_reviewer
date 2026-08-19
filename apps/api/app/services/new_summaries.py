from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.analysis import Analysis, AnalysisCheckRun
from app.schemas.analyses import NewSummaryRead, NewSummaryVariantRead
from app.schemas.enums import RunStatus
from app.services.summary_localizations import latest_completed_ic_review
from app.services.summary_localizations import SUMMARY_LOCALIZATIONS_EXPECTED_PARAMETER


NEW_SUMMARY_KEY = "new_summary"
NEW_SUMMARY_VERSION = 1
NEW_SUMMARY_GENERATION_MODE = "new_summary_skill"
STALE_NEW_SUMMARY_AFTER = timedelta(minutes=30)


def request_new_summary(
    *,
    db: Session,
    analysis: Analysis,
    create_if_missing: bool = False,
) -> tuple[NewSummaryRead, bool]:
    analysis = db.execute(select(Analysis).where(Analysis.id == analysis.id).with_for_update()).scalar_one()
    check_run = latest_completed_ic_review(db=db, analysis_id=analysis.id)
    if analysis.status != RunStatus.COMPLETED.value or check_run is None:
        return read_new_summary(analysis), False

    response, should_enqueue = prepare_new_summary_for_check_run(
        analysis=analysis,
        check_run=check_run,
        create_if_missing=create_if_missing,
    )
    if should_enqueue:
        db.commit()
    return response, should_enqueue


def prepare_new_summary_for_check_run(
    *,
    analysis: Analysis,
    check_run: AnalysisCheckRun,
    create_if_missing: bool,
) -> tuple[NewSummaryRead, bool]:
    if analysis.status != RunStatus.COMPLETED.value or check_run.status != RunStatus.COMPLETED.value:
        return read_new_summary(analysis), False

    revision = str(check_run.id)
    state = _state(analysis)
    postprocessing_finished = (
        (check_run.run_parameters or {}).get(SUMMARY_LOCALIZATIONS_EXPECTED_PARAMETER) is True
    )
    if not postprocessing_finished:
        is_waiting_current = (
            state.get("source_revision") == revision
            and state.get("version") == NEW_SUMMARY_VERSION
            and state.get("generation_mode") == NEW_SUMMARY_GENERATION_MODE
        )
        if create_if_missing and not is_waiting_current:
            state = _empty_state(revision, status="waiting")
            _persist_state(analysis, state)
        return _read_state(analysis.id, state), False

    should_enqueue = False
    is_current = (
        state.get("source_revision") == revision
        and state.get("version") == NEW_SUMMARY_VERSION
        and state.get("generation_mode") == NEW_SUMMARY_GENERATION_MODE
    )
    if not is_current:
        if not create_if_missing:
            return _read_state(analysis.id, state), False
        state = _empty_state(revision)
        should_enqueue = True
    else:
        for language in ("ru", "en"):
            variant = state.get(language)
            if isinstance(variant, dict) and variant.get("status") == "waiting":
                state[language] = _queued_variant()
                should_enqueue = True
            elif not isinstance(variant, dict) or variant.get("status") in {None, "failed"}:
                state[language] = _queued_variant()
                should_enqueue = True
            elif variant.get("status") in {"queued", "running"} and _is_stale(variant):
                state[language] = _queued_variant()
                should_enqueue = True
    if should_enqueue:
        _persist_state(analysis, state)
    return _read_state(analysis.id, state), should_enqueue


def mark_new_summary_enqueue_failed(*, db: Session, analysis: Analysis, error_message: str) -> None:
    state = _state(analysis)
    for language in ("ru", "en"):
        variant = state.get(language)
        if isinstance(variant, dict) and variant.get("status") == "queued":
            state[language] = {**variant, "status": "failed", "error_message": error_message}
    _persist_state(analysis, state)
    db.commit()


def mark_new_summary_running(*, analysis: Analysis, revision: str, language: str) -> None:
    state = _state_for_revision(analysis=analysis, revision=revision)
    state[language] = {
        "status": "running",
        "payload": None,
        "error_message": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    _persist_state(analysis, state)


def mark_new_summary_failed(*, analysis: Analysis, revision: str, language: str, error_message: str) -> None:
    state = _state_for_revision(analysis=analysis, revision=revision)
    state[language] = {"status": "failed", "payload": None, "error_message": error_message[:1000]}
    _persist_state(analysis, state)


def persist_new_summary_variant(
    *,
    analysis: Analysis,
    revision: str,
    language: str,
    payload: dict[str, Any],
    source_fingerprint: str,
    trace_step_id: str | None,
) -> None:
    state = _state_for_revision(analysis=analysis, revision=revision)
    state[language] = {
        "status": "completed",
        "payload": payload,
        "error_message": None,
        "source_fingerprint": source_fingerprint,
        "trace_step_id": trace_step_id,
    }
    _persist_state(analysis, state)


def read_new_summary(analysis: Analysis) -> NewSummaryRead:
    return _read_state(analysis.id, _state(analysis))


def _state(analysis: Analysis) -> dict[str, Any]:
    output = analysis.structured_output or {}
    result = output.get("result") if isinstance(output, dict) else None
    state = result.get(NEW_SUMMARY_KEY) if isinstance(result, dict) else None
    return dict(state) if isinstance(state, dict) else {}


def _state_for_revision(*, analysis: Analysis, revision: str) -> dict[str, Any]:
    state = _state(analysis)
    if (
        state.get("source_revision") != revision
        or state.get("version") != NEW_SUMMARY_VERSION
        or state.get("generation_mode") != NEW_SUMMARY_GENERATION_MODE
    ):
        return _empty_state(revision)
    return dict(state)


def _empty_state(revision: str | None, *, status: str = "queued") -> dict[str, Any]:
    variant = _queued_variant() if status == "queued" else {
        "status": status,
        "payload": None,
        "error_message": None,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "version": NEW_SUMMARY_VERSION,
        "generation_mode": NEW_SUMMARY_GENERATION_MODE,
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
    return datetime.now(timezone.utc) - timestamp > STALE_NEW_SUMMARY_AFTER


def _persist_state(analysis: Analysis, state: dict[str, Any]) -> None:
    output = dict(analysis.structured_output or {})
    result = dict(output.get("result") or {})
    result[NEW_SUMMARY_KEY] = state
    output["result"] = result
    analysis.structured_output = output
    flag_modified(analysis, "structured_output")


def _read_state(analysis_id: UUID, state: dict[str, Any]) -> NewSummaryRead:
    available = (
        state.get("version") == NEW_SUMMARY_VERSION
        and state.get("generation_mode") == NEW_SUMMARY_GENERATION_MODE
    )
    return NewSummaryRead(
        analysis_id=analysis_id,
        source_revision=state.get("source_revision"),
        generation_mode=state.get("generation_mode") if available else None,
        available=available,
        ru=_variant(state.get("ru") if available else None),
        en=_variant(state.get("en") if available else None),
    )


def _variant(value: Any) -> NewSummaryVariantRead:
    item = value if isinstance(value, dict) else {}
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else None
    return NewSummaryVariantRead(
        status=str(item.get("status") or "missing"),
        payload=payload,
        error_message=item.get("error_message") if isinstance(item.get("error_message"), str) else None,
        source_fingerprint=item.get("source_fingerprint") if isinstance(item.get("source_fingerprint"), str) else None,
    )
