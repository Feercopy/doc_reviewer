from pathlib import Path
from uuid import UUID

import pytest

from app.core.config import get_settings
from app.main import app
from app.models.document import Document
from app.models.etalon import Etalon
from app.routers import etalons as etalons_router
from app.schemas.enums import DocumentParseStatus, EtalonStatus, Role
from app.services.gate2_benchmark_cases import (
    discover_gate2_benchmark_cases,
    gate2_case_to_etalon_payload,
    parse_gate2_etalon_csv,
)

from test_documents_upload import create_user, login


@pytest.fixture()
def storage_root(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    yield tmp_path / "storage"
    get_settings.cache_clear()


@pytest.fixture()
def enqueued_parse_jobs():
    enqueued: list[str] = []
    app.dependency_overrides[etalons_router.get_parse_document_enqueue] = lambda: lambda document_id: enqueued.append(str(document_id))
    yield enqueued
    app.dependency_overrides.pop(etalons_router.get_parse_document_enqueue, None)


def test_discovers_gate2_cases_with_csv_preferred(tmp_path):
    benchmark_dir = _write_benchmark_tree(tmp_path, include_travel=True)

    cases = discover_gate2_benchmark_cases(benchmark_dir)

    assert [case.name for case in cases] == ["travel", "trx-se"]
    trx = next(case for case in cases if case.name == "trx-se")
    travel = next(case for case in cases if case.name == "travel")
    assert trx.original_path.name == "TRX_SE.md"
    assert trx.etalon_path.name == "SE TRX bench.csv"
    assert trx.etalon_markdown_path and trx.etalon_markdown_path.name == "SE TRX bench.md"
    assert travel.original_path.name == "travel.dotx"
    assert travel.etalon_path.name == "Travel bench.csv"


def test_parses_gate2_csv_into_valid_etalon_payload(tmp_path):
    benchmark_dir = _write_benchmark_tree(tmp_path)
    case = discover_gate2_benchmark_cases(benchmark_dir)[0]

    parsed = parse_gate2_etalon_csv(case.etalon_path)
    payload = gate2_case_to_etalon_payload(case)

    assert parsed.input_doc_url == "https://example.test/trx"
    assert payload.expected_verdict == "need_evidence"
    assert [item.id for item in payload.layer_1] == [
        "L1-problem-framing-and-segments-1",
        "L1-problem-framing-and-segments-2",
    ]
    assert payload.layer_1[0].status == "partial"
    assert payload.layer_1[0].severity == "high"
    assert payload.layer_1[0].evidence[0].location == "Gate2 benchmark etalon: Layer 1 / Problem framing and segments"
    assert payload.layer_2[0].id == "L2-problem-framing-and-segments-1"
    assert payload.layer_2[0].parent_layer_1_id == "L1-problem-framing-and-segments-1"
    assert payload.layer_2[0].status == "fail"
    assert payload.layer_2[0].severity == "high"
    assert payload.layer_2[1].status == "partial"
    assert payload.layer_2[1].severity == "medium"


def test_admin_imports_gate2_benchmark_into_project_storage(
    client,
    db_session,
    tmp_path,
    storage_root,
    enqueued_parse_jobs,
):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    benchmark_dir = _write_benchmark_tree(tmp_path)
    login(client, admin.login, "secret")

    response = client.post(
        "/etalons/import/gate2-benchmark",
        json={"benchmark_dir": str(benchmark_dir), "activate": True},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["imported_count"] == 1
    assert payload["skipped_count"] == 0
    assert payload["parse_enqueued_count"] == 1
    assert len(payload["etalons"]) == 1

    etalon_id = UUID(payload["etalons"][0]["id"])
    etalon = db_session.get(Etalon, etalon_id)
    assert etalon is not None
    assert etalon.status == EtalonStatus.ACTIVE.value
    assert etalon.source == "gate2_benchmark"
    assert etalon.layer_1[0]["id"] == "L1-problem-framing-and-segments-1"
    assert etalon.layer_2[0]["parent_layer_1_id"] == "L1-problem-framing-and-segments-1"
    assert etalon.source_metadata["case_name"] == "trx-se"
    assert etalon.source_metadata["original_path"] == "original/TRX_SE.md"
    assert etalon.source_metadata["etalon_csv_path"] == "Эталоны/csv_by_document/SE TRX bench.csv"

    document = db_session.get(Document, etalon.document_id)
    assert document is not None
    assert document.owner_id == admin.id
    assert document.original_filename == "TRX_SE.md"
    assert document.manual_document_type == "gate_2"
    assert document.parse_status == DocumentParseStatus.QUEUED.value
    stored_path = Path(document.storage_path)
    assert stored_path.is_file()
    assert stored_path.read_text(encoding="utf-8") == "# TRX\n\nOriginal document"
    assert stored_path.resolve().is_relative_to(storage_root.resolve())
    assert enqueued_parse_jobs == [str(document.id)]


def test_gate2_benchmark_import_requires_admin(client, db_session, tmp_path, storage_root):
    user = create_user(db_session, "user", "secret")
    benchmark_dir = _write_benchmark_tree(tmp_path)
    login(client, user.login, "secret")

    response = client.post(
        "/etalons/import/gate2-benchmark",
        json={"benchmark_dir": str(benchmark_dir), "activate": True},
    )

    assert response.status_code == 403
    assert db_session.query(Etalon).count() == 0


def test_gate2_benchmark_import_is_idempotent(client, db_session, tmp_path, storage_root, enqueued_parse_jobs):
    admin = create_user(db_session, "admin", "secret", Role.ADMIN)
    benchmark_dir = _write_benchmark_tree(tmp_path)
    login(client, admin.login, "secret")

    first = client.post(
        "/etalons/import/gate2-benchmark",
        json={"benchmark_dir": str(benchmark_dir), "activate": True},
    )
    second = client.post(
        "/etalons/import/gate2-benchmark",
        json={"benchmark_dir": str(benchmark_dir), "activate": True},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["imported_count"] == 0
    assert second.json()["skipped_count"] == 1
    assert db_session.query(Document).count() == 1
    assert db_session.query(Etalon).count() == 1
    assert len(enqueued_parse_jobs) == 1


def _write_benchmark_tree(tmp_path, *, include_travel: bool = False) -> Path:
    benchmark_dir = tmp_path / "benchmark"
    original_dir = benchmark_dir / "original"
    etalon_dir = benchmark_dir / "Эталоны"
    csv_dir = etalon_dir / "csv_by_document"
    original_dir.mkdir(parents=True)
    csv_dir.mkdir(parents=True)

    (original_dir / "TRX_SE.md").write_text("# TRX\n\nOriginal document", encoding="utf-8")
    (etalon_dir / "SE TRX bench.md").write_text("## Layer 1\n\nMarkdown trace", encoding="utf-8")
    (csv_dir / "SE TRX bench.csv").write_text(_gate2_csv(), encoding="utf-8")

    if include_travel:
        (original_dir / "travel.dotx").write_bytes(b"dotx bytes")
        (etalon_dir / "Travel bench.md").write_text("## Layer 1\n\nTravel trace", encoding="utf-8")
        (csv_dir / "Travel bench.csv").write_text(_gate2_csv(url="https://example.test/travel"), encoding="utf-8")

    return benchmark_dir


def _gate2_csv(*, url: str = "https://example.test/trx") -> str:
    return (
        "section,block,status,item_type,item_id,field,value\n"
        f"metadata,Input Doc,,,,url,{url}\n"
        "Layer 1,verdict,,,,value,NEED_EVIDENCE\n"
        "Layer 1,Problem framing and segments,PARTIAL,dimension,,status,PARTIAL\n"
        "Layer 1,Problem framing and segments,PARTIAL,issue,1,id,1\n"
        "Layer 1,Problem framing and segments,PARTIAL,issue,1,issue,First L1 issue\n"
        "Layer 1,Problem framing and segments,PARTIAL,issue,1,evidence,First L1 evidence\n"
        "Layer 1,Problem framing and segments,PARTIAL,issue,1,severity,HIGH\n"
        "Layer 1,Problem framing and segments,PARTIAL,issue,2,id,2\n"
        "Layer 1,Problem framing and segments,PARTIAL,issue,2,issue,Second L1 issue\n"
        "Layer 1,Problem framing and segments,PARTIAL,issue,2,evidence,Second L1 evidence\n"
        "Layer 1,Problem framing and segments,PARTIAL,issue,2,severity,LOW\n"
        "Layer 2,Problem framing and segments,PARTIAL,atomic_check_block,,status,PARTIAL\n"
        "Layer 2,Problem framing and segments,PARTIAL,atomic_check,1,question,Question one?\n"
        "Layer 2,Problem framing and segments,PARTIAL,atomic_check,1,answer,NO\n"
        "Layer 2,Problem framing and segments,PARTIAL,atomic_check,1,evidence,First L2 evidence\n"
        "Layer 2,Problem framing and segments,PARTIAL,atomic_check,1,issue,First L2 issue\n"
        "Layer 2,Problem framing and segments,PARTIAL,atomic_check,2,question,Question two?\n"
        "Layer 2,Problem framing and segments,PARTIAL,atomic_check,2,answer,PARTIAL\n"
        "Layer 2,Problem framing and segments,PARTIAL,atomic_check,2,evidence,Second L2 evidence\n"
        "Layer 2,Problem framing and segments,PARTIAL,atomic_check,2,issue,Second L2 issue\n"
    )
