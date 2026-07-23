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
      source.indexOf("{visibleAnalyses.length > 0 ?"),
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

  it("waits for the full Gate, Devil's Advocate, and IC Review package before showing history rows", () => {
    const source = readFileSync(join(__dirname, "page.tsx"), "utf8");

    expect(source).toContain("function isFullAnalysisComplete");
    expect(source).toContain('analysis.predicted_comment_run?.status === "completed"');
    expect(source).toContain('analysis.ic_review_run?.status === "completed"');
    expect(source).toContain("const visibleAnalyses = useMemo");
    expect(source).toContain("Full analysis is running");
    expect(source).toContain("Stop Analysis");
    expect(source).toContain("cancelAnalysisChain");
    expect(source).toContain("isAnalysisChainCancelled");
    expect(source).toContain("analysis_chain_cancel_requested_at");
    expect(source).toContain("Analysis stopped after Gate Challenger");
    expect(source).toContain("The completed result will appear here after Gate Challenger, Devils Advocate, and IC Review finish.");
    expect(source).toContain("await refresh();");
    expect(source).not.toContain("window.location.href = appPath(`/analyses/${analysis.id}`)");
  });

  it("shows IC Review subagent progress while a full analysis is running", () => {
    const source = readFileSync(join(__dirname, "page.tsx"), "utf8");

    expect(source).toContain("DOCUMENT_POLL_INTERVAL_MS");
    expect(source).toContain("buildIcReviewProgressSteps");
    expect(source).toContain("getIcReviewProgressPercent");
    expect(source).toContain("getIcReviewStageText");
    expect(source).toContain('role="progressbar"');
    expect(source).toContain('aria-label="IC Review progress"');
    expect(source).toContain("{pendingIcReviewProgressPercent}%");
    expect(source).toContain("gc-ic-progress-meter");
    expect(source).toContain('aria-label="IC Review subagent progress"');
    expect(source).toContain("Financial auditor");
    expect(source).toContain("Product analyst");
    expect(source).toContain("Market analyst");
    expect(source).toContain("Risk scenario");
    expect(source).toContain("Running ${formatIcReviewRoleLabel(role)}");
    expect(source).toContain("gc-ic-progress-step");
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

  it("keeps the blocked analysis marker circular like the ready marker", () => {
    const source = readFileSync(join(__dirname, "page.tsx"), "utf8");
    const markerStyles = source.slice(
      source.indexOf(".document-detail .gc-step span {"),
      source.indexOf(".document-detail .gc-step.is-active span {"),
    );
    const blockedMarkerStyles = source.slice(
      source.indexOf(".document-detail .gc-step.is-blocked span {"),
      source.indexOf(".document-detail .gc-step.is-active {"),
    );

    expect(markerStyles).toContain("width: 11px;");
    expect(markerStyles).toContain("height: 11px;");
    expect(markerStyles).toContain("flex: 0 0 11px;");
    expect(markerStyles).toContain("border-radius: 999px;");
    expect(blockedMarkerStyles).toContain("background: #c92036;");
    expect(blockedMarkerStyles).not.toContain("border-radius:");
  });
});
