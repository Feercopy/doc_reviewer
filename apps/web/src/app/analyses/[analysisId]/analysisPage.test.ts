import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

describe("analysis result page", () => {
  it("does not render run metadata under the Gate Challenger heading", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const mainPanelSource = pageSource.slice(
      pageSource.indexOf("function MainSkillMarkdownPanel"),
      pageSource.indexOf("function LayeredGateChecks"),
    );

    expect(mainPanelSource).not.toContain("analysis.skill_name");
    expect(mainPanelSource).not.toContain("analysis.provider");
    expect(mainPanelSource).not.toContain("analysis.model");
  });

  it("does not render a normal Layer 1 finding card for no-material PASS blocks", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

    expect(pageSource).toContain("hasMaterialLayer1Finding");
    expect(pageSource).toContain("analysis-layer-clear-state");
    expect(pageSource).toContain(
      'group.issue !== "No material issue" ? <LabeledText label="Issue" value={group.issue} /> : null',
    );
  });

  it("renders Layer 2 in the original skill format without risk, recommendation, or reference fields", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const layer2Source = pageSource.slice(
      pageSource.indexOf("function Layer2Question"),
      pageSource.indexOf("function LayerStatusBadge"),
    );

    expect(layer2Source).toContain('label="Evidence"');
    expect(layer2Source).toContain('label="Issue"');
    expect(layer2Source).not.toContain('label="Risk"');
    expect(layer2Source).not.toContain('label="Recommendation"');
    expect(layer2Source).not.toContain("evidenceDisplayLabel");
  });

  it("adds document comments as a focused tab before Full Output", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const tabsSource = pageSource.slice(
      pageSource.indexOf("const analysisTabs"),
      pageSource.indexOf("const feedbackRatings"),
    );

    expect(tabsSource).toContain('{ id: "documentComments", label: "Document comments" }');
    expect(tabsSource.indexOf("Gate Challenger")).toBeLessThan(tabsSource.indexOf("Document comments"));
    expect(tabsSource.indexOf("Document comments")).toBeLessThan(tabsSource.indexOf("Full Output"));
    expect(tabsSource).not.toContain('id: "devilsAdvocate"');
    expect(pageSource).toContain("function DocumentCommentsPanel");
    expect(pageSource).not.toContain("Show in document");
    expect(pageSource).not.toContain("Copy anchor");
    expect(pageSource).not.toContain("All severity");
  });

  it("moves detailed checks and the full Devil's Advocate display into Full Output", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const mainPanelSource = pageSource.slice(
      pageSource.indexOf("function MainSkillMarkdownPanel"),
      pageSource.indexOf("function DetailedGateChecksOutput"),
    );
    const fullOutputSource = pageSource.slice(
      pageSource.indexOf("function FullOutputPanel"),
      pageSource.indexOf("function TracePanel"),
    );

    expect(mainPanelSource).not.toContain('aria-label="Detailed checks"');
    expect(fullOutputSource).toContain("<DetailedGateChecksOutput analysis={analysis} />");
    expect(fullOutputSource).toContain("<PredictedSkillOutputSection run={analysis.predicted_comment_run} />");
  });

  it("does not render the etalon draft action on the analysis page", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

    expect(pageSource).not.toContain("Etalon draft");
    expect(pageSource).not.toContain("Create etalon draft");
    expect(pageSource).not.toContain("createEtalonDraft");
  });

  it("renders a guarded delete action that returns to the source document", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

    expect(pageSource).toContain("deleteAnalysis");
    expect(pageSource).toContain("async function deleteCurrentAnalysis");
    expect(pageSource).toContain('window.confirm(`Delete analysis for "${analysisDocument?.title || "this document"}"?`)');
    expect(pageSource).toContain("await deleteAnalysis(analysis.id)");
    expect(pageSource).toContain("window.location.href = `/documents/${analysis.document_id}`");
    expect(pageSource).toContain('className="analysis-danger-action"');
  });

  it("collects feedback through a floating button and modal instead of a side card", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

    expect(pageSource).toContain("analysis-feedback-fab");
    expect(pageSource).toContain("analysis-feedback-sheet");
    expect(pageSource).not.toContain('className="analysis-card analysis-feedback-card stack"');
    expect(pageSource).not.toContain('<aside className="analysis-inspector">');
  });

  it("renders the short summary text across the full summary card width", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const shortSummaryParagraphStyles = pageSource.slice(
      pageSource.indexOf(".analysis-short-summary p"),
      pageSource.indexOf(".analysis-detail-checks h3"),
    );

    expect(pageSource).toContain("<h3>Short summary</h3>");
    expect(shortSummaryParagraphStyles).toContain("width: 100%");
    expect(shortSummaryParagraphStyles).not.toContain("max-width");
  });

  it("allows long Layer 2 question text to wrap inside its card", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const layer2TopTextStyles = pageSource.slice(
      pageSource.indexOf(".analysis-layer2-question__top > div"),
      pageSource.indexOf(".analysis-layer2-question__top > span:first-child"),
    );

    expect(layer2TopTextStyles).toContain("min-width: 0");
  });

  it("keeps compact Layer 2 detail fields inset from the card edge", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const compactFieldRuleStart = pageSource.indexOf(".analysis-layer-fields--compact {");
    const compactFieldStyles = pageSource.slice(
      compactFieldRuleStart,
      pageSource.indexOf(".analysis-layer-field {", compactFieldRuleStart),
    );

    expect(compactFieldStyles).toContain("padding: 10px 12px 12px");
  });

  it("polls analysis detail while the main or predicted-comment run is still active", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

    expect(pageSource).toContain("const ANALYSIS_POLL_INTERVAL_MS");
    expect(pageSource).toContain("function isAnalysisRefreshPending");
    expect(pageSource).toContain("analysis.predicted_comment_run?.status");
    expect(pageSource).toContain("analysis.detail_run?.status");
    expect(pageSource).toContain("window.setInterval(refreshAnalysis, ANALYSIS_POLL_INTERVAL_MS)");
    expect(pageSource).toContain("window.clearInterval(intervalId)");
  });

  it("renders a waiting loader for queued and running analysis states", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

    expect(pageSource).toContain("function AnalysisWaitingPanel");
    expect(pageSource).toContain("analysis-waiting__spinner");
    expect(pageSource).toContain('aria-live="polite"');
    expect(pageSource).toContain('analysis.status === "queued"');
    expect(pageSource).toContain('analysis.status === "running"');
  });

  it("loads lazy Gate Challenger details from Full Output", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const fullOutputSource = pageSource.slice(
      pageSource.indexOf("function FullOutputPanel"),
      pageSource.indexOf("function TracePanel"),
    );

    expect(pageSource).toContain("createAnalysisDetails");
    expect(pageSource).toContain("async function loadAnalysisDetails");
    expect(fullOutputSource).toContain("Load detailed Layer 1 / Layer 2");
    expect(fullOutputSource).toContain("analysis.detail_run?.status");
    expect(fullOutputSource).toContain("<DetailedGateChecksOutput analysis={analysis} />");
    expect(fullOutputSource).toContain("Detail run failed");
  });

  it("lets analysis tabs wrap on narrow screens without clipping Full Output", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const tabStyles = pageSource.slice(
      pageSource.indexOf(".analysis-tabs {", pageSource.indexOf("const paperAnalysisOverrides")),
      pageSource.indexOf(".analysis-tab {", pageSource.indexOf("const paperAnalysisOverrides")),
    );
    const mobileStyles = pageSource.slice(
      pageSource.indexOf("@media (max-width: 640px)", pageSource.indexOf("const paperAnalysisOverrides")),
      pageSource.indexOf(".analysis-document-panel", pageSource.indexOf("@media (max-width: 640px)", pageSource.indexOf("const paperAnalysisOverrides"))),
    );

    expect(tabStyles).toContain("min-height: 52px");
    expect(tabStyles).not.toContain("\n  height: 52px;");
    expect(mobileStyles).toContain("grid-template-columns: repeat(auto-fit, minmax(150px, 1fr))");
  });

  it("keeps analysis controls at accessible touch target height", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

    expect(pageSource).toContain(".analysis-secondary-action {\n  min-height: 44px;");
    expect(pageSource).toContain(".analysis-tab {\n  min-height: 44px;");
    expect(pageSource).toContain("width: 44px;\n  height: 44px;\n  min-height: 44px;");
    expect(pageSource).toContain(".analysis-feedback-submit {\n  width: 100%;\n  min-height: 44px;");
  });
});
