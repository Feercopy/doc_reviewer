import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, test } from "vitest";

describe("Paper redesign tokens", () => {
  const css = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8");

  test("uses the light Paper visual system as the app baseline", () => {
    expect(css).toContain("color-scheme: light");
    expect(css).toContain("--background: #f7f9fb");
    expect(css).toContain("--foreground: #111827");
    expect(css).toContain("--accent: #0e9f6e");
    expect(css).toContain("--panel: #ffffff");
    expect(css).not.toContain("color-scheme: dark");
  });
});
