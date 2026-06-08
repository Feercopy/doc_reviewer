import { afterEach, describe, expect, it, vi } from "vitest";

import { cancelBenchmark, createBenchmark, getBenchmarkReport } from "./benchmarks";

const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("benchmarks api", () => {
  it("creates benchmark runs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "benchmark-id" }) });
    global.fetch = fetchMock;

    await createBenchmark({
      name: "Gate 2 baseline",
      description: "Benchmark",
      etalon_ids: ["etalon-id"],
      skill_id: "skill-id",
      provider: "openai_compatible",
      model: "gpt-test",
      judge_skill_id: "judge-id",
      evaluation_mode: "layer_1_and_layer_2",
      run_parameters: {},
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/benchmarks",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          name: "Gate 2 baseline",
          description: "Benchmark",
          etalon_ids: ["etalon-id"],
          skill_id: "skill-id",
          provider: "openai_compatible",
          model: "gpt-test",
          judge_skill_id: "judge-id",
          evaluation_mode: "layer_1_and_layer_2",
          run_parameters: {},
        }),
      }),
    );
  });

  it("reads report and cancels benchmark", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ overall: { f1: 1 } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "benchmark-id" }) });
    global.fetch = fetchMock;

    await getBenchmarkReport("benchmark-id");
    await cancelBenchmark("benchmark-id");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/benchmarks/benchmark-id/report",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/benchmarks/benchmark-id/cancel",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
