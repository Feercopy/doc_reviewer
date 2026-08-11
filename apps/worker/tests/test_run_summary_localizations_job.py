from __future__ import annotations

import json
from pathlib import Path
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
        assert en["stage_checklist"][0]["label"].startswith("EN generated")
        assert en["stage_checklist"][0]["id"] == ru["stage_checklist"][0]["id"]
        assert en["stage_checklist"][0]["status"] == ru["stage_checklist"][0]["status"]
        assert en["financial_analysis"]["verdict"] == ru["financial_analysis"]["verdict"]
        assert en["financial_analysis"]["confidence"] == ru["financial_analysis"]["confidence"]
        assert en["financial_analysis"]["key_numbers"][0]["value"] == "42"
        assert en["financial_analysis"]["spreadsheet_audit"]["formula_issues_count"] == 2
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
