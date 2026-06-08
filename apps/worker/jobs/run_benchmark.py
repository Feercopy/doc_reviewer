import json
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.logging import worker_logger
from app.models.benchmark import Benchmark
from app.models.document import Document
from app.models.etalon import Etalon
from app.models.provider_key import ProviderKey
from app.models.skill import Skill
from app.models.base import utc_now
from app.schemas.enums import Provider, RunStatus
from app.security.secrets import decrypt_secret
from app.services.audit import record_audit
from benchmark.judge_prompt import build_judge_prompt
from benchmark.report_builder import build_benchmark_report
from benchmark.scoring import score_judge_output
from providers.base import ProviderRunRequest
from providers.registry import get_provider_adapter
from results.schema_validation import parse_and_validate_json_output
from skills.prompt_renderer import render_prompt


def run_benchmark(benchmark_id: str, *, db: Session | None = None) -> None:
    owns_session = db is None
    session = db or SessionLocal()
    benchmark_uuid = UUID(str(benchmark_id))
    try:
        worker_logger.info(
            "worker_job_started",
            extra={"job_type": "run_benchmark", "entity_id": str(benchmark_uuid), "status": "running"},
        )
        benchmark = session.get(Benchmark, benchmark_uuid)
        if benchmark is None:
            raise ValueError(f"Benchmark {benchmark_id} not found")
        benchmark.status = RunStatus.RUNNING.value
        benchmark.started_at = utc_now()
        benchmark.error_message = None
        session.commit()

        main_skill = session.get(Skill, benchmark.skill_id)
        judge_skill = session.get(Skill, benchmark.judge_skill_id)
        if main_skill is None or judge_skill is None:
            raise RuntimeError("benchmark_skill_missing")

        document_results = []
        for etalon_id in benchmark.etalon_ids:
            document_results.append(
                _run_one_etalon(
                    session=session,
                    benchmark=benchmark,
                    etalon_id=UUID(str(etalon_id)),
                    main_skill=main_skill,
                    judge_skill=judge_skill,
                )
            )

        aggregate = _aggregate_results(document_results)
        benchmark.layer_1_score = Decimal(str(aggregate["layer_1"]["f1"]))
        benchmark.layer_2_score = Decimal(str(aggregate["layer_2"]["f1"]))
        benchmark.precision = Decimal(str(aggregate["precision"]))
        benchmark.recall = Decimal(str(aggregate["recall"]))
        benchmark.f1 = Decimal(str(aggregate["f1"]))
        benchmark.overall_score = benchmark.f1
        benchmark.missed_findings = aggregate["missed_findings"]
        benchmark.false_positives = aggregate["false_positives"]
        benchmark.partial_matches = aggregate["partial_matches"]
        benchmark.judge_output = {"documents": document_results}
        benchmark.report = build_benchmark_report(
            benchmark_name=benchmark.name,
            document_results=document_results,
            aggregate=aggregate,
        )
        benchmark.status = RunStatus.COMPLETED.value if any(item["status"] == "completed" for item in document_results) else RunStatus.FAILED.value
        benchmark.completed_at = utc_now()
        record_audit(
            db=session,
            actor_id=benchmark.started_by_id,
            action="benchmark.completed" if benchmark.status == RunStatus.COMPLETED.value else "benchmark.failed",
            entity_type="benchmark",
            entity_id=benchmark.id,
            metadata={
                "provider": benchmark.provider,
                "model": benchmark.model,
                "etalon_count": len(benchmark.etalon_ids),
                "f1": str(benchmark.f1),
            },
        )
        session.commit()
        worker_logger.info(
            "worker_job_completed",
            extra={"job_type": "run_benchmark", "entity_id": str(benchmark_uuid), "status": benchmark.status},
        )
    except Exception as exc:
        session.rollback()
        failed = session.get(Benchmark, benchmark_uuid)
        if failed is None:
            raise
        failed.status = RunStatus.FAILED.value
        failed.error_message = str(exc)
        failed.completed_at = utc_now()
        record_audit(
            db=session,
            actor_id=failed.started_by_id,
            action="benchmark.failed",
            entity_type="benchmark",
            entity_id=failed.id,
            metadata={"provider": failed.provider, "model": failed.model, "error_class": exc.__class__.__name__},
        )
        session.commit()
        worker_logger.info(
            "worker_job_failed",
            extra={
                "job_type": "run_benchmark",
                "entity_id": str(benchmark_uuid),
                "status": "failed",
                "error_class": exc.__class__.__name__,
            },
        )
    finally:
        if owns_session:
            session.close()


def _run_one_etalon(*, session: Session, benchmark: Benchmark, etalon_id: UUID, main_skill: Skill, judge_skill: Skill) -> dict:
    etalon = session.get(Etalon, etalon_id)
    if etalon is None:
        return {"etalon_id": str(etalon_id), "status": "failed", "error": "etalon_missing"}
    document = session.get(Document, etalon.document_id)
    if document is None or not document.parsed_text:
        return {"etalon_id": str(etalon.id), "status": "failed", "error": "document_parsed_text_missing"}

    try:
        actual_output = _run_provider(
            session=session,
            benchmark=benchmark,
            skill=main_skill,
            prompt=render_prompt(
                document=document,
                skill=main_skill,
                response_schema=_load_schema(main_skill.result_schema_path),
                run_parameters=benchmark.run_parameters,
            ),
            schema_path=main_skill.result_schema_path,
            run_parameters=benchmark.run_parameters,
        )
        expected_output = {
            "verdict": etalon.expected_verdict,
            "layer_1": etalon.layer_1,
            "layer_2": etalon.layer_2,
            "key_findings": etalon.key_findings,
        }
        judge_run_parameters = dict(benchmark.run_parameters)
        if "judge_mock_provider_result" in benchmark.run_parameters:
            judge_run_parameters["mock_provider_result"] = benchmark.run_parameters["judge_mock_provider_result"]
        judge_output = _run_provider(
            session=session,
            benchmark=benchmark,
            skill=judge_skill,
            prompt=build_judge_prompt(
                etalon=expected_output,
                actual=actual_output,
                judge_prompt=judge_skill.prompt_text,
            ),
            schema_path=judge_skill.result_schema_path,
            run_parameters=judge_run_parameters,
        )
        scores = score_judge_output(expected=expected_output, actual=actual_output, judge_output=judge_output)
        return {
            "etalon_id": str(etalon.id),
            "document_id": str(document.id),
            "status": "completed",
            "actual_output": actual_output,
            "judge_output": judge_output,
            "scores": scores,
        }
    except Exception as exc:
        return {"etalon_id": str(etalon.id), "document_id": str(document.id), "status": "failed", "error": str(exc)}


def _run_provider(
    *,
    session: Session,
    benchmark: Benchmark,
    skill: Skill,
    prompt: str,
    schema_path: str,
    run_parameters: dict,
) -> dict:
    provider = Provider(benchmark.provider)
    provider_key = _get_provider_key(session=session, benchmark=benchmark, provider=provider)
    api_key = decrypt_secret(provider_key.encrypted_api_key) if provider_key else None
    result = get_provider_adapter(provider, run_parameters).run(
        ProviderRunRequest(
            provider=provider,
            model=benchmark.model,
            api_key=api_key,
            base_url=provider_key.base_url if provider_key else None,
            prompt=prompt,
            response_schema=_load_schema(schema_path),
            run_parameters=run_parameters,
        )
    )
    return parse_and_validate_json_output(structured_text=result.structured_text, schema_path=skill.result_schema_path)


def _get_provider_key(*, session: Session, benchmark: Benchmark, provider: Provider) -> ProviderKey | None:
    if "mock_provider_result" in benchmark.run_parameters:
        return None
    return (
        session.query(ProviderKey)
        .filter(ProviderKey.owner_id == benchmark.started_by_id, ProviderKey.provider == provider.value)
        .one_or_none()
    )


def _load_schema(schema_path: str) -> dict:
    return json.loads((Path(__file__).resolve().parents[3] / schema_path).read_text(encoding="utf-8"))


def _aggregate_results(document_results: list[dict]) -> dict:
    completed = [item for item in document_results if item.get("status") == "completed"]
    if not completed:
        empty_layer = {"precision": 0, "recall": 0, "f1": 0}
        return {
            "layer_1": empty_layer,
            "layer_2": empty_layer,
            "precision": 0,
            "recall": 0,
            "f1": 0,
            "missed_findings": [],
            "false_positives": [],
            "partial_matches": [],
        }
    layer_1_f1 = sum(item["scores"]["layer_1"]["f1"] for item in completed) / len(completed)
    layer_2_f1 = sum(item["scores"]["layer_2"]["f1"] for item in completed) / len(completed)
    precision = sum(item["scores"]["precision"] for item in completed) / len(completed)
    recall = sum(item["scores"]["recall"] for item in completed) / len(completed)
    f1 = sum(item["scores"]["f1"] for item in completed) / len(completed)
    missed = []
    false_positives = []
    partial = []
    for item in completed:
        judge = item["judge_output"]
        missed.extend(judge["layer_1"]["missed_findings"])
        missed.extend(judge["layer_2"]["missed_findings"])
        false_positives.extend(judge["layer_1"]["false_positives"])
        false_positives.extend(judge["layer_2"]["false_positives"])
        partial.extend(judge["layer_1"]["partial_matches"])
        partial.extend(judge["layer_2"]["partial_matches"])
    return {
        "layer_1": {"f1": layer_1_f1},
        "layer_2": {"f1": layer_2_f1},
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "missed_findings": missed,
        "false_positives": false_positives,
        "partial_matches": partial,
    }
