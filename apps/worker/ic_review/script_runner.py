from __future__ import annotations

import json
import os
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


WORKSPACE_DIR_NAME = "source_snapshot_workspace"
DEFAULT_SCRIPT_TIMEOUT_SECONDS = 600
MAX_PERSISTED_LOG_CHARS = 200_000
STREAM_READ_CHARS = 8192
SAFE_SUBPROCESS_ENV_KEYS = {
    "PATH",
    "PYTHONPATH",
    "PYTHONHOME",
    "VIRTUAL_ENV",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TEMP",
    "TMP",
}


@dataclass(frozen=True)
class ScriptResult:
    script_name: str
    args: list[str]
    status: str
    exit_code: int
    elapsed_ms: int
    stdout_path: str
    stderr_path: str
    artifact_paths: list[str]

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True)
class ScriptPipelineResult:
    scripts: list[ScriptResult]
    artifacts: dict[str, str]

    @property
    def succeeded(self) -> bool:
        return all(script.succeeded for script in self.scripts)


def prepare_snapshot_workspace(*, snapshot_dir: Path | str, run_dir: Path | str) -> Path:
    """Copy a saved skill source snapshot into a clean per-run execution workspace."""
    source_root = Path(snapshot_dir).expanduser().resolve()
    manifest_path = source_root / "manifest.json"
    files_root = (source_root / "files").resolve()
    if not manifest_path.is_file() or not files_root.is_dir():
        raise RuntimeError("source_snapshot_unavailable")

    run_root = Path(run_dir).expanduser().resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    workspace_root = (run_root / WORKSPACE_DIR_NAME).resolve()
    if not workspace_root.is_relative_to(run_root):
        raise RuntimeError("source_snapshot_workspace_invalid")
    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    workspace_root.mkdir(parents=True)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest.get("files", []):
        relative_path = _safe_relative_path(str(item["path"]))
        source_path = (files_root / relative_path).resolve()
        if not source_path.is_relative_to(files_root) or not source_path.is_file():
            raise RuntimeError("source_snapshot_unavailable")
        target_path = (workspace_root / relative_path).resolve()
        if not target_path.is_relative_to(workspace_root):
            raise RuntimeError("source_snapshot_unavailable")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)

    return workspace_root


def run_source_script(
    *,
    snapshot_workspace_root: Path | str,
    args: list[str | Path],
    log_dir: Path | str,
    owner_root: Path | str,
    script_name: str | None = None,
    artifact_paths: Iterable[Path | str] = (),
    timeout_seconds: int = DEFAULT_SCRIPT_TIMEOUT_SECONDS,
    max_log_chars: int = MAX_PERSISTED_LOG_CHARS,
) -> ScriptResult:
    if not isinstance(args, list):
        raise TypeError("args must be a list; shell execution is not supported")

    workspace_root = Path(snapshot_workspace_root).expanduser().resolve()
    if not workspace_root.is_dir():
        raise RuntimeError("source_snapshot_workspace_unavailable")
    owner = Path(owner_root).expanduser().resolve()
    if not workspace_root.is_relative_to(owner):
        raise RuntimeError("source_snapshot_workspace_escapes_run_dir")

    safe_script_name = _safe_log_name(script_name or _script_name_from_args(args))
    logs_root = _resolve_owned_path(log_dir, owner, "script_log_dir_escapes_run_dir")
    logs_root.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_root / f"{safe_script_name}.stdout.txt"
    stderr_path = logs_root / f"{safe_script_name}.stderr.txt"
    normalized_args = [str(arg) for arg in args]
    owned_artifacts = [
        _resolve_owned_path(path, owner, "script_artifact_escapes_run_dir") for path in artifact_paths
    ]

    stdout_capture = _BoundedTextCapture(max_log_chars=max_log_chars)
    stderr_capture = _BoundedTextCapture(max_log_chars=max_log_chars)
    started = time.perf_counter()
    try:
        process = subprocess.Popen(
            normalized_args,
            shell=False,
            cwd=workspace_root,
            env=_bounded_subprocess_env(workspace_root=workspace_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        stdout_thread = _start_stream_capture_thread(process.stdout, stdout_capture)
        stderr_thread = _start_stream_capture_thread(process.stderr, stderr_capture)
        try:
            exit_code = int(process.wait(timeout=timeout_seconds))
        except subprocess.TimeoutExpired:
            _kill_process_tree(process)
            exit_code = -1
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            stderr_capture.append(f"\n[TIMEOUT] script exceeded timeout_seconds={timeout_seconds}\n")
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            _kill_process_tree(process)
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
    except subprocess.TimeoutExpired as exc:
        exit_code = -1
        stdout_capture.append(_coerce_output(exc.stdout))
        stderr_capture.append(_coerce_output(exc.stderr))
        timeout_marker = f"[TIMEOUT] script exceeded timeout_seconds={timeout_seconds}"
        stderr_capture.append(f"\n{timeout_marker}\n")
    except OSError as exc:
        exit_code = -1
        stderr_capture.append(str(exc))
    elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))

    stdout_path.write_text(stdout_capture.text(), encoding="utf-8")
    stderr_path.write_text(stderr_capture.text(), encoding="utf-8")
    return ScriptResult(
        script_name=safe_script_name,
        args=normalized_args,
        status="completed" if exit_code == 0 else "failed",
        exit_code=exit_code,
        elapsed_ms=elapsed_ms,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        artifact_paths=[str(path) for path in owned_artifacts],
    )


def run_ic_review_script_pipeline(
    *,
    run_dir: Path | str,
    snapshot_workspace_root: Path | str,
    legacy_report_json_path: Path | str,
    artifacts_dir: Path | str,
    log_dir: Path | str,
    workbook_path: Path | str | None,
    formula_audit_json_path: Path | str | None = None,
    stage_callback: Callable[[str], None] | None = None,
    python_executable: str | None = None,
    timeout_seconds: int = DEFAULT_SCRIPT_TIMEOUT_SECONDS,
) -> ScriptPipelineResult:
    python = python_executable or sys.executable
    run_root = Path(run_dir).expanduser().resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    workspace_root = _resolve_owned_path(
        snapshot_workspace_root,
        run_root,
        "source_snapshot_workspace_escapes_run_dir",
    )
    if not workspace_root.is_dir():
        raise RuntimeError("source_snapshot_workspace_unavailable")
    artifacts_root = _resolve_owned_path(artifacts_dir, run_root, "script_artifact_dir_escapes_run_dir")
    logs_root = _resolve_owned_path(log_dir, run_root, "script_log_dir_escapes_run_dir")
    artifacts_root.mkdir(parents=True, exist_ok=True)

    legacy_report = _resolve_owned_path(
        legacy_report_json_path,
        run_root,
        "legacy_report_json_escapes_run_dir",
    )
    postprocessed_json = artifacts_root / "postprocessed_legacy_report.json"
    formula_audit = (
        _resolve_owned_path(formula_audit_json_path, run_root, "formula_audit_json_escapes_run_dir")
        if formula_audit_json_path is not None
        else artifacts_root / "formula_audit.json"
    )
    legacy_report_text = artifacts_root / "legacy_report.txt"
    legacy_audit_xlsx = artifacts_root / "legacy_audit.xlsx"
    validation_report = artifacts_root / "validation_report.txt"

    shutil.copy2(legacy_report, postprocessed_json)

    scripts: list[ScriptResult] = []
    if workbook_path is not None and formula_audit_json_path is None:
        workbook = _resolve_owned_path(workbook_path, run_root, "workbook_path_escapes_run_dir")
        _notify_stage(stage_callback, "formula_auditor")
        scripts.append(
            run_source_script(
                snapshot_workspace_root=workspace_root,
                args=[
                    python,
                    "scripts/invest/formula_auditor.py",
                    workbook,
                    "--json",
                    "--output",
                    formula_audit,
                ],
                log_dir=logs_root,
                script_name="formula_auditor",
                artifact_paths=[formula_audit],
                owner_root=run_root,
                timeout_seconds=timeout_seconds,
            )
        )
    elif workbook_path is not None and not formula_audit.is_file():
        raise RuntimeError("formula_audit_json_missing")

    _notify_stage(stage_callback, "json_postprocess")
    scripts.append(
        run_source_script(
            snapshot_workspace_root=workspace_root,
            args=[python, "scripts/invest/json_postprocess.py", postprocessed_json],
            log_dir=logs_root,
            script_name="json_postprocess",
            artifact_paths=[postprocessed_json],
            owner_root=run_root,
            timeout_seconds=timeout_seconds,
        )
    )
    _write_legacy_report_text(postprocessed_json, legacy_report_text)

    if workbook_path is not None:
        workbook = _resolve_owned_path(workbook_path, run_root, "workbook_path_escapes_run_dir")
        _notify_stage(stage_callback, "excel_audit")
        scripts.append(
            run_source_script(
                snapshot_workspace_root=workspace_root,
                args=[
                    python,
                    "scripts/invest/excel_audit.py",
                    "--source",
                    workbook,
                    "--data",
                    postprocessed_json,
                    "--formula-json",
                    formula_audit,
                    "--output",
                    legacy_audit_xlsx,
                ],
                log_dir=logs_root,
                script_name="excel_audit",
                artifact_paths=[legacy_audit_xlsx],
                owner_root=run_root,
                timeout_seconds=timeout_seconds,
            )
        )

    validate_args: list[str | Path] = [
        python,
        "scripts/invest/validate_report.py",
        "--json",
        postprocessed_json,
    ]
    artifacts = {
        "postprocessed_json": str(postprocessed_json),
        "legacy_report_text": str(legacy_report_text),
        "validation_report": str(validation_report),
    }
    if workbook_path is not None:
        validate_args.extend(["--excel", legacy_audit_xlsx])
        artifacts["formula_audit_json"] = str(formula_audit)
        artifacts["legacy_audit_xlsx"] = str(legacy_audit_xlsx)

    _notify_stage(stage_callback, "validate_report")
    validate_result = run_source_script(
        snapshot_workspace_root=workspace_root,
        args=validate_args,
        log_dir=logs_root,
        script_name="validate_report",
        artifact_paths=[validation_report],
        owner_root=run_root,
        timeout_seconds=timeout_seconds,
    )
    scripts.append(validate_result)
    validation_report.write_text(_validation_report_text(validate_result), encoding="utf-8")

    return ScriptPipelineResult(scripts=scripts, artifacts=artifacts)


def _notify_stage(stage_callback: Callable[[str], None] | None, script_name: str) -> None:
    if stage_callback is not None:
        stage_callback(script_name)


def _write_legacy_report_text(json_path: Path, output_path: Path) -> None:
    source_text = json_path.read_text(encoding="utf-8")
    try:
        payload = json.loads(source_text)
    except json.JSONDecodeError:
        output_path.write_text(source_text, encoding="utf-8")
        return
    output_path.write_text(_legacy_report_debug_text(payload), encoding="utf-8")


def _legacy_report_debug_text(payload: object) -> str:
    if not isinstance(payload, dict):
        return json.dumps(payload, ensure_ascii=False, indent=2)

    lines: list[str] = ["# IC Review Legacy Output"]
    meta = payload.get("meta")
    if isinstance(meta, dict):
        _append_mapping(lines, "Meta", meta)

    sections = payload.get("sections")
    if isinstance(sections, dict):
        for section_key in sorted(sections.keys(), key=_section_sort_key):
            lines.append("")
            lines.append(f"## {section_key}")
            _append_value(lines, sections[section_key])

    for key in ("scenarios", "formula_issues", "kpis", "risks_structured", "appendices"):
        if key in payload:
            lines.append("")
            lines.append(f"## {key}")
            _append_value(lines, payload[key])

    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


def _append_mapping(lines: list[str], title: str, value: dict) -> None:
    lines.append("")
    lines.append(f"## {title}")
    for key, item in value.items():
        if isinstance(item, (dict, list)):
            lines.append(f"{key}: {json.dumps(item, ensure_ascii=False, sort_keys=True)}")
        else:
            lines.append(f"{key}: {item}")


def _append_value(lines: list[str], value: object) -> None:
    if isinstance(value, dict):
        content = value.get("content")
        if content:
            lines.append(str(content))
        for key, item in value.items():
            if key == "content":
                continue
            if isinstance(item, list):
                for entry in item:
                    lines.append(f"- {entry if not isinstance(entry, (dict, list)) else json.dumps(entry, ensure_ascii=False, sort_keys=True)}")
            elif isinstance(item, dict):
                lines.append(f"{key}: {json.dumps(item, ensure_ascii=False, sort_keys=True)}")
            elif item not in (None, ""):
                lines.append(f"{key}: {item}")
    elif isinstance(value, list):
        if not value:
            lines.append("[]")
        for entry in value:
            lines.append(f"- {entry if not isinstance(entry, (dict, list)) else json.dumps(entry, ensure_ascii=False, sort_keys=True)}")
    else:
        lines.append(str(value))


def _section_sort_key(value: str) -> tuple[int, str]:
    match = re.search(r"(\d+)$", value)
    return (int(match.group(1)) if match else 9999, value)


def _safe_relative_path(path: str) -> Path:
    relative_path = Path(path)
    if (
        relative_path.is_absolute()
        or not relative_path.parts
        or any(part in ("", ".", "..") for part in relative_path.parts)
    ):
        raise RuntimeError("source_snapshot_unavailable")
    return relative_path


def _script_name_from_args(args: list[str | Path]) -> str:
    for arg in args:
        path = Path(str(arg))
        if path.suffix == ".py":
            return path.stem
    return "script"


def _safe_log_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "script"


def _resolve_owned_path(path: Path | str, owner_root: Path | None, error_code: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if owner_root is not None and not resolved.is_relative_to(owner_root):
        raise RuntimeError(error_code)
    return resolved


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _start_stream_capture_thread(pipe, capture: "_BoundedTextCapture") -> threading.Thread:
    thread = threading.Thread(target=_capture_stream, args=(pipe, capture), daemon=True)
    thread.start()
    return thread


def _kill_process_tree(process: subprocess.Popen) -> None:
    pid = process.pid
    if hasattr(os, "killpg"):
        try:
            os.killpg(pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    process.kill()


def _bounded_subprocess_env(*, workspace_root: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key in SAFE_SUBPROCESS_ENV_KEYS and value
    }
    env.setdefault("PATH", os.defpath)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{workspace_root}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(workspace_root)
    )
    return env


def _capture_stream(pipe, capture: "_BoundedTextCapture") -> None:
    if pipe is None:
        return
    try:
        while True:
            chunk = pipe.read(STREAM_READ_CHARS)
            if not chunk:
                break
            capture.append(_coerce_output(chunk))
    finally:
        try:
            pipe.close()
        except OSError:
            pass


class _BoundedTextCapture:
    def __init__(self, *, max_log_chars: int) -> None:
        self.max_log_chars = max_log_chars
        self.total_chars = 0
        self._head = ""
        self._tail = ""
        self._truncated = False

    def append(self, value: str) -> None:
        if not value:
            return
        self.total_chars += len(value)
        if self.max_log_chars <= 0:
            self._truncated = True
            return
        if not self._truncated:
            combined = f"{self._head}{value}"
            if len(combined) <= self.max_log_chars:
                self._head = combined
                return
            self._truncated = True
            self._head = combined[: self.max_log_chars]
            self._tail = combined[-self.max_log_chars :]
            return
        self._tail = f"{self._tail}{value}"[-self.max_log_chars :]

    def text(self) -> str:
        if not self._truncated:
            return self._head
        omitted = max(0, self.total_chars - self.max_log_chars)
        marker = f"\n[TRUNCATED: omitted {omitted} characters]\n"
        budget = self.max_log_chars - len(marker)
        if budget <= 0:
            return self._head[: self.max_log_chars]
        head_chars = budget // 2
        tail_chars = budget - head_chars
        return f"{self._head[:head_chars]}{marker}{self._tail[-tail_chars:]}"


def _trim_text(value: str, max_chars: int) -> str:
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    omitted = len(value) - max_chars
    marker = f"\n[TRUNCATED: omitted {omitted} characters]\n"
    budget = max_chars - len(marker)
    if budget <= 0:
        return value[:max_chars]
    head_chars = budget // 2
    tail_chars = budget - head_chars
    return f"{value[:head_chars]}{marker}{value[-tail_chars:]}"


def _validation_report_text(validate_result: ScriptResult) -> str:
    stdout = Path(validate_result.stdout_path).read_text(encoding="utf-8")
    stderr = Path(validate_result.stderr_path).read_text(encoding="utf-8")
    if validate_result.exit_code == 0 and not stderr.strip():
        return stdout

    sections = [
        f"status: {validate_result.status}",
        f"exit_code: {validate_result.exit_code}",
        "",
        "stdout:",
        stdout.rstrip() or "<empty>",
        "",
        "stderr:",
        stderr.rstrip() or "<empty>",
        "",
    ]
    return "\n".join(sections)
