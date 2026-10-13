import { afterEach, describe, expect, it, vi } from "vitest";

import { createAnalysisShare, getSharedAnalysis, revokeAnalysisShare } from "./analysis-shares";

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

  it("requires an authenticated session for creating and revoking a link", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ token: "share-token" }) })
      .mockResolvedValueOnce({ ok: true });
    global.fetch = fetchMock;

    expect(await createAnalysisShare("analysis-id")).toBe("share-token");
    await revokeAnalysisShare("analysis-id");

    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "POST", credentials: "include" }));
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({ method: "DELETE", credentials: "include" }));
  });
});
