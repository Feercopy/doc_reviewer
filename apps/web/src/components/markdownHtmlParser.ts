export type AllowedHtmlTag =
  | "a"
  | "b"
  | "br"
  | "em"
  | "i"
  | "li"
  | "ol"
  | "p"
  | "strong"
  | "table"
  | "tbody"
  | "td"
  | "th"
  | "thead"
  | "tr"
  | "u"
  | "ul";

export type HtmlNode =
  | { type: "text"; text: string }
  | { type: "element"; tag: AllowedHtmlTag; attrs: Record<string, string>; children: HtmlNode[] };

type HtmlContainerNode = { children: HtmlNode[] };

const ALLOWED_HTML_TAGS = new Set<AllowedHtmlTag>([
  "a",
  "b",
  "br",
  "em",
  "i",
  "li",
  "ol",
  "p",
  "strong",
  "table",
  "tbody",
  "td",
  "th",
  "thead",
  "tr",
  "u",
  "ul",
]);
const VOID_HTML_TAGS = new Set<AllowedHtmlTag>(["br"]);

export const TABLE_STRUCTURE_TAGS = new Set<AllowedHtmlTag>(["table", "thead", "tbody", "tr"]);

export function htmlBlockTagName(line: string): AllowedHtmlTag | null {
  const match = /^<(table|ul|ol|p)\b/i.exec(line);
  return match ? (match[1].toLowerCase() as AllowedHtmlTag) : null;
}

export function readHtmlBlock(lines: string[], startIndex: number, tagName: AllowedHtmlTag): { html: string; nextIndex: number } {
  const closingTag = new RegExp(`</${tagName}>`, "i");
  const htmlLines = [lines[startIndex]];
  let nextIndex = startIndex + 1;

  while (nextIndex < lines.length && !closingTag.test(htmlLines.join("\n")) && lines[nextIndex].trim()) {
    htmlLines.push(lines[nextIndex]);
    nextIndex += 1;
  }

  return { html: htmlLines.join("\n"), nextIndex };
}

export function parseAllowedHtmlFragment(html: string): HtmlNode[] {
  const root: HtmlContainerNode = { children: [] };
  const stack: Array<HtmlContainerNode | Extract<HtmlNode, { type: "element" }>> = [root];
  const tokenPattern = /<\/?[^>]+>|[^<]+/g;
  let match: RegExpExecArray | null;

  while ((match = tokenPattern.exec(html)) !== null) {
    const token = match[0];

    if (!token.startsWith("<")) {
      appendHtmlNode(stack, { type: "text", text: token });
      continue;
    }

    const tagMatch = /^<\s*(\/?)\s*([a-zA-Z][\w:-]*)([^>]*)>$/.exec(token);
    if (!tagMatch) {
      appendHtmlNode(stack, { type: "text", text: token });
      continue;
    }

    const isClosingTag = tagMatch[1] === "/";
    const tagName = tagMatch[2].toLowerCase();

    if (!ALLOWED_HTML_TAGS.has(tagName as AllowedHtmlTag)) {
      continue;
    }

    const tag = tagName as AllowedHtmlTag;
    if (isClosingTag) {
      closeHtmlTag(stack, tag);
      continue;
    }

    const element: Extract<HtmlNode, { type: "element" }> = {
      type: "element",
      tag,
      attrs: parseHtmlAttributes(tagMatch[3]),
      children: [],
    };
    appendHtmlNode(stack, element);

    if (!VOID_HTML_TAGS.has(tag) && !/\/\s*>$/.test(token)) {
      stack.push(element);
    }
  }

  return root.children;
}

export function sanitizeHref(href: string | undefined): string | null {
  const value = href?.trim();
  if (!value) {
    return null;
  }

  if (/^(https?:|mailto:|#|\/)/i.test(value)) {
    return value;
  }

  return null;
}

export function isExternalHref(href: string): boolean {
  return /^https?:\/\//i.test(href);
}

export function decodeHtmlEntities(value: string): string {
  return value.replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, (entity, body: string) => {
    const normalized = body.toLowerCase();
    if (normalized.startsWith("#x")) {
      return decodeCodePoint(Number.parseInt(normalized.slice(2), 16), entity);
    }
    if (normalized.startsWith("#")) {
      return decodeCodePoint(Number.parseInt(normalized.slice(1), 10), entity);
    }

    switch (normalized) {
      case "amp":
        return "&";
      case "apos":
        return "'";
      case "gt":
        return ">";
      case "lt":
        return "<";
      case "nbsp":
        return " ";
      case "quot":
        return '"';
      default:
        return entity;
    }
  });
}

function appendHtmlNode(stack: Array<HtmlContainerNode | Extract<HtmlNode, { type: "element" }>>, node: HtmlNode) {
  stack[stack.length - 1].children.push(node);
}

function closeHtmlTag(stack: Array<HtmlContainerNode | Extract<HtmlNode, { type: "element" }>>, tag: AllowedHtmlTag) {
  for (let index = stack.length - 1; index > 0; index -= 1) {
    const item = stack[index];
    if ("tag" in item && item.tag === tag) {
      stack.length = index;
      return;
    }
  }
}

function parseHtmlAttributes(rawAttributes: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  const attrPattern = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'>]+))/g;
  let match: RegExpExecArray | null;

  while ((match = attrPattern.exec(rawAttributes)) !== null) {
    const name = match[1].toLowerCase();
    if (name !== "href") {
      continue;
    }
    attrs[name] = decodeHtmlEntities(match[3] ?? match[4] ?? match[5] ?? "");
  }

  return attrs;
}

function decodeCodePoint(codePoint: number, fallback: string): string {
  if (!Number.isFinite(codePoint) || codePoint <= 0) {
    return fallback;
  }

  try {
    return String.fromCodePoint(codePoint);
  } catch {
    return fallback;
  }
}
