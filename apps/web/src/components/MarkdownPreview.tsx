import { type ReactNode } from "react";

import { isOrderedListMarker, parseLooseOrderedList, type LooseOrderedListBlock } from "./markdownListParser";

type MarkdownPreviewProps = {
  markdown: string;
  className?: string;
};

export function MarkdownPreview({ markdown, className = "" }: MarkdownPreviewProps) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      blocks.push(
        <pre className="gc-md-code" key={`code-${index}`}>
          {codeLines.join("\n")}
        </pre>,
      );
      index += 1;
      continue;
    }

    const headingMatch = /^(#{1,6})\s+(.+)$/.exec(trimmed);
    if (headingMatch) {
      const level = headingMatch[1].length;
      blocks.push(renderMarkdownHeading(level, headingMatch[2], `heading-${index}`));
      index += 1;
      continue;
    }

    if (isMarkdownTableRow(trimmed) && index + 1 < lines.length && isMarkdownTableSeparator(lines[index + 1])) {
      const headers = splitMarkdownTableRow(trimmed);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && isMarkdownTableRow(lines[index])) {
        rows.push(splitMarkdownTableRow(lines[index]));
        index += 1;
      }
      blocks.push(<MarkdownTable headers={headers} rows={rows} key={`table-${index}`} />);
      continue;
    }

    if (/^[-*+]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*+]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*+]\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ul className="gc-md-list" key={`ul-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={`${item}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    if (isOrderedListMarker(trimmed)) {
      const list = parseLooseOrderedList(lines, index);
      blocks.push(
        <ol className="gc-md-list" key={`ol-${index}`} start={list.start === 1 ? undefined : list.start}>
          {list.items.map((item, itemIndex) => (
            <li key={`${item.text}-${itemIndex}`}>
              <div className="gc-md-list-item-title">{renderInlineMarkdown(item.text)}</div>
              {item.blocks.map((block, blockIndex) => renderLooseListItemBlock(block, `${item.text}-${blockIndex}`))}
            </li>
          ))}
        </ol>,
      );
      index = list.nextIndex;
      continue;
    }

    if (trimmed.startsWith(">")) {
      const quoteLines: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push(
        <blockquote className="gc-md-quote" key={`quote-${index}`}>
          {renderInlineMarkdown(quoteLines.join(" "))}
        </blockquote>,
      );
      continue;
    }

    if (/^---+$|^\*\*\*+$/.test(trimmed)) {
      blocks.push(<hr className="gc-md-rule" key={`rule-${index}`} />);
      index += 1;
      continue;
    }

    const paragraphLines: string[] = [trimmed];
    index += 1;
    while (index < lines.length && lines[index].trim() && !isMarkdownBlockStart(lines, index)) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    blocks.push(
      <p className="gc-md-paragraph" key={`paragraph-${index}`}>
        {renderInlineMarkdown(paragraphLines.join(" "))}
      </p>,
    );
  }

  return (
    <>
      <style>{markdownPreviewStyles}</style>
      <div className={`gc-markdown-preview ${className}`.trim()}>{blocks}</div>
    </>
  );
}

function MarkdownTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  const columnKinds = headers.map(markdownTableColumnKind);

  return (
    <div className="gc-md-table-scroll">
      <table className="gc-md-table">
        <thead>
          <tr>
            {headers.map((header, index) => (
              <th className={`gc-md-col--${columnKinds[index]}`} key={`${header}-${index}`}>
                {renderInlineMarkdown(header)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`}>
              {headers.map((_, cellIndex) => (
                <td className={`gc-md-col--${columnKinds[cellIndex]}`} key={`cell-${rowIndex}-${cellIndex}`}>
                  {renderInlineMarkdown(row[cellIndex] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function renderLooseListItemBlock(block: LooseOrderedListBlock, key: string): ReactNode {
  if (block.type === "unorderedList") {
    return (
      <ul className="gc-md-list gc-md-list--nested" key={key}>
        {block.items.map((item, itemIndex) => (
          <li key={`${item}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>
        ))}
      </ul>
    );
  }

  return (
    <p className="gc-md-list-paragraph" key={key}>
      {renderInlineMarkdown(block.text)}
    </p>
  );
}

function markdownTableColumnKind(header: string): "index" | "token" | "anchor" | "text" {
  const normalized = header.trim().toLowerCase().replace(/[^a-z0-9#]+/g, "_");

  if (normalized === "#" || normalized === "no" || normalized === "n" || normalized === "id") {
    return "index";
  }
  if (
    normalized.includes("type") ||
    normalized.includes("status") ||
    normalized.includes("severity") ||
    normalized.includes("verdict") ||
    normalized.includes("risk")
  ) {
    return "token";
  }
  if (normalized.includes("anchor") || normalized.includes("source") || normalized.includes("citation")) {
    return "anchor";
  }
  return "text";
}

function isMarkdownBlockStart(lines: string[], index: number): boolean {
  const trimmed = lines[index].trim();
  return (
    /^#{1,6}\s+/.test(trimmed) ||
    trimmed.startsWith("```") ||
    /^[-*+]\s+/.test(trimmed) ||
    isOrderedListMarker(trimmed) ||
    trimmed.startsWith(">") ||
    /^---+$|^\*\*\*+$/.test(trimmed) ||
    (isMarkdownTableRow(trimmed) && index + 1 < lines.length && isMarkdownTableSeparator(lines[index + 1]))
  );
}

function isMarkdownTableRow(line: string): boolean {
  return splitMarkdownTableRow(line).length > 1;
}

function isMarkdownTableSeparator(line: string): boolean {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line.trim());
}

function splitMarkdownTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderMarkdownHeading(level: number, text: string, key: string): ReactNode {
  const className = `gc-md-heading gc-md-heading-${level}`;
  const content = renderInlineMarkdown(text);

  switch (level) {
    case 1:
      return (
        <h1 className={className} key={key}>
          {content}
        </h1>
      );
    case 2:
      return (
        <h2 className={className} key={key}>
          {content}
        </h2>
      );
    case 3:
      return (
        <h3 className={className} key={key}>
          {content}
        </h3>
      );
    case 4:
      return (
        <h4 className={className} key={key}>
          {content}
        </h4>
      );
    case 5:
      return (
        <h5 className={className} key={key}>
          {content}
        </h5>
      );
    default:
      return (
        <h6 className={className} key={key}>
          {content}
        </h6>
      );
  }
}

function renderInlineMarkdown(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    const token = match[0];
    const key = `${match.index}-${token}`;
    if (token.startsWith("`")) {
      parts.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**") || token.startsWith("__")) {
      parts.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else {
      parts.push(<em key={key}>{token.slice(1, -1)}</em>);
    }
    lastIndex = match.index + token.length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts;
}

const markdownPreviewStyles = `
.gc-markdown-preview {
  max-height: 620px;
  overflow: auto;
  border: 1px solid #e5eaf0;
  border-radius: 8px;
  background: #ffffff;
  color: #344054;
  padding: 18px;
  font-size: 15px;
  line-height: 1.62;
}

.gc-markdown-preview--narrative {
  max-height: none;
}

.gc-markdown-preview--full {
  max-height: none;
  overflow: visible;
}

.gc-markdown-preview > :first-child {
  margin-top: 0;
}

.gc-markdown-preview > :last-child {
  margin-bottom: 0;
}

.gc-markdown-preview .gc-md-heading {
  margin: 22px 0 10px;
  color: #111827;
  font-weight: 850;
  letter-spacing: 0;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.gc-markdown-preview .gc-md-heading-1 {
  font-size: 24px;
}

.gc-markdown-preview .gc-md-heading-2 {
  font-size: 20px;
}

.gc-markdown-preview .gc-md-heading-3 {
  font-size: 18px;
}

.gc-markdown-preview .gc-md-heading-4,
.gc-markdown-preview .gc-md-heading-5,
.gc-markdown-preview .gc-md-heading-6 {
  font-size: 16px;
}

.gc-md-paragraph {
  margin: 0 0 14px;
  overflow-wrap: anywhere;
}

.gc-md-list {
  margin: 0 0 16px;
  padding-left: 22px;
}

.gc-md-list li {
  margin: 6px 0;
  overflow-wrap: anywhere;
}

.gc-md-list-item-title {
  margin: 0 0 8px;
}

.gc-md-list-paragraph {
  margin: 0 0 10px;
}

.gc-md-list--nested {
  margin: 6px 0 12px;
}

.gc-md-quote {
  margin: 0 0 16px;
  border-left: 3px solid #0e9f6e;
  background: #eaf8f2;
  color: #344054;
  padding: 10px 14px;
}

.gc-md-code {
  margin: 0 0 16px;
  overflow: auto;
  border: 1px solid #e5eaf0;
  border-radius: 8px;
  background: #fbfcfd;
  color: #111827;
  padding: 14px;
  font: 13px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.gc-md-rule {
  margin: 20px 0;
  border: 0;
  border-top: 1px solid #e5eaf0;
}

.gc-md-table-scroll {
  max-width: 100%;
  width: 100%;
  margin: 0 0 18px;
  overflow-x: auto;
  border: 1px solid #e5eaf0;
  border-radius: 8px;
  -webkit-overflow-scrolling: touch;
}

.gc-md-table {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.gc-md-table th,
.gc-md-table td {
  border-bottom: 1px solid #edf1f5;
  padding: 10px 12px;
  text-align: left;
  vertical-align: top;
  overflow-wrap: break-word;
  word-break: normal;
}

.gc-md-table th {
  background: #fbfcfd;
  color: #111827;
  font-size: 12px;
  font-weight: 850;
  text-transform: uppercase;
  white-space: nowrap;
}

.gc-md-table tr:last-child td {
  border-bottom: 0;
}

.gc-md-table .gc-md-col--index {
  width: 48px;
  min-width: 48px;
  max-width: 64px;
  text-align: center;
  white-space: nowrap;
}

.gc-md-table .gc-md-col--token {
  min-width: 112px;
  max-width: 156px;
}

.gc-md-table .gc-md-col--anchor {
  min-width: 200px;
  max-width: 300px;
}

.gc-md-table .gc-md-col--text {
  min-width: 360px;
  max-width: 640px;
}

.gc-markdown-preview code {
  border: 1px solid #e5eaf0;
  border-radius: 6px;
  background: #f7f9fb;
  color: #111827;
  padding: 1px 5px;
  font: 0.9em/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.gc-markdown-preview strong {
  color: #111827;
  font-weight: 850;
}

.gc-markdown-preview em {
  color: #5b6472;
}
`;
