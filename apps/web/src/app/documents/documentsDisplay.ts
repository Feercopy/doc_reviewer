import type { ParseStatus } from "@/lib/api/documents";

export type FileKindTone = "word" | "pdf" | "markdown" | "text" | "generic";

const documentTypeLabels: Record<string, string> = {
  gate_2: "Gate 2",
  gate_3: "Gate 3",
  stream_review_1: "Stream review 1",
  stream_review_2_plus: "Stream review 2 plus",
};

export function formatDocumentTypeLabel(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }

  return documentTypeLabels[value] ?? value.replaceAll("_", " ");
}

export function getDocumentFileKind(filename: string): { label: string; tone: FileKindTone } {
  const normalized = filename.toLowerCase();

  if (normalized.endsWith(".doc") || normalized.endsWith(".docx")) {
    return { label: "W", tone: "word" };
  }
  if (normalized.endsWith(".pdf")) {
    return { label: "PDF", tone: "pdf" };
  }
  if (normalized.endsWith(".md") || normalized.endsWith(".markdown")) {
    return { label: "MD", tone: "markdown" };
  }
  if (normalized.endsWith(".txt")) {
    return { label: "TXT", tone: "text" };
  }

  return { label: "DOC", tone: "generic" };
}

export function getDocumentParsePresentation(
  status: ParseStatus,
): { label: string; tone: "good" | "info" | "warn" | "bad" } {
  if (status === "completed") {
    return { label: "Parsed", tone: "good" };
  }
  if (status === "running") {
    return { label: "Parsing", tone: "info" };
  }
  if (status === "failed") {
    return { label: "Parser failed", tone: "bad" };
  }

  return { label: "Queued", tone: "warn" };
}
