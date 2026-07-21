import { describe, expect, it } from "vitest";

import { parseLooseOrderedList } from "./markdownListParser";

describe("parseLooseOrderedList", () => {
  it("keeps paragraphs and nested bullets inside one ordered list", () => {
    const lines = [
      "1. **First issue**",
      "",
      "First paragraph belongs to the first numbered item.",
      "",
      "- First evidence",
      "- Second evidence",
      "",
      "1. **Second issue**",
      "",
      "Second paragraph belongs to the second numbered item.",
      "",
      "1. **Third issue**",
      "",
      "## Next section",
    ];

    const result = parseLooseOrderedList(lines, 0);

    expect(result.start).toBe(1);
    expect(result.nextIndex).toBe(13);
    expect(result.items).toEqual([
      {
        text: "**First issue**",
        blocks: [
          { type: "paragraph", text: "First paragraph belongs to the first numbered item." },
          { type: "unorderedList", items: ["First evidence", "Second evidence"] },
        ],
      },
      {
        text: "**Second issue**",
        blocks: [{ type: "paragraph", text: "Second paragraph belongs to the second numbered item." }],
      },
      {
        text: "**Third issue**",
        blocks: [],
      },
    ]);
  });

  it("splits Gate Challenger section labels out of loose ordered lists and resets following numbering", () => {
    const lines = [
      "1. **What is good:** Existing funnel data is present.",
      "",
      "2. **Market scope:** Buyer and seller segments are named.",
      "",
      "- Mass limit pre-approval and data purchases.",
      "- Implementation of the untested buyer transaction fee.",
      "",
      "**What needs to be improved in the document:**",
      "",
      "6. **Pricing A/B Tests:** Provide price elasticity data.",
      "7. **Partner Commitments:** Secure signed agreements.",
    ];

    const strengths = parseLooseOrderedList(lines, 0);
    const improvements = parseLooseOrderedList(lines, 9);

    expect(strengths.nextIndex).toBe(7);
    expect(strengths.items).toEqual([
      {
        text: "**What is good:** Existing funnel data is present.",
        blocks: [],
      },
      {
        text: "**Market scope:** Buyer and seller segments are named.",
        blocks: [
          {
            type: "unorderedList",
            items: [
              "Mass limit pre-approval and data purchases.",
              "Implementation of the untested buyer transaction fee.",
            ],
          },
        ],
      },
    ]);
    expect(improvements.start).toBe(1);
    expect(improvements.items.map((item) => item.text)).toEqual([
      "**Pricing A/B Tests:** Provide price elasticity data.",
      "**Partner Commitments:** Secure signed agreements.",
    ]);
  });
});
