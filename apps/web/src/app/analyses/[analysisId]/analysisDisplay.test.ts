import { describe, expect, it } from "vitest";

import {
  analysisGateDetailsOutput,
  analysisShortSummary,
  buildDocumentCommentAnchors,
  buildLayeredGateChecks,
  devilsAdvocateMarkdownFromRun,
  devilsAdvocateRoleComments,
  devilsAdvocateRoleCommentsFromRun,
  predictedRunDisplayError,
  splitDevilsAdvocateMarkdown,
  stripAssessmentHeading,
} from "./analysisDisplay";

describe("analysis display helpers", () => {
  it("uses the persisted analysis summary before structured fallback fields", () => {
    expect(
      analysisShortSummary({
        summary: "Persisted short summary.",
        structured_output: {
          summary: "Structured short summary.",
          narrative_summary: { executive_summary: "Narrative summary." },
        },
      }),
    ).toBe("Persisted short summary.");
  });

  it("falls back to structured summary fields when persisted summary is absent", () => {
    expect(
      analysisShortSummary({
        summary: null,
        structured_output: {
          narrative_summary: { executive_summary: "Narrative summary." },
        },
      }),
    ).toBe("Narrative summary.");
  });

  it("removes the leading assessment heading from reader-facing markdown", () => {
    expect(stripAssessmentHeading("Оценка документа\n\n**Рекомендация:** запросить доказательства.")).toBe(
      "**Рекомендация:** запросить доказательства.",
    );
  });

  it("leaves non-leading assessment headings intact", () => {
    expect(stripAssessmentHeading("**Рекомендация:** запросить доказательства.\n\n## Оценка документа")).toBe(
      "**Рекомендация:** запросить доказательства.\n\n## Оценка документа",
    );
  });

  it("splits Devil's Advocate markdown into pre-role, role synthesis, and JTBD sections", () => {
    const sections = splitDevilsAdvocateMarkdown(
      "🔴 Devil's Advocate — IC+Gate 3\n\n" +
        "Pre-flight summary\n- Stage: Gate-3\n\n" +
        "---\nThe Brutal Truth\n\nFatal flaw.\n\n" +
        "---\nRole comments / voter synthesis\n\nMP: reject.\nCPO: reject.\n\n" +
        "---\nActionable JTBDs\n\n1. Add a hard KPI gate.\n\n" +
        "=== IC Decision ===\nVerdict: Rework",
    );

    expect(sections).toEqual([
      {
        title: "Before Role comments",
        markdown:
          "🔴 Devil's Advocate — IC+Gate 3\n\nPre-flight summary\n- Stage: Gate-3\n\n---\nThe Brutal Truth\n\nFatal flaw.",
      },
      {
        title: "Role comments / voter synthesis",
        markdown: "Role comments / voter synthesis\n\nMP: reject.\nCPO: reject.",
      },
      {
        title: "Actionable JTBDs",
        markdown: "Actionable JTBDs\n\n1. Add a hard KPI gate.\n\n=== IC Decision ===\nVerdict: Rework",
      },
    ]);
  });

  it("extracts Devil's Advocate voter comments using the original skill comment contract", () => {
    expect(
      devilsAdvocateRoleComments({
        role_comments: [
          {
            voter: "MP",
            vote: "reject",
            rationale: "No incrementality proof.",
            comments: [
              {
                anchor_text: "CR contact to payment",
                body: "What is the baseline and control group?",
                comment_type: "missing_data",
                severity: "critical",
              },
            ],
          },
        ],
      }),
    ).toEqual([
      {
        id: "MP-0",
        voter: "MP",
        vote: "reject",
        anchorText: "CR contact to payment",
        body: "What is the baseline and control group?",
        commentType: "missing_data",
        severity: "critical",
      },
    ]);
  });

  it("extracts native markdown from truncated Devil's Advocate provider JSON", () => {
    const rawOutput = JSON.stringify({
      choices: [
        {
          message: {
            content:
              '{"run_mode":"full_ic_voting","native_markdown":"The Brutal Truth\\n\\nFatal flaw.\\n\\nActionable JTBDs\\n\\n1. Add proof.","role_comments":[{"unfinished":"',
          },
          finish_reason: "length",
        },
      ],
    });

    expect(
      devilsAdvocateMarkdownFromRun({
        structured_output: null,
        raw_output: rawOutput,
      }),
    ).toBe("The Brutal Truth\n\nFatal flaw.\n\nActionable JTBDs\n\n1. Add proof.");
  });

  it("extracts Devil's Advocate role comments from truncated provider JSON", () => {
    const rawOutput = JSON.stringify({
      choices: [
        {
          message: {
            content:
              '{"run_mode":"full_ic_voting","native_markdown":"The Brutal Truth","role_comments":[' +
              '{"voter":"MP","vote":"reject","comments":[{"anchor_text":"CR contact to payment","body":"Show control-group incrementality.","comment_type":"missing_data","severity":"critical"}]},' +
              '{"voter":"CPO","vote":"reject","comments":[{"anchor_text":"Payment flow","body":"Split conversion by user segment.","comment_type":"weak_argument","severity":"high"}]},' +
              '{"voter":"TechDir","vote":"approve_with_conditions","comments":[{"anchor_text":"CRM automation","body":"Clarify delivery dependency.","comment_type":"execution_risk","severity":"medium"}]},' +
              '{"voter":"VertDir","vote":"reject","comments":[{"anchor_text":"dealer stock contraction","body":"Separate market headwind from product effect.","comment_type":"missing_counterfactual","severity":"high"}]}' +
              '],"tough_questions":[{"question":"unfinished',
          },
          finish_reason: "length",
        },
      ],
    });

    expect(
      devilsAdvocateRoleCommentsFromRun({
        structured_output: null,
        raw_output: rawOutput,
      }),
    ).toEqual([
      {
        id: "MP-0",
        voter: "MP",
        vote: "reject",
        anchorText: "CR contact to payment",
        body: "Show control-group incrementality.",
        commentType: "missing_data",
        severity: "critical",
      },
      {
        id: "CPO-0",
        voter: "CPO",
        vote: "reject",
        anchorText: "Payment flow",
        body: "Split conversion by user segment.",
        commentType: "weak_argument",
        severity: "high",
      },
      {
        id: "TechDir-0",
        voter: "TechDir",
        vote: "approve_with_conditions",
        anchorText: "CRM automation",
        body: "Clarify delivery dependency.",
        commentType: "execution_risk",
        severity: "medium",
      },
      {
        id: "VertDir-0",
        voter: "VertDir",
        vote: "reject",
        anchorText: "dealer stock contraction",
        body: "Separate market headwind from product effect.",
        commentType: "missing_counterfactual",
        severity: "high",
      },
    ]);
  });

  it("shows a readable message for truncated Devil's Advocate JSON errors", () => {
    expect(
      predictedRunDisplayError({
        status: "failed",
        error_message: "Unterminated string starting at: line 1 column 50056 (char 50055)",
      }),
    ).toBe("Provider cut off the Devil's Advocate response before valid JSON was completed. Partial output is shown below when available.");
  });

  it("matches repeated Devil's Advocate anchors to parsed document text", () => {
    const comments = [
      {
        id: "MP-0",
        voter: "MP",
        vote: "reject",
        anchorText: "CR contact to payment",
        body: "What is the baseline and control group?",
        commentType: "missing_data",
        severity: "critical",
      },
      {
        id: "CPO-0",
        voter: "CPO",
        vote: "reject",
        anchorText: "CR contact to payment",
        body: "Split this by buyer and seller segment.",
        commentType: "scope_gap",
        severity: "high",
      },
      {
        id: "VertDir-0",
        voter: "VertDir",
        vote: "approve",
        anchorText: "buyer trust uplift",
        body: "This direction is plausible.",
        commentType: "supporting_signal",
        severity: "low",
      },
    ];

    expect(
      buildDocumentCommentAnchors(
        "The document says CR contact to payment is below target. Later it cites buyer trust uplift.",
        comments,
      ).anchors,
    ).toEqual([
      {
        id: "anchor-1",
        anchorText: "CR contact to payment",
        commentIds: ["MP-0", "CPO-0"],
        commentCount: 2,
        tone: "bad",
      },
      {
        id: "anchor-2",
        anchorText: "buyer trust uplift",
        commentIds: ["VertDir-0"],
        commentCount: 1,
        tone: "good",
      },
    ]);
  });

  it("matches Devil's Advocate anchors across parser spacing and punctuation differences", () => {
    const comments = [
      {
        id: "MP-0",
        voter: "MP",
        vote: "reject",
        anchorText: "Approve an additional RUB 14M in CY 26 for the B2C New Cars test",
        body: "This funding request needs a stricter approval gate.",
        commentType: "risk_not_addressed",
        severity: "important",
      },
    ];

    const result = buildDocumentCommentAnchors(
      "The proposal asks to Approve an additional RUB 14M in CY'26 for the B2C New Cars test before PMF is proven.",
      comments,
    );

    expect(result.anchors).toHaveLength(1);
    expect(result.unmatchedComments).toEqual([]);
    expect(result.segments.find((segment) => segment.anchorId === "anchor-1")?.text).toBe(
      "Approve an additional RUB 14M in CY'26 for the B2C New Cars test",
    );
  });

  it("anchors an over-broad model quote to the strongest exact token window in parsed text", () => {
    const comments = [
      {
        id: "CPO-0",
        voter: "CPO",
        vote: "reject",
        anchorText:
          "Overall business case metrics are behind plan due to dealer stock contraction. For Jan-Apr CY'26 monetized transactions miss budget by 16%.",
        body: "The plan uses a weak base for scaling.",
        commentType: "weak_argument",
        severity: "important",
      },
    ];

    const result = buildDocumentCommentAnchors(
      "Overall business case metrics are behind plan due to dealer stock contraction. The follow-up table is OCR-fragmented.",
      comments,
    );

    expect(result.anchors).toHaveLength(1);
    expect(result.unmatchedComments).toEqual([]);
    expect(result.segments.find((segment) => segment.anchorId === "anchor-1")?.text).toContain(
      "Overall business case metrics are behind plan due to dealer stock contraction",
    );
  });

  it("keeps comments visible when their anchor is not present in parsed text", () => {
    const comments = [
      {
        id: "MP-0",
        voter: "MP",
        vote: "reject",
        anchorText: "missing exact quote",
        body: "The quote is not in parsed text.",
        commentType: "missing_anchor",
        severity: "high",
      },
    ];

    expect(buildDocumentCommentAnchors("Parsed document text.", comments).unmatchedComments).toEqual(comments);
  });

  it("groups Layer 2 checks under Layer 1 and preserves the PASS/PARTIAL/FAIL status", () => {
    expect(
      buildLayeredGateChecks({
        layer_1_markdown:
          "## Layer 1\n\n" +
          "### Solution quality and logic: FAIL\n" +
          "- id: L1-001\n" +
          "  severity: high\n" +
          "  issue: Solution quality and logic is incomplete.\n" +
          "  evidence: The validation method is not decision-relevant.",
        layer_1: [
          {
            id: "L1-001",
            severity: "high",
            issue: "Solution quality and logic is incomplete.",
            evidence: "The validation method is not decision-relevant.",
          },
        ],
        layer_2: [
          {
            id: "L2-001",
            parent_layer_1_id: "L1-001",
            status: "partial",
            severity: "medium",
            question: "Does each central hypothesis use a validation method that answers the decision question?",
            answer: "PARTIAL",
            issue: "The validation method does not answer the approval decision.",
            evidence: "The document names validation activities but not the decision threshold.",
          },
        ],
      }),
    ).toEqual([
      {
        id: "L1-001",
        title: "Solution Quality and Logic",
        description: "Hypothesis validation, decision logic, and product friction",
        status: "fail",
        severity: "high",
        issue: "Solution quality and logic is incomplete.",
        evidence: "The validation method is not decision-relevant.",
        layer2: [
          {
            id: "L2-001",
            parentLayer1Id: "L1-001",
            status: "partial",
            severity: "medium",
            title: "Does each central hypothesis use a validation method that answers the decision question?",
            question: "Does each central hypothesis use a validation method that answers the decision question?",
            answer: "PARTIAL",
            issue: "The validation method does not answer the approval decision.",
            evidence: "The document names validation activities but not the decision threshold.",
          },
        ],
      },
    ]);
  });

  it("uses completed lazy detail output for Layer 1 and Layer 2 while keeping legacy fallback", () => {
    const legacyOutput = {
      layer_1: [{ id: "legacy-l1", severity: "high", issue: "Legacy issue", evidence: "Legacy evidence" }],
      layer_2: [],
    };
    const detailOutput = {
      layer_1: [{ id: "detail-l1", severity: "high", issue: "Detail issue", evidence: "Detail evidence" }],
      layer_2: [],
    };

    expect(
      analysisGateDetailsOutput({
        structured_output: legacyOutput,
        detail_run: {
          status: "completed",
          structured_output: detailOutput,
        },
      }),
    ).toBe(detailOutput);

    expect(
      analysisGateDetailsOutput({
        structured_output: legacyOutput,
        detail_run: {
          status: "failed",
          structured_output: detailOutput,
        },
      }),
    ).toBe(legacyOutput);
  });

  it("keeps markdown-only PASS Layer 1 sections and their Layer 2 clarifying answers visible", () => {
    expect(
      buildLayeredGateChecks({
        layer_1_markdown:
          "## Layer 1\n\n" +
          "### Problem framing and segments: PASS\n" +
          "- No material issue\n\n" +
          "### Solution quality and logic: FAIL\n" +
          "- id: L1_SOL_01\n" +
          "  severity: high\n" +
          "  issue: Payment flow friction.\n" +
          "  evidence: FAQ 2.",
        layer_1: [
          {
            id: "L1_SOL_01",
            severity: "high",
            issue: "Payment flow friction.",
            evidence: "FAQ 2.",
          },
        ],
        layer_2_markdown:
          "## Layer 2\n\n" +
          "### Atomic checks - Problem framing and segments: PASS\n" +
          "- question: Can the reviewer identify the target segment, pain point, and intended behavior change without reconstructing missing logic by inference?\n" +
          "  answer: YES\n" +
          "  evidence: FAQ 1\n\n" +
          "### Atomic checks - Solution quality and logic: FAIL\n" +
          "- question: Does each central hypothesis use a validation method that actually answers the decision question?\n" +
          "  answer: PARTIAL\n" +
          "  evidence: FAQ 2.\n" +
          "  id: L2_SOL_01\n" +
          "  parent_layer_1_id: L1_SOL_01\n" +
          "  status: partial\n" +
          "  severity: high\n" +
          "  title: Payment CJM Friction\n" +
          "  atomic_issue: The pilot's payment flow has high drop-off rates.",
        layer_2: [
          {
            id: "L2_SOL_01",
            parent_layer_1_id: "L1_SOL_01",
            status: "partial",
            severity: "high",
            title: "Payment CJM Friction",
            atomic_issue: "The pilot's payment flow has high drop-off rates.",
            evidence: "FAQ 2.",
          },
        ],
      })[0],
    ).toEqual({
      id: "layer-1-problem-framing-and-segments",
      title: "Problem Framing and Segments",
      description: "Target segment, pain, behavior change, and Gate 1 hypothesis framing",
      status: "pass",
      severity: null,
      issue: "No material issue",
      evidence: null,
      layer2: [
        {
          id: "layer-2-problem-framing-and-segments-1",
          parentLayer1Id: "layer-1-problem-framing-and-segments",
          status: "pass",
          severity: null,
          title:
            "Can the reviewer identify the target segment, pain point, and intended behavior change without reconstructing missing logic by inference?",
          question:
            "Can the reviewer identify the target segment, pain point, and intended behavior change without reconstructing missing logic by inference?",
          answer: "YES",
          issue: "No material issue",
          evidence: "FAQ 1",
        },
      ],
    });
  });

  it("merges lazy detail shorthand markdown bullets with structured Layer 1 and Layer 2 records", () => {
    const groups = buildLayeredGateChecks({
      layer_1_markdown:
        "### Gate 2 Continuity And Gate 3 Decision Boundary: FAIL\n" +
        "- L1-1: The Gate 3 approval boundary is materially broader than Gate 2.\n\n" +
        "### Mlp Launch Fact Base And Progress Against Gate 2 Commitments: FAIL\n" +
        "- L1-2: The launch fact base is incomplete.",
      layer_1: [
        {
          id: "L1-1",
          severity: "high",
          issue: "The Gate 3 approval boundary is materially broader than Gate 2.",
          evidence: "The document expands approval scope without matching Gate 2 closure evidence.",
        },
        {
          id: "L1-2",
          severity: "medium",
          issue: "The launch fact base is incomplete.",
          evidence: "The launch section does not close the prior commitment list.",
        },
      ],
      layer_2_markdown:
        "### Atomic checks - Gate 2 Continuity And Gate 3 Decision Boundary: FAIL\n" +
        "- L2-1: The decision boundary expanded.\n\n" +
        "### Atomic checks - Mlp Launch Fact Base And Progress Against Gate 2 Commitments: FAIL\n" +
        "- L2-2: Commitment closure is only partial.",
      layer_2: [
        {
          id: "L2-1",
          parent_layer_1_id: "L1-1",
          status: "fail",
          severity: "high",
          question: "Does the Gate 3 boundary preserve the Gate 2 decision logic?",
          answer: "NO",
          issue: "The decision boundary expanded.",
          evidence: "The Gate 3 scope adds approval cases beyond the Gate 2 commitment.",
        },
        {
          id: "L2-2",
          parent_layer_1_id: "L1-2",
          status: "partial",
          severity: "medium",
          question: "Are Gate 2 launch commitments explicitly closed?",
          answer: "PARTIAL",
          issue: "Commitment closure is only partial.",
          evidence: "Only part of the prior commitment list has measured evidence.",
        },
      ],
    });

    expect(groups).toHaveLength(2);
    expect(groups[0]).toMatchObject({
      id: "L1-1",
      status: "fail",
      severity: "high",
      issue: "The Gate 3 approval boundary is materially broader than Gate 2.",
      evidence: "The document expands approval scope without matching Gate 2 closure evidence.",
      layer2: [
        {
          id: "L2-1",
          parentLayer1Id: "L1-1",
          status: "fail",
          question: "Does the Gate 3 boundary preserve the Gate 2 decision logic?",
          issue: "The decision boundary expanded.",
        },
      ],
    });
    expect(groups[1]).toMatchObject({
      id: "L1-2",
      layer2: [
        {
          id: "L2-2",
          parentLayer1Id: "L1-2",
          status: "partial",
          question: "Are Gate 2 launch commitments explicitly closed?",
          issue: "Commitment closure is only partial.",
        },
      ],
    });
  });

  it("normalizes legacy Layer 2 markdown answers when structured status is absent", () => {
    const groups = buildLayeredGateChecks({
      layer_1: [
        {
          id: "L1-001",
          severity: "high",
          issue: "Solution quality and logic is incomplete.",
          evidence: "The validation method is not decision-relevant.",
        },
      ],
      layer_2_markdown:
        "### Atomic checks - Solution quality and logic: FAIL\n\n" +
        "- question: Does each central hypothesis use a validation method that answers the decision question?\n" +
        "  answer: NO\n" +
        "  evidence: Missing decision threshold.\n" +
        "  issue: Validation is not decision-relevant.",
      layer_2: [
        {
          id: "L2-001",
          parent_layer_1_id: "L1-001",
          severity: "high",
          question: "Does each central hypothesis use a validation method that answers the decision question?",
          answer: "NO",
          issue: "Validation is not decision-relevant.",
          evidence: "Missing decision threshold.",
        },
      ],
    });

    expect(groups[0]?.layer2[0]?.status).toBe("fail");
  });

  it("falls back to the Layer 2 markdown section order when titles are issue labels, not questions", () => {
    const groups = buildLayeredGateChecks({
      layer_1: [
        {
          id: "L1-001",
          severity: "high",
          issue: "Solution quality and logic is incomplete.",
          evidence: "The validation method is not decision-relevant.",
        },
      ],
      layer_2_markdown:
        "### Atomic checks - Solution quality and logic: FAIL\n\n" +
        "- question: Does each central hypothesis use a validation method that answers the decision question?\n" +
        "  answer: PARTIAL\n\n" +
        "- question: Is the end-state path explicit enough to evaluate the claimed scale-up?\n" +
        "  answer: NO",
      layer_2: [
        {
          id: "L2-001",
          parent_layer_1_id: "L1-001",
          severity: "medium",
          title: "Слабая статистическая значимость теста комиссии",
          issue: "Validation is weak.",
          answer: "PARTIAL",
          evidence: "The evidence is incomplete.",
        },
        {
          id: "L2-002",
          parent_layer_1_id: "L1-001",
          severity: "high",
          title: "Отсутствие целевого пути пользователя",
          issue: "The end-state path is missing.",
          answer: "NO",
          evidence: "The path is incomplete.",
        },
      ],
    });

    expect(groups[0]?.layer2.map((item) => item.status)).toEqual(["partial", "fail"]);
  });
});
