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

  it("keeps run details metadata readable in the Paper light theme", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const paperOverrides = pageSource.slice(pageSource.indexOf("const paperAnalysisOverrides"));

    expect(paperOverrides).toContain(".analysis-modal .analysis-chip span");
    expect(paperOverrides).toContain(".analysis-modal .analysis-chip strong");
    expect(paperOverrides).toContain("color: #111827;");
    expect(paperOverrides).toContain("overflow-wrap: anywhere;");
    expect(paperOverrides).toContain(".analysis-modal .analysis-trace__title");
    expect(paperOverrides).toContain(".analysis-modal .analysis-details summary");
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

  it("renders AI Summary, Product Analysis, and Financial Analysis as top-level tabs for all users", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const topTabsSource = pageSource.slice(
      pageSource.indexOf("const analysisTabs"),
      pageSource.indexOf("const feedbackRatings"),
    );

    expect(topTabsSource).toContain('{ id: "executiveSummary", label: "AI Summary" }');
    expect(topTabsSource).toContain('{ id: "mainOutput", label: "Product Analysis" }');
    expect(topTabsSource).toContain('{ id: "icReview", label: "Financial Analysis" }');
    expect(topTabsSource.indexOf("AI Summary")).toBeLessThan(topTabsSource.indexOf("Product Analysis"));
    expect(topTabsSource.indexOf("Product Analysis")).toBeLessThan(topTabsSource.indexOf("Financial Analysis"));
    expect(topTabsSource).not.toContain("Full Report");
    expect(topTabsSource).not.toContain("Legacy Summary");
    expect(topTabsSource).not.toContain("Document comments");
    expect(topTabsSource).not.toContain("Full Output");
    expect(pageSource).not.toContain("const fullReportTabs");
    expect(pageSource).not.toContain("visibleAnalysisTabs.map");
    expect(pageSource).not.toContain("canViewFullReport");
    expect(pageSource).toContain('const [activeTopTab, setActiveTopTab] = useState<AnalysisTopTab>("executiveSummary")');
    expect(pageSource).toContain("function NewSummaryPanel");
    expect(pageSource).toContain('activeTopTab === "executiveSummary"');
    expect(pageSource).toContain('activeTopTab === "mainOutput"');
    expect(pageSource).toContain('activeTopTab === "icReview"');
    expect(pageSource).toContain('<NewSummaryPanel analysis={analysis} newSummary={newSummary} newSummaryError={newSummaryError} />');
    expect(pageSource).toContain("{activeTopTab === \"mainOutput\" ? <MainSkillMarkdownPanel analysis={analysis} /> : null}");
    expect(pageSource).toContain('{activeTopTab === "icReview" ? (');
    expect(pageSource).toContain("resultProductAnalysisMarkdown(analysis)");
    expect(pageSource).toContain("truncateGateMarkdownBeforeIcRecommendations");
    expect(pageSource).toContain("function IcReviewPanel");
    expect(pageSource).not.toContain('activeTopTab === "fullReport"');
    expect(pageSource).not.toContain("activeFullReportTab");
    expect(pageSource).not.toContain("Show in document");
    expect(pageSource).not.toContain("Copy anchor");
    expect(pageSource).not.toContain("All severity");
  });

  it("renders parsed document markdown in Document comments instead of raw pre-wrapped text", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const documentCommentsSource = pageSource.slice(
      pageSource.indexOf("function DocumentCommentsPanel"),
      pageSource.indexOf("function RoleAvatarIcon"),
    );
    const documentTextStyles = pageSource.slice(
      pageSource.indexOf(".analysis-document-text {"),
      pageSource.indexOf(".analysis-document-anchor {"),
    );

    expect(documentCommentsSource).toContain("function DocumentMarkdownText");
    expect(documentCommentsSource).toContain("function DocumentMarkdownTable");
    expect(documentCommentsSource).toContain("renderDocumentSegmentText");
    expect(documentTextStyles).toContain(".analysis-document-table-scroll");
    expect(documentTextStyles).toContain(".analysis-document-heading");
    expect(documentTextStyles).not.toContain("white-space: pre-wrap");
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
    expect(pageSource).toContain("window.location.href = appPath(`/documents/${analysis.document_id}`)");
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
    const shortSummaryParagraphRule = /^\.analysis-short-summary p \{[\s\S]*?\n\}/m.exec(pageSource)?.[0] || "";
    const shortSummaryParagraphStyles = pageSource.slice(
      pageSource.indexOf(shortSummaryParagraphRule),
      pageSource.indexOf(".analysis-detail-checks h3"),
    );

    expect(pageSource).toContain("<h3>Short summary</h3>");
    expect(shortSummaryParagraphRule).toContain("width: 100%");
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
    const waitingSource = pageSource.slice(
      pageSource.indexOf("function AnalysisWaitingPanel"),
      pageSource.indexOf("function RunDetailsDialog"),
    );
    const activeStatusSource = pageSource.slice(
      pageSource.indexOf("function activeAnalysisRefreshStatus"),
      pageSource.indexOf("function isActiveRunStatus"),
    );

    expect(pageSource).toContain("const ANALYSIS_POLL_INTERVAL_MS");
    expect(pageSource).toContain("function isAnalysisRefreshPending");
    expect(pageSource).toContain("function shouldShowAnalysisWaitingPanel");
    expect(pageSource).toContain("analysis.predicted_comment_run?.status");
    expect(pageSource).toContain("analysis.detail_run?.status");
    expect(pageSource).toContain("analysis.ic_review_run?.status");
    expect(pageSource).toContain("shouldShowAnalysisWaitingPanel(analysis)");
    expect(waitingSource).toContain("activeAnalysisRefreshStatus(analysis)");
    expect(activeStatusSource).toContain("analysis.predicted_comment_run?.status");
    expect(activeStatusSource).toContain("analysis.detail_run?.status");
    expect(activeStatusSource).not.toContain("analysis.ic_review_run?.status");
    expect(pageSource).toContain("getAnalysisStatus(params.analysisId)");
    expect(pageSource).toContain("mergeAnalysisStatus");
    expect(pageSource).toContain("window.setTimeout(refreshAnalysis, ANALYSIS_POLL_INTERVAL_MS)");
    expect(pageSource).toContain("window.clearTimeout(timer)");
    expect(pageSource).not.toContain("window.setInterval");
  });

  it("wires IC review launch to configured provider models and optional xlsx upload", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

    expect(pageSource).toContain("listProviderModels");
    expect(pageSource).toContain("getProviderDefaultModel");
    expect(pageSource).toContain("type ProviderModelOptions");
    expect(pageSource).toContain("createIcReviewRun");
    expect(pageSource).toContain('useState<OutputLanguage>("ru")');
    expect(pageSource).toContain("financial_model: icReviewWorkbook");
    expect(pageSource).toContain("icReviewWorkbookInputKey");
    expect(pageSource).toContain("key={workbookInputKey}");
    expect(pageSource).toContain('accept=".xlsx');
    expect(pageSource).toContain("analysis-ic-workbook-upload");
    expect(pageSource).toContain("Upload financial model");
    expect(pageSource).toContain("Optional .xlsx for formula and table checks");
    expect(pageSource).toContain("Only .xlsx financial model files are supported.");
  });

  it("keeps IC review tab compact, relaunchable after failure, and shows the IC Review PDF download", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const icPanelSource = pageSource.slice(
      pageSource.indexOf("function IcReviewPanel"),
      pageSource.indexOf("function PredictedSkillOutputSection"),
    );

    expect(icPanelSource).toContain('run.status === "failed"');
    expect(icPanelSource).toContain("IC review failed:");
    expect(icPanelSource).toContain("run.error_message");
    expect(icPanelSource).not.toContain("IcReviewFullReportDownloads");
    expect(icPanelSource).toContain('{run.status === "completed" ? <IcReviewPdfDownload run={run} /> : null}');
    expect(icPanelSource).toContain('"artifact:legacy_report_pdf"');
    expect(icPanelSource).not.toContain('"artifact:legacy_report_markdown"');
    expect(icPanelSource).toContain("IC Review PDF");
    expect(icPanelSource).toContain("Скачать PDF");
    expect(icPanelSource).not.toContain("Скачать MD");
    expect(icPanelSource).toContain('const setupControlsDisabled = analysis.status !== "completed" || isLaunching || runIsActive');
    expect(icPanelSource).toContain("const launchDisabled = launchAvailability.disabled || runIsActive");
    expect(icPanelSource).toContain("{!runIsActive ? (");
    expect(icPanelSource).toContain('className="analysis-ic-launch"');
    expect(icPanelSource).not.toContain('className="analysis-secondary-action analysis-ic-launch"');
    expect(icPanelSource).not.toContain("<span>Provider</span>");
    expect(icPanelSource).not.toContain('aria-label="IC review provider"');
    expect(icPanelSource).not.toContain("onChangeProvider");
    expect(icPanelSource).not.toContain("analysis-token-list");
    expect(icPanelSource).not.toContain("<strong>Provider</strong>");
    expect(icPanelSource).not.toContain("<strong>Model</strong>");
    expect(icPanelSource).not.toContain("<strong>Created</strong>");
    expect(icPanelSource).not.toContain("raw_output");
    expect(icPanelSource).not.toContain("legacy_output");
    expect(icPanelSource).not.toContain("JsonBlock");
    expect(icPanelSource).not.toContain("analysis-details");
  });

  it("renders a waiting loader for queued and running analysis states", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

    expect(pageSource).toContain("function AnalysisWaitingPanel");
    expect(pageSource).toContain("analysis-waiting__spinner");
    expect(pageSource).toContain('aria-live="polite"');
    expect(pageSource).toContain('analysis.status === "queued"');
    expect(pageSource).toContain('analysis.status === "running"');
  });

  it("keeps lazy Gate Challenger detail rendering out of the visible top-level tabs", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const fullOutputSource = pageSource.slice(
      pageSource.indexOf("function FullOutputPanel"),
      pageSource.indexOf("function TracePanel"),
    );

    expect(pageSource).not.toContain("createAnalysisDetails");
    expect(pageSource).not.toContain("async function loadAnalysisDetails");
    expect(pageSource).not.toContain('label: "Full Output"');
    expect(fullOutputSource).toContain("Load detailed Layer 1 / Layer 2");
    expect(fullOutputSource).not.toContain("isAnalysisDetailsResponseIdMissing(analysis)");
    expect(fullOutputSource).not.toContain("Gate Challenger response id was not saved");
    expect(fullOutputSource).toContain("analysis.detail_run?.status");
    expect(fullOutputSource).toContain("<DetailedGateChecksOutput analysis={analysis} />");
    expect(fullOutputSource).toContain("Detail run failed");
    expect(pageSource).not.toContain("!analysis.run_parameters?.gate_challenger_response_id");
  });

  it("lets analysis tabs wrap on narrow screens without clipping Financial Analysis", () => {
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
    expect(pageSource).toContain(".analysis-ic-workbook-upload {\n  position: relative;\n  display: flex;");
    expect(pageSource).toContain(".analysis-ic-download {\n  display: inline-flex;\n  min-height: 44px;");
    expect(pageSource).toContain("min-height: 56px;");
  });

  it("styles the Result short summary block like Gate Challenger short summary with dark text", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const summaryStyles = pageSource.slice(
      pageSource.indexOf(".analysis-result-summary {"),
      pageSource.indexOf(".analysis-layout {"),
    );
    const gateSummaryStyles = pageSource.slice(
      pageSource.indexOf(".analysis-short-summary {", pageSource.indexOf("const paperAnalysisOverrides")),
      pageSource.indexOf(".analysis-section-heading", pageSource.indexOf("const paperAnalysisOverrides")),
    );

    expect(gateSummaryStyles).toContain("background: #f7f9fb;");
    expect(summaryStyles).toContain("border: 1px solid #e5eaf0;");
    expect(summaryStyles).toContain("background: #f7f9fb;");
    expect(summaryStyles).toContain("color: #161616;");
    expect(summaryStyles).toContain(".analysis-result-summary h2");
    expect(summaryStyles).toContain(".analysis-result-summary p");
  });

  it("wraps Result blocks in a white auto-sized surface", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const resultSurfaceStyles = pageSource.slice(
      pageSource.indexOf(".analysis-result-surface {"),
      pageSource.indexOf(".analysis-result-stack {"),
    );

    expect(pageSource).toContain('<section className="analysis-result-surface" aria-label={labels.summaryReport}>');
    expect(resultSurfaceStyles).toContain("display: grid;");
    expect(resultSurfaceStyles).toContain("width: 100%;");
    expect(resultSurfaceStyles).toContain("height: auto;");
    expect(resultSurfaceStyles).toContain("background: #ffffff;");
  });

  it("renders Summary analysis output as two collapsible report blocks", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const resultPanelSource = pageSource.slice(
      pageSource.indexOf("function ResultPanel"),
      pageSource.indexOf("function MainSkillMarkdownPanel"),
    );

    expect(resultPanelSource).toContain("<ResultReportSection title={labels.productAnalysis}>");
    expect(resultPanelSource).toContain("<StageChecklist items={stageChecklist} language={displayLanguage} />");
    expect(resultPanelSource).toContain("<ResultReportSection title={labels.financialAnalysis}>");
    expect(resultPanelSource).toContain("<details className=\"analysis-result-report-section\" open>");
    expect(resultPanelSource).toContain("productAnalysisMarkdownForSummary(sections.main)");
    expect(resultPanelSource).toContain("removeProductAnalysisSummaryExcludedSections");
    expect(resultPanelSource).toContain("Рекомендация инвестиционного комитета");
    expect(resultPanelSource).toContain("Что (?:можно|нужно) улучшить в документе");
    expect(resultPanelSource).toContain("<IcReviewTextOutput display={financialDisplay} language={displayLanguage} />");
    expect(resultPanelSource).not.toContain("IcReviewFullReportDownloads");
    expect(pageSource).toContain(".analysis-result-report-section__body > .gc-markdown-preview");
  });

  it("shows instant RU and EN switching through generated AI Summary variants without legacy localization requests", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const newSummaryPanelSource = pageSource.slice(
      pageSource.indexOf("function NewSummaryPanel"),
      pageSource.indexOf("function ResultReportSection"),
    );

    expect(pageSource).not.toContain("ensureSummaryLocalizations(params.analysisId)");
    expect(pageSource).not.toContain("getSummaryLocalizations(params.analysisId)");
    expect(pageSource).toContain("ensureNewSummary(params.analysisId)");
    expect(pageSource).toContain("getNewSummary(params.analysisId)");
    expect(newSummaryPanelSource).toContain('newSummary.ru.status === "completed"');
    expect(newSummaryPanelSource).toContain('newSummary.en.status === "completed"');
    expect(newSummaryPanelSource).toContain("return <NewSummaryReportView embedded report={report} />");
    expect(pageSource).toContain('useState<OutputLanguage>("ru")');
    expect(pageSource).not.toContain("window.location.reload");
  });

  it("renders repository AI Summary as the primary tab for every analysis viewer", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const resultPanelSource = pageSource.slice(
      pageSource.indexOf("function ResultPanel"),
      pageSource.indexOf("function NewSummaryPanel"),
    );
    const newSummaryPanelSource = pageSource.slice(
      pageSource.indexOf("function NewSummaryPanel"),
      pageSource.indexOf("function ResultReportSection"),
    );

    expect(pageSource).toContain("ensureNewSummary(params.analysisId)");
    expect(pageSource).toContain("getNewSummary(params.analysisId)");
    expect(pageSource).toContain('if (analysis?.status !== "completed" || analysis.ic_review_run?.status !== "completed")');
    expect(pageSource).not.toContain('activeFullReportTab === "legacySummary"');
    expect(pageSource).not.toContain('activeTopTab === "fullReport"');
    expect(pageSource).toContain('import { NewSummaryReportView } from "@/components/new-summary/NewSummaryReport";');
    expect(resultPanelSource).not.toContain("NewSummaryReportView");
    expect(resultPanelSource).toContain("<ResultReportSection title={labels.productAnalysis}>");
    expect(newSummaryPanelSource).toContain('newSummary?.available === true');
    expect(newSummaryPanelSource).toContain('newSummary.ru.status === "completed"');
    expect(newSummaryPanelSource).toContain('newSummary.en.status === "completed"');
    expect(newSummaryPanelSource).toContain("return <NewSummaryReportView embedded report={report} />");
    expect(newSummaryPanelSource).toContain("<NewSummaryProgress progress={newSummary?.progress ?? fallbackNewSummaryProgress(newSummary)} />");
    expect(newSummaryPanelSource).toContain("Повторная попытка начнётся автоматически при следующем открытии страницы.");
    expect(pageSource).toContain("function NewSummaryProgress");
    expect(pageSource).toContain("analysis-new-summary-progress__track");
    expect(pageSource).toContain("Модель собирает RU/EN Summary");
  });

  it("keeps embedded AI Summary aligned to the analysis tab content width", () => {
    const newSummarySource = readFileSync(
      new URL("../../../components/new-summary/NewSummaryReport.tsx", import.meta.url),
      "utf8",
    );
    const embeddedStyles = newSummarySource.slice(
      newSummarySource.indexOf(".new-summary-shell--embedded {"),
      newSummarySource.indexOf(".new-summary-toolbar {"),
    );

    expect(embeddedStyles).toContain("width: 100%;");
    expect(embeddedStyles).toContain("max-width: none;");
    expect(embeddedStyles).toContain("margin: 0;");
  });

  it("renders the stage checklist as a red and green traffic-light block above Summary product analysis", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const resultPanelSource = pageSource.slice(
      pageSource.indexOf("function ResultPanel"),
      pageSource.indexOf("function ResultReportSection"),
    );
    const stageChecklistSource = pageSource.slice(
      pageSource.indexOf("function StageChecklist"),
      pageSource.indexOf("function IcReviewTextOutput"),
    );

    expect(resultPanelSource.indexOf("<StageChecklist items={stageChecklist} language={displayLanguage} />")).toBeLessThan(
      resultPanelSource.indexOf("<MarkdownPreview markdown={productMarkdown}"),
    );
    expect(stageChecklistSource).toContain('aria-label={language === "ru" ? "Обязательные элементы" : "Required elements"}');
    expect(stageChecklistSource).toContain('aria-label={`${statusLabel}: ${item.label}`}');
    expect(stageChecklistSource).toContain('className="analysis-stage-checklist__status"');
    expect(stageChecklistSource).toContain("analysis-stage-checklist__item--${item.status}");
    expect(pageSource).toContain(".analysis-stage-checklist__item--green .analysis-stage-checklist__marker");
    expect(pageSource).toContain(".analysis-stage-checklist__item--red .analysis-stage-checklist__marker");
    expect(pageSource).toContain(".analysis-stage-checklist__item--green .analysis-stage-checklist__status");
    expect(pageSource).toContain(".analysis-stage-checklist__item--red .analysis-stage-checklist__status");
  });

  it("styles Summary report disclosure controls and financial brief as requested", () => {
    const pageSource = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
    const reportSectionStyles = pageSource.slice(
      pageSource.indexOf(".analysis-result-report-section {"),
      pageSource.indexOf(".analysis-result-report-section__body {"),
    );
    const financialBriefStyles = pageSource.slice(
      pageSource.indexOf(".analysis-result-ic-output .analysis-short-summary {"),
      pageSource.indexOf(".analysis-layout {"),
    );

    expect(reportSectionStyles).toContain("background: #ffffff;");
    expect(reportSectionStyles).toContain("font-weight: 900;");
    expect(reportSectionStyles).toContain("border-color: #0e9f6e;");
    expect(reportSectionStyles).toContain("background: #0e9f6e;");
    expect(reportSectionStyles).toContain("color: #ffffff;");
    expect(financialBriefStyles).toContain("background: #ffffff;");
    expect(financialBriefStyles).toContain("color: #161616;");
  });
});
