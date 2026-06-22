import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("document detail analysis controls", () => {
  it("keeps document actions at the title level", () => {
    const source = readFileSync(join(__dirname, "page.tsx"), "utf8");
    const titleToolbarSource = source.slice(
      source.indexOf('className="gc-title-toolbar"'),
      source.indexOf('<p className="gc-muted">'),
    );
    const analysisSetupSource = source.slice(
      source.indexOf('aria-label="Analysis setup"'),
      source.indexOf('<div className="gc-stepper"'),
    );

    expect(titleToolbarSource).toContain('aria-label="Document actions"');
    expect(titleToolbarSource).toContain("Download raw");
    expect(titleToolbarSource).toContain("Reparse");
    expect(titleToolbarSource).toContain("Delete");
    expect(analysisSetupSource).not.toContain("Download raw");
    expect(analysisSetupSource).not.toContain("Reparse");
    expect(analysisSetupSource).not.toContain("Delete");
  });

  it("keeps model, language, and launch in the analysis setup block", () => {
    const source = readFileSync(join(__dirname, "page.tsx"), "utf8");
    const analysisSetupSource = source.slice(
      source.indexOf('aria-label="Analysis setup"'),
      source.indexOf('<div className="gc-detail-columns">'),
    );

    expect(analysisSetupSource).toContain("gc-analysis-launch");
    expect(analysisSetupSource).toContain("<span>Model</span>");
    expect(analysisSetupSource).toContain("<span>Output language</span>");
    expect(analysisSetupSource).toContain("▷ Start analysis");
    expect(analysisSetupSource).toContain("changeModel");
    expect(source).not.toContain("gc-model-trigger");
    expect(source).not.toContain("gc-model-popover");
    expect(source).not.toContain('aria-label="Model settings"');
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
