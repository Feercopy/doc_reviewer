import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch, apiFetchNoContent, apiFetchText } from "./client";

const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("api client cache policy", () => {
  it("defaults JSON requests to no-store", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    global.fetch = fetchMock;

    await apiFetch("/documents");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/documents",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("defaults text requests to no-store", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, text: async () => "Parsed text" });
    global.fetch = fetchMock;

    await apiFetchText("/documents/doc-id/parsed-text");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/documents/doc-id/parsed-text",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("defaults no-content requests to no-store", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    global.fetch = fetchMock;

    await apiFetchNoContent("/documents/doc-id", { method: "DELETE" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/documents/doc-id",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("keeps explicit caller cache options", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    global.fetch = fetchMock;

    await apiFetch("/documents", { cache: "reload" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/documents",
      expect.objectContaining({ cache: "reload" }),
    );
  });
});
