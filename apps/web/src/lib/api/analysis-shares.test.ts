import { afterEach, describe, expect, it, vi } from "vitest";

import { createAnalysisShare, getAnalysisShareStatus, getSharedAnalysis, revokeAnalysisShare, SharedAnalysisLinkUnavailableError } from "./analysis-shares";

const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("analysis share API", () => {
  it("sends the guest token only in a header and never includes credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "analysis-id" }) });
    global.fetch = fetchMock;

    await getSharedAnalysis("analysis-id", "secret-token");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/public/analyses/analysis-id",
      expect.objectContaining({
        credentials: "omit",
        cache: "no-store",
        headers: { "X-Analysis-Share-Token": "secret-token" },
      }),
    );
  });

  it("requires an authenticated session for creating, checking and revoking a link", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ token: "share-token" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ active: true }) })
      .mockResolvedValueOnce({ ok: true });
    global.fetch = fetchMock;

    expect(await createAnalysisShare("analysis-id")).toBe("share-token");
    expect(await getAnalysisShareStatus("analysis-id")).toBe(true);
    await revokeAnalysisShare("analysis-id");

    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "POST", credentials: "include" }));
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({ credentials: "include" }));
    expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({ method: "DELETE", credentials: "include" }));
  });

  it("distinguishes revoked links from transient refresh failures", async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 404 })
      .mockResolvedValueOnce({ ok: false, status: 422 })
      .mockResolvedValueOnce({ ok: false, status: 408 })
      .mockResolvedValueOnce({ ok: false, status: 425 })
      .mockResolvedValueOnce({ ok: false, status: 429 })
      .mockResolvedValueOnce({ ok: false, status: 502 });

    await expect(getSharedAnalysis("analysis-id", "token")).rejects.toBeInstanceOf(SharedAnalysisLinkUnavailableError);
    await expect(getSharedAnalysis("analysis-id", "token")).rejects.toBeInstanceOf(SharedAnalysisLinkUnavailableError);
    await expect(getSharedAnalysis("analysis-id", "token")).rejects.toThrow("Не удалось обновить результаты");
    await expect(getSharedAnalysis("analysis-id", "token")).rejects.toThrow("Не удалось обновить результаты");
    await expect(getSharedAnalysis("analysis-id", "token")).rejects.toThrow("Не удалось обновить результаты");
    await expect(getSharedAnalysis("analysis-id", "token")).rejects.toThrow("Не удалось обновить результаты");
  });
});
