import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const source = (path: string) => readFileSync(join(process.cwd(), path), "utf8");

describe("admin feedback dashboard page", () => {
  it("renders dashboard summary, improvement signals, and run-level feedback details", () => {
    const pageSource = source("src/app/admin/feedback/page.tsx");

    expect(pageSource).toContain("Feedback Dashboard");
    expect(pageSource).toContain("Average rating");
    expect(pageSource).toContain("Scored feedback");
    expect(pageSource).toContain("What to improve");
    expect(pageSource).toContain("Low ratings");
    expect(pageSource).toContain("Incorrect verdicts");
    expect(pageSource).toContain("False findings");
    expect(pageSource).toContain("Missed findings");
    expect(pageSource).toContain("Legacy / no score");
    expect(pageSource).toContain("Open run");
  });

  it("keeps filters aligned with the admin feedback API contract", () => {
    const pageSource = source("src/app/admin/feedback/page.tsx");

    expect(pageSource).toContain("Provider");
    expect(pageSource).toContain("Processed state");
    expect(pageSource).toContain("Date from");
    expect(pageSource).toContain("Date to");
    expect(pageSource).toContain("skill_id");
    expect(pageSource).toContain("user_id");
  });
});
