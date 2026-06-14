import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("document detail model trigger", () => {
  it("keeps the model label separate from the decorative chevron", () => {
    const source = readFileSync(join(__dirname, "page.tsx"), "utf8");

    expect(source).toContain("gc-model-trigger");
    expect(source).toContain("gc-model-chevron");
    expect(source).not.toContain('Model{modelDialogOpen ? "⌃" : "⌄"}');
  });

  it("keeps model settings focused on language, model, and saving", () => {
    const source = readFileSync(join(__dirname, "page.tsx"), "utf8");

    expect(source).toContain("<span>Output language</span>");
    expect(source).toContain("<span>Model</span>");
    expect(source).toContain("Save");
    expect(source).not.toContain("<span>Provider</span>");
    expect(source).not.toContain("<span>Shared key</span>");
    expect(source).not.toContain("Valid");
    expect(source).not.toContain("No shared key");
    expect(source).not.toContain("Cancel");
    expect(source).not.toContain("Apply");
  });
});
