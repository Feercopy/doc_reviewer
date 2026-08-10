from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.models.analysis import Analysis, AnalysisCheckRun
from app.models.document import Document
from app.models.provider_key import ProviderKey
from app.models.skill import Skill
from app.models.user import User
from app.schemas.enums import DocumentParseStatus, DocumentType, EntityStatus, Provider, Role, RunStatus, SkillSourceType, SkillType, UserStatus
from app.security.secrets import encrypt_secret
from jobs.run_summary_localizations import run_summary_localizations
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
