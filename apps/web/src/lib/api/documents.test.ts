import { afterEach, describe, expect, it, vi } from "vitest";

import {
  USER_SELECTABLE_DOCUMENT_TYPES,
  createAnalysis,
  createAnalysisDetails,
  deleteAnalysis,
  deleteDocument,
  getParsedText,
  patchDocumentTitle,
  patchDocumentType,
  uploadDocument,
} from "./documents";
import {
  createIcReviewRun,
  getIcReviewRun,
  getLatestIcReviewRun,
  listIcReviewRuns,
} from "./ic-review";

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

  it("patches document title", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "doc-id", title: "TRX_SE revised" }),
    });
    global.fetch = fetchMock;

    await patchDocumentTitle("doc-id", "TRX_SE revised");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/documents/doc-id/title",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ title: "TRX_SE revised" }),
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

  it("deletes analyses without parsing a response body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    global.fetch = fetchMock;

    await deleteAnalysis("analysis-id");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/analyses/analysis-id",
      expect.objectContaining({ method: "DELETE", credentials: "include" }),
    );
  });

  it("launches analysis from document detail", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "analysis-id" }) });
    global.fetch = fetchMock;

    await createAnalysis("doc-id", {
      provider: "openai_compatible",
      model: "gpt-test",
      run_parameters: { output_language: "en" },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/documents/doc-id/analyses",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          provider: "openai_compatible",
          model: "gpt-test",
          run_parameters: { output_language: "en" },
        }),
      }),
    );
  });

  it("requests lazy Gate Challenger details for an analysis", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "detail-run-id" }) });
    global.fetch = fetchMock;

    await createAnalysisDetails("analysis-id");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/analyses/analysis-id/details",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
      }),
    );
  });

  it("launches IC review with multipart provider, model, output language, and file", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "run-id" }) });
    global.fetch = fetchMock;
    const financialModel = new File(["xlsx"], "model.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });

    await createIcReviewRun("analysis-id", {
      provider: "openai_compatible",
      model: "gpt-test",
      output_language: "en",
      financial_model: financialModel,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/analyses/analysis-id/ic-review-runs",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
      }),
    );
    const init = fetchMock.mock.calls[0][1];
    const body = init.body as FormData;
    expect(init.headers).toBeUndefined();
    expect(body.get("provider")).toBe("openai_compatible");
    expect(body.get("model")).toBe("gpt-test");
    expect(body.get("output_language")).toBe("en");
    expect(body.get("financial_model")).toBe(financialModel);
  });

  it("launches IC review without appending absent financial model", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "run-id" }) });
    global.fetch = fetchMock;

    await createIcReviewRun("analysis-id", {
      provider: "anthropic_compatible",
      model: "claude-test",
      output_language: "ru",
    });

    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.get("provider")).toBe("anthropic_compatible");
    expect(body.get("model")).toBe("claude-test");
    expect(body.get("output_language")).toBe("ru");
    expect(body.has("financial_model")).toBe(false);
  });

  it("reads IC review runs through run, list, and latest endpoints", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "run-id" }) });
    global.fetch = fetchMock;

    await getIcReviewRun("run-id");
    await listIcReviewRuns("analysis-id");
    await getLatestIcReviewRun("analysis-id");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/ic-review-runs/run-id",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/analyses/analysis-id/ic-review-runs",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/analyses/analysis-id/ic-review-runs/latest",
      expect.objectContaining({ credentials: "include" }),
    );
  });
});
