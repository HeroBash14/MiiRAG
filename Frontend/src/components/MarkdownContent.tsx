import React from "react";

interface MarkdownContentProps {
  content: string;
  className?: string;
}

/**
 * Format inline markdown: **bold**, *italic*, `code`
 */
function renderInlineFormatting(text: string): React.ReactNode {
  // Regex to match **bold**, *italic*, `code`
  const parts: React.ReactNode[] = [];
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const token = match[0];
    if (token.startsWith("**") && token.endsWith("**")) {
      parts.push(<strong key={match.index}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("*") && token.endsWith("*")) {
      parts.push(<em key={match.index}>{token.slice(1, -1)}</em>);
    } else if (token.startsWith("`") && token.endsWith("`")) {
      parts.push(
        <code key={match.index} className="md-inline-code">
          {token.slice(1, -1)}
        </code>
      );
    }
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? parts : text;
}

export const MarkdownContent: React.FC<MarkdownContentProps> = ({ content, className = "" }) => {
  if (!content) return null;

  const rawBlocks = content.split("\n\n");
  const nodes: React.ReactNode[] = [];

  rawBlocks.forEach((block, bIdx) => {
    const trimmed = block.trim();
    if (!trimmed) return;

    // 1. Table Detection
    const lines = trimmed.split("\n").map((l) => l.trim());
    if (
      lines.length >= 2 &&
      lines[0].startsWith("|") &&
      lines[0].endsWith("|") &&
      lines[1].startsWith("|") &&
      lines[1].includes("-")
    ) {
      const headerCells = lines[0]
        .slice(1, -1)
        .split("|")
        .map((c) => c.trim());
      const bodyRows = lines.slice(2).map((rowLine) =>
        rowLine
          .slice(1, -1)
          .split("|")
          .map((c) => c.trim())
      );

      nodes.push(
        <div key={`table-${bIdx}`} className="md-table-wrap">
          <table className="md-table">
            <thead>
              <tr>
                {headerCells.map((h, i) => (
                  <th key={i}>{renderInlineFormatting(h)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bodyRows.map((row, rIdx) => (
                <tr key={rIdx}>
                  {row.map((cell, cIdx) => (
                    <td key={cIdx}>{renderInlineFormatting(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      return;
    }

    // 2. Code Block Detection (```...```)
    if (trimmed.startsWith("```") && trimmed.endsWith("```")) {
      const codeLines = trimmed.slice(3, -3).replace(/^.*\n/, "");
      nodes.push(
        <pre key={`code-${bIdx}`} className="md-code-block">
          <code>{codeLines}</code>
        </pre>
      );
      return;
    }

    // 3. Headings (#, ##, ###)
    if (trimmed.startsWith("# ") || trimmed.startsWith("## ") || trimmed.startsWith("### ")) {
      const level = trimmed.startsWith("### ") ? 3 : trimmed.startsWith("## ") ? 2 : 1;
      const headingText = trimmed.replace(/^#+\s*/, "");
      const HeadingTag = level === 1 ? "h3" : level === 2 ? "h4" : "h5";
      nodes.push(
        <HeadingTag key={`head-${bIdx}`} className="md-heading">
          {renderInlineFormatting(headingText)}
        </HeadingTag>
      );
      return;
    }

    // 4. List Items (- or 1.)
    const isList = lines.every(
      (l) => l.startsWith("- ") || l.startsWith("* ") || /^\d+[\.\)]\s/.test(l)
    );
    if (isList) {
      const isNumbered = /^\d+[\.\)]\s/.test(lines[0]);
      const ListTag = isNumbered ? "ol" : "ul";
      nodes.push(
        <ListTag key={`list-${bIdx}`} className="md-list">
          {lines.map((item, iIdx) => {
            const itemText = item.replace(/^([-*]|\d+[\.\)])\s*/, "");
            return <li key={iIdx}>{renderInlineFormatting(itemText)}</li>;
          })}
        </ListTag>
      );
      return;
    }

    // 5. Standard Paragraph
    nodes.push(
      <p key={`p-${bIdx}`} className="md-p">
        {lines.map((line, lIdx) => (
          <React.Fragment key={lIdx}>
            {renderInlineFormatting(line)}
            {lIdx < lines.length - 1 && <br />}
          </React.Fragment>
        ))}
      </p>
    );
  });

  return <div className={`md-content ${className}`}>{nodes}</div>;
};
