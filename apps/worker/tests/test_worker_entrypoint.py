import pytest

from worker import QUEUE_NAMES, selected_queue_names


def test_worker_defaults_to_all_queues():
    assert selected_queue_names([]) == QUEUE_NAMES


def test_worker_accepts_dedicated_queue_groups():
    assert selected_queue_names(["documents"]) == ["documents"]
    assert selected_queue_names(["analysis", "benchmark"]) == ["analysis", "benchmark"]


def test_worker_rejects_unknown_queue_names():
    with pytest.raises(ValueError, match="Unknown worker queues: emails"):
        selected_queue_names(["emails"])
