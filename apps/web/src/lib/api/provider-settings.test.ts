import { afterEach, describe, expect, it, vi } from "vitest";

import { testProviderKey } from "./provider-settings";

const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("provider settings api", () => {
  it("posts provider key test request", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        provider: "openai_compatible",
        status: "ok",
        message: "Provider key is configured and decryptable.",
        default_model: "gpt-test",
        base_url: null,
      }),
    });
    global.fetch = fetchMock;

    const response = await testProviderKey("openai_compatible");

    expect(response.status).toBe("ok");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/settings/provider-keys/openai_compatible/test",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
      }),
    );
  });
});
