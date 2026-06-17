import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const source = (path: string) => readFileSync(join(process.cwd(), path), "utf8");

describe("responsive UI safeguards", () => {
  it("keeps app shell navigation targets at least 44px on compact viewports", () => {
    const css = source("src/app/globals.css");

    expect(css).toContain(".brand {\n  display: flex;\n  min-height: 44px;");
    expect(css).toContain(".nav-link {\n    min-height: 44px;");
  });

  it("keeps checkbox labels large enough to tap comfortably", () => {
    const css = source("src/app/globals.css");

    expect(css).toContain(".checkbox-label {\n  min-height: 44px;");
    expect(css).toContain(".checkbox-label input {\n  width: 18px;\n  height: 18px;");
  });

  it("keeps document list controls touch-friendly and wraps filter tabs", () => {
    const documentsPage = source("src/app/documents/page.tsx");

    expect(documentsPage).toContain("min-height: 44px;");
    expect(documentsPage).toContain(".documents-review input,\n.documents-review select {\n  min-height: 44px;");
    expect(documentsPage).toContain(".gc-filter-tabs {\n    flex-wrap: wrap;");
    expect(documentsPage).toContain("flex: 1 1 104px;");
  });

  it("keeps document detail compact actions touch-friendly", () => {
    const documentDetailPage = source("src/app/documents/[documentId]/page.tsx");

    expect(documentDetailPage).toContain(".document-detail .gc-back-link {\n  display: inline-flex;\n  min-height: 44px;");
    expect(documentDetailPage).toContain("width: 44px;\n  height: 44px;");
    expect(documentDetailPage).toContain("min-height: 44px;");
  });

  it("lets document detail desktop metadata and parsed tables avoid clipping", () => {
    const documentDetailPage = source("src/app/documents/[documentId]/page.tsx");

    expect(documentDetailPage).toContain("flex: 1 1 150px;");
    expect(documentDetailPage).toContain(".document-detail .gc-stepper {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: stretch;");
    expect(documentDetailPage).toContain(".document-detail .gc-step strong,\n.document-detail .gc-step small {");
    expect(documentDetailPage).toContain("overflow-wrap: anywhere;");
    expect(documentDetailPage).toContain("white-space: normal;");
    expect(documentDetailPage).toContain(".document-detail .gc-markdown-preview--full table {\n  min-width: 620px;\n  overflow: visible;");
    expect(documentDetailPage).toContain(".document-detail .gc-markdown-preview--full th,\n.document-detail .gc-markdown-preview--full td {\n  min-width: 0;");
  });

  it("shrinks parsed document before hiding the analysis history open action", () => {
    const documentDetailPage = source("src/app/documents/[documentId]/page.tsx");

    expect(documentDetailPage).toContain("@media (max-width: 1440px) {\n  .document-detail .gc-detail-columns {");
    expect(documentDetailPage).toContain("grid-template-columns: minmax(0, 1fr) minmax(600px, 1fr);");
    expect(documentDetailPage).toContain(".document-detail .gc-table {\n  display: table;\n  min-width: 560px;");
  });

  it("keeps benchmark command buttons at least 44px tall", () => {
    const benchmarksPage = source("src/app/benchmarks/page.tsx");

    expect(benchmarksPage).toContain(".benchmarks-console button,\n.benchmarks-open {\n  display: inline-flex;\n  min-height: 44px;");
  });
});
