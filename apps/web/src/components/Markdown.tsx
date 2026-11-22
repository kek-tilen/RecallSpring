import { Fragment, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { API } from "../api";
import type { NoteRef } from "../types";
import { Visual, type VisualResult } from "./Visual";

/**
 * Shows Markdown from a model as React elements only: paragraphs, headings, lists, quotes, tables, code and
 * inline bold/italic/code/links. Nothing is ever inserted as HTML, so HTML, scripts or styles in a reply are shown
 * as text and never run (AGENTS.md: no model-generated HTML/JS/CSS). A fence tagged `recallspring-visual` is drawn
 * from the server's checked copy (`visuals`, in the same order), never from the raw text.
 *
 * In a note (`refs` given) `[name](source:<id>)` links a Library file and `![name](source:<id>)` shows a picture,
 * always through RecallSpring's own owner-checked file address; elsewhere such text stays plain.
 */

export const VISUAL_LANG = "recallspring-visual";

/** An excerpt of the learner's own material that was really sent with the question ("S2"), resolved by the server. */
export interface Cite {
  section_id: string;
  source_id: string;
  filename: string;
  label: string;
}
export type Cites = Record<string, Cite>;
/** The note's linked files by ID, as the server resolved them. */
export type Refs = Record<string, NoteRef>;

const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
/** `[name](source:<id>)` / `![name](source:<id>)` anywhere in a text, as the server reads it. */
export const SOURCE_REF = new RegExp(`(!?)\\[([^\\]\\n]*)\\]\\(source:(${UUID})\\)`, "g");

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

const INLINE = new RegExp(
  [
    /(`[^`\n]+`)/.source,
    /(\*\*[^*\n]+\*\*|__[^_\n]+__)/.source,
    /(\*[^*\s][^*\n]*\*|_[^_\s][^_\n]*_)/.source,
    /(\[[^\]\n]+\]\((https?:\/\/[^\s)]+)\))/.source,
    /\[(S\d{1,4})\]/.source,
    `((!?)\\[([^\\]\\n]*)\\]\\(source:(${UUID})\\))`,
  ].join("|"),
);

function safeUrl(url: string): string | null {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

/** A citation such as [S2]: a link to the cited file when the server confirmed it was sent, otherwise plain text. */
function Citation({ id, cite }: { id: string; cite: Cite | undefined }) {
  if (!cite) return <>{`[${id}]`}</>;
  return (
    <Link className="cite" to={`/library/${cite.source_id}`} title={`${cite.filename} · ${cite.label}`} aria-label={`Source ${id}: ${cite.filename}, ${cite.label}`}>
      {id}
    </Link>
  );
}

/** A linked Library file: a picture is shown, any other file is a link to it in the Library. */
export function SourceRef({ id, label, image, info }: { id: string; label: string; image: boolean; info: NoteRef | undefined }) {
  const name = label.trim() || info?.filename || "file";
  if (info?.missing) {
    return (
      <span className="note-ref missing" title="This file was deleted from your Library or is not available.">
        {name} (missing file)
      </span>
    );
  }
  if (image && (!info || info.kind === "image")) return <NoteImage id={id} name={name} filename={info?.filename ?? name} />;
  return (
    <Link to={`/library/${id}`} className="note-ref" title={info?.filename ? `${info.filename}: open in Library` : "Open in Library"}>
      {name}
    </Link>
  );
}

/** A picture from the Library; if its file cannot be loaded, a link to it in the Library instead of a broken image. */
function NoteImage({ id, name, filename }: { id: string; name: string; filename: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <Link to={`/library/${id}`} className="note-ref" title="The picture could not be loaded. Open it in Library.">
        {name} (picture could not be loaded)
      </Link>
    );
  }
  return (
    <Link to={`/library/${id}`} className="note-image" title={`${filename}: open in Library`}>
      <img src={`${API}/sources/${id}/file`} alt={name} loading="lazy" onError={() => setFailed(true)} />
    </Link>
  );
}

export function inline(text: string, key = "i", cites?: Cites, refs?: Refs): ReactNode[] {
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
    else if (m[2]) out.push(<strong key={k}>{inline(token.slice(2, -2), k, cites, refs)}</strong>);
    else if (m[3]) out.push(<em key={k}>{inline(token.slice(1, -1), k, cites, refs)}</em>);
    else if (m[6]) out.push(cites ? <Citation key={k} id={m[6]} cite={cites[m[6]]} /> : token);
    else if (m[7]) {
      const id = m[10]!.toLowerCase();
      out.push(refs ? <SourceRef key={k} id={id} label={m[9]!} image={m[8] === "!"} info={refs[id]} /> : token);
    }
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

function List({
  items,
  ordered,
  start,
  cites,
  refs,
}: {
  items: { text: string; depth: number }[];
  ordered: boolean;
  start: number;
  cites?: Cites;
  refs?: Refs;
}) {
  const Tag = ordered ? "ol" : "ul";
  return (
    <Tag start={ordered && start !== 1 ? start : undefined}>
      {items.map((it, i) => (
        <li key={i} style={it.depth ? { marginLeft: `${it.depth * 1.25}em` } : undefined}>
          {inline(it.text, `l${i}`, cites, refs)}
        </li>
      ))}
    </Tag>
  );
}

export function Markdown({
  text,
  visuals,
  source = "the model",
  cites,
  refs,
}: {
  text: string;
  visuals?: VisualResult[];
  source?: string;
  cites?: Cites;
  /** Only for the learner's notes: resolves `source:` links to their Library files. */
  refs?: Refs;
}) {
  let visual = 0;
  return (
    <div className="md">
      {parseBlocks(text).map((b, i) => {
        switch (b.kind) {
          case "h": {
            const Tag = b.level <= 2 ? "h3" : b.level === 3 ? "h4" : "h5";
            return <Tag key={i}>{inline(b.text, `h${i}`, cites, refs)}</Tag>;
          }
          case "code":
            if (visuals && b.lang.toLowerCase() === VISUAL_LANG) {
              return <Visual key={i} result={visuals[visual++]} raw={b.text} source={source} cites={cites} />;
            }
            return (
              <pre key={i} className="md-code" aria-label={b.lang ? `${b.lang} code` : "Code"}>
                <code>{b.text}</code>
              </pre>
            );
          case "list":
            return <List key={i} items={b.items} ordered={b.ordered} start={b.start} cites={cites} refs={refs} />;
          case "quote":
            return <blockquote key={i}>{b.lines.map((l, j) => <p key={j}>{inline(l, `q${i}-${j}`, cites, refs)}</p>)}</blockquote>;
          case "table":
            return (
              <div key={i} className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      {b.head.map((c, j) => (
                        <th key={j}>{inline(c, `t${i}-${j}`, cites, refs)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r, j) => (
                      <tr key={j}>
                        {r.map((c, k) => (
                          <td key={k}>{inline(c, `t${i}-${j}-${k}`, cites, refs)}</td>
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
                    {inline(l, `p${i}-${j}`, cites, refs)}
                  </Fragment>
                ))}
              </p>
            );
        }
      })}
    </div>
  );
}
