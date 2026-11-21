import { Fragment, type ReactNode } from "react";
import { Visual, type VisualResult } from "./Visual";

/**
 * Shows Markdown from a model as React elements only: paragraphs, headings, lists, quotes, tables, code and
 * inline bold/italic/code/links. Nothing is ever inserted as HTML, so HTML, scripts or styles in a reply are shown
 * as text and never run (AGENTS.md: no model-generated HTML/JS/CSS). A fence tagged `recallspring-visual` is drawn
 * from the server's checked copy (`visuals`, in the same order), never from the raw text.
 */

export const VISUAL_LANG = "recallspring-visual";

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "h"; level: number; text: string }
  | { kind: "code"; lang: string; text: string }
  | { kind: "list"; ordered: boolean; start: number; items: { text: string; depth: number }[] }
  | { kind: "quote"; lines: string[] }
  | { kind: "table"; head: string[]; rows: string[][] }
  | { kind: "hr" };

const FENCE = /^\s*(```|~~~)\s*([\w+#.-]*)\s*$/;
const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const BULLET = /^(\s*)[-*+]\s+(.*)$/;
const NUMBERED = /^(\s*)(\d{1,9})[.)]\s+(.*)$/;
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function cells(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i]!;
    if (!line.trim()) {
      i++;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i]!.trim().startsWith(fence[1]!)) body.push(lines[i++]!);
      i++;
      blocks.push({ kind: "code", lang: fence[2] ?? "", text: body.join("\n") });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      blocks.push({ kind: "h", level: heading[1]!.length, text: heading[2]! });
      i++;
      continue;
    }
    if (RULE.test(line)) {
      blocks.push({ kind: "hr" });
      i++;
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1]!)) {
      const head = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i]!.includes("|") && lines[i]!.trim()) rows.push(cells(lines[i++]!));
      blocks.push({ kind: "table", head, rows });
      continue;
    }
    if (line.trimStart().startsWith(">")) {
      const quote: string[] = [];
      while (i < lines.length && lines[i]!.trimStart().startsWith(">")) quote.push(lines[i++]!.trimStart().replace(/^>\s?/, ""));
      blocks.push({ kind: "quote", lines: quote });
      continue;
    }
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    if (bullet || numbered) {
      const ordered = !bullet;
      const items: { text: string; depth: number }[] = [];
      while (i < lines.length) {
        const l = lines[i]!;
        const m = ordered ? NUMBERED.exec(l) : BULLET.exec(l);
        const other = ordered ? BULLET.exec(l) : NUMBERED.exec(l);
        if (m) {
          const text = ordered ? m[3]! : m[2]!;
          items.push({ text, depth: Math.min(Math.floor(m[1]!.length / 2), 3) });
        } else if (other && other[1]!.length > 0) {
          items.push({ text: ordered ? other[2]! : other[3]!, depth: Math.min(Math.floor(other[1]!.length / 2), 3) || 1 });
        } else if (l.trim() && /^\s{2,}/.test(l) && items.length) {
          items[items.length - 1]!.text += ` ${l.trim()}`;
        } else break;
        i++;
      }
      blocks.push({ kind: "list", ordered, start: numbered ? Number(numbered[2]) : 1, items });
      continue;
    }
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i]!.trim() &&
      !FENCE.test(lines[i]!) &&
      !HEADING.test(lines[i]!) &&
      !BULLET.test(lines[i]!) &&
      !NUMBERED.test(lines[i]!) &&
      !lines[i]!.trimStart().startsWith(">")
    ) {
      para.push(lines[i++]!);
    }
    if (!para.length) para.push(lines[i++]!);
    blocks.push({ kind: "p", lines: para });
  }
  return blocks;
}

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*|__[^_\n]+__)|(\*[^*\s][^*\n]*\*|_[^_\s][^_\n]*_)|(\[[^\]\n]+\]\((https?:\/\/[^\s)]+)\))/;

function safeUrl(url: string): string | null {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

export function inline(text: string, key = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = text;
  let n = 0;
  while (rest) {
    const m = INLINE.exec(rest);
    if (!m) {
      out.push(rest);
      break;
    }
    if (m.index > 0) out.push(rest.slice(0, m.index));
    const token = m[0];
    const k = `${key}-${n++}`;
    if (m[1]) out.push(<code key={k}>{token.slice(1, -1)}</code>);
    else if (m[2]) out.push(<strong key={k}>{inline(token.slice(2, -2), k)}</strong>);
    else if (m[3]) out.push(<em key={k}>{inline(token.slice(1, -1), k)}</em>);
    else if (m[4]) {
      const label = token.slice(1, token.indexOf("]("));
      const href = safeUrl(m[5]!);
      out.push(
        href ? (
          <a key={k} href={href} target="_blank" rel="noopener noreferrer nofollow" title={href}>
            {label}
          </a>
        ) : (
          <Fragment key={k}>{token}</Fragment>
        ),
      );
    }
    rest = rest.slice(m.index + token.length);
  }
  return out;
}

function List({ items, ordered, start }: { items: { text: string; depth: number }[]; ordered: boolean; start: number }) {
  const Tag = ordered ? "ol" : "ul";
  return (
    <Tag start={ordered && start !== 1 ? start : undefined}>
      {items.map((it, i) => (
        <li key={i} style={it.depth ? { marginLeft: `${it.depth * 1.25}em` } : undefined}>
          {inline(it.text, `l${i}`)}
        </li>
      ))}
    </Tag>
  );
}

export function Markdown({ text, visuals, source = "the model" }: { text: string; visuals?: VisualResult[]; source?: string }) {
  let visual = 0;
  return (
    <div className="md">
      {parseBlocks(text).map((b, i) => {
        switch (b.kind) {
          case "h": {
            const Tag = b.level <= 2 ? "h3" : b.level === 3 ? "h4" : "h5";
            return <Tag key={i}>{inline(b.text, `h${i}`)}</Tag>;
          }
          case "code":
            if (visuals && b.lang.toLowerCase() === VISUAL_LANG) {
              return <Visual key={i} result={visuals[visual++]} raw={b.text} source={source} />;
            }
            return (
              <pre key={i} className="md-code" aria-label={b.lang ? `${b.lang} code` : "Code"}>
                <code>{b.text}</code>
              </pre>
            );
          case "list":
            return <List key={i} items={b.items} ordered={b.ordered} start={b.start} />;
          case "quote":
            return <blockquote key={i}>{b.lines.map((l, j) => <p key={j}>{inline(l, `q${i}-${j}`)}</p>)}</blockquote>;
          case "table":
            return (
              <div key={i} className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      {b.head.map((c, j) => (
                        <th key={j}>{inline(c, `t${i}-${j}`)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r, j) => (
                      <tr key={j}>
                        {r.map((c, k) => (
                          <td key={k}>{inline(c, `t${i}-${j}-${k}`)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "hr":
            return <hr key={i} />;
          default:
            return (
              <p key={i}>
                {b.lines.map((l, j) => (
                  <Fragment key={j}>
                    {j > 0 && <br />}
                    {inline(l, `p${i}-${j}`)}
                  </Fragment>
                ))}
              </p>
            );
        }
      })}
    </div>
  );
}
