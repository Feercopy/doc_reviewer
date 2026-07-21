import { describe, expect, it } from "vitest";

import type { IcReviewCompactResult, Provider } from "@/lib/api/documents";
import type { ProviderModelOptions } from "@/lib/api/provider-settings";

import {
  IC_REVIEW_EMPTY_STATE,
  buildIcReviewCompactDisplay,
  getIcReviewLaunchAvailability,
  getIcReviewRunStageText,
  getIcReviewSpreadsheetAuditText,
  isXlsxFinancialModelFile,
} from "./icReviewDisplay";

const providerModels: ProviderModelOptions[] = [
  {
    provider: "openai_compatible",
    default_model: "gpt-4.1",
    available_models: ["gpt-4.1"],
    has_key: true,
  },
];

function launchAvailability(overrides: {
  analysisStatus?: "queued" | "running" | "completed" | "failed" | "cancelled";
  provider?: Provider;
  model?: string;
  isLaunching?: boolean;
}) {
  return getIcReviewLaunchAvailability({
    analysisStatus: overrides.analysisStatus ?? "completed",
    providerModels,
    provider: overrides.provider ?? "openai_compatible",
    model: overrides.model ?? "gpt-4.1",
    isLaunching: overrides.isLaunching ?? false,
  });
}

describe("icReviewDisplay", () => {
  it("disables launch before the product analysis is completed", () => {
    expect(launchAvailability({ analysisStatus: "running" })).toEqual({
      disabled: true,
      reason: IC_REVIEW_EMPTY_STATE,
    });
  });

  it("enables launch after the product analysis is completed", () => {
    expect(launchAvailability({ analysisStatus: "completed" })).toEqual({
      disabled: false,
      reason: null,
    });
  });

  it("shows not-provided spreadsheet audit text when no workbook was uploaded", () => {
    expect(
      getIcReviewSpreadsheetAuditText({
        status: "not_provided",
        summary: "",
        formula_issues_count: 0,
        critical_formula_issues_count: 0,
        source_filename: null,
      }),
    ).toBe("Spreadsheet audit not provided");
    expect(isXlsxFinancialModelFile("model.xlsx")).toBe(true);
    expect(isXlsxFinancialModelFile("model.xlsm")).toBe(false);
  });

  it("renders every compact completed-result section", () => {
    const display = buildIcReviewCompactDisplay({
      run_mode: "ic_agentic_review_compact",
      verdict: "CONDITIONAL",
      executive_brief: "Proceed only after validating the model and closing the pricing gap.",
      confidence: 0.72,
      top_findings: [
        {
          title: "Unit economics gap",
          severity: "high",
          summary: "Gross margin proof is thin.",
          evidence: "Document page 12",
          recommendation: "Rebuild the cohort bridge.",
        },
      ],
      key_numbers: [
        {
          label: "ARR",
          value: "12.4",
          unit: "M USD",
          source: "Financial model",
        },
      ],
      spreadsheet_audit: {
        status: "completed",
        summary: "Workbook checked.",
        formula_issues_count: 3,
        critical_formula_issues_count: 1,
        source_filename: "model.xlsx",
      },
      critical_risks: ["Pricing pressure"],
      data_gaps: ["Net revenue retention backup"],
      required_actions: ["Validate expansion assumptions"],
      questions_for_team: ["Why does churn improve in Q4?"],
      role_summaries: [
        {
          role: "ic-market-analyst",
          summary: "Market size is plausible but competition is underdeveloped.",
        },
      ],
      validation: {
        status: "warn",
        summary: "One warning remains.",
        warnings_count: 1,
        failures_count: 0,
      },
      artifacts: [],
    } satisfies IcReviewCompactResult);

    expect(display.verdict).toBe("CONDITIONAL");
    expect(display.executiveBrief).toBe("Proceed only after validating the model and closing the pricing gap.");
    expect(display.spreadsheetAudit).toBe("Spreadsheet audit completed: Workbook checked.");
    expect(display.validation).toBe("Validation warn: 1 warning, 0 failures. One warning remains.");
    expect(display.sections.map((section) => section.title)).toEqual([
      "Top findings",
      "Key numbers",
      "Critical risks",
      "Data gaps",
      "Required actions",
      "Questions for team",
    ]);
    expect(display.sections.flatMap((section) => section.items)).toEqual([
      "Unit economics gap - high: Gross margin proof is thin. Evidence: Document page 12. Recommendation: Rebuild the cohort bridge.",
      "ARR: 12.4 M USD (Financial model)",
      "Pricing pressure",
      "Net revenue retention backup",
      "Validate expansion assumptions",
      "Why does churn improve in Q4?",
    ]);
  });

  it("shows the current stage for running runs", () => {
    expect(
      getIcReviewRunStageText({
        status: "running",
        current_stage: "Running ic-market-analyst",
      }),
    ).toBe("Running ic-market-analyst");
  });
});
