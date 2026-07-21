import { describe, expect, it } from "vitest";

import { decodeHtmlEntities, htmlBlockTagName, parseAllowedHtmlFragment, readHtmlBlock, sanitizeHref } from "./markdownHtmlParser";

describe("markdownHtmlParser", () => {
  it("parses parser HTML tables without preserving unsafe attributes", () => {
    const nodes = parseAllowedHtmlFragment(
      '<table style="width:99%;"><colgroup><col style="width: 21%" /></colgroup><tbody><tr><td><strong>Review / Result / Frontmen / Date</strong></td><td><p><a href="https://ab.k.avito.ru/portfolio-items/1043#comment-46004">GATE 1</a></p><p>(Click &amp; Collect)</p></td><td><u>As result of Gate 1</u></td></tr></tbody></table>',
    );
    const table = nodes[0];

    expect(table).toMatchObject({ type: "element", tag: "table", attrs: {} });
    expect(JSON.stringify(nodes)).toContain('"tag":"tbody"');
    expect(JSON.stringify(nodes)).toContain('"tag":"strong"');
    expect(JSON.stringify(nodes)).toContain('"tag":"a"');
    expect(JSON.stringify(nodes)).toContain('"href":"https://ab.k.avito.ru/portfolio-items/1043#comment-46004"');
    expect(JSON.stringify(nodes)).toContain('"tag":"u"');
    expect(JSON.stringify(nodes)).not.toContain("style");
  });

  it("detects multiline HTML blocks from parser output", () => {
    const lines = [
      '<table style="width:99%;">',
      "<tbody><tr><td>Executive</td></tr></tbody>",
      "</table>",
      "Executive Summary",
    ];

    expect(htmlBlockTagName(lines[0])).toBe("table");
    expect(readHtmlBlock(lines, 0, "table")).toEqual({
      html: lines.slice(0, 3).join("\n"),
      nextIndex: 3,
    });
  });

  it("decodes document entities and rejects unsafe links", () => {
    expect(decodeHtmlEntities("Click &amp; Collect &lt;30%&gt;")).toBe("Click & Collect <30%>");
    expect(sanitizeHref("https://ab.k.avito.ru/portfolio-items/1043#comment-46004")).toBe(
      "https://ab.k.avito.ru/portfolio-items/1043#comment-46004",
    );
    expect(sanitizeHref("#appendix-8")).toBe("#appendix-8");
    expect(sanitizeHref("javascript:alert(1)")).toBeNull();
  });
});
