import json
import io
import subprocess
import sys
from pathlib import Path

import pytest

from ic_review import script_runner, workbook_parser


def test_run_source_script_uses_argv_without_shell_and_persists_streams(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    logs_dir = tmp_path / "logs"
    captured = {}

    class FakeProcess:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            self.stdout = io.StringIO("stdout text")
            self.stderr = io.StringIO("stderr text")
            self.returncode = 0

        def wait(self, timeout=None):
            captured["timeout"] = timeout
            return self.returncode

        def kill(self):
            captured["killed"] = True

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess(args, **kwargs)

    monkeypatch.setattr(script_runner.subprocess, "Popen", fake_popen)

    result = script_runner.run_source_script(
        snapshot_workspace_root=workspace,
        args=[sys.executable, "scripts/invest/json_postprocess.py", "legacy.json"],
        log_dir=logs_dir,
        owner_root=tmp_path,
        script_name="json_postprocess",
    )

    assert captured["args"] == [sys.executable, "scripts/invest/json_postprocess.py", "legacy.json"]
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["cwd"] == workspace
    assert captured["kwargs"]["stdout"] == subprocess.PIPE
    assert captured["kwargs"]["stderr"] == subprocess.PIPE
    assert captured["kwargs"]["stdin"] == subprocess.DEVNULL
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["timeout"] == script_runner.DEFAULT_SCRIPT_TIMEOUT_SECONDS
    assert result.status == "completed"
    assert Path(result.stdout_path).read_text(encoding="utf-8") == "stdout text"
    assert Path(result.stderr_path).read_text(encoding="utf-8") == "stderr text"


def test_ensure_pdf_fonts_available_copies_snapshotted_dejavu_fonts(tmp_path):
    workspace = tmp_path / "workspace"
    fonts_dir = workspace / "fonts"
    target_dir = tmp_path / "system-fonts"
    fonts_dir.mkdir(parents=True)
    (fonts_dir / "DejaVuSans.ttf").write_bytes(b"regular")
    (fonts_dir / "DejaVuSans-Bold.ttf").write_bytes(b"bold")

    script_runner._ensure_pdf_fonts_available(workspace, target_dir=target_dir)

    assert (target_dir / "DejaVuSans.ttf").read_bytes() == b"regular"
    assert (target_dir / "DejaVuSans-Bold.ttf").read_bytes() == b"bold"
    assert (target_dir / "DejaVuSans-Oblique.ttf").read_bytes() == b"regular"


def test_run_source_script_passes_bounded_env_without_secrets(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    logs_dir = tmp_path / "logs"
    captured = {}
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("DATABASE_URL", "postgres://secret")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    class FakeProcess:
        stdout = io.StringIO("")
        stderr = io.StringIO("")

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    def fake_popen(args, **kwargs):
        captured["env"] = kwargs["env"]
        return FakeProcess()

    monkeypatch.setattr(script_runner.subprocess, "Popen", fake_popen)

    script_runner.run_source_script(
        snapshot_workspace_root=workspace,
        args=[sys.executable, "scripts/invest/json_postprocess.py", "legacy.json"],
        log_dir=logs_dir,
        owner_root=tmp_path,
        script_name="json_postprocess",
    )

    assert captured["env"]["PATH"] == "/usr/bin:/bin"
    assert captured["env"]["PYTHONPATH"].split(":")[0] == str(workspace)
    assert "OPENAI_API_KEY" not in captured["env"]
    assert "DATABASE_URL" not in captured["env"]
    assert "HTTPS_PROXY" not in captured["env"]


def test_run_source_script_represents_nonzero_exit_as_failed_and_keeps_logs(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    script_path = workspace / "fails.py"
    script_path.write_text(
        "import sys\n"
        "print('before fail')\n"
        "print('failure details', file=sys.stderr)\n"
        "sys.exit(3)\n",
        encoding="utf-8",
    )

    result = script_runner.run_source_script(
        snapshot_workspace_root=workspace,
        args=[sys.executable, str(script_path)],
        log_dir=tmp_path / "logs",
        owner_root=tmp_path,
        script_name="fails",
    )

    assert result.status == "failed"
    assert result.exit_code == 3
    assert Path(result.stdout_path).read_text(encoding="utf-8").strip() == "before fail"
    assert Path(result.stderr_path).read_text(encoding="utf-8").strip() == "failure details"


def test_run_source_script_timeout_records_partial_logs_and_timeout_marker(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    killed = {}

    class TimeoutProcess:
        pid = 12345
        stdout = io.StringIO("partial stdout")
        stderr = io.StringIO("partial stderr")

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="slow", timeout=timeout)

        def kill(self):
            killed["direct"] = True

    monkeypatch.setattr(script_runner.subprocess, "Popen", lambda *args, **kwargs: TimeoutProcess())
    monkeypatch.setattr(script_runner.os, "killpg", lambda pid, sig: killed.update({"pid": pid, "sig": sig}))

    result = script_runner.run_source_script(
        snapshot_workspace_root=workspace,
        args=[sys.executable, "scripts/invest/slow.py"],
        log_dir=tmp_path / "logs",
        owner_root=tmp_path,
        script_name="slow",
        timeout_seconds=1,
    )

    assert result.status == "failed"
    assert result.exit_code == -1
    assert Path(result.stdout_path).read_text(encoding="utf-8") == "partial stdout"
    stderr = Path(result.stderr_path).read_text(encoding="utf-8")
    assert killed == {"pid": 12345, "sig": script_runner.signal.SIGKILL}
    assert "partial stderr" in stderr
    assert "[TIMEOUT] script exceeded timeout_seconds=1" in stderr


def test_run_source_script_trims_persisted_logs(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class NoisyProcess:
        stdout = io.StringIO("a" * 30 + "b" * 30)
        stderr = io.StringIO("c" * 30 + "d" * 30)

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(script_runner.subprocess, "Popen", lambda *args, **kwargs: NoisyProcess())

    result = script_runner.run_source_script(
        snapshot_workspace_root=workspace,
        args=[sys.executable, "scripts/invest/noisy.py"],
        log_dir=tmp_path / "logs",
        owner_root=tmp_path,
        script_name="noisy",
        max_log_chars=50,
    )

    stdout = Path(result.stdout_path).read_text(encoding="utf-8")
    stderr = Path(result.stderr_path).read_text(encoding="utf-8")
    assert len(stdout) == 50
    assert len(stderr) == 50
    assert "[TRUNCATED:" in stdout
    assert "[TRUNCATED:" in stderr


def test_prepare_snapshot_workspace_copies_manifest_files_and_rejects_traversal(tmp_path):
    snapshot_dir = tmp_path / "snapshot"
    files_dir = snapshot_dir / "files" / "scripts" / "invest"
    files_dir.mkdir(parents=True)
    (files_dir / "json_postprocess.py").write_text("print('ok')\n", encoding="utf-8")
    (snapshot_dir / "manifest.json").write_text(
        json.dumps({"files": [{"path": "scripts/invest/json_postprocess.py"}]}),
        encoding="utf-8",
    )

    workspace = script_runner.prepare_snapshot_workspace(
        snapshot_dir=snapshot_dir,
        run_dir=tmp_path / "run",
    )

    copied = workspace / "scripts" / "invest" / "json_postprocess.py"
    assert copied.read_text(encoding="utf-8") == "print('ok')\n"

    (snapshot_dir / "manifest.json").write_text(
        json.dumps({"files": [{"path": "../escape.py"}]}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="source_snapshot_unavailable"):
        script_runner.prepare_snapshot_workspace(
            snapshot_dir=snapshot_dir,
            run_dir=tmp_path / "run",
        )


def test_run_ic_review_script_pipeline_without_workbook_skips_formula_and_excel(tmp_path):
    run_dir = tmp_path / "run"
    workspace = run_dir / "workspace"
    scripts_dir = workspace / "scripts" / "invest"
    scripts_dir.mkdir(parents=True)
    calls_path = workspace / "calls.txt"

    _write_script(
        scripts_dir / "json_postprocess.py",
        "import pathlib, sys\n"
        "pathlib.Path('calls.txt').open('a').write('json_postprocess ' + ' '.join(sys.argv[1:]) + '\\n')\n",
    )
    _write_script(
        scripts_dir / "validate_report.py",
        "import pathlib, sys\n"
        "pathlib.Path('calls.txt').open('a').write('validate_report ' + ' '.join(sys.argv[1:]) + '\\n')\n"
        "print('validation ok')\n",
    )
    _write_script(
        scripts_dir / "pdf_generator.py",
        "import pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "pathlib.Path('calls.txt').open('a').write('pdf_generator ' + ' '.join(args) + '\\n')\n"
        "pathlib.Path(args[args.index('--output') + 1]).write_bytes(b'%PDF-1.4\\n')\n",
    )
    _write_script(scripts_dir / "formula_auditor.py", "raise SystemExit('should not run')\n")
    _write_script(scripts_dir / "excel_audit.py", "raise SystemExit('should not run')\n")

    legacy_report = run_dir / "structured" / "legacy_report.json"
    legacy_report.parent.mkdir(parents=True)
    legacy_report.write_text(
        json.dumps(
            {
                "meta": {"title": "Legacy IC report"},
                "sections": {"section_1": {"content": "One compact section."}},
            }
        ),
        encoding="utf-8",
    )

    result = script_runner.run_ic_review_script_pipeline(
        run_dir=run_dir,
        snapshot_workspace_root=workspace,
        legacy_report_json_path=legacy_report,
        artifacts_dir=run_dir / "artifacts",
        log_dir=run_dir / "logs",
        workbook_path=None,
        python_executable=sys.executable,
    )

    assert [item.script_name for item in result.scripts] == [
        "json_postprocess",
        "pdf_generator",
        "validate_report",
    ]
    calls = calls_path.read_text(encoding="utf-8")
    assert "formula_auditor" not in calls
    assert "excel_audit" not in calls
    assert "pdf_generator" in calls
    assert "--pdf" in calls
    assert "--excel" not in calls
    assert Path(result.artifacts["postprocessed_json"]).is_file()
    legacy_markdown = Path(result.artifacts["legacy_report_markdown"])
    assert legacy_markdown.is_file()
    assert "Legacy IC report" in legacy_markdown.read_text(encoding="utf-8")
    assert Path(result.artifacts["legacy_report_pdf"]).is_file()
    assert Path(result.artifacts["validation_report"]).read_text(encoding="utf-8").strip() == "validation ok"


def test_run_ic_review_script_pipeline_with_existing_formula_audit_skips_formula_auditor(tmp_path):
    run_dir = tmp_path / "run"
    workspace = run_dir / "workspace"
    scripts_dir = workspace / "scripts" / "invest"
    scripts_dir.mkdir(parents=True)
    calls_path = workspace / "calls.txt"

    _write_script(scripts_dir / "formula_auditor.py", "raise SystemExit('should not run')\n")
    _write_script(
        scripts_dir / "json_postprocess.py",
        "import pathlib, sys\n"
        "pathlib.Path('calls.txt').open('a').write('json_postprocess ' + ' '.join(sys.argv[1:]) + '\\n')\n",
    )
    _write_script(
        scripts_dir / "excel_audit.py",
        "import pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "pathlib.Path('calls.txt').open('a').write('excel_audit ' + ' '.join(args) + '\\n')\n"
        "pathlib.Path(args[args.index('--output') + 1]).write_text('xlsx', encoding='utf-8')\n",
    )
    _write_script(
        scripts_dir / "validate_report.py",
        "import pathlib, sys\n"
        "pathlib.Path('calls.txt').open('a').write('validate_report ' + ' '.join(sys.argv[1:]) + '\\n')\n"
        "print('validation ok')\n",
    )
    _write_script(
        scripts_dir / "pdf_generator.py",
        "import pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "pathlib.Path('calls.txt').open('a').write('pdf_generator ' + ' '.join(args) + '\\n')\n"
        "pathlib.Path(args[args.index('--output') + 1]).write_bytes(b'%PDF-1.4\\n')\n",
    )

    legacy_report = run_dir / "structured" / "legacy_report.json"
    legacy_report.parent.mkdir(parents=True)
    legacy_report.write_text('{"sections": {}}', encoding="utf-8")
    workbook = run_dir / "uploads" / "model.xlsx"
    workbook.parent.mkdir(parents=True)
    workbook.write_bytes(b"xlsx")
    formula_audit = run_dir / "artifacts" / "formula_audit.json"
    formula_audit.parent.mkdir(parents=True)
    formula_audit.write_text('{"issues": []}', encoding="utf-8")
    stages = []

    result = script_runner.run_ic_review_script_pipeline(
        run_dir=run_dir,
        snapshot_workspace_root=workspace,
        legacy_report_json_path=legacy_report,
        artifacts_dir=run_dir / "artifacts",
        log_dir=run_dir / "logs",
        workbook_path=workbook,
        formula_audit_json_path=formula_audit,
        stage_callback=stages.append,
        python_executable=sys.executable,
    )

    assert [item.script_name for item in result.scripts] == [
        "json_postprocess",
        "pdf_generator",
        "excel_audit",
        "validate_report",
    ]
    calls = calls_path.read_text(encoding="utf-8")
    assert "formula_auditor" not in calls
    assert "pdf_generator" in calls
    assert "--pdf" in calls
    assert f"--formula-json {formula_audit}" in calls
    assert result.artifacts["formula_audit_json"] == str(formula_audit)
    assert stages == ["json_postprocess", "pdf_generator", "excel_audit", "validate_report"]


def test_run_ic_review_script_pipeline_rejects_paths_outside_run_dir(tmp_path):
    run_dir = tmp_path / "run"
    workspace = run_dir / "workspace"
    (workspace / "scripts" / "invest").mkdir(parents=True)
    legacy_report = run_dir / "structured" / "legacy_report.json"
    legacy_report.parent.mkdir(parents=True)
    legacy_report.write_text('{"sections": {}}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="script_log_dir_escapes_run_dir"):
        script_runner.run_ic_review_script_pipeline(
            run_dir=run_dir,
            snapshot_workspace_root=workspace,
            legacy_report_json_path=legacy_report,
            artifacts_dir=run_dir / "artifacts",
            log_dir=tmp_path / "outside_logs",
            workbook_path=None,
            python_executable=sys.executable,
        )

    with pytest.raises(RuntimeError, match="legacy_report_json_escapes_run_dir"):
        script_runner.run_ic_review_script_pipeline(
            run_dir=run_dir,
            snapshot_workspace_root=workspace,
            legacy_report_json_path=tmp_path / "outside_legacy_report.json",
            artifacts_dir=run_dir / "artifacts",
            log_dir=run_dir / "logs",
            workbook_path=None,
            python_executable=sys.executable,
        )

    with pytest.raises(RuntimeError, match="script_artifact_escapes_run_dir"):
        script_runner.run_source_script(
            snapshot_workspace_root=workspace,
            args=[sys.executable, "scripts/invest/json_postprocess.py"],
            log_dir=run_dir / "logs",
            owner_root=run_dir,
            script_name="json_postprocess",
            artifact_paths=[tmp_path / "outside.json"],
        )

    with pytest.raises(RuntimeError, match="workbook_path_escapes_run_dir"):
        script_runner.run_ic_review_script_pipeline(
            run_dir=run_dir,
            snapshot_workspace_root=workspace,
            legacy_report_json_path=legacy_report,
            artifacts_dir=run_dir / "artifacts",
            log_dir=run_dir / "logs",
            workbook_path=tmp_path / "outside.xlsx",
            python_executable=sys.executable,
        )


def test_validation_report_includes_stderr_exit_metadata_on_failure(tmp_path):
    run_dir = tmp_path / "run"
    workspace = run_dir / "workspace"
    scripts_dir = workspace / "scripts" / "invest"
    scripts_dir.mkdir(parents=True)

    _write_script(scripts_dir / "json_postprocess.py", "")
    _write_script(
        scripts_dir / "validate_report.py",
        "import sys\n"
        "print('validation broke', file=sys.stderr)\n"
        "sys.exit(2)\n",
    )

    legacy_report = run_dir / "structured" / "legacy_report.json"
    legacy_report.parent.mkdir(parents=True)
    legacy_report.write_text('{"sections": {}}', encoding="utf-8")

    result = script_runner.run_ic_review_script_pipeline(
        run_dir=run_dir,
        snapshot_workspace_root=workspace,
        legacy_report_json_path=legacy_report,
        artifacts_dir=run_dir / "artifacts",
        log_dir=run_dir / "logs",
        workbook_path=None,
        python_executable=sys.executable,
    )

    report = Path(result.artifacts["validation_report"]).read_text(encoding="utf-8")
    assert result.scripts[-1].status == "failed"
    assert "status: failed" in report
    assert "exit_code: 2" in report
    assert "stdout:\n<empty>" in report
    assert "stderr:\nvalidation broke" in report


def test_extract_workbook_snapshot_bounds_formulas_values_and_redaction(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook_path = tmp_path / "financial_model.xlsx"
    workbook = openpyxl.Workbook()
    first_sheet = workbook.active
    first_sheet.title = "Financials"
    for index in range(2, workbook_parser.MAX_SHEETS + 2):
        workbook.create_sheet(f"Extra {index}")
    first_sheet["A1"] = "Metric"
    first_sheet["A2"] = 10
    first_sheet["B2"] = "=A2*2"
    first_sheet["C3"] = "x" * (workbook_parser.MAX_CELL_TEXT_LENGTH + 1)
    first_sheet.cell(
        row=workbook_parser.MAX_ROWS_PER_SHEET + 1,
        column=workbook_parser.MAX_COLUMNS_PER_ROW + 1,
        value="outside extraction bounds",
    )
    workbook.save(workbook_path)
    workbook.close()

    snapshot = workbook_parser.extract_workbook_snapshot(workbook_path)

    assert snapshot["format"] == "xlsx_bounded_snapshot_v1"
    assert snapshot["source_filename"] == "financial_model.xlsx"
    assert snapshot["sheet_count"] == workbook_parser.MAX_SHEETS + 1
    assert snapshot["sheets_truncated"] is True
    assert len(snapshot["sheets"]) == workbook_parser.MAX_SHEETS

    first = snapshot["sheets"][0]
    assert first["name"] == "Financials"
    assert first["dimensions"]["max_row"] == workbook_parser.MAX_ROWS_PER_SHEET + 1
    assert first["dimensions"]["max_column"] == workbook_parser.MAX_COLUMNS_PER_ROW + 1
    assert first["rows_truncated"] is True
    assert first["columns_truncated"] is True

    cells = {
        cell["address"]: cell
        for row in first["rows"]
        for cell in row["cells"]
    }
    assert cells["B2"]["formula"] == "=A2*2"
    assert "data_only_value" in cells["B2"]
    assert cells["C3"]["value"] == {
        "redacted": True,
        "reason": "cell_text_too_long",
        "length": workbook_parser.MAX_CELL_TEXT_LENGTH + 1,
    }
    assert "AE81" not in cells


def test_extract_workbook_snapshot_uses_linear_row_iteration(tmp_path, monkeypatch):
    openpyxl = pytest.importorskip("openpyxl")

    class FakeCell:
        def __init__(self, coordinate, value):
            self.coordinate = coordinate
            self.value = value

    class FakeSheet:
        title = "Financials"
        max_row = 2
        max_column = 2

        def __init__(self, rows):
            self._rows = rows

        def iter_rows(self, *, max_row, max_col):
            assert max_row == 2
            assert max_col == 2
            return iter(tuple(row[:max_col]) for row in self._rows[:max_row])

        def cell(self, *, row, column):
            raise AssertionError("read-only sheets must be consumed through iter_rows")

    class FakeWorkbook:
        sheetnames = ["Financials"]

        def __init__(self, sheet):
            self._sheet = sheet
            self.closed = False

        def __getitem__(self, name):
            assert name == "Financials"
            return self._sheet

        def close(self):
            self.closed = True

    formula_sheet = FakeSheet(
        [
            [FakeCell("A1", "Metric"), FakeCell("B1", "Value")],
            [FakeCell("A2", "ARR"), FakeCell("B2", "=A2*2")],
        ]
    )
    values_sheet = FakeSheet(
        [
            [FakeCell("A1", "Metric"), FakeCell("B1", "Value")],
            [FakeCell("A2", "ARR"), FakeCell("B2", 20)],
        ]
    )
    workbooks = {
        False: FakeWorkbook(formula_sheet),
        True: FakeWorkbook(values_sheet),
    }

    def fake_load_workbook(path, *, data_only, read_only):
        assert read_only is True
        return workbooks[data_only]

    monkeypatch.setattr(openpyxl, "load_workbook", fake_load_workbook)

    snapshot = workbook_parser.extract_workbook_snapshot(tmp_path / "financial_model.xlsx")

    cells = {
        cell["address"]: cell
        for row in snapshot["sheets"][0]["rows"]
        for cell in row["cells"]
    }
    assert cells["B2"] == {
        "address": "B2",
        "column": 2,
        "formula": "=A2*2",
        "data_only_value": 20,
    }
    assert workbooks[False].closed is True
    assert workbooks[True].closed is True


def _write_script(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
