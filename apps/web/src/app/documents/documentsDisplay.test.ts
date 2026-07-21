import { describe, expect, it } from "vitest";

import { formatDocumentTypeLabel, getDocumentFileKind, getDocumentParsePresentation } from "./documentsDisplay";

describe("documents display helpers", () => {
  it.each([
    ["memo.docx", { label: "W", tone: "word" }],
    ["deck.pdf", { label: "PDF", tone: "pdf" }],
    ["notes.md", { label: "MD", tone: "markdown" }],
    ["source.txt", { label: "TXT", tone: "text" }],
    ["archive", { label: "DOC", tone: "generic" }],
  ])("maps %s to a compact file marker", (filename, expected) => {
    expect(getDocumentFileKind(filename)).toEqual(expected);
  });

  it.each([
    ["completed", { label: "Parsed", tone: "good" }],
    ["running", { label: "Parsing", tone: "info" }],
    ["queued", { label: "Queued", tone: "warn" }],
    ["failed", { label: "Parser failed", tone: "bad" }],
  ] as const)("maps %s to the document table parse presentation", (status, expected) => {
    expect(getDocumentParsePresentation(status)).toEqual(expected);
  });

  it.each([
    ["gate_2", "Gate 2"],
    ["stream_review_1", "Stream review 1"],
    ["stream_review_2_plus", "Stream review 2 plus"],
    ["gate_3", "Gate 3"],
    [null, "-"],
  ] as const)("formats %s as a reader-facing document type", (value, expected) => {
    expect(formatDocumentTypeLabel(value)).toBe(expected);
  });
});
