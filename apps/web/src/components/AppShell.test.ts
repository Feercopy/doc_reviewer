import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("AppShell anonymizer banner", () => {
  it("aligns the compact anonymizer banner with page content", () => {
    const shellSource = readFileSync(join(process.cwd(), "src/components/AppShell.tsx"), "utf8");
    const globalsSource = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8");

    expect(shellSource).toContain('className="anonymizer-banner-shell"');
    expect(shellSource).toContain('className="anonymizer-banner"');
    expect(globalsSource).toContain(".anonymizer-banner-shell");
    expect(globalsSource).toContain("width: min(1536px, 100%);");
    expect(globalsSource).toContain("padding: 0 36px;");
    expect(globalsSource).toContain("min-height: 35px;");
    expect(globalsSource).toContain("font-size: 12px;");
  });
});
