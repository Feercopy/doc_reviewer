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
    const documentHeroSource = source.slice(
      source.indexOf('className="gc-document-hero"'),
      source.indexOf('<div className="gc-stepper"'),
    );

    expect(titleToolbarSource).toContain('aria-label="Document actions"');
    expect(titleToolbarSource).toContain("Download raw");
    expect(titleToolbarSource).toContain("Reparse");
    expect(titleToolbarSource).toContain("Delete");
    expect(documentHeroSource).not.toContain("gc-analysis-toolbar");
  });

  it("keeps model, language, and launch compactly under analysis history", () => {
    const source = readFileSync(join(__dirname, "page.tsx"), "utf8");
    const historyPanelSource = source.slice(
      source.indexOf('className="gc-panel gc-history-panel"'),
      source.indexOf("{analyses.length > 0 ?"),
    );

    expect(historyPanelSource).toContain("<h2>Analysis history</h2>");
    expect(historyPanelSource).toContain('className="gc-analysis-toolbar"');
    expect(historyPanelSource).toContain('aria-label="Model"');
    expect(historyPanelSource).toContain('aria-label="Output language"');
    expect(historyPanelSource).toContain("▷ Start analysis");
    expect(historyPanelSource).toContain("changeModel");
    expect(source).not.toContain("gc-analysis-launch");
    expect(source).not.toContain("Choose output settings before starting analysis.");
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

  it("uses the manual document type override when launching analysis", () => {
    const source = readFileSync(join(__dirname, "page.tsx"), "utf8");

    expect(source).toContain("document_type_override: document?.manual_document_type ?? document?.detected_document_type");
  });
});
