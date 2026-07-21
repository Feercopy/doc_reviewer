import { afterEach, describe, expect, it, vi } from "vitest";

import { login, me } from "./auth";
import { resolveApiBaseUrl } from "./client";

const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("auth api", () => {
  it("posts login credentials to the backend", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        user: {
          id: "user-id",
          login: "admin",
          display_name: "Administrator",
          role: "admin",
          status: "active",
        },
      }),
    });
    global.fetch = fetchMock;

    const response = await login("admin", "secret");

    expect(response.user.login).toBe("admin");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/auth/login",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({ login: "admin", password: "secret" }),
      }),
    );
  });

  it("throws backend detail on failed me request", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Authentication required" }),
    });

    await expect(me()).rejects.toThrow("Authentication required");
  });

  it("keeps local frontend and API hostnames aligned", () => {
    expect(resolveApiBaseUrl("127.0.0.1")).toBe("http://127.0.0.1:8000");
    expect(resolveApiBaseUrl("localhost")).toBe("http://localhost:8000");
  });
});
