import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_EXTERNAL_ACCESS_DISABLED", "true");
  vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/doc-challanger");
  vi.stubEnv("PUBLIC_WEB_ORIGIN", "https://iseremenko.ru");
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

async function guard(path: string, cookie?: string) {
  const { middleware } = await import("./middleware");
  return middleware(new NextRequest(`https://iseremenko.ru/doc-challanger${path}`, {
    headers: cookie ? { cookie } : undefined,
  }));
}

describe("private access redirects", () => {
  it("sends direct document and guest links to the announcement", async () => {
    for (const path of ["/documents", "/analyses/123", "/shared/analyses/123", "/health"]) {
      const response = await guard(path);
      expect(response.status).toBe(307);
      expect(response.headers.get("location")).toBe("https://iseremenko.ru/doc-challanger/transition");
    }
  });

  it("keeps admin pages and admin login available", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ role: "admin" }) }));
    expect((await guard("/documents", "session=admin")).headers.get("x-middleware-next")).toBe("1");
    expect((await guard("/login")).headers.get("x-middleware-next")).toBe("1");
  });

  it("redirects signed-in non-admins but keeps the login form available", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ role: "user" }) }));
    expect((await guard("/documents", "session=user")).status).toBe(307);
    expect((await guard("/login", "session=user")).headers.get("x-middleware-next")).toBe("1");
  });

  it("allows an expired session to return to admin login", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    expect((await guard("/login", "session=expired")).headers.get("x-middleware-next")).toBe("1");
  });
});
