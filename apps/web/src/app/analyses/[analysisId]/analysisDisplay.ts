import type { AnalysisRecord } from "@/lib/api/documents";

type SummarySource = Pick<AnalysisRecord, "summary" | "structured_output">;

const ASSESSMENT_HEADINGS = new Set(["Оценка документа", "Document assessment"]);

export function analysisShortSummary(analysis: SummarySource): string | null {
  return analysis.summary || summaryFromOutput(analysis.structured_output);
}

export function stripAssessmentHeading(markdown: string | null): string | null {
  const value = asString(markdown);
  if (!value) {
    return null;
  }

  const trimmedStart = value.trimStart();
  const lines = trimmedStart.split(/\r?\n/);
  const firstLine = lines[0]?.trim().replace(/^#{1,6}\s+/, "").trim();
  if (!ASSESSMENT_HEADINGS.has(firstLine)) {
    return value;
  }

  return asString(lines.slice(1).join("\n").trimStart());
}

function summaryFromOutput(output: Record<string, unknown> | null | undefined): string | null {
  const narrative = asRecord(output?.narrative_summary);
  return (
    asString(output?.summary) ||
    asString(narrative?.summary) ||
    asString(narrative?.executive_summary) ||
    asString(narrative?.assessment) ||
    null
  );
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}
