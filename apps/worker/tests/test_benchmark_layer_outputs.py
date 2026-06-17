import pytest

from benchmark.layer_outputs import BenchmarkLayerOutputError, extract_benchmark_layers


def test_extract_benchmark_layers_keeps_only_verdict_layer_1_and_layer_2():
    output = {
        "verdict": "need_evidence",
        "summary": "Executive summary must not be judged.",
        "assessment_markdown": "Full synthesis must not be judged.",
        "layer_1": [{"id": "L1-001", "issue": "Weak proof", "evidence": "No cohort"}],
        "layer_2": [{"id": "L2-001", "parent_layer_1_id": "L1-001", "issue": "No holdout"}],
        "layer_3": [{"id": "L3-001", "issue": "Diagnostic only"}],
    }

    extracted = extract_benchmark_layers(output)

    assert extracted == {
        "verdict": "need_evidence",
        "layer_1": [{"id": "L1-001", "issue": "Weak proof", "evidence": "No cohort"}],
        "layer_2": [{"id": "L2-001", "parent_layer_1_id": "L1-001", "issue": "No holdout"}],
    }


def test_extract_benchmark_layers_rejects_summary_only_output():
    output = {
        "verdict": "need_evidence",
        "layer_1_index": [{"id": "L1-001", "issue": "Weak proof"}],
        "layer_2_index": [{"id": "L2-001", "parent_layer_1_id": "L1-001", "question": "Any proof?"}],
    }

    with pytest.raises(BenchmarkLayerOutputError, match="full Layer 1 and Layer 2"):
        extract_benchmark_layers(output)


def test_extract_benchmark_layers_accepts_detail_output():
    output = {
        "analysis_id": "00000000-0000-0000-0000-000000000001",
        "verdict": "reject",
        "summary": "Details summary.",
        "layer_1_markdown": "Layer 1",
        "layer_1": [{"id": "L1-001", "issue": "Weak proof", "evidence": "No cohort"}],
        "layer_2_markdown": "Layer 2",
        "layer_2": [{"id": "L2-001", "parent_layer_1_id": "L1-001", "issue": "No holdout"}],
    }

    extracted = extract_benchmark_layers(output)

    assert extracted["verdict"] == "reject"
    assert extracted["layer_1"][0]["id"] == "L1-001"
    assert extracted["layer_2"][0]["id"] == "L2-001"
