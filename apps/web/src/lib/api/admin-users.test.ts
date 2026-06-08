import { afterEach, describe, expect, it, vi } from "vitest";

import { deleteUser } from "./admin-users";

const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("admin users api", () => {
  it("deletes users without parsing a response body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    global.fetch = fetchMock;

    await deleteUser("user-id");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/admin/users/user-id",
      expect.objectContaining({ method: "DELETE", credentials: "include" }),
    );
  });
});
