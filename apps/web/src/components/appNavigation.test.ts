import { describe, expect, it } from "vitest";

import { getVisibleNavItems } from "./appNavigation";

describe("app navigation", () => {
  it.each(["user", "annotator"] as const)("hides etalons and benchmarks from %s users", (role) => {
    const labels = getVisibleNavItems(role).map((item) => item.label);

    expect(labels).toEqual(["Documents"]);
    expect(labels).not.toContain("Etalons");
    expect(labels).not.toContain("Benchmarks");
    expect(labels).not.toContain("Feedback");
  });

  it("shows etalons and benchmarks to admins", () => {
    const labels = getVisibleNavItems("admin").map((item) => item.label);

    expect(labels).toContain("Feedback");
    expect(labels).toContain("Etalons");
    expect(labels).toContain("Benchmarks");
    expect(labels).toContain("Settings");
    expect(labels).toContain("Admin");
  });
});
