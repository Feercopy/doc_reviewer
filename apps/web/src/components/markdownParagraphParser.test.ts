import { describe, expect, it } from "vitest";

import { markdownParagraphClassName, parseMarkdownParagraphLines } from "./markdownParagraphParser";

describe("parseMarkdownParagraphLines", () => {
  it("separates Gate Challenger verdict lines from following section text", () => {
    const lines = [
      "**Recommendation: Reject progress review and request comprehensive rework (Rework Required)**",
      "**Decision Context:** We are facing an unprecedented structural decline.",
    ];

    const verdict = parseMarkdownParagraphLines(lines, 0, () => false);
    const context = parseMarkdownParagraphLines(lines, verdict.nextIndex, () => false);

    expect(verdict).toEqual({
      lines: ["**Recommendation: Reject progress review and request comprehensive rework (Rework Required)**"],
      nextIndex: 1,
    });
    expect(context).toEqual({
      lines: ["**Decision Context:** We are facing an unprecedented structural decline."],
      nextIndex: 2,
    });
  });

  it("keeps normal wrapped prose in the same paragraph", () => {
    const paragraph = parseMarkdownParagraphLines(
      ["The model depends on optimistic assumptions", "that are contradicted by current facts."],
      0,
      () => false,
    );

    expect(paragraph).toEqual({
      lines: ["The model depends on optimistic assumptions", "that are contradicted by current facts."],
      nextIndex: 2,
    });
  });

  it("marks standalone Gate Challenger verdict paragraphs for extra visual separation", () => {
    expect(
      markdownParagraphClassName([
        "**Recommendation: Reject progress review and request comprehensive rework (Rework Required)**",
      ]),
    ).toBe("gc-md-paragraph gc-md-paragraph--lead-label");
    expect(markdownParagraphClassName(["**Decision Context:** We are facing a structural decline."])).toBe(
      "gc-md-paragraph",
    );
  });
});
