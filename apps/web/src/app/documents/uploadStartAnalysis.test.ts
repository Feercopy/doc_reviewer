import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const source = () => readFileSync(join(process.cwd(), "src/app/documents/page.tsx"), "utf8");

describe("documents upload start analysis flow", () => {
  it("uploads, waits for parsing, and starts analysis from the primary documents page", () => {
    const pageSource = source();

    expect(pageSource).toContain("function waitForUploadedDocumentParse");
    expect(pageSource).toContain("await getDocument(documentId)");
    expect(pageSource).toContain("await createAnalysis(parsedDocument.id");
    expect(pageSource).toContain('return "Start Analysis";');
    expect(pageSource).toContain("Full analysis starts automatically as soon as the parser finishes.");
  });

  it("renders started analyzed cases and separates case and analysis result actions", () => {
    const pageSource = source();

    expect(pageSource).toContain("function getFinSummaryPresentation");
    expect(pageSource).toContain('return { label: "Workbook attached", tone: "good" };');
    expect(pageSource).toContain("function isFullAnalysisComplete");
    expect(pageSource).toContain("function getLatestCaseAnalysis");
    expect(pageSource).toContain("function getAnalysisStatusSignal");
    expect(pageSource).toContain("const filteredCases = useMemo");
    expect(pageSource).toContain("caseAnalysesByDocumentId[document.id]");
    expect(pageSource).toContain("<th>Case</th>");
    expect(pageSource).toContain("<th>Analysis</th>");
    expect(pageSource).not.toContain("<th>Document</th>");
    expect(pageSource).not.toContain("gc-file-kind");
    expect(pageSource).toContain("const canOpenAnalysis = isFullAnalysisComplete(caseAnalysis)");
    expect(pageSource).toContain('href={`/analyses/${caseAnalysis.id}`}');
    expect(pageSource).toContain("Analysis results");
    expect(pageSource).toContain('href={`/documents/${document.id}`}');
    expect(pageSource).toContain('target="_blank"');
    expect(pageSource).toContain("Open Case");
    expect(pageSource).toContain('className="gc-compact-link is-disabled"');
  });
});
