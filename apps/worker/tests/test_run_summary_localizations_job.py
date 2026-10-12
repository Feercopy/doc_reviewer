from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from jsonschema import ValidationError, validate
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.models.analysis import Analysis, AnalysisCheckRun, AnalysisCheckStep
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.models.skill import Skill
from app.models.user import User
from app.schemas.enums import DocumentParseStatus, DocumentType, EntityStatus, Provider, Role, RunStatus, SkillSourceType, SkillType, UserStatus
from app.security.secrets import encrypt_secret
from app.services.new_summary_titles import clean_initiative_title, display_new_summary_title
from app.services.new_summary_traction import apply_revenue_from_dtb_fallback
from jobs.run_summary_localizations import run_summary_localizations
from providers.base import AnalysisProviderResult
from skills import new_summary_generation
from skills import summary_localization
from skills.context_relevance import decision_context_score


@pytest.fixture
def original_excerpt_limit(monkeypatch):
    monkeypatch.setattr(new_summary_generation, "SOURCE_DOCUMENT_MAX_CHARS", 16000)


def test_context_priority_does_not_penalize_selected_plan_for_separate_alternative():
    active = "Selected base scenario: Bank B is the active partner."
    alternative = "Maximum illustrative scenario: Bank A was rejected."
    historical = "Previous selected scenario: Bank A was considered."

    assert decision_context_score(active + " " + alternative) == decision_context_score(active)
    assert decision_context_score(historical) < decision_context_score(active)


def test_context_priority_downranks_dated_or_retired_selected_scenarios():
    active = "Selected scenario: Bank B is the active partner."

    for historical in (
        "Selected scenario in 2023: Bank A was the old partner.",
        "Selected base scenario from the previous period: Bank A.",
        "Selected scenario retired: Bank A.",
    ):
        assert decision_context_score(historical) < decision_context_score(active)
        assert decision_context_score(active + " " + historical) == decision_context_score(active)


@pytest.mark.usefixtures("original_excerpt_limit")
def test_new_summary_source_excerpt_keeps_selected_current_context_beyond_initial_limit():
    beginning = "Executive Summary: the initiative serves business customers.\n" + "Background only.\n" * 700
    historical = "Previous scenario: Bank A was considered for the original plan.\n"
    current = (
        "Current Defense: Progress Review.\n"
        "Selected LTM scenario: Bank B is the active partner; the maximum scenario is only illustrative.\n"
    )
    source = beginning + historical + "Unrelated appendix material.\n" * 550 + current

    excerpt = new_summary_generation._bounded_source_text(source)

    assert len(source) > new_summary_generation.SOURCE_DOCUMENT_MAX_CHARS
    assert len(excerpt) <= new_summary_generation.SOURCE_DOCUMENT_MAX_CHARS
    assert "Executive Summary" in excerpt
    assert "Selected LTM scenario: Bank B" in excerpt
    assert "Current Defense: Progress Review" in excerpt
    assert "[Source chars " in excerpt
    assert source != excerpt


@pytest.mark.usefixtures("original_excerpt_limit")
def test_new_summary_source_excerpt_prefers_active_plan_over_dated_selections():
    source = (
        "Executive Summary: case overview.\n"
        + ("Selected scenario in 2023: Bank A was the old partner.\n" + "Old option details.\n" * 50) * 35
        + "Selected scenario: Bank B is the active partner for this defense.\n"
    )

    excerpt = new_summary_generation._bounded_source_text(source)

    assert len(excerpt) <= new_summary_generation.SOURCE_DOCUMENT_MAX_CHARS
    assert "Selected scenario: Bank B is the active partner" in excerpt


def test_new_summary_source_excerpt_keeps_short_document_unchanged():
    source = "Current Defense: Gate 2.\nSelected scenario: base case."

    assert new_summary_generation._bounded_source_text(source) == source


def test_new_summary_source_excerpt_uses_100k_limit_and_keeps_late_defense():
    assert new_summary_generation.SOURCE_DOCUMENT_MAX_CHARS == 100000
    source = "Background only.\n" * 5600
    assert 90000 < len(source) < 100000
    assert new_summary_generation._bounded_source_text(source) == source

    longer_source = source + "More background.\n" * 1000 + "Current Defense: Gate 3.\n"
    excerpt = new_summary_generation._bounded_source_text(longer_source)

    assert len(longer_source) > 100000
    assert len(excerpt) <= 100000
    assert "Current Defense: Gate 3" in excerpt


@pytest.mark.usefixtures("original_excerpt_limit")
def test_new_summary_source_excerpt_reserves_late_current_defense():
    source = (
        "Executive Summary: case overview.\n"
        + "Background only.\n" * 400
        + ("Selected scenario: option under discussion.\n" + "Scenario details.\n" * 35) * 30
        + "Current Defense: Gate 3, with an active LTM base scenario.\n"
    )

    excerpt = new_summary_generation._bounded_source_text(source)

    assert len(excerpt) <= new_summary_generation.SOURCE_DOCUMENT_MAX_CHARS
    assert "Current Defense: Gate 3" in excerpt


@pytest.mark.usefixtures("original_excerpt_limit")
def test_new_summary_source_excerpt_backfills_unused_context_before_late_window():
    source = (
        "Executive Summary: case overview.\n"
        + "Plain background.\n" * 350
        + "MIDPOINT_METRIC_SENTINEL is the current measured value.\n"
        + "More plain background.\n" * 450
        + "Selected LTM scenario: base case for the active defense.\n"
    )

    excerpt = new_summary_generation._bounded_source_text(source)

    assert len(excerpt) <= new_summary_generation.SOURCE_DOCUMENT_MAX_CHARS
    assert "MIDPOINT_METRIC_SENTINEL" in excerpt
    assert "Selected LTM scenario" in excerpt


@pytest.mark.usefixtures("original_excerpt_limit")
def test_new_summary_source_excerpt_handles_dense_large_document():
    source = "Executive Summary: case overview.\n" + "scenario " * 120000
    source += "\nCurrent Defense: Gate 3 with selected LTM base scenario.\n"

    excerpt = new_summary_generation._bounded_source_text(source)

    assert len(excerpt) <= new_summary_generation.SOURCE_DOCUMENT_MAX_CHARS
    assert "Current Defense: Gate 3" in excerpt


@pytest.mark.usefixtures("original_excerpt_limit")
def test_new_summary_source_excerpt_prioritizes_selected_qualified_scenario():
    source = (
        "Executive Summary: case overview.\n"
        + "Scenario under discussion.\n" * 900
        + "Selected base scenario: the active LTM plan uses Bank B.\n"
        + "More generic scenario text.\n" * 600
        + "Выбранный базовый сценарий: план с Банком Б.\n"
    )

    excerpt = new_summary_generation._bounded_source_text(source)

    assert "Selected base scenario" in excerpt
    assert "Выбранный базовый сценарий" in excerpt


@pytest.mark.usefixtures("original_excerpt_limit")
def test_new_summary_source_excerpt_keeps_later_selection_within_large_bucket():
    source = (
        "Executive Summary: case overview.\n"
        + "Neutral appendix text.\n" * 300
        + "Previous selected scenario: Bank A was considered.\n"
        + "Neutral appendix text.\n" * 50
        + "Selected base scenario: Bank B is the active LTM partner.\n"
        + "Neutral appendix text.\n" * 100000
    )

    excerpt = new_summary_generation._bounded_source_text(source)

    assert len(excerpt) <= new_summary_generation.SOURCE_DOCUMENT_MAX_CHARS
    assert "Selected base scenario: Bank B" in excerpt


@pytest.mark.usefixtures("original_excerpt_limit")
def test_new_summary_source_excerpt_keeps_distinct_scope_in_same_large_bucket(monkeypatch):
    monkeypatch.setattr(new_summary_generation, "SOURCE_DOCUMENT_MAX_BUCKETS", 8)
    source = (
        "Executive Summary: case overview.\n"
        + "Neutral appendix text.\n" * 210
        + "Selected base scenario: Bank B is the active LTM partner.\n"
        + "Neutral appendix text.\n" * 500
        + "Current scope: only SMB customers are included.\n"
        + "Neutral appendix text.\n" * 7000
    )

    excerpt = new_summary_generation._bounded_source_text(source)

    assert len(excerpt) <= new_summary_generation.SOURCE_DOCUMENT_MAX_CHARS
    assert "Selected base scenario: Bank B" in excerpt
    assert "Current scope: only SMB customers" in excerpt


@pytest.mark.usefixtures("original_excerpt_limit")
def test_new_summary_source_excerpt_reserves_scope_among_many_selected_scenarios():
    source = (
        "Executive Summary: case overview.\n"
        + ("Selected scenario: illustrative option.\n" + "Neutral appendix text.\n" * 60) * 35
        + "Current scope: only SMB customers are included.\n"
    )

    excerpt = new_summary_generation._bounded_source_text(source)

    assert len(excerpt) <= new_summary_generation.SOURCE_DOCUMENT_MAX_CHARS
    assert "Current scope: only SMB customers" in excerpt


@pytest.mark.usefixtures("original_excerpt_limit")
def test_new_summary_source_excerpt_prioritizes_russian_current_scope():
    source = (
        "Executive Summary: case overview.\n"
        + "Selected scenario: unconfirmed option.\n" * 400
        + "Текущий охват: защита касается только TnS.\n"
    )

    excerpt = new_summary_generation._bounded_source_text(source)

    assert "Текущий охват: защита касается только TnS" in excerpt


@pytest.mark.usefixtures("original_excerpt_limit")
def test_new_summary_source_excerpt_without_context_markers_stays_bounded():
    source = "General background without decision markers.\n" * 1000

    excerpt = new_summary_generation._bounded_source_text(source)

    assert len(excerpt) <= new_summary_generation.SOURCE_DOCUMENT_MAX_CHARS
    assert excerpt.endswith("[TRUNCATED: remaining source text was omitted.]")


def test_legacy_translation_job_is_skipped_without_enabling_language_variants(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, check_run = _seed(db)
        output = dict(analysis.structured_output)
        result = dict(output["result"])
        result["summary_localizations"] = {
            "version": 1,
            "source_revision": str(check_run.id),
            "ru": {"status": "completed", "payload": {"language": "ru"}},
            "en": {"status": "queued", "payload": None},
        }
        output["result"] = result
        analysis.structured_output = output
        db.commit()

        monkeypatch.setattr(
            summary_localization,
            "get_provider_adapter",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("provider must not be called")),
        )

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        state = analysis.structured_output["result"]["summary_localizations"]
        assert state["version"] == 1
        assert state["en"]["status"] == "queued"
        assert db.query(AnalysisCheckStep).count() == 0
    finally:
        db.close()
        get_settings.cache_clear()


def test_waiting_localizations_are_not_started_by_a_delayed_job(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, _check_run = _seed(db)
        output = dict(analysis.structured_output)
        result = dict(output["result"])
        state = dict(result["summary_localizations"])
        state["ru"] = {"status": "waiting", "payload": None, "error_message": None}
        state["en"] = {"status": "waiting", "payload": None, "error_message": None}
        result["summary_localizations"] = state
        output["result"] = result
        analysis.structured_output = output
        db.commit()

        monkeypatch.setattr(
            summary_localization,
            "get_provider_adapter",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("provider must not be called")),
        )

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        state = analysis.structured_output["result"]["summary_localizations"]
        assert state["ru"]["status"] == "waiting"
        assert state["en"]["status"] == "waiting"
        assert db.query(AnalysisCheckStep).count() == 0
    finally:
        db.close()
        get_settings.cache_clear()


def test_summary_variants_are_generated_independently_without_changing_decision_data(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, check_run = _seed(db)
        source = summary_localization.build_summary_generation_source(analysis=analysis, check_run=check_run)
        assert source["short_summary"] != analysis.structured_output["result"]["short_summary"]
        assert "Gate Challenger recommendations" in source["short_summary"]
        assert "IC Review executive brief" in source["short_summary"]
        paths = summary_localization._translatable_paths(source)
        segment_ids = summary_localization._generation_plan(source, paths)[0]
        generated = {
            language: {
                segment_id: f"{language.upper()} generated {index}"
                for index, segment_id in enumerate(segment_ids)
            }
            for language in ("ru", "en")
        }
        check_run.run_parameters = {
            "output_language": "ru",
            "summary_generation_mock_provider_results": {
                language: {
                    "structured_text": json.dumps(
                        {
                            "run_mode": "independent_summary_generation",
                            "language": language,
                            "content": generated[language],
                        }
                    ),
                    "raw_output": f"raw {language} generation",
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "latency_ms": 30,
                }
                for language in ("ru", "en")
            },
        }
        db.commit()

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        variants = analysis.structured_output["result"]["summary_localizations"]
        assert variants["ru"]["status"] == "completed"
        assert variants["en"]["status"] == "completed"
        ru = variants["ru"]["payload"]
        en = variants["en"]["payload"]
        assert ru["short_summary"].startswith("RU generated")
        assert en["short_summary"].startswith("EN generated")
        assert ru["stage_checklist"][0]["label"] == "Результаты проверки гипотез из Gate 1"
        assert en["stage_checklist"][0]["label"] == "Gate 1 hypothesis validation results"
        assert en["stage_checklist"][0]["id"] == ru["stage_checklist"][0]["id"]
        assert en["stage_checklist"][0]["status"] == ru["stage_checklist"][0]["status"]
        assert en["financial_analysis"]["verdict"] == ru["financial_analysis"]["verdict"]
        assert en["financial_analysis"]["confidence"] == ru["financial_analysis"]["confidence"]
        assert en["financial_analysis"]["key_numbers"][0]["value"] == "42"
        assert en["financial_analysis"]["spreadsheet_audit"]["formula_issues_count"] == 2
    finally:
        db.close()
        get_settings.cache_clear()


def test_new_summary_variants_are_generated_from_repository_skill(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, check_run = _seed(db)
        output = dict(analysis.structured_output)
        result = dict(output["result"])
        result["summary_localizations"] = {
            "version": summary_localization.SUMMARY_LOCALIZATION_VERSION,
            "generation_mode": summary_localization.SUMMARY_GENERATION_MODE,
            "source_revision": str(check_run.id),
            "ru": {"status": "completed", "payload": {"language": "ru"}, "source_fingerprint": "legacy"},
            "en": {"status": "completed", "payload": {"language": "en"}, "source_fingerprint": "legacy"},
        }
        result["new_summary"] = {
            "version": 2,
            "generation_mode": "new_summary_skill",
            "source_revision": str(check_run.id),
            "ru": {"status": "queued", "payload": None, "error_message": None},
            "en": {"status": "queued", "payload": None, "error_message": None},
        }
        output["stage_checklist"] = [
            *output["stage_checklist"],
            {
                "id": "gate2_mvp_or_target_product",
                "label": "Описание MVP/целевого продукта",
                "status": "yellow",
                "evidence": "Описан только план MVP.",
            },
        ]
        output["result"] = result
        analysis.structured_output = output
        payload = _new_summary_report_payload(
            ru_context="Команда проверяет новый продукт.",
            en_context="The team is validating a new product.",
        )
        check_run.run_parameters = {
            "new_summary_mock_provider_result": {
                "structured_text": json.dumps(payload, ensure_ascii=False),
                "raw_output": "raw new summary bilingual",
                "input_tokens": 11,
                "output_tokens": 22,
                "latency_ms": 33,
            }
        }
        db.commit()

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        state = analysis.structured_output["result"]["new_summary"]
        assert state["ru"]["status"] == "completed", state["ru"]
        assert state["en"]["status"] == "completed", state["en"]
        assert state["ru"]["payload"]["schema_version"] == "new-summary-v8"
        assert state["en"]["payload"]["schema_version"] == "new-summary-v8"
        assert state["ru"]["payload"]["context"] == "Команда проверяет новый продукт."
        assert state["en"]["payload"]["context"] == "The team is validating a new product."
        assert state["progress"]["stage"] == "completed"
        assert state["progress"]["percent"] == 100
        assert state["ru"]["payload"]["required_elements"][0]["status"] == "нет"
        assert state["en"]["payload"]["required_elements"][0]["status"] == "нет"
        for language in ("ru", "en"):
            required = {item["id"]: item for item in state[language]["payload"]["required_elements"]}
            assert required["gate2_target_product"]["status"] == "частично подтверждено"
        assert state["ru"]["source_fingerprint"] == new_summary_generation.new_summary_source_fingerprint(
            new_summary_generation.build_new_summary_source(session=db, analysis=analysis, check_run=check_run)
        )
        steps = {
            step.step_name: step
            for step in db.query(AnalysisCheckStep).filter_by(check_run_id=check_run.id).all()
        }
        assert "new_summary_bilingual" in steps
        assert "new_summary_ru" not in steps
        assert "new_summary_en" not in steps
        skill_artifact = next(item for item in steps["new_summary_bilingual"].artifacts if item["key"] == "skill")
        assert skill_artifact["skill"]["source_path"] == "skills/new-summary/SKILL.md"
        parameters_artifact = next(
            item for item in steps["new_summary_bilingual"].artifacts if item["key"] == "effective_run_parameters"
        )
        assert parameters_artifact["run_parameters"]["response_format"] == {"type": "json_object"}
    finally:
        db.close()
        get_settings.cache_clear()


def test_progress_review_summary_is_saved_with_presentation_stage_and_current_stage_context(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, check_run = _seed(db)
        document = db.get(Document, analysis.document_id)
        document.title = "Auction - Progress Review"
        document.parsed_text = "[Page 1]\nAuction InvCom May'26 [Eng]\nCase properties & validation\n"
        document.manual_document_type = DocumentType.STREAM_REVIEW_2_PLUS.value
        output = dict(analysis.structured_output)
        output["result"] = {
            **output["result"],
            "new_summary": {
                "version": 2,
                "generation_mode": "new_summary_skill",
                "source_revision": str(check_run.id),
                "ru": {"status": "queued", "payload": None},
                "en": {"status": "queued", "payload": None},
            },
        }
        analysis.structured_output = output
        payload = _new_summary_report_payload(
            ru_context="Инициатива находится на стадии Stream Review 2+.",
            en_context="The initiative is at Stream Review 2+.",
            stage="Stream Review 2+",
        )
        check_run.run_parameters = {
            "new_summary_mock_provider_result": {
                "structured_text": json.dumps(payload, ensure_ascii=False),
                "raw_output": "raw bilingual result",
                "input_tokens": 11,
                "output_tokens": 22,
                "latency_ms": 33,
            }
        }
        db.commit()

        source = new_summary_generation.build_new_summary_source(session=db, analysis=analysis, check_run=check_run)
        assert source["document_type"] == DocumentType.STREAM_REVIEW_2_PLUS.value
        assert source["document_stage"] == "Progress Review"
        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        state = analysis.structured_output["result"]["new_summary"]
        assert state["ru"]["status"] == state["en"]["status"] == "completed", state
        assert state["ru"]["payload"]["stage"] == "Progress Review"
        assert state["en"]["payload"]["stage"] == "Progress Review"
        assert state["ru"]["payload"]["context"] == "Инициатива находится на стадии Progress Review."
        assert state["en"]["payload"]["context"] == "The initiative is at Progress Review."
    finally:
        db.close()
        get_settings.cache_clear()


def test_native_progress_review_summary_keeps_its_own_checklist_and_stage(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, check_run = _seed(db)
        document = db.get(Document, analysis.document_id)
        document.title = "Auction - Progress Review"
        document.parsed_text = "Executive Summary\nPrevious Defense: Gate 3\nCurrent Defense: Progress Review"
        document.detected_document_type = DocumentType.PROGRESS_REVIEW.value
        analysis.run_parameters = {"document_type": DocumentType.PROGRESS_REVIEW.value, "output_language": "ru"}
        output = dict(analysis.structured_output)
        output["stage_checklist"] = [
            {"id": item["id"], "label": item["label_ru"], "status": "yellow", "evidence": "Частично показано."}
            for item in new_summary_generation._new_summary_stage_checklists()["progress_review"]
        ]
        output["result"] = {
            **output["result"],
            "new_summary": {
                "version": 2, "generation_mode": "new_summary_skill", "source_revision": str(check_run.id),
                "ru": {"status": "queued", "payload": None},
                "en": {"status": "queued", "payload": None},
            },
        }
        analysis.structured_output = output
        report = _new_summary_report_payload(
            ru_context="Инициатива находится на стадии Progress Review.",
            en_context="The initiative is at Progress Review.",
            stage="Progress Review",
            required_elements=new_summary_generation._new_summary_stage_checklists()["progress_review"],
        )
        check_run.run_parameters = {
            "new_summary_mock_provider_result": {
                "structured_text": json.dumps(report, ensure_ascii=False),
                "raw_output": "raw bilingual result", "input_tokens": 11, "output_tokens": 22, "latency_ms": 33,
            }
        }
        db.commit()

        source = new_summary_generation.build_new_summary_source(session=db, analysis=analysis, check_run=check_run)
        assert source["document_type"] == DocumentType.PROGRESS_REVIEW.value
        assert source["document_stage"] == "Progress Review"
        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        state = analysis.structured_output["result"]["new_summary"]
        for language in ("ru", "en"):
            payload = state[language]["payload"]
            assert payload["stage"] == "Progress Review"
            assert [item["id"] for item in payload["required_elements"]] == [
                "progress_review_next_half_year_plan", "progress_review_plan_fact_last_half_year",
                "progress_review_stop_criteria",
            ]
            assert all(item["status"] == ("есть" if item["id"].endswith("_stop_criteria") else "частично подтверждено")
                       for item in payload["required_elements"])
    finally:
        db.close()
        get_settings.cache_clear()


def test_new_summary_generation_tolerates_optional_sections_and_stray_appendices(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, check_run = _seed(db)
        output = dict(analysis.structured_output)
        result = dict(output["result"])
        result["new_summary"] = {
            "version": 2,
            "generation_mode": "new_summary_skill",
            "source_revision": str(check_run.id),
            "ru": {"status": "queued", "payload": None, "error_message": None},
            "en": {"status": "queued", "payload": None, "error_message": None},
        }
        output["result"] = result
        analysis.structured_output = output
        payload = _new_summary_report_payload(
            ru_context="Команда проверяет новый продукт.",
            en_context="The team is validating a new product.",
        )
        payload["appendices"] = {"ignored": True}
        payload["versions"][1].pop("language")
        for version in payload["versions"]:
            version.pop("confirmed")
            version.pop("insufficiently_confirmed")
            version.pop("critical_problems")
            version.pop("other")
            version["appendices"] = [{"title": "Appendix 1", "body": "legacy free-form appendix"}]
        check_run.run_parameters = {
            "new_summary_mock_provider_result": {
                "structured_text": json.dumps(payload, ensure_ascii=False),
                "raw_output": "raw new summary with optional sections omitted",
                "latency_ms": 1,
            }
        }
        db.commit()

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        state = analysis.structured_output["result"]["new_summary"]
        assert state["ru"]["status"] == "completed", state["ru"]
        assert state["en"]["status"] == "completed", state["en"]
        assert "confirmed" not in state["ru"]["payload"]
        assert state["ru"]["payload"]["context"] == "Команда проверяет новый продукт."
        assert "insufficiently_confirmed" not in state["en"]["payload"]
        assert state["ru"]["payload"]["critical_problems"] == []
        assert "other" not in state["en"]["payload"]
        assert "appendices" not in state["ru"]["payload"]
        assert "appendices" not in state["en"]["payload"]
        assert state["progress"]["stage"] == "completed"
    finally:
        db.close()
        get_settings.cache_clear()


def test_new_summary_accepts_empty_critical_problems_without_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, check_run = _seed(db)
        output = dict(analysis.structured_output)
        result = dict(output["result"])
        result["new_summary"] = {
            "version": 2,
            "generation_mode": "new_summary_skill",
            "source_revision": str(check_run.id),
            "ru": {"status": "queued", "payload": None, "error_message": None},
            "en": {"status": "queued", "payload": None, "error_message": None},
        }
        output["result"] = result
        analysis.structured_output = output
        payload = _new_summary_report_payload(
            ru_context="Команда проверяет новый продукт.",
            en_context="The team is validating a new product.",
        )
        for version in payload["versions"]:
            version["critical_problems"] = []
        check_run.run_parameters = {
            "new_summary_mock_provider_result": {
                "structured_text": json.dumps(payload, ensure_ascii=False),
                "raw_output": "raw new summary with empty critical problems",
                "latency_ms": 1,
            },
        }
        db.commit()

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        state = analysis.structured_output["result"]["new_summary"]
        assert state["ru"]["status"] == "completed", state["ru"]
        assert state["en"]["status"] == "completed", state["en"]
        assert state["ru"]["payload"]["context"] == "Команда проверяет новый продукт."
        assert state["en"]["payload"]["critical_problems"] == []
    finally:
        db.close()
        get_settings.cache_clear()


def test_new_summary_traction_summary_filters_blank_period_values_together():
    normalized = new_summary_generation._normalize_traction_summary(
        {
            "periods": ["2025", "2027", "Total"],
            "rows": [
                {"label": "DTB Uplift (Cumul)", "values": ["1", "3", "—"]},
                {"label": "Revenue from DTB", "values": ["—", "—", "—"]},
                {"label": "Revenue non-DTB", "values": ["—", "—", "—"]},
                {"label": "Total Revenue", "values": ["—", "—", "—"]},
            ],
        },
        language="en",
    )

    assert normalized["periods"] == ["2025", "2027", "Total"]
    assert [row["label"] for row in normalized["rows"]] == [
        "DTB Uplift (Cumul)", "Revenue from DTB", "Revenue non-DTB", "Total Revenue",
    ]
    assert normalized["rows"][0]["values"] == ["1", "3", "—"]


def test_new_summary_traction_uses_annual_columns_and_labeled_dtb_h2_only():
    normalized = new_summary_generation._normalize_traction_summary(
        {"periods": ["Q3 2026", "H2 2026", "CY27", "Total"], "rows": [
            {"label": "DTB Uplift (Cumul)", "values": ["1%", "2%", "3%", "—"]},
            {"label": "Revenue from DTB", "values": ["10", "20", "30", "—"]},
            {"label": "Revenue non-DTB", "values": ["—", "—", "—", "—"]},
            {"label": "Total Revenue", "values": ["40", "50", "60", "—"], "mismatch_periods": ["CY27"]},
        ]}, language="en",
    )
    assert normalized["periods"] == ["2026", "2027", "Total"]
    assert normalized["rows"][0]["values"] == ["2% (H2 2026)", "3%", "—"]
    assert normalized["rows"][3]["values"] == ["—", "60", "—"]
    assert normalized["rows"][3]["mismatch_periods"] == ["2027"]


def test_new_summary_generated_blank_cell_records_extraction_uncertainty():
    normalized = new_summary_generation._normalize_traction_summary(
        {"periods": ["2026", "2027", "Total"], "rows": [
            {"label": "DTB Uplift (Cumul)", "values": ["—", "—", "—"]},
            {"label": "Revenue from DTB", "values": ["—", "—", "—"]},
            {"label": "Revenue non-DTB", "values": ["—", "—", "—"]},
            {"label": "Total Revenue", "values": ["10", "", "—"]},
         ]},
        language="ru",
    )
    assert normalized["rows"][3]["values"] == ["10", "—", "—"]


def test_new_summary_title_excludes_trisigma_link_annotations():
    assert display_new_summary_title("From People to People (3sigma link)") == "From People to People - AI Summary"
    assert display_new_summary_title("From People to People [3sigma link](https://example.com/case)") == "From People to People - AI Summary"
    assert display_new_summary_title("AI Summary From People to People") == "From People to People - AI Summary"
    assert clean_initiative_title("[From People to People](https://example.com/case)") == "From People to People"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Cars TRX — Progress review and IC update request", "Cars TRX"),
        ("Gate 3 - Cars TRX - ENG", "Cars TRX"),
        ("Cars TRX (Русский) - Дозапрос ресурсов", "Cars TRX"),
        ("Cars TRX _ Stream Review #1 - RU", "Cars TRX"),
        ("Gate Keeper - AI Summary", "Gate Keeper"),
        ("English Garden - AI Summary", "English Garden"),
        ("Learning English - AI Summary", "Learning English"),
        ("Progress Review - AI Summary", "Untitled initiative"),
        ("External Ad Network (inc. AdRiver) -<br>Gate 2 - AI Summary", "External Ad Network (inc. AdRiver)"),
        ("External Ad Network (inc. AdRiver) -&lt;br/&gt;Gate 2 - AI Summary", "External Ad Network (inc. AdRiver)"),
    ],
)
def test_new_summary_title_excludes_stage_and_language_annotations(source, expected):
    assert clean_initiative_title(source) == expected
    assert display_new_summary_title(source) == f"{expected} - AI Summary"


def test_new_summary_source_title_uses_filename_case_for_matching_name():
    analysis = SimpleNamespace(structured_output={})
    document = SimpleNamespace(
        parsed_text="From people to people (3sigma link)\nCurrent Defense: Stream Review 1",
        title="From People to People _ Stream Review #1",
        original_filename="From People to People _ Stream Review #1.docx",
    )
    assert new_summary_generation._initiative_title(analysis=analysis, document=document) == "From People to People"


def test_new_summary_ignores_stage_only_model_title_when_document_has_real_name():
    analysis = SimpleNamespace(structured_output={"result": {"initiative_title": "Progress Review"}})
    document = SimpleNamespace(
        parsed_text="Cars TRX - Progress Review\n",
        title="Cars TRX - Progress Review",
        original_filename="Cars TRX.pdf",
    )
    assert new_summary_generation._initiative_title(analysis=analysis, document=document) == "Cars TRX"


@pytest.mark.parametrize(
    "page_marker",
    ["[Page 1]", "Page 1", "[Page 1 of 34]", "[Страница 1]"],
)
def test_new_summary_source_title_skips_pdf_page_markers(page_marker):
    analysis = SimpleNamespace(structured_output={})
    document = SimpleNamespace(
        parsed_text=f"{page_marker}\n[Image on page 1: 9 x 9]\nCars TRX - Progress Review\n",
        title="1028159917_1cf4a5f876314a538184d6f2ee2b3b34",
        original_filename="1028159917_1cf4a5f876314a538184d6f2ee2b3b34.pdf",
    )
    assert new_summary_generation._initiative_title(analysis=analysis, document=document) == "Cars TRX"


def test_new_summary_revenue_from_dtb_fallback_requires_dtb_and_missing_non_dtb():
    def version(dtb: str, non_dtb: str, from_dtb: str = "—") -> dict:
        return {"traction_summary": {"periods": ["2026", "2027", "Total"], "rows": [
            {"label": "DTB Uplift (Cumul)", "values": [dtb, "2%" if dtb != "—" else "—", "—"]},
            {"label": "Revenue from DTB", "values": [from_dtb, "—", "—"]},
            {"label": "Revenue non-DTB", "values": [non_dtb, "—", "—"]},
            {"label": "Total Revenue", "values": ["10", "20", "30"]},
        ]}}

    output = apply_revenue_from_dtb_fallback(version("1%", "—"))
    assert output["traction_summary"]["rows"][1]["values"] == ["10", "20", "30"]

    sourced = apply_revenue_from_dtb_fallback(version("1%", "—", "8"))
    assert sourced["traction_summary"]["rows"][1]["values"] == ["8", "20", "30"]

    no_dtb = apply_revenue_from_dtb_fallback(version("—", "—"))
    assert no_dtb["traction_summary"]["rows"][1]["values"] == ["—", "—", "—"]

    has_non_dtb = apply_revenue_from_dtb_fallback(version("1%", "5"))
    assert has_non_dtb["traction_summary"]["rows"][1]["values"] == ["—", "—", "—"]


def test_new_summary_revenue_fallback_requires_dtb_for_each_period_and_total_horizon():
    version = {"traction_summary": {"periods": ["2026", "2027", "Total"], "rows": [
        {"label": "DTB Uplift (Cumul)", "values": ["1%", "—", "—"]},
        {"label": "Revenue from DTB", "values": ["—", "—", "—"]},
        {"label": "Revenue non-DTB", "values": ["—", "—", "—"]},
        {"label": "Total Revenue", "values": ["10", "20", "30"]},
    ]}}
    result = apply_revenue_from_dtb_fallback(version)
    assert result["traction_summary"]["rows"][1]["values"] == ["10", "—", "—"]


def test_new_summary_persists_clean_title_and_revenue_fallback_in_both_languages():
    checklist = new_summary_generation._new_summary_stage_checklists()["gate_2"]
    report = _new_summary_report_payload(
        ru_context="Контекст.", en_context="Context.", required_elements=checklist,
    )
    report["title"] = "AI Summary [3sigma link](https://example.com/case)"
    for version in report["versions"]:
        version["traction_summary"] = {"periods": ["2026", "Total"], "rows": [
            {"label": "DTB Uplift (Cumul)", "values": ["1%", "—"]},
            {"label": "Revenue from DTB", "values": ["—", "—"]},
            {"label": "Revenue non-DTB", "values": ["—", "—"]},
            {"label": "Total Revenue", "values": ["10", "10"]},
        ]}
    source = {
        "initiative_title": "From People to People (3sigma link)",
        "document_type": "gate_2",
        "document_stage": "Gate 2",
        "gate_challenger": {"stage_checklist": [
            {"id": item["id"], "status": "green", "evidence": "Source evidence"} for item in checklist
        ]},
    }

    normalized = new_summary_generation._validated_source_dependent_report(
        payload=report,
        source_payload=source,
        response_schema=new_summary_generation._new_summary_schema(),
    )

    assert normalized["title"] == "From People to People - AI Summary"
    for version in normalized["versions"]:
        assert version["traction_summary"]["rows"][1]["values"] == ["10", "10"]
        assert version["traction_summary"]["total_source_policy"] == "same_table_verified_total"
        assert version["traction_summary"]["total_revenue_provenance"] == {"method": "annual_sum"}


def test_new_summary_retries_old_or_partial_traction_tables():
    with pytest.raises(ValueError, match="new_summary_traction_format_mismatch"):
        new_summary_generation._normalize_traction_summary({"tables": []}, language="en")
    with pytest.raises(ValueError, match="new_summary_traction_rows_mismatch"):
        new_summary_generation._normalize_traction_summary(
            {"periods": ["2026", "Total"], "rows": [{"label": "Total Revenue", "values": ["1", "1"]}]},
            language="en",
        )


def test_new_summary_schema_accepts_one_table_with_four_metrics():
    report = _new_summary_report_payload(ru_context="Контекст.", en_context="Context.")
    report["schema_version"] = "new-summary-v8"
    report["title"] = "Case - AI Summary"
    for version in report["versions"]:
        for legacy in ("confirmed", "insufficiently_confirmed", "other"):
            version.pop(legacy)
        version["traction_summary"] = {"periods": ["2026", "2027", "Total"], "rows": [
            {"label": "DTB Uplift (Cumul)", "values": ["1%", "2%", "—"]},
            {"label": "Revenue from DTB", "values": ["1", "2", "3"]},
            {"label": "Revenue non-DTB", "values": ["4", "5", "9"]},
            {"label": "Total Revenue", "values": ["5", "7", "12"]},
        ]}
    validate(instance=report, schema=new_summary_generation._new_summary_schema())


def test_new_summary_solution_validation_detail_ignores_non_list_items():
    assert (
        new_summary_generation._normalized_required_detail(
            {"type": "solution_validation", "items": None}
        )
        is None
    )


def test_new_summary_detail_keeps_confirmed_findings_first():
    detail = new_summary_generation._normalized_required_detail({"type": "solution_validation", "items": [
        {"text": "a (Not sufficiently confirmed)", "verdict": "insufficient"},
        {"text": "b (Confirmed)", "verdict": "confirmed"},
        {"text": "c", "verdict": "insufficient"},
    ]})
    assert [item["text"] for item in detail["items"]] == ["b", "a", "c"]
    metrics = new_summary_generation._normalized_metric_binding_items([
        {"metric": "a", "binding": "insufficient", "evidence": "one"},
        {"metric": "b", "binding": "confirmed", "evidence": "two"},
    ])
    assert [item["metric"] for item in metrics] == ["b", "a"]


def test_gate2_details_are_saved_below_their_required_elements():
    checklist = new_summary_generation._new_summary_stage_checklists()["gate_2"]
    report = _new_summary_report_payload(
        ru_context="Контекст.",
        en_context="Context.",
        required_elements=checklist,
    )
    for version in report["versions"]:
        if version["language"] == "en":
            version["document_quality_percent"] = 99
        by_id = {item["id"]: item for item in version["required_elements"]}
        by_id["gate2_hypothesis_results"]["detail"] = {
            "type": "solution_validation",
            "items": [
                {"text": "Validated need", "verdict": "confirmed"},
                {"text": "Unproven growth", "verdict": "insufficient"},
            ],
        }
        by_id["gate2_metric_linkage"]["detail"] = {
            "type": "metric_binding",
            "input_metrics": [{"metric": "Activation", "binding": "confirmed", "evidence": "Measured in pilot"}],
            "output_metrics": ([{"metric": "Revenue", "binding": "confirmed", "evidence": "Measured in pilot"}]
                               if version["language"] == "en" else []),
        }
        by_id["gate2_commitments"]["detail"] = {
            "type": "next_review_plan",
            "outputs_until_next_review": ["Launch MVP"],
            "metrics_until_next_review": [{"metric": "Activation", "current": "", "next_review": "20%"}],
        }
        by_id["gate2_stop_criteria"]["detail"] = {"type": "stop_criteria", "criteria": ["Stop if pilot fails"]}
        version["required_details"] = {
            "gate2_hypothesis_results": by_id["gate2_hypothesis_results"]["detail"]
        }
        if version["language"] == "ru":
            del by_id["gate2_hypothesis_results"]["detail"]

    source_payload = {
        "document_type": "gate_2",
        "document_stage": "Gate 2",
        "gate_challenger": {
            "stage_checklist": [
                {"id": item["id"], "status": "yellow", "evidence": "Source evidence"}
                for item in checklist
            ]
        },
    }
    normalized = new_summary_generation._validated_source_dependent_report(
        payload=report,
        source_payload=source_payload,
        response_schema=new_summary_generation._new_summary_schema(),
    )

    for version in normalized["versions"]:
        elements = {item["id"]: item for item in version["required_elements"]}
        assert "required_details" not in version
        assert elements["gate2_hypothesis_results"]["status"] == "1/2"
        assert elements["gate2_hypothesis_results"]["detail"]["items"][1]["verdict"] == "insufficient"
        assert elements["gate2_metric_linkage"]["detail"]["input_metrics"][0]["metric"] == "Activation"
        assert elements["gate2_commitments"]["detail"]["metrics_until_next_review"][0]["current"] == ""
        assert elements["gate2_stop_criteria"]["detail"]["criteria"] == ["Stop if pilot fails"]
        assert "document_quality_percent" not in version


@pytest.mark.parametrize(
    ("document_type", "stage", "item_id", "detail"),
    [
        (
            "gate_1", "Gate 1", "gate1_hypotheses_with_metrics",
            {"type": "hypotheses_with_thresholds", "items": [
                {"hypothesis": "Demand exists", "confirmation_condition": "At least 20 qualified leads"}
            ]},
        ),
        (
            "stream_review_1", "Stream Review 1", "stream_review_1_solution_validation",
            {"type": "solution_validation", "items": [
                {"text": "Prototype demand", "verdict": "confirmed"}
            ]},
        ),
        (
            "stream_review_1", "Stream Review 1", "stream_review_1_input_output_metric_link",
            {"type": "metric_binding", "input_metrics": [
                {"metric": "Activation", "binding": "confirmed", "evidence": "Pilot result"}
            ], "output_metrics": []},
        ),
        (
            "stream_review_1", "Stream Review 1", "stream_review_1_half_year_plan_with_metrics",
            {"type": "next_review_plan", "outputs_until_next_review": ["Launch pilot"],
             "metrics_until_next_review": [{"metric": "Activation", "current": "", "next_review": "20%"}]},
        ),
        (
            "progress_review", "Progress Review", "progress_review_next_half_year_plan",
            {"type": "next_review_plan", "outputs_until_next_review": ["Launch pilot"],
             "metrics_until_next_review": [{"metric": "Activation", "current": "", "next_review": "20%"}]},
        ),
        (
            "stream_review_2_plus", "Stream Review 2+", "stream_review_2_plus_next_half_year_plan",
            {"type": "next_review_plan", "outputs_until_next_review": ["Launch pilot"],
             "metrics_until_next_review": [{"metric": "Activation", "current": "", "next_review": "20%"}]},
        ),
    ],
)
def test_new_stage_details_are_saved_inline_without_generic_evidence(document_type, stage, item_id, detail):
    checklist = new_summary_generation._new_summary_stage_checklists()[document_type]
    report = _new_summary_report_payload(
        ru_context="Контекст.", en_context="Context.", stage=stage, required_elements=checklist,
    )
    for version in report["versions"]:
        by_id = {item["id"]: item for item in version["required_elements"]}
        by_id[item_id]["detail"] = detail
        version["required_details"] = {item_id: detail}
        version["critical_problems"] = []
    source_payload = {
        "document_type": document_type,
        "document_stage": stage,
        "gate_challenger": {"stage_checklist": [
            {"id": item["id"], "status": "yellow", "evidence": "Source evidence"} for item in checklist
        ]},
    }
    normalized = new_summary_generation._validated_source_dependent_report(
        payload=report, source_payload=source_payload,
        response_schema=new_summary_generation._new_summary_schema(),
    )
    for version in normalized["versions"]:
        element = next(item for item in version["required_elements"] if item["id"] == item_id)
        assert element["detail"] == detail
        if item_id in new_summary_generation.DETAIL_REPLACES_EVIDENCE:
            assert "evidence" not in element
        else:
            assert element.get("evidence") == ("Source evidence" if version["language"] == "ru" else None)
        assert "required_details" not in version
        assert version["critical_problems"] == []
        assert "confirmed" not in version
        assert "insufficiently_confirmed" not in version


@pytest.mark.parametrize(
    ("item_id", "detail_type", "first_key", "second_key", "first_item", "second_item"),
    [
        (
            "progress_review_next_half_year_plan", "next_review_plan",
            "outputs_until_next_review", "metrics_until_next_review",
            "Launch pilot", {"metric": "Activation", "current": "10%", "next_review": "20%"},
        ),
        (
            "progress_review_plan_fact_last_half_year", "plan_fact",
            "launches", "metrics",
            {"output": "Launch pilot", "status": "not_completed"},
            {"metric": "Activation", "planned": "20%", "actual": "10%"},
        ),
    ],
)
@pytest.mark.parametrize(
    ("has_first", "has_second", "expected_status"),
    [
        (True, True, "есть"),
        (True, False, "частично подтверждено"),
        (False, True, "частично подтверждено"),
        (False, False, "нет"),
    ],
)
def test_progress_review_status_uses_the_two_visible_detail_groups(
    item_id, detail_type, first_key, second_key, first_item, second_item,
    has_first, has_second, expected_status,
):
    checklist = new_summary_generation._new_summary_stage_checklists()["progress_review"]
    report = _new_summary_report_payload(
        ru_context="Контекст.", en_context="Context.",
        stage="Progress Review", required_elements=checklist,
    )
    detail = {
        "type": detail_type,
        first_key: [first_item] if has_first else [],
        second_key: [second_item] if has_second else [],
    }
    for version in report["versions"]:
        item = next(element for element in version["required_elements"] if element["id"] == item_id)
        item["status"] = "есть"
        if has_first or has_second:
            item["detail"] = detail
    source_payload = {
        "document_type": "progress_review",
        "document_stage": "Progress Review",
        "gate_challenger": {"stage_checklist": [
            {"id": item["id"], "status": "green" if has_first or has_second else "red", "evidence": "Source evidence"}
            for item in checklist
        ]},
    }

    normalized = new_summary_generation._validated_source_dependent_report(
        payload=report, source_payload=source_payload,
        response_schema=new_summary_generation._new_summary_schema(),
    )

    for version in normalized["versions"]:
        element = next(item for item in version["required_elements"] if item["id"] == item_id)
        assert element["status"] == expected_status
        assert ("detail" in element) == (has_first or has_second)


def test_progress_review_missing_detail_keeps_gate_challenger_evidence_status():
    assert new_summary_generation._required_element_status(
        {"status": "yellow", "evidence": "Plan partly documented"},
        item_id="progress_review_plan_fact_last_half_year",
        generated_item={"status": "нет"},
        required_details={},
    ) == "частично подтверждено"


@pytest.mark.parametrize(
    ("has_launches", "has_metrics", "expected_status"),
    [
        (True, True, "есть"),
        (True, False, "частично подтверждено"),
        (False, True, "частично подтверждено"),
        (False, False, "нет"),
    ],
)
def test_stream_review_two_plus_plan_fact_uses_structured_groups(
    has_launches, has_metrics, expected_status,
):
    item_id = "stream_review_2_plus_plan_fact_last_half_year"
    checklist = new_summary_generation._new_summary_stage_checklists()["stream_review_2_plus"]
    report = _new_summary_report_payload(
        ru_context="Контекст.", en_context="Context.",
        stage="Stream Review 2+", required_elements=checklist,
    )
    detail = {
        "type": "plan_fact",
        "launches": [{"output": "Launch pilot", "status": "completed"}] if has_launches else [],
        "metrics": [{"metric": "Activation", "planned": "20%", "actual": "10%"}] if has_metrics else [],
    }
    for version in report["versions"]:
        item = next(element for element in version["required_elements"] if element["id"] == item_id)
        item["status"] = "есть"
        item["detail"] = detail
    source_payload = {
        "document_type": "stream_review_2_plus",
        "document_stage": "Stream Review 2+",
        "gate_challenger": {"stage_checklist": [
            {"id": item["id"], "status": "green", "evidence": "Source evidence"}
            for item in checklist
        ]},
    }

    normalized = new_summary_generation._validated_source_dependent_report(
        payload=report, source_payload=source_payload,
        response_schema=new_summary_generation._new_summary_schema(),
    )

    for version in normalized["versions"]:
        item = next(element for element in version["required_elements"] if element["id"] == item_id)
        assert item["status"] == expected_status
        assert item["detail"]["type"] == "plan_fact"


def test_stream_review_two_plus_legacy_required_detail_is_retained():
    item_id = "stream_review_2_plus_plan_fact_last_half_year"
    details = new_summary_generation._normalized_required_details({"required_details": {
        item_id: {"type": "plan_fact", "launches": [{"output": "Launch pilot", "status": "completed"}], "metrics": []},
    }})
    assert details[item_id]["launches"][0]["output"] == "Launch pilot"


def test_stream_review_two_plus_keeps_its_existing_plan_status_policy():
    assert new_summary_generation._required_element_status(
        {"status": "green"},
        item_id="stream_review_2_plus_next_half_year_plan",
        generated_item={"status": "нет"},
        required_details={"stream_review_2_plus_next_half_year_plan": {
            "type": "next_review_plan", "outputs_until_next_review": ["Launch pilot"],
            "metrics_until_next_review": [],
        }},
    ) == "есть"


def test_new_summary_schema_allows_zero_to_ten_critical_problems():
    report = _new_summary_report_payload(ru_context="Контекст.", en_context="Context.")
    report["schema_version"] = "new-summary-v8"
    report["title"] = "Case - AI Summary"
    for version in report["versions"]:
        version.pop("confirmed")
        version.pop("insufficiently_confirmed")
        version.pop("other")
        version["critical_problems"] = []
        for element in version["required_elements"]:
            element.pop("evidence", None)
        version["traction_summary"] = new_summary_generation._normalize_traction_summary(None, language=version["language"])
    schema = new_summary_generation._new_summary_schema()
    validate(instance=report, schema=schema)
    for version in report["versions"]:
        version["critical_problems"] = [
            {"issue": f"Problem {index}.", "fact": f"Source fact {index}."} for index in range(10)
        ]
        version["critical_problems"][0]["fact"] = "Earlier review projected IRR 126%. FAQ 5 now reports 77%."
    validate(instance=report, schema=schema)
    report["versions"][0]["critical_problems"][0] = "Legacy plain-text problem"
    with pytest.raises(ValidationError):
        validate(instance=report, schema=schema)
    report["versions"][0]["critical_problems"][0] = {"issue": "Problem 0."}
    with pytest.raises(ValidationError):
        validate(instance=report, schema=schema)
    report["versions"][0]["critical_problems"][0] = {"issue": "Problem 0.", "fact": "Source fact 0."}
    for removed in ("document_quality_percent", "other", "confirmed", "insufficiently_confirmed"):
        report["versions"][0][removed] = 50 if removed == "document_quality_percent" else []
        with pytest.raises(ValidationError):
            validate(instance=report, schema=schema)
        report["versions"][0].pop(removed)
    report["versions"][0]["critical_problems"].append({"issue": "Problem 11.", "fact": "Source fact 11."})
    with pytest.raises(ValidationError):
        validate(instance=report, schema=schema)


def test_new_summary_problem_issue_drops_model_markdown_bold_markers():
    report = _new_summary_report_payload(ru_context="Контекст.", en_context="Context.")
    report["versions"][0]["critical_problems"][0]["issue"] = "**Stop criteria are missing.**"
    normalized = new_summary_generation._normalize_generated_report_shell(
        payload=report, source_payload={"document_stage": "Gate 2"}
    )
    assert normalized["versions"][0]["critical_problems"][0] == {
        "issue": "Stop criteria are missing.", "fact": "The document does not define them."
    }


def test_new_summary_checklist_order_matches_updated_skill():
    checklists = new_summary_generation._new_summary_stage_checklists()
    assert [item["id"] for item in checklists["gate_3"]][-2:] == [
        "gate3_performance_vs_gate2_plan", "gate3_stop_criteria"
    ]
    assert [item["id"] for item in checklists["progress_review"]][-2:] == [
        "progress_review_plan_fact_last_half_year", "progress_review_stop_criteria"
    ]
    assert checklists["progress_review"][-1]["label_ru"].endswith("над продуктом")


def test_new_summary_v4_uses_concise_solution_checks_and_consistent_problem_status():
    checklist = new_summary_generation._new_summary_stage_checklists()["stream_review_1"]
    report = _new_summary_report_payload(
        ru_context="Контекст.", en_context="Context.", stage="Stream Review 1",
        required_elements=checklist,
    )
    for version in report["versions"]:
        elements = {item["id"]: item for item in version["required_elements"]}
        elements["stream_review_1_solution_validation"]["detail"] = {
            "type": "solution_validation", "items": [
                {"text": "Pilot", "verdict": "confirmed", "test": "Pilot with 20 users",
                 "expected_result": "10 activations", "actual_result": "12 activations"},
                {"text": "Launch", "verdict": "insufficient"},
            ],
        }
        elements["stream_review_1_confirmed_problem"]["evidence"] = "Pilot confirms the problem."
    source = {"document_type": "stream_review_1", "document_stage": "Stream Review 1",
              "gate_challenger": {"stage_checklist": [
                  {"id": item["id"], "status": "green", "evidence": "The pilot provided evidence."}
                  for item in checklist
              ]}}
    result = new_summary_generation._validated_source_dependent_report(
        payload=report, source_payload=source,
        response_schema=new_summary_generation._new_summary_schema(),
    )
    assert result["schema_version"] == "new-summary-v8"
    for version in result["versions"]:
        elements = {item["id"]: item for item in version["required_elements"]}
        assert elements["stream_review_1_confirmed_problem"]["status"] == "частично подтверждено"
        detail = elements["stream_review_1_solution_validation"]["detail"]
        assert detail["items"][0] == {"text": "Pilot", "verdict": "confirmed"}
        assert "document_quality_percent" not in version
        assert "other" not in version


def test_new_summary_required_elements_preserve_three_gate_checklist_statuses():
    expected = {
        "green": "есть",
        "yellow": "частично подтверждено",
        "red": "нет",
    }
    for source_status, summary_status in expected.items():
        assert new_summary_generation._required_element_status(
            {"status": source_status},
            item_id="gate2_target_product",
            generated_item={"status": "есть"},
            required_details={},
        ) == summary_status


def test_explicit_stop_criterion_is_present_even_when_gate_checklist_missed_it():
    assert new_summary_generation._required_element_status(
        {"status": "red"},
        item_id="progress_review_stop_criteria",
        generated_item=None,
        required_details={"progress_review_stop_criteria": {
            "type": "stop_criteria", "criteria": ["Stop after failed pilot"],
        }},
    ) == "есть"
    assert new_summary_generation._required_element_status(
        {"status": "red"},
        item_id="progress_review_stop_criteria",
        generated_item=None,
        required_details={},
    ) == "нет"


def test_edited_skill_allows_explicit_gate2_utp_and_complete_gate3_stop_criteria():
    assert new_summary_generation._required_element_status(
        {"status": "yellow"}, item_id="gate2_value_proposition",
        generated_item={"status": "есть", "evidence": "Документ явно описывает отличие продукта."},
        required_details={},
    ) == "есть"
    assert new_summary_generation._required_element_status(
        {"status": "red"}, item_id="gate2_value_proposition",
        generated_item={"status": "есть"}, required_details={},
    ) == "нет"
    assert new_summary_generation._required_element_status(
        {"status": "yellow"}, item_id="gate3_stop_criteria",
        generated_item={"status": "есть"},
        required_details={"gate3_stop_criteria": {
            "type": "stop_criteria", "criteria": ["Остановить при провале пилота"],
        }},
    ) == "есть"


def test_new_summary_hypothesis_fraction_comes_from_structured_detail_not_traffic_light():
    assert new_summary_generation._required_element_status(
        {"status": "yellow"},
        item_id="gate2_hypothesis_results",
        generated_item={"status": "2/5"},
        required_details={
            "gate2_hypothesis_results": {
                "type": "solution_validation",
                "items": [
                    {"text": "A", "verdict": "confirmed"},
                    {"text": "B", "verdict": "insufficient"},
                    {"text": "C", "verdict": "confirmed"},
                ],
            }
        },
    ) == "2/3"
    assert new_summary_generation._required_element_status(
        {"status": "red"},
        item_id="stream_review_1_solution_validation",
        generated_item={"status": "1/4"},
        required_details={},
    ) == "нет"


def test_metric_linkage_status_uses_eighty_percent_of_both_metric_groups():
    def detail(confirmed: int, insufficient: int):
        return {"type": "metric_binding", "input_metrics": [
            {"binding": "confirmed"} for _ in range(confirmed)
        ], "output_metrics": [
            {"binding": "insufficient"} for _ in range(insufficient)
        ]}

    for item_id in ("gate2_metric_linkage", "stream_review_1_input_output_metric_link"):
        assert new_summary_generation._required_element_status(
            {"status": "red"}, item_id=item_id, generated_item={"status": "нет"},
            required_details={item_id: detail(4, 1)},
        ) == "есть"
        assert new_summary_generation._required_element_status(
            {"status": "green"}, item_id=item_id, generated_item={"status": "есть"},
            required_details={item_id: detail(3, 2)},
        ) == "частично подтверждено"
        assert new_summary_generation._required_element_status(
            {"status": "green"}, item_id=item_id, generated_item={"status": "есть"},
            required_details={item_id: detail(0, 1)},
        ) == "нет"


def test_gate3_pmf_criteria_are_kept_as_inline_structured_list():
    generated = {"required_elements": [{
        "id": "gate3_pmf_criteria",
        "evidence": "This should be replaced by the criteria list.",
        "detail": {"type": "criteria_list", "criteria": ["Retention threshold", "Pilot adoption"]},
    }]}
    elements = new_summary_generation._required_elements_from_source(
        source_payload={"document_type": "gate_3", "gate_challenger": {}},
        target_language="en", generated_payload=generated, required_details={},
    )
    pmf = next(item for item in elements if item["id"] == "gate3_pmf_criteria")
    assert pmf["detail"] == {"type": "criteria_list", "criteria": ["Retention threshold", "Pilot adoption"]}
    assert "evidence" not in pmf


def test_new_summary_source_fingerprint_changes_with_skill_contract(monkeypatch):
    source_payload = {"initiative_title": "Case", "document_stage": "Gate 2"}
    monkeypatch.setattr(new_summary_generation, "_skill_text", lambda: "skill contract v1")
    monkeypatch.setattr(new_summary_generation, "_new_summary_schema", lambda: {"type": "object"})
    monkeypatch.setattr(new_summary_generation, "_new_summary_stage_checklists", lambda: {"gate_2": []})
    first = new_summary_generation.new_summary_source_fingerprint(source_payload)

    monkeypatch.setattr(new_summary_generation, "_skill_text", lambda: "skill contract v2")
    second = new_summary_generation.new_summary_source_fingerprint(source_payload)

    assert second != first


def test_new_summary_source_allows_unknown_document_type():
    db = _session()
    try:
        analysis, check_run = _seed(db)
        document = db.get(Document, analysis.document_id)
        assert document is not None
        document.detected_document_type = DocumentType.UNKNOWN.value
        analysis.run_parameters = {"document_type": DocumentType.UNKNOWN.value}
        db.commit()

        source = new_summary_generation.build_new_summary_source(
            session=db,
            analysis=analysis,
            check_run=check_run,
        )

        assert source["document_type"] == DocumentType.UNKNOWN.value
        assert source["document_stage"] == "Unknown"
    finally:
        db.close()


def test_new_summary_variants_are_generated_for_unknown_document_type(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, check_run = _seed(db)
        document = db.get(Document, analysis.document_id)
        assert document is not None
        document.detected_document_type = DocumentType.UNKNOWN.value
        analysis.run_parameters = {"document_type": DocumentType.UNKNOWN.value}
        output = dict(analysis.structured_output)
        result = dict(output["result"])
        result["new_summary"] = {
            "version": 2,
            "generation_mode": "new_summary_skill",
            "source_revision": str(check_run.id),
            "ru": {"status": "queued", "payload": None, "error_message": None},
            "en": {"status": "queued", "payload": None, "error_message": None},
        }
        output["result"] = result
        analysis.structured_output = output
        payload = _new_summary_report_payload(
            ru_context="Команда проверяет инициативу с неопределённой стадией.",
            en_context="The team is reviewing an initiative with an unknown stage.",
            stage="Unknown",
            required_elements=[
                {
                    "id": "unknown_document_type",
                    "label_ru": "Тип документа не определён автоматически",
                    "label_en": "Document type was not detected automatically",
                },
                {
                    "id": "unknown_source_materials",
                    "label_ru": "Доступны исходные материалы для анализа",
                    "label_en": "Source materials are available for analysis",
                },
            ],
        )
        for version in payload["versions"]:
            version["critical_problems"] = []
        check_run.run_parameters = {
            "new_summary_mock_provider_result": {
                "structured_text": json.dumps(payload, ensure_ascii=False),
                "raw_output": "raw new summary unknown stage",
                "latency_ms": 1,
            }
        }
        db.commit()

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        state = analysis.structured_output["result"]["new_summary"]
        assert state["ru"]["status"] == "completed", state["ru"]
        assert state["en"]["status"] == "completed", state["en"]
        assert state["ru"]["payload"]["stage"] == "Unknown"
        assert state["en"]["payload"]["stage"] == "Unknown"
        assert [item["id"] for item in state["ru"]["payload"]["required_elements"]] == [
            "unknown_document_type",
            "unknown_source_materials",
        ]
        assert state["ru"]["payload"]["critical_problems"] == []
        assert state["en"]["payload"]["critical_problems"] == []
    finally:
        db.close()
        get_settings.cache_clear()


def test_english_generation_uses_original_evidence_not_russian_variant(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, check_run = _seed(db)
        source = summary_localization.build_summary_generation_source(analysis=analysis, check_run=check_run)
        paths = summary_localization._translatable_paths(source)
        segment_ids = list(summary_localization._generation_plan(source, paths)[0])
        check_run.run_parameters = {"summary_generation_mock_provider_results": {
            language: {
                "structured_text": json.dumps(
                    {
                        "run_mode": "independent_summary_generation",
                        "language": language,
                        "content": {segment_id: f"{language.upper()} generated {index}" for index, segment_id in enumerate(segment_ids)},
                    }
                ),
                "raw_output": f"raw {language}",
                "latency_ms": 1,
            }
            for language in ("ru", "en")
        }}
        db.commit()

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        variants = analysis.structured_output["result"]["summary_localizations"]
        assert variants["ru"]["status"] == "completed"
        assert variants["ru"]["source_language"] is None
        assert variants["en"]["status"] == "completed"
        assert variants["en"]["source_language"] is None
        assert variants["ru"]["payload"]["short_summary"].startswith("RU generated")
        assert variants["en"]["payload"]["short_summary"].startswith("EN generated")
        en_step = db.query(AnalysisCheckStep).filter_by(
            check_run_id=check_run.id,
            step_name="summary_generation_en",
        ).one()
        en_prompt = Path(en_step.prompt_artifact_path).read_text(encoding="utf-8")
        assert "RU generated" not in en_prompt
        assert "Нужны данные" in en_prompt
        assert "This is an independent synthesis task, not a translation task" in en_prompt
        assert "do not use Cyrillic characters" in en_prompt
        assert "Translate ordinary Russian business and product terms by meaning" in en_prompt
        assert "otherwise transliterate them into Latin characters" in en_prompt
    finally:
        db.close()
        get_settings.cache_clear()


def test_english_generation_rewrites_only_segments_with_cyrillic(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    injected_segment_id: str | None = None
    correction_segment_ids: list[str] = []

    class LanguageQualityAdapter:
        def run(self, request):
            nonlocal injected_segment_id
            segment_ids = request.response_schema["properties"]["content"]["required"]
            language = request.response_schema["properties"]["language"]["const"]
            if "LANGUAGE QUALITY RETRY" in request.prompt:
                correction_segment_ids.extend(segment_ids)
                content = {
                    segment_id: "A five-year vertical business case with confirmed demand"
                    for segment_id in segment_ids
                }
            else:
                content = {
                    segment_id: f"Generated {language} {segment_id}"
                    for segment_id in segment_ids
                }
                if language == "en" and injected_segment_id is None:
                    injected_segment_id = segment_ids[0]
                    content[injected_segment_id] = "A five-year Вертикальный кейс with confirmed demand"
            return AnalysisProviderResult(
                structured_text=json.dumps(
                    {
                        "run_mode": "independent_summary_generation",
                        "language": language,
                        "content": content,
                    }
                ),
                raw_output="language quality generation",
                latency_ms=1,
            )

    monkeypatch.setattr(summary_localization, "get_provider_adapter", lambda *_args, **_kwargs: LanguageQualityAdapter())
    try:
        analysis, check_run = _seed(db)

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        variant = analysis.structured_output["result"]["summary_localizations"]["en"]
        assert variant["status"] == "completed"
        assert injected_segment_id is not None
        assert correction_segment_ids == [injected_segment_id]
        assert not summary_localization.CYRILLIC_PATTERN.search(
            json.dumps(variant["payload"], ensure_ascii=False)
        )
        step = db.query(AnalysisCheckStep).filter_by(
            check_run_id=check_run.id,
            step_name="summary_generation_en",
        ).one()
        assert len(json.loads(step.raw_output)) == 2
    finally:
        db.close()
        get_settings.cache_clear()


def test_english_generation_fails_when_quality_retry_still_contains_cyrillic(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()

    class PersistentlyMixedLanguageAdapter:
        def run(self, request):
            segment_ids = request.response_schema["properties"]["content"]["required"]
            language = request.response_schema["properties"]["language"]["const"]
            content = {
                segment_id: (
                    "Generated Russian summary"
                    if language == "ru"
                    else "The result still contains кейс"
                )
                for segment_id in segment_ids
            }
            return AnalysisProviderResult(
                structured_text=json.dumps(
                    {
                        "run_mode": "independent_summary_generation",
                        "language": language,
                        "content": content,
                    }
                ),
                raw_output="persistent mixed language",
                latency_ms=1,
            )

    monkeypatch.setattr(
        summary_localization,
        "get_provider_adapter",
        lambda *_args, **_kwargs: PersistentlyMixedLanguageAdapter(),
    )
    try:
        analysis, check_run = _seed(db)

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        variants = analysis.structured_output["result"]["summary_localizations"]
        assert variants["ru"]["status"] == "completed"
        assert variants["en"]["status"] == "failed"
        assert variants["en"]["error_message"].startswith("english_summary_contains_cyrillic:")
        assert db.query(AnalysisCheckStep).filter_by(
            check_run_id=check_run.id,
            step_name="summary_generation_en",
            status=RunStatus.FAILED.value,
        ).count() == 1
    finally:
        db.close()
        get_settings.cache_clear()


def test_english_language_check_runs_before_person_names_are_deanonymized(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("DOCUMENT_ANONYMIZATION_ENABLED", "true")
    get_settings.cache_clear()
    db = _session()

    class PlaceholderGenerationAdapter:
        def run(self, request):
            assert "Иван Петров" not in request.prompt
            segment_ids = request.response_schema["properties"]["content"]["required"]
            language = request.response_schema["properties"]["language"]["const"]
            return AnalysisProviderResult(
                structured_text=json.dumps(
                    {
                        "run_mode": "independent_summary_generation",
                        "language": language,
                        "content": {
                            segment_id: "Approved by [PERSON_001]"
                            for segment_id in segment_ids
                        },
                    }
                ),
                raw_output="anonymized person placeholder",
                latency_ms=1,
            )

    monkeypatch.setattr(
        summary_localization,
        "get_provider_adapter",
        lambda *_args, **_kwargs: PlaceholderGenerationAdapter(),
    )
    try:
        analysis, _ = _seed(db)
        output = dict(analysis.structured_output)
        output["assessment_markdown"] = "Оценка документа\n\nИван Петров owns the launch."
        analysis.structured_output = output
        db.commit()

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        variant = analysis.structured_output["result"]["summary_localizations"]["en"]
        assert variant["status"] == "completed"
        assert "Иван Петров" in json.dumps(variant["payload"], ensure_ascii=False)
        assert "[PERSON_001]" not in json.dumps(variant["payload"], ensure_ascii=False)
    finally:
        db.close()
        get_settings.cache_clear()
        monkeypatch.delenv("DOCUMENT_ANONYMIZATION_ENABLED", raising=False)


def test_long_summary_is_generated_in_bounded_independent_batches(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    calls: list[tuple[int, int]] = []

    class BoundedGenerationAdapter:
        def run(self, request):
            segment_ids = request.response_schema["properties"]["content"]["required"]
            language = request.response_schema["properties"]["language"]["const"]
            calls.append((len(segment_ids), len(request.prompt)))
            return AnalysisProviderResult(
                structured_text=json.dumps(
                    {
                        "run_mode": "independent_summary_generation",
                        "language": language,
                        "content": {segment_id: f"Generated {language} {segment_id}" for segment_id in segment_ids},
                    }
                ),
                raw_output=f"batch {len(calls)}",
                latency_ms=1,
            )

    monkeypatch.setattr(summary_localization, "get_provider_adapter", lambda *_args, **_kwargs: BoundedGenerationAdapter())
    try:
        analysis, _ = _seed(db)
        output = dict(analysis.structured_output)
        output["assessment_markdown"] = "Оценка документа\n\n" + "\n\n".join(
            f"## Раздел {index}\n" + ("Подробное доказательство спроса и рисков. " * 120)
            for index in range(12)
        )
        analysis.structured_output = output
        db.commit()

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        variant = analysis.structured_output["result"]["summary_localizations"]["en"]
        assert variant["status"] == "completed"
        assert len(calls) > 1
        assert all(segment_count <= summary_localization.MAX_BATCH_SEGMENTS for segment_count, _ in calls)
        assert all(prompt_length < 30000 for _, prompt_length in calls)
    finally:
        db.close()
        get_settings.cache_clear()


def test_invalid_generation_json_is_retried_and_both_attempts_are_traced(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    calls = 0

    class RetryGenerationAdapter:
        def run(self, request):
            nonlocal calls
            calls += 1
            if calls == 1:
                return AnalysisProviderResult(structured_text="{", raw_output="truncated", latency_ms=1)
            segment_ids = request.response_schema["properties"]["content"]["required"]
            language = request.response_schema["properties"]["language"]["const"]
            return AnalysisProviderResult(
                structured_text=json.dumps(
                    {
                        "run_mode": "independent_summary_generation",
                        "language": language,
                        "content": {segment_id: f"Generated {language} {segment_id}" for segment_id in segment_ids},
                    }
                ),
                raw_output="valid retry",
                latency_ms=1,
            )

    monkeypatch.setattr(summary_localization, "get_provider_adapter", lambda *_args, **_kwargs: RetryGenerationAdapter())
    try:
        analysis, check_run = _seed(db)

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        variant = analysis.structured_output["result"]["summary_localizations"]["en"]
        assert variant["status"] == "completed"
        assert calls == 3
        step = db.query(AnalysisCheckStep).filter_by(
            check_run_id=check_run.id,
            step_name="summary_generation_ru",
        ).one()
        assert "truncated" in step.raw_output
        assert "valid retry" in step.raw_output
    finally:
        db.close()
        get_settings.cache_clear()


def test_failed_russian_generation_does_not_block_english_variant(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()

    class PartialGenerationAdapter:
        def run(self, request):
            language = request.response_schema["properties"]["language"]["const"]
            if language == "ru":
                return AnalysisProviderResult(structured_text="{", raw_output="invalid ru", latency_ms=1)
            segment_ids = request.response_schema["properties"]["content"]["required"]
            return AnalysisProviderResult(
                structured_text=json.dumps(
                    {
                        "run_mode": "independent_summary_generation",
                        "language": "en",
                        "content": {segment_id: f"Generated en {segment_id}" for segment_id in segment_ids},
                    }
                ),
                raw_output="valid en",
                latency_ms=1,
            )

    monkeypatch.setattr(summary_localization, "get_provider_adapter", lambda *_args, **_kwargs: PartialGenerationAdapter())
    try:
        analysis, check_run = _seed(db)

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        variants = analysis.structured_output["result"]["summary_localizations"]
        assert variants["ru"]["status"] == "failed"
        assert variants["en"]["status"] == "completed"
        assert db.query(AnalysisCheckStep).filter_by(
            check_run_id=check_run.id,
            step_name="summary_generation_ru",
            status=RunStatus.FAILED.value,
        ).count() == 1
        assert db.query(AnalysisCheckStep).filter_by(
            check_run_id=check_run.id,
            step_name="summary_generation_en",
            status=RunStatus.COMPLETED.value,
        ).count() == 1
    finally:
        db.close()
        get_settings.cache_clear()


def test_new_run_uses_current_provider_when_original_provider_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, check_run = _seed(db)
        check_run.provider = Provider.ANTHROPIC_COMPATIBLE.value
        check_run.model = "claude-retired"
        source = summary_localization.build_summary_generation_source(analysis=analysis, check_run=check_run)
        paths = summary_localization._translatable_paths(source)
        segment_ids = list(summary_localization._generation_plan(source, paths)[0])
        check_run.run_parameters = {
            "output_language": "ru",
            "summary_generation_mock_provider_results": {
                language: {
                    "structured_text": json.dumps(
                        {
                            "run_mode": "independent_summary_generation",
                            "language": language,
                            "content": {
                                segment_id: f"Generated {language} {index}"
                                for index, segment_id in enumerate(segment_ids)
                            },
                        }
                    ),
                    "raw_output": f"fallback provider {language} generation",
                    "latency_ms": 1,
                }
                for language in ("ru", "en")
            },
        }
        db.commit()

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        assert analysis.structured_output["result"]["summary_localizations"]["en"]["status"] == "completed"
        step = db.query(AnalysisCheckStep).filter_by(
            check_run_id=check_run.id,
            step_name="summary_generation_en",
        ).one()
        effective = next(item for item in step.artifacts if item["key"] == "effective_run_parameters")
        assert effective["run_parameters"]["summary_generation_provider"] == Provider.OPENAI_COMPATIBLE.value
        assert effective["run_parameters"]["summary_generation_model"] == "gpt-test"
    finally:
        db.close()
        get_settings.cache_clear()


def test_new_summary_failure_persists_public_error_code_only(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, check_run = _seed(db)
        output = dict(analysis.structured_output)
        result = dict(output["result"])
        result["new_summary"] = {
            "version": 2,
            "generation_mode": "new_summary_skill",
            "source_revision": str(check_run.id),
            "ru": {"status": "queued", "payload": None, "error_message": None},
            "en": {"status": "queued", "payload": None, "error_message": None},
        }
        output["result"] = result
        analysis.structured_output = output
        invalid_payload = _new_summary_report_payload(
            ru_context="Очень чувствительный текст не должен попасть в публичную ошибку.",
            en_context="Sensitive text must not leak into the public error.",
        )
        invalid_payload["versions"][0]["critical_problems"] = [
            {"issue": f"Sensitive issue {index}", "fact": "Sensitive fact"} for index in range(11)
        ]
        check_run.run_parameters = {
            "new_summary_mock_provider_result": {
                "structured_text": json.dumps(invalid_payload, ensure_ascii=False),
                "raw_output": "raw new summary with sensitive validation content",
                "latency_ms": 1,
            },
            "new_summary_json_retry_mock_provider_result": {
                "structured_text": json.dumps(invalid_payload, ensure_ascii=False),
                "raw_output": "raw retry with sensitive validation content",
                "latency_ms": 2,
            },
        }
        db.commit()

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        state = analysis.structured_output["result"]["new_summary"]
        assert state["ru"]["status"] == "failed"
        assert state["en"]["status"] == "failed"
        assert state["progress"]["stage"] == "failed"
        assert state["ru"]["error_message"].startswith("new_summary_generation_failed:")
        assert "чувствительный" not in state["ru"]["error_message"]
        step = db.query(AnalysisCheckStep).filter_by(
            check_run_id=check_run.id,
            step_name="new_summary_bilingual",
        ).one()
        assert step.status == RunStatus.FAILED.value
        assert step.error_message.startswith("new_summary_generation_failed:")
        assert "Sensitive" not in step.error_message
    finally:
        db.close()
        get_settings.cache_clear()


def _session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def _new_summary_report_payload(
    *,
    ru_context: str,
    en_context: str,
    stage: str = "Gate 2",
    required_elements: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "schema_version": "new-summary-v1",
        "language": "en",
        "title": "AI Summary Case",
        "versions": [
            _new_summary_payload(
                language="en",
                context=en_context,
                stage=stage,
                required_elements=required_elements,
            ),
            _new_summary_payload(
                language="ru",
                context=ru_context,
                stage=stage,
                required_elements=required_elements,
            ),
        ],
    }


def _new_summary_payload(
    *,
    language: str,
    context: str,
    stage: str,
    required_elements: list[dict[str, str]] | None,
) -> dict:
    return {
        "language": language,
        "stage": stage,
        "traction_summary": {
            "periods": ["Total"],
            "rows": [
                {"label": "DTB Uplift (Cumul)", "values": ["—"]},
                {"label": "Revenue from DTB", "values": ["—"]},
                {"label": "Revenue non-DTB", "values": ["—"]},
                {"label": "Total Revenue", "values": ["—"]},
            ],
        },
        "context": context,
        "required_elements": [
            {
                "id": "gate2_hypothesis_results",
                "label": "Результаты проверки гипотез из Gate 1" if language == "ru" else "Gate 1 hypothesis validation results",
                "status": "есть",
                "evidence": "Раздел есть." if language == "ru" else "The section is present.",
            },
            {
                "id": "gate2_target_product",
                "label": "Описание MVP/целевого продукта" if language == "ru" else "MVP or target product description",
                "status": "нет",
                "evidence": "Нет данных." if language == "ru" else "No evidence is provided.",
            },
            {
                "id": "gate2_user_flow",
                "label": "Mockups или видео пользовательского flow" if language == "ru" else "User-flow mockups or video",
                "status": "есть",
                "evidence": "Раздел есть." if language == "ru" else "The section is present.",
            },
            {
                "id": "gate2_commitments",
                "label": "Commitments к Gate 3: сроки, expected performance, метрики" if language == "ru" else "Gate 3 commitments: timeline, expected performance, and metrics",
                "status": "нет",
                "evidence": "Нет данных." if language == "ru" else "No evidence is provided.",
            },
        ] if required_elements is None else [
            {
                "id": item["id"],
                "label": item["label_ru"] if language == "ru" else item["label_en"],
                "status": "нет",
                "evidence": "Нет данных." if language == "ru" else "No evidence is provided.",
            }
            for item in required_elements
        ],
        "confirmed": ["Спрос частично подтверждён." if language == "ru" else "Demand is partly confirmed."],
        "insufficiently_confirmed": [
            "Не хватает связи метрик с продуктом." if language == "ru" else "Metric linkage to the product is missing."
        ],
        "critical_problems": [{
            "issue": "Нет stop-критериев." if language == "ru" else "Stop criteria are missing.",
            "fact": "Документ их не задаёт." if language == "ru" else "The document does not define them.",
        }],
        "other": [],
    }


def _seed(db):
    user = User(id=uuid4(), login="admin", display_name="Admin", password_hash="x", role=Role.ADMIN.value, status=UserStatus.ACTIVE.value)
    document = Document(
        id=uuid4(), owner_id=user.id, title="Case", original_filename="case.docx", mime_type="application/docx",
        file_size_bytes=1, file_hash_sha256="a" * 64, storage_path="case.docx", parse_status=DocumentParseStatus.COMPLETED.value,
        parsed_text="text", detected_document_type=DocumentType.GATE_2.value, document_role="primary", status=EntityStatus.ACTIVE.value,
    )
    skill = Skill(
        id=uuid4(), name="gate", description="gate", version="1", skill_type=SkillType.MAIN_ANALYSIS.value,
        supported_document_types=[DocumentType.GATE_2.value], source_type=SkillSourceType.INLINE_PROMPT.value,
        prompt_text="prompt", result_schema_path="contracts/schemas/main-analysis-result.schema.json", runtime_mode="inline",
        status=EntityStatus.ACTIVE.value,
    )
    analysis = Analysis(
        id=uuid4(), document_id=document.id, user_id=user.id, skill_id=skill.id, skill_version="1",
        provider=Provider.OPENAI_COMPATIBLE.value, model="gpt-test", status=RunStatus.COMPLETED.value,
        verdict="need_evidence", summary="Нужны подтверждения",
        structured_output={
            "assessment_markdown": "Оценка документа\n\n## Вывод\nНужно подтвердить спрос.",
            "stage_checklist": [{"id": "gate2_hypothesis_results", "label": "Результаты гипотез", "status": "red", "evidence": "Нет данных"}],
            "result": {"short_summary": "Нужны подтверждения"},
        },
        run_parameters={"output_language": "ru"},
    )
    check_run = AnalysisCheckRun(
        id=uuid4(), analysis_id=analysis.id, skill_id=skill.id, skill_version="1", check_type="ic_agentic_review",
        provider=Provider.OPENAI_COMPATIBLE.value, model="gpt-test", status=RunStatus.COMPLETED.value,
        structured_output={
            "run_mode": "ic_agentic_review_compact", "verdict": "CONDITIONAL", "executive_brief": "Нужны данные.",
            "confidence": 0.8,
            "top_findings": [{"title": "Риск", "severity": "high", "summary": "Нет данных", "evidence": "Документ", "recommendation": "Добавить"}],
            "key_numbers": [{"label": "Пользователи", "value": "42", "unit": "шт.", "source": "Документ"}],
            "spreadsheet_audit": {"status": "completed", "summary": "Есть замечания", "formula_issues_count": 2, "critical_formula_issues_count": 1, "source_filename": "model.xlsx"},
            "critical_risks": ["Риск спроса"], "data_gaps": ["Нет метрики"], "required_actions": ["Добавить метрику"],
            "questions_for_team": ["Как измерять?"],
            "validation": {"status": "warn", "summary": "Есть предупреждения", "warnings_count": 1, "failures_count": 0},
        },
        run_parameters={}, artifacts=[], uploaded_workbook_metadata={},
    )
    output = dict(analysis.structured_output)
    result = dict(output["result"])
    result["summary_localizations"] = {
        "version": summary_localization.SUMMARY_LOCALIZATION_VERSION,
        "generation_mode": summary_localization.SUMMARY_GENERATION_MODE,
        "source_revision": str(check_run.id),
        "ru": {"status": "queued", "payload": None, "error_message": None},
        "en": {"status": "queued", "payload": None, "error_message": None},
    }
    output["result"] = result
    analysis.structured_output = output
    key = ProviderKey(
        owner_id=user.id, provider=Provider.OPENAI_COMPATIBLE.value, default_model="gpt-test", available_models=["gpt-test"],
        encrypted_api_key=encrypt_secret("sk-test"), api_key_fingerprint="test",
    )
    db.add_all([user, document, skill, analysis, check_run, key])
    db.commit()
    return analysis, check_run
