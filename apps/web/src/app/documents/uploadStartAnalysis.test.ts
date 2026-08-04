import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const source = () => readFileSync(join(process.cwd(), "src/app/documents/page.tsx"), "utf8");

describe("documents upload start analysis flow", () => {
  it("persists the analysis request with the upload and leaves parsing to the worker", () => {
    const pageSource = source();

    expect(pageSource).toContain('form.set("analysis_provider", analysisConfig.provider)');
    expect(pageSource).toContain('form.set("analysis_model", analysisConfig.model)');
    expect(pageSource).toContain('form.set("analysis_output_language", defaultOutputLanguage)');
    expect(pageSource).not.toContain("function waitForUploadedDocumentParse");
    expect(pageSource).not.toContain("await createAnalysis(parsedDocument.id");
    expect(pageSource).toContain('return "Start Analysis";');
    expect(pageSource).toContain("Full analysis starts automatically as soon as the parser finishes.");
  });

  it("renders uploaded cases immediately and separates case and analysis result actions", () => {
    const pageSource = source();

    expect(pageSource).toContain("function getFinSummaryPresentation");
    expect(pageSource).toContain('return { label: "Workbook attached", tone: "good" };');
    expect(pageSource).toContain("function isFullAnalysisComplete");
    expect(pageSource).toContain("function getLatestCaseAnalysis");
    expect(pageSource).toContain("function getAnalysisStatusSignal");
    expect(pageSource).toContain("const filteredCases = useMemo");
    expect(pageSource).toContain("const caseDocuments = documents");
    expect(pageSource).toContain('return { label: "Waiting for parser"');
    expect(pageSource).toContain("caseAnalysesByDocumentId[document.id]");
    expect(pageSource).toContain("<th>Case</th>");
    expect(pageSource).toContain("<th>Analysis</th>");
    expect(pageSource).not.toContain("<th>Document</th>");
    expect(pageSource).not.toContain("gc-file-kind");
    expect(pageSource).toContain("const canOpenAnalysis = caseAnalysis ? isFullAnalysisComplete(caseAnalysis) : false");
    expect(pageSource).toContain('href={`/analyses/${caseAnalysis.id}`}');
    expect(pageSource).toContain("Analysis results");
    expect(pageSource).toContain('href={`/documents/${document.id}`}');
    expect(pageSource).toContain('target="_blank"');
    expect(pageSource).toContain("Open Case");
    expect(pageSource).toContain('className="gc-compact-link is-disabled"');
    expect(pageSource).toContain("deleteDocumentAnalyses");
    expect(pageSource).toContain("ConfirmDeleteDialog");
    expect(pageSource).toContain("Are you sure you want to delete all the analysis results for this case?");
    expect(pageSource).not.toContain("Delete document");
  });

  it("shows a compact instruction card above upload controls", () => {
    const pageSource = source();
    const instructionIndex = pageSource.indexOf('className="gc-instruction-card"');
    const uploadCardIndex = pageSource.indexOf('className="gc-upload-card"');
    const uploadCardSource = pageSource.slice(uploadCardIndex, pageSource.indexOf('<form className="gc-upload-form"'));

    expect(pageSource).toContain('className="gc-instruction-card"');
    expect(instructionIndex).toBeGreaterThan(-1);
    expect(uploadCardIndex).toBeGreaterThan(instructionIndex);
    expect(pageSource).toContain("Инструкция");
    expect(pageSource).toContain("Чтобы использовать Gate Challenger, приложите документ для защиты в поле Документ для защиты.");
    expect(pageSource).toContain("Чтобы повысить точность ответа также приложите документ Fin Summary в соответствующее поле.");
    expect(pageSource).toContain("Нажмите кнопку Start Analysis.");
    expect(uploadCardSource).toContain("<h1>Documents</h1>");
    expect(pageSource).not.toContain("Upload investment review and product defense documents.");
    expect(pageSource).not.toContain("gc-hero");
  });

  it("labels primary and fin summary upload requirements explicitly", () => {
    const pageSource = source();

    expect(pageSource).toContain("Обязательный документ. Без него нельзя выполнить анализ");
    expect(pageSource).toContain("Опциональный документ. Загрузите, чтобы повысить качество анализа");
    expect(pageSource).toContain("Optimized for .xlsx; max 25 MB");
    expect(pageSource).toContain("gc-format-note");
    expect(pageSource).toContain("gc-format-note is-optional");
    expect(pageSource).toContain(".gc-format-note.is-optional");
    expect(pageSource).toContain("color: #075e45");
    expect(pageSource).not.toContain("Any file format");
    expect(pageSource).not.toContain("Optional attachment");
  });
});
