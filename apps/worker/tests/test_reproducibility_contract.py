from app.models.analysis import Analysis, PredictedCommentRun
from app.models.benchmark import Benchmark
from app.schemas.enums import Provider, RunStatus


def test_completed_analysis_reproducibility_contract_is_explicit():
    required_fields = {
        "document_id",
        "raw_output",
        "provider",
        "model",
        "skill_id",
        "skill_version",
        "run_parameters",
        "structured_output",
        "created_at",
    }

    assert required_fields.issubset(set(Analysis.__table__.columns.keys()))


def test_predicted_comment_run_reproducibility_contract_is_explicit():
    required_fields = {
        "analysis_id",
        "raw_output",
        "provider",
        "model",
        "skill_id",
        "skill_version",
        "run_parameters",
        "structured_output",
        "created_at",
    }

    assert required_fields.issubset(set(PredictedCommentRun.__table__.columns.keys()))


def test_benchmark_reproducibility_contract_is_explicit():
    required_fields = {
        "etalon_ids",
        "skill_id",
        "skill_version",
        "judge_skill_id",
        "provider",
        "model",
        "run_parameters",
        "judge_output",
        "report",
        "status",
    }

    assert required_fields.issubset(set(Benchmark.__table__.columns.keys()))


def test_reproducibility_snapshots_are_required_in_run_parameters():
    analysis = Analysis(
        document_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        skill_id="00000000-0000-0000-0000-000000000003",
        skill_version="1.0.0",
        provider=Provider.OPENAI_COMPATIBLE.value,
        model="gpt-test",
        status=RunStatus.COMPLETED.value,
        structured_output={"verdict": "need_evidence"},
        raw_output="raw",
        run_parameters={
            "skill_source_snapshot": {
                "source_path": "/skills/gate2/SKILL.md",
                "source_entrypoint": "SKILL.md",
                "source_revision": "abc123",
                "source_fingerprint": "sha256:abc",
            }
        },
    )

    snapshot = analysis.run_parameters["skill_source_snapshot"]
    assert {"source_path", "source_entrypoint", "source_revision", "source_fingerprint"}.issubset(snapshot)
