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
});
