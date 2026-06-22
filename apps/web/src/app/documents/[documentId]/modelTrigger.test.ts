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
    const modelPopoverSource = source.slice(
      source.indexOf('aria-label="Model settings"'),
      source.indexOf('<div className="gc-detail-columns">'),
    );

    expect(modelPopoverSource).toContain("<span>Output language</span>");
    expect(modelPopoverSource).toContain("<span>Model</span>");
    expect(modelPopoverSource).toContain("Save");
    expect(modelPopoverSource).not.toContain("<span>Provider</span>");
    expect(modelPopoverSource).not.toContain("<span>Shared key</span>");
    expect(modelPopoverSource).not.toContain("Valid");
    expect(modelPopoverSource).not.toContain("No shared key");
    expect(modelPopoverSource).not.toContain("Cancel");
    expect(modelPopoverSource).not.toContain("Apply");
  });

  it("uses an interactive title editor instead of a decorative pencil", () => {
    const source = readFileSync(join(__dirname, "page.tsx"), "utf8");

    expect(source).toContain("patchDocumentTitle");
    expect(source).toContain('aria-label="Edit document title"');
    expect(source).toContain('aria-label="Document title"');
    expect(source).toContain("gc-title-edit-button");
    expect(source).toContain("gc-title-edit-form");
    expect(source).not.toContain("gc-title-edit-mark");
  });

  it("shows an explicit parser loading state before parsed markdown is ready", () => {
    const source = readFileSync(join(__dirname, "page.tsx"), "utf8");

    expect(source).toContain("getParseProgressText");
    expect(source).toContain("parseInProgress");
    expect(source).toContain('role="status"');
    expect(source).toContain("gc-parse-spinner");
    expect(source).toContain("The parsed markdown will appear here automatically when the parser finishes.");
  });
});
