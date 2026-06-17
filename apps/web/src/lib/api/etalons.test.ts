import { afterEach, describe, expect, it, vi } from "vitest";

import {
  archiveEtalon,
  createEtalonDraft,
  importGate2Benchmark,
  importPastDefense,
  publishEtalon,
  updateEtalon,
} from "./etalons";

const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("etalons api", () => {
  it("creates etalon draft from analysis", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "etalon-id" }) });
    global.fetch = fetchMock;

    await createEtalonDraft("analysis-id");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/analyses/analysis-id/etalon-draft",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("imports past defense as multipart", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "etalon-id" }) });
    global.fetch = fetchMock;
    const form = new FormData();
    form.set("file", new File(["Gate 2"], "gate.txt", { type: "text/plain" }));

    await importPastDefense(form);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/documents/past-defense",
      expect.objectContaining({ method: "POST", body: form }),
    );
    expect(fetchMock.mock.calls[0][1].headers).toBeUndefined();
  });

  it("imports Gate2 benchmark etalons from a configured folder", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ imported_count: 1, skipped_count: 0, etalons: [] }),
    });
    global.fetch = fetchMock;

    await importGate2Benchmark({ benchmark_dir: "/external/Gate2-challenger/benchmark", activate: true });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/etalons/import/gate2-benchmark",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ benchmark_dir: "/external/Gate2-challenger/benchmark", activate: true }),
      }),
    );
  });

  it("patches and changes lifecycle state", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "etalon-id" }) });
    global.fetch = fetchMock;

    await updateEtalon("etalon-id", { expected_verdict: "reject" });
    await publishEtalon("etalon-id");
    await archiveEtalon("etalon-id");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/etalons/etalon-id",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ expected_verdict: "reject" }) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/etalons/etalon-id/publish",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/etalons/etalon-id/archive",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
