export type MarkdownParagraphLines = {
  lines: string[];
  nextIndex: number;
};

export function parseMarkdownParagraphLines(
  lines: string[],
  startIndex: number,
  isBlockStart: (lines: string[], index: number) => boolean,
): MarkdownParagraphLines {
  const paragraphLines: string[] = [lines[startIndex].trim()];
  let index = startIndex + 1;

  while (index < lines.length && lines[index].trim() && !isBlockStart(lines, index)) {
    const currentLine = lines[index].trim();
    if (paragraphLines.length > 0 && startsSectionLabelLine(currentLine)) {
      break;
    }

    paragraphLines.push(currentLine);
    index += 1;
  }

  return { lines: paragraphLines, nextIndex: index };
}

export function markdownParagraphClassName(lines: string[]): string {
  if (isStandaloneLeadLabelParagraph(lines)) {
    return "gc-md-paragraph gc-md-paragraph--lead-label";
  }
  return "gc-md-paragraph";
}

function startsSectionLabelLine(trimmed: string): boolean {
  return (
    /^(\*\*[^*]{1,120}:\*\*|__[^_]{1,120}:__)\s+\S/.test(trimmed) ||
    /^[A-Z][A-Za-z0-9&/(),.' -]{1,80}:\s+\S/.test(trimmed)
  );
}

function isStandaloneLeadLabelParagraph(lines: string[]): boolean {
  if (lines.length !== 1) {
    return false;
  }

  return /^(\*\*Recommendation:[^*]+\*\*|__Recommendation:[^_]+__)$/.test(lines[0].trim());
}
