export type LooseOrderedListBlock =
  | {
      text: string;
      type: "paragraph";
    }
  | {
      items: string[];
      type: "unorderedList";
    };

export type LooseOrderedListItem = {
  blocks: LooseOrderedListBlock[];
  text: string;
};

export type LooseOrderedList = {
  items: LooseOrderedListItem[];
  nextIndex: number;
  start: number;
};

export function parseLooseOrderedList(lines: string[], startIndex: number): LooseOrderedList {
  const firstMatch = orderedListMarker(lines[startIndex]);
  if (!firstMatch) {
    return { items: [], nextIndex: startIndex, start: 1 };
  }

  const items: LooseOrderedListItem[] = [];
  let index = startIndex;
  const listStart = orderedListStart(lines, startIndex, firstMatch.number);

  while (index < lines.length) {
    const itemMatch = orderedListMarker(lines[index]);
    if (!itemMatch) {
      break;
    }

    const item: LooseOrderedListItem = {
      blocks: [],
      text: itemMatch.text,
    };
    index += 1;

    while (index < lines.length) {
      const trimmed = lines[index].trim();
      if (!trimmed) {
        index += 1;
        continue;
      }
      if (orderedListMarker(lines[index])) {
        break;
      }
      if (isLooseListTerminator(lines, index)) {
        return { items: [...items, item], nextIndex: index, start: listStart };
      }
      if (isUnorderedListMarker(trimmed)) {
        const nestedItems: string[] = [];
        while (index < lines.length && isUnorderedListMarker(lines[index].trim())) {
          nestedItems.push(lines[index].trim().replace(/^[-*+]\s+/, ""));
          index += 1;
        }
        item.blocks.push({ items: nestedItems, type: "unorderedList" });
        continue;
      }

      const paragraphLines: string[] = [];
      while (index < lines.length) {
        const paragraphLine = lines[index].trim();
        if (
          !paragraphLine ||
          orderedListMarker(lines[index]) ||
          isUnorderedListMarker(paragraphLine) ||
          isLooseListTerminator(lines, index)
        ) {
          break;
        }
        paragraphLines.push(paragraphLine);
        index += 1;
      }
      if (paragraphLines.length) {
        item.blocks.push({ text: paragraphLines.join(" "), type: "paragraph" });
      }
    }

    items.push(item);
  }

  return { items, nextIndex: index, start: listStart };
}

export function isOrderedListMarker(line: string): boolean {
  return Boolean(orderedListMarker(line));
}

function orderedListMarker(line: string): { number: number; text: string } | null {
  const match = /^(\d+)[.)]\s+(.+)$/.exec(line.trim());
  if (!match) {
    return null;
  }
  return {
    number: Number.parseInt(match[1], 10),
    text: match[2],
  };
}

function isUnorderedListMarker(trimmed: string): boolean {
  return /^[-*+]\s+/.test(trimmed);
}

function isLooseListTerminator(lines: string[], index: number): boolean {
  const trimmed = lines[index].trim();
  return (
    /^#{1,6}\s+/.test(trimmed) ||
    trimmed.startsWith("```") ||
    trimmed.startsWith(">") ||
    /^---+$|^\*\*\*+$/.test(trimmed) ||
    isStandaloneSectionLabelBeforeOrderedList(lines, index) ||
    (isMarkdownTableRow(trimmed) && index + 1 < lines.length && isMarkdownTableSeparator(lines[index + 1]))
  );
}

function orderedListStart(lines: string[], startIndex: number, markerNumber: number): number {
  if (markerNumber <= 1) {
    return markerNumber;
  }

  const previousIndex = previousNonBlankLineIndex(lines, startIndex);
  if (previousIndex !== null && isStandaloneSectionLabel(lines[previousIndex].trim())) {
    return 1;
  }

  return markerNumber;
}

function isStandaloneSectionLabelBeforeOrderedList(lines: string[], index: number): boolean {
  if (!isStandaloneSectionLabel(lines[index].trim())) {
    return false;
  }

  const nextIndex = nextNonBlankLineIndex(lines, index);
  return nextIndex !== null && Boolean(orderedListMarker(lines[nextIndex]));
}

function isStandaloneSectionLabel(trimmed: string): boolean {
  return /^(\*\*[^*]+:\*\*|__[^_]+:__)$/.test(trimmed);
}

function previousNonBlankLineIndex(lines: string[], startIndex: number): number | null {
  for (let index = startIndex - 1; index >= 0; index -= 1) {
    if (lines[index].trim()) {
      return index;
    }
  }
  return null;
}

function nextNonBlankLineIndex(lines: string[], startIndex: number): number | null {
  for (let index = startIndex + 1; index < lines.length; index += 1) {
    if (lines[index].trim()) {
      return index;
    }
  }
  return null;
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
