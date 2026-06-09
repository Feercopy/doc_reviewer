import { afterEach, describe, expect, it, vi } from "vitest";

import { getProviderDefaultModel, testProviderKey } from "./provider-settings";

const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("provider settings api", () => {
  it("resolves saved default model for the selected provider", () => {
    expect(
      getProviderDefaultModel(
        [
          {
            provider: "anthropic_compatible",
            base_url: null,
            default_model: "claude-test",
            api_key_fingerprint: "anthropic_compatible:...test",
            has_key: true,
          },
          {
            provider: "openai_compatible",
            base_url: "https://api.example.test/v1",
            default_model: "gpt-saved",
            api_key_fingerprint: "openai_compatible:...test",
            has_key: true,
          },
        ],
        "openai_compatible",
      ),
    ).toBe("gpt-saved");
  });

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
