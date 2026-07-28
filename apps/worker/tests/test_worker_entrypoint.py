import pytest

from supervisor import supervise_worker_processes, worker_commands
from worker import QUEUE_NAMES, selected_queue_names


def test_worker_defaults_to_all_queues():
    assert selected_queue_names([]) == QUEUE_NAMES


def test_worker_accepts_dedicated_queue_groups():
    assert selected_queue_names(["documents"]) == ["documents"]
    assert selected_queue_names(["analysis", "benchmark"]) == ["analysis", "benchmark"]


def test_worker_rejects_unknown_queue_names():
    with pytest.raises(ValueError, match="Unknown worker queues: emails"):
        selected_queue_names(["emails"])


def test_supervisor_starts_independent_document_and_analysis_workers():
    assert worker_commands("python") == [
        ["python", "worker.py", "documents"],
        ["python", "worker.py", "analysis", "benchmark"],
    ]


def test_supervisor_stops_sibling_when_a_worker_exits():
    processes = [_FakeProcess(), _FakeProcess()]

    def fake_popen(_command):
        return processes.pop(0)

    started: list[_FakeProcess] = []

    def recording_popen(command):
        process = fake_popen(command)
        started.append(process)
        return process

    def finish_document_worker(_seconds):
        started[0].return_code = 7

    assert (
        supervise_worker_processes(
            popen=recording_popen,
            sleep=finish_document_worker,
            install_signal_handlers=False,
        )
        == 7
    )
    assert started[0].terminated is False
    assert started[1].terminated is True


class _FakeProcess:
    def __init__(self):
        self.return_code = None
        self.terminated = False

    def poll(self):
        return self.return_code

    def terminate(self):
        self.terminated = True
        self.return_code = 0

    def wait(self, timeout=None):
        return self.return_code

    def kill(self):
        self.return_code = -9
