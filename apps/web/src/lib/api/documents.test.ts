import { afterEach, describe, expect, it, vi } from "vitest";

import {
  USER_SELECTABLE_DOCUMENT_TYPES,
  createAnalysis,
  deleteDocument,
  getParsedText,
  patchDocumentType,
  uploadDocument,
} from "./documents";

const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("documents api", () => {
  it("exposes only Gate Challenger stages for user selection", () => {
    expect(USER_SELECTABLE_DOCUMENT_TYPES).toEqual([
      "gate_2",
      "stream_review_1",
      "stream_review_2_plus",
      "gate_3",
    ]);
  });

  it("uploads multipart documents without forcing json content type", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "doc-id" }),
    });
    global.fetch = fetchMock;
    const form = new FormData();
    form.set("title", "Gate 2");
    form.set("file", new File(["Gate 2"], "gate.txt", { type: "text/plain" }));

    await uploadDocument(form);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/documents",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: form,
      }),
    );
    expect(fetchMock.mock.calls[0][1].headers).toBeUndefined();
  });

  it("patches manual document type", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "doc-id" }) });
    global.fetch = fetchMock;

    await patchDocumentType("doc-id", "gate_2");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/documents/doc-id/document-type",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ manual_document_type: "gate_2" }),
      }),
    );
  });

  it("reads parsed text as plain text", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => "Parsed text",
    });

    await expect(getParsedText("doc-id")).resolves.toBe("Parsed text");
  });

  it("deletes documents without parsing a response body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    global.fetch = fetchMock;

    await deleteDocument("doc-id");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/documents/doc-id",
      expect.objectContaining({ method: "DELETE", credentials: "include" }),
    );
  });

  it("launches analysis from document detail", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "analysis-id" }) });
    global.fetch = fetchMock;

    await createAnalysis("doc-id", { provider: "openai_compatible", model: "gpt-test" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/documents/doc-id/analyses",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ provider: "openai_compatible", model: "gpt-test" }),
      }),
    );
  });
});
