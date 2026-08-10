from __future__ import annotations

import json
from uuid import uuid4

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
from jobs.run_summary_localizations import run_summary_localizations
from providers.base import AnalysisProviderResult
from skills import summary_localization


def test_summary_localization_translates_text_without_changing_decision_data(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, check_run = _seed(db)
        source = summary_localization.build_summary_payload(analysis=analysis, check_run=check_run, language="ru")
        paths = summary_localization._translatable_paths(source)
        translations = {
            f"s{index:04d}": f"English {index}: {summary_localization._get_path(source, path)}"
            for index, path in enumerate(paths)
        }
        check_run.run_parameters = {
            "output_language": "ru",
            "summary_localization_mock_provider_results": {
                "en": {
                    "structured_text": json.dumps(
                        {
                            "run_mode": "summary_localization_translation",
                            "language": "en",
                            "translations": translations,
                        }
                    ),
                    "raw_output": "raw translation",
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "latency_ms": 30,
                }
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
        assert en["short_summary"].startswith("English")
        assert en["stage_checklist"][0]["label"].startswith("English")
        assert en["stage_checklist"][0]["id"] == ru["stage_checklist"][0]["id"]
        assert en["stage_checklist"][0]["status"] == ru["stage_checklist"][0]["status"]
        assert en["financial_analysis"]["verdict"] == ru["financial_analysis"]["verdict"]
        assert en["financial_analysis"]["confidence"] == ru["financial_analysis"]["confidence"]
        assert en["financial_analysis"]["key_numbers"][0]["value"] == "42"
        assert en["financial_analysis"]["spreadsheet_audit"]["formula_issues_count"] == 2
    finally:
        db.close()
        get_settings.cache_clear()


def test_mixed_historical_output_builds_russian_before_english(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, check_run = _seed(db)
        check_run.run_parameters = {"output_language": "en"}
        source = summary_localization.build_summary_payload(analysis=analysis, check_run=check_run, language="ru")
        segment_count = len(summary_localization._translatable_paths(source))
        check_run.run_parameters["summary_localization_mock_provider_results"] = {
            language: {
                "structured_text": json.dumps(
                    {
                        "run_mode": "summary_localization_translation",
                        "language": language,
                        "translations": {f"s{index:04d}": f"{language.upper()} translation {index}" for index in range(segment_count)},
                    }
                ),
                "raw_output": f"raw {language}",
                "latency_ms": 1,
            }
            for language in ("ru", "en")
        }
        db.commit()

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        variants = analysis.structured_output["result"]["summary_localizations"]
        assert variants["ru"]["status"] == "completed"
        assert variants["ru"]["source_language"] == "mixed"
        assert variants["en"]["status"] == "completed"
        assert variants["en"]["source_language"] == "ru"
        assert variants["ru"]["payload"]["short_summary"].startswith("RU translation")
        assert variants["en"]["payload"]["short_summary"].startswith("EN translation")
    finally:
        db.close()
        get_settings.cache_clear()


def test_long_historical_summary_is_translated_in_bounded_batches(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    calls: list[tuple[int, int]] = []

    class BoundedTranslationAdapter:
        def run(self, request):
            segment_ids = request.response_schema["properties"]["translations"]["required"]
            calls.append((len(segment_ids), len(request.prompt)))
            return AnalysisProviderResult(
                structured_text=json.dumps(
                    {
                        "run_mode": "summary_localization_translation",
                        "language": "en",
                        "translations": {segment_id: f"Translated {segment_id}" for segment_id in segment_ids},
                    }
                ),
                raw_output=f"batch {len(calls)}",
                latency_ms=1,
            )

    monkeypatch.setattr(summary_localization, "get_provider_adapter", lambda *_args, **_kwargs: BoundedTranslationAdapter())
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


def test_invalid_translation_json_is_retried_and_both_attempts_are_traced(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    calls = 0

    class RetryTranslationAdapter:
        def run(self, request):
            nonlocal calls
            calls += 1
            if calls == 1:
                return AnalysisProviderResult(structured_text="{", raw_output="truncated", latency_ms=1)
            segment_ids = request.response_schema["properties"]["translations"]["required"]
            return AnalysisProviderResult(
                structured_text=json.dumps(
                    {
                        "run_mode": "summary_localization_translation",
                        "language": "en",
                        "translations": {segment_id: f"Translated {segment_id}" for segment_id in segment_ids},
                    }
                ),
                raw_output="valid retry",
                latency_ms=1,
            )

    monkeypatch.setattr(summary_localization, "get_provider_adapter", lambda *_args, **_kwargs: RetryTranslationAdapter())
    try:
        analysis, check_run = _seed(db)

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        variant = analysis.structured_output["result"]["summary_localizations"]["en"]
        assert variant["status"] == "completed"
        assert calls == 2
        step = db.query(AnalysisCheckStep).filter_by(
            check_run_id=check_run.id,
            step_name="summary_localization_en",
        ).one()
        assert "truncated" in step.raw_output
        assert "valid retry" in step.raw_output
    finally:
        db.close()
        get_settings.cache_clear()


def test_historical_run_uses_current_provider_when_old_provider_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    db = _session()
    try:
        analysis, check_run = _seed(db)
        check_run.provider = Provider.ANTHROPIC_COMPATIBLE.value
        check_run.model = "claude-retired"
        source = summary_localization.build_summary_payload(analysis=analysis, check_run=check_run, language="ru")
        paths = summary_localization._translatable_paths(source)
        check_run.run_parameters = {
            "output_language": "ru",
            "summary_localization_mock_provider_results": {
                "en": {
                    "structured_text": json.dumps(
                        {
                            "run_mode": "summary_localization_translation",
                            "language": "en",
                            "translations": {
                                f"s{index:04d}": f"Translated {index}"
                                for index in range(len(paths))
                            },
                        }
                    ),
                    "raw_output": "fallback provider translation",
                    "latency_ms": 1,
                }
            },
        }
        db.commit()

        run_summary_localizations(str(analysis.id), db=db)

        db.refresh(analysis)
        assert analysis.structured_output["result"]["summary_localizations"]["en"]["status"] == "completed"
        step = db.query(AnalysisCheckStep).filter_by(
            check_run_id=check_run.id,
            step_name="summary_localization_en",
        ).one()
        effective = next(item for item in step.artifacts if item["key"] == "effective_run_parameters")
        assert effective["run_parameters"]["summary_localization_provider"] == Provider.OPENAI_COMPATIBLE.value
        assert effective["run_parameters"]["summary_localization_model"] == "gpt-test"
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
            "stage_checklist": [{"id": "G2-1", "label": "Результаты гипотез", "status": "red", "evidence": "Нет данных"}],
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
    key = ProviderKey(
        owner_id=user.id, provider=Provider.OPENAI_COMPATIBLE.value, default_model="gpt-test", available_models=["gpt-test"],
        encrypted_api_key=encrypt_secret("sk-test"), api_key_fingerprint="test",
    )
    db.add_all([user, document, skill, analysis, check_run, key])
    db.commit()
    return analysis, check_run
