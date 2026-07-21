import { describe, expect, it } from "vitest";

import type { AnalysisRecord } from "@/lib/api/documents";

import { buildAgentVerdicts, buildFinalVerdict, verdictFromGateChallenger, verdictFromIcReview } from "./resultDisplay";

describe("resultDisplay", () => {
  it("uses the strictest verdict across Gate Challenger and IC review", () => {
    expect(
      buildFinalVerdict({
        verdict: "approved",
        ic_review_run: {
          structured_output: {
            run_mode: "ic_agentic_review_compact",
            verdict: "CONDITIONAL",
          },
        } as AnalysisRecord["ic_review_run"],
      }),
    ).toEqual({ label: "Need Evidence", rank: 1, tone: "warn" });

    expect(
      buildFinalVerdict({
        verdict: "need_evidence",
        ic_review_run: {
          structured_output: {
            run_mode: "ic_agentic_review_compact",
            verdict: "NO-GO",
          },
        } as AnalysisRecord["ic_review_run"],
      }),
    ).toEqual({ label: "Rejected", rank: 0, tone: "bad" });
  });

  it("maps Gate Challenger verdicts into the three user-facing states", () => {
    expect(verdictFromGateChallenger("approved")?.label).toBe("Approved");
    expect(verdictFromGateChallenger("need_evidence")?.label).toBe("Need Evidence");
    expect(verdictFromGateChallenger("rework")?.label).toBe("Rejected");
  });

  it("maps IC review compact verdicts into the three user-facing states", () => {
    expect(verdictFromIcReview({ verdict: "GO" })?.label).toBe("Approved");
    expect(verdictFromIcReview({ verdict: "CONDITIONAL" })?.label).toBe("Need Evidence");
    expect(verdictFromIcReview({ verdict: "UNKNOWN" })?.label).toBe("Need Evidence");
    expect(verdictFromIcReview({ verdict: "FREEZE" })?.label).toBe("Rejected");
    expect(verdictFromIcReview({ verdict: "NO-GO" })?.label).toBe("Rejected");
  });

  it("builds product and financial agent verdict rows with normalized statuses", () => {
    const rows = buildAgentVerdicts({
      verdict: "approved",
      ic_review_run: {
        structured_output: {
          run_mode: "ic_agentic_review_compact",
          verdict: "CONDITIONAL",
        },
      } as AnalysisRecord["ic_review_run"],
    });

    expect(rows).toEqual([
      {
        label: "Продуктовый анализ",
        verdict: { label: "Approved", rank: 2, tone: "good" },
      },
      {
        label: "Финансовый анализ",
        verdict: { label: "Need Evidence", rank: 1, tone: "warn" },
      },
    ]);
  });
});
