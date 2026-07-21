from types import SimpleNamespace

from app.services.devils_retrieval import build_devils_retrieval_dossier


def test_devils_retrieval_is_deterministic_with_path_tie_breaking(tmp_path):
    artifact_path = _create_source_snapshot(
        tmp_path,
        {
            "wiki-ic/cases/a-case.md": "marketplace incrementality control group",
            "wiki-ic/cases/b-case.md": "marketplace incrementality control group",
            "wiki-ic/patterns/missing-incrementality.md": "incrementality experiment holdout",
            "wiki-ic/personas/cfo.md": "CFO asks about budget and incremental return",
        },
    )
    document = SimpleNamespace(
        title="Gate 2",
        parsed_text="Marketplace growth asks for budget but lacks incrementality control group.",
        detected_document_type="gate_2",
    )
    analysis = SimpleNamespace(
        summary="Needs incrementality evidence.",
        structured_output={
            "findings": [{"title": "Missing control group", "summary": "No holdout proof"}],
            "checks": [{"name": "Incrementality", "explanation": "No experiment"}],
        },
    )

    first = build_devils_retrieval_dossier(
        source_snapshot_artifact_path=artifact_path,
        document=document,
        analysis=analysis,
        top_k=2,
    )
    second = build_devils_retrieval_dossier(
        source_snapshot_artifact_path=artifact_path,
        document=document,
        analysis=analysis,
        top_k=2,
    )

    assert first == second
    assert [item["path"] for item in first["selected_items"]["top_cases"]] == [
        "wiki-ic/cases/a-case.md",
        "wiki-ic/cases/b-case.md",
    ]
    assert first["selected_items"]["top_patterns"][0]["path"] == "wiki-ic/patterns/missing-incrementality.md"
    assert first["selected_items"]["top_persona_question_examples"][0]["path"] == "wiki-ic/personas/cfo.md"
    assert first["retrieval_mode"] == "deterministic_topk"
    assert first["corpus_fingerprint"]
    assert first["query_fingerprint"]


def test_devils_retrieval_corpus_fingerprint_changes_when_file_changes(tmp_path):
    artifact_path = _create_source_snapshot(
        tmp_path,
        {
            "wiki-ic/cases/case.md": "first version incrementality",
            "wiki-ic/patterns/pattern.md": "risk pattern",
        },
    )
    document = SimpleNamespace(title="Gate 2", parsed_text="incrementality", detected_document_type="gate_2")
    analysis = SimpleNamespace(summary="", structured_output={})

    first = build_devils_retrieval_dossier(
        source_snapshot_artifact_path=artifact_path,
        document=document,
        analysis=analysis,
        top_k=1,
    )
    (artifact_path / "files" / "wiki-ic" / "cases" / "case.md").write_text(
        "second version incrementality",
        encoding="utf-8",
    )
    second = build_devils_retrieval_dossier(
        source_snapshot_artifact_path=artifact_path,
        document=document,
        analysis=analysis,
        top_k=1,
    )

    assert first["corpus_fingerprint"] != second["corpus_fingerprint"]


def test_devils_retrieval_builds_evidence_packet_from_selected_pages_and_raw_material(tmp_path):
    artifact_path = _create_source_snapshot(
        tmp_path,
        {
            "wiki-ic/cases/ic-2025-292.md": "case summary incrementality hard KPI gate",
            "wiki-ic/patterns/experimental-traction-gap.md": "pattern says missing holdout is a blocker",
            "wiki-ic/raw/comments/raw-ic-2025-292-comments.md": "real MP comment: how much is incremental?",
            "wiki-ic/raw/minutes/raw-ic-2025-292-minutes.md": "real IC decision: rework until KPI gate is closed",
        },
    )
    document = SimpleNamespace(
        title="Gate 2",
        parsed_text="The proposal asks for budget but has no holdout or incrementality proof.",
        detected_document_type="gate_2",
    )
    analysis = SimpleNamespace(summary="Needs incrementality evidence.", structured_output={})

    dossier = build_devils_retrieval_dossier(
        source_snapshot_artifact_path=artifact_path,
        document=document,
        analysis=analysis,
        top_k=1,
    )

    evidence_packet = dossier["evidence_packet"]
    evidence_paths = [section["path"] for section in evidence_packet["sections"]]
    assert "wiki-ic/cases/ic-2025-292.md" in evidence_paths
    assert "wiki-ic/patterns/experimental-traction-gap.md" in evidence_paths
    assert "wiki-ic/raw/comments/raw-ic-2025-292-comments.md" in evidence_paths
    assert "wiki-ic/raw/minutes/raw-ic-2025-292-minutes.md" in evidence_paths
    assert "case summary incrementality hard KPI gate" in evidence_packet["markdown"]
    assert "real MP comment: how much is incremental?" in evidence_packet["markdown"]
    assert "real IC decision: rework until KPI gate is closed" in evidence_packet["markdown"]
    assert evidence_packet["packet_version"] == "expanded-wiki-evidence-v1"


def _create_source_snapshot(tmp_path, files: dict[str, str]):
    artifact_path = tmp_path / "skill-snapshots" / "source"
    files_root = artifact_path / "files"
    manifest_files = []
    for relative_path, content in files.items():
        path = files_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        manifest_files.append({"path": relative_path, "sha256": "unused"})
    (artifact_path / "manifest.json").write_text(
        '{"source_slug":"devils-advocate","files":[]}',
        encoding="utf-8",
    )
    return artifact_path
