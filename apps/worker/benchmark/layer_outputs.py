class BenchmarkLayerOutputError(ValueError):
    pass


def extract_benchmark_layers(output: dict) -> dict:
    layer_1 = output.get("layer_1")
    layer_2 = output.get("layer_2")
    if not isinstance(layer_1, list) or not isinstance(layer_2, list):
        raise BenchmarkLayerOutputError("Benchmark scoring requires full Layer 1 and Layer 2 output")
    verdict = output.get("verdict")
    if not isinstance(verdict, str) or not verdict:
        raise BenchmarkLayerOutputError("Benchmark scoring requires a verdict")
    return {
        "verdict": verdict,
        "layer_1": layer_1,
        "layer_2": layer_2,
    }
