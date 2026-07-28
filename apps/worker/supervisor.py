from __future__ import annotations

import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence


WORKER_QUEUE_GROUPS = (
    ("documents",),
    ("analysis", "benchmark"),
)


def worker_commands(python_executable: str = sys.executable) -> list[list[str]]:
    return [
        [python_executable, "worker.py", *queue_names]
        for queue_names in WORKER_QUEUE_GROUPS
    ]


def supervise_worker_processes(
    *,
    popen: Callable[[Sequence[str]], subprocess.Popen] = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
    install_signal_handlers: bool = True,
) -> int:
    processes: list[subprocess.Popen] = []
    stop_requested = False
    previous_handlers: dict[signal.Signals, signal.Handlers] = {}

    def request_stop(_signum=None, _frame=None) -> None:
        nonlocal stop_requested
        stop_requested = True

    try:
        for command in worker_commands():
            processes.append(popen(command))

        if install_signal_handlers:
            for signal_number in (signal.SIGTERM, signal.SIGINT):
                previous_handlers[signal_number] = signal.signal(signal_number, request_stop)

        while not stop_requested:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    return return_code
            sleep(0.2)
        return 0
    finally:
        _stop_processes(processes)
        for signal_number, handler in previous_handlers.items():
            signal.signal(signal_number, handler)


def _stop_processes(processes: Sequence[subprocess.Popen]) -> None:
    running = [process for process in processes if process.poll() is None]
    for process in running:
        process.terminate()
    for process in running:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    raise SystemExit(supervise_worker_processes())
