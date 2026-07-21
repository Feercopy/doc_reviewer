import { afterEach, describe, expect, it, vi } from "vitest";

import { deleteAdminEtalon, listAdminAnalyses, listAdminDocuments, listAdminFeedback } from "./admin";

const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("admin api", () => {
  it("serializes document filters", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ documents: [] }) });
    global.fetch = fetchMock;

    await listAdminDocuments({ owner_id: "user-id", document_type: "gate_2" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/admin/documents?owner_id=user-id&document_type=gate_2",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("serializes analysis filters", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ analyses: [] }) });
    global.fetch = fetchMock;

    await listAdminAnalyses({ provider: "openai_compatible", status: "completed" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/admin/analyses?provider=openai_compatible&status=completed",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("serializes feedback filters", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ feedback: [] }) });
    global.fetch = fetchMock;

    await listAdminFeedback({ model: "gpt-test", verdict: "need_evidence" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/admin/feedback?model=gpt-test&verdict=need_evidence",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("serializes feedback dashboard filters", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ feedback: [], summary: {} }) });
    global.fetch = fetchMock;

    await listAdminFeedback({
      provider: "openai_compatible",
      model: "gpt-test",
      verdict: "need_evidence",
      skill_id: "skill-id",
      user_id: "user-id",
      date_from: "2026-06-01",
      date_to: "2026-06-18",
      processed_state: "unprocessed",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/admin/feedback?provider=openai_compatible&model=gpt-test&verdict=need_evidence&skill_id=skill-id&user_id=user-id&date_from=2026-06-01&date_to=2026-06-18&processed_state=unprocessed",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("deletes admin etalons without parsing a response body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    global.fetch = fetchMock;

    await deleteAdminEtalon("etalon-id");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/admin/etalons/etalon-id",
      expect.objectContaining({ method: "DELETE", credentials: "include" }),
    );
  });
});
