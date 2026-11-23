/**
 * Formulas in plain text drawn as MathML through the DOM, for pages that do not run React: the MCP forms (Claude,
 * ChatGPT, Codex, Antigravity) get this file as a self-contained script (`npm run build:mcp-math`, ADR-012). Same
 * parser and the same rules as Math.tsx: elements are created one by one, text goes in as text nodes, nothing is
 * parsed as HTML, and no attribute value comes from the formula. Unsupported TeX stays visible as its source.
 */

import { parseTex, type MathNode } from "./mathParse";

const NS = "http://www.w3.org/1998/Math/MathML";

function el(tag: string, attrs: Record<string, string | undefined> = {}, children: Node[] = []): Element {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined) e.setAttribute(k, v);
  for (const c of children) e.appendChild(c);
  return e;
}

function leaf(tag: string, v: string, attrs: Record<string, string | undefined> = {}): Element {
  return el(tag, attrs, [document.createTextNode(v)]);
}

function node(n: MathNode): Element {
  switch (n.t) {
    case "mi":
      return leaf("mi", n.v, {
        mathvariant: n.normal && [...n.v].length === 1 ? "normal" : undefined,
        class: n.bold ? "m-bold" : undefined,
      });
    case "mn":
    case "mtext":
      return leaf(n.t, n.v, { class: n.bold ? "m-bold" : undefined });
    case "mo":
      return leaf("mo", n.v, {
        stretchy: n.stretchy === undefined ? undefined : String(n.stretchy),
        movablelimits: n.movable ? "true" : undefined,
        largeop: n.movable && n.v.length === 1 ? "true" : undefined,
        minsize: n.size,
        maxsize: n.size,
        symmetric: n.size ? "true" : undefined,
        form: n.prefix ? "prefix" : undefined,
        class: n.bold ? "m-bold" : undefined,
      });
    case "row":
      return el("mrow", { class: n.cls }, n.c.map(node));
    case "frac":
      return el("mfrac", { linethickness: n.thin ? "0" : undefined }, [node(n.n), node(n.d)]);
    case "sqrt":
      return n.idx ? el("mroot", {}, [node(n.c), node(n.idx)]) : el("msqrt", {}, [node(n.c)]);
    case "scripts": {
      const base = node(n.base);
      if (n.under) {
        if (n.sub && n.sup) return el("munderover", {}, [base, node(n.sub), node(n.sup)]);
        if (n.sub) return el("munder", {}, [base, node(n.sub)]);
        return el("mover", {}, [base, node(n.sup!)]);
      }
      if (n.sub && n.sup) return el("msubsup", {}, [base, node(n.sub), node(n.sup)]);
      if (n.sub) return el("msub", {}, [base, node(n.sub)]);
      return el("msup", {}, [base, node(n.sup!)]);
    }
    case "over":
      return n.under
        ? el("munder", { accentunder: n.accent ? "true" : undefined }, [node(n.c), node(n.acc)])
        : el("mover", { accent: n.accent ? "true" : undefined }, [node(n.c), node(n.acc)]);
    case "space":
      return el("mspace", { width: n.w });
    case "table":
      return el(
        "mtable",
        { class: n.cls },
        n.rows.map((r) => el("mtr", {}, r.map((c) => el("mtd", {}, [node(c)])))),
      );
    case "phantom":
      return el("mphantom", {}, [node(n.c)]);
  }
}

/** One formula as a <math> element, or its source in <code> when it cannot be drawn. */
export function formulaElement(tex: string, display: boolean, delims: [string, string]): Element {
  const tree = parseTex(tex.trim());
  if (!tree) {
    const code = document.createElement("code");
    code.className = "math-raw";
    code.textContent = `${delims[0]}${tex}${delims[1]}`;
    return code;
  }
  return el("math", { display: display ? "block" : undefined, class: display ? "math-block" : "math-inline" }, [node(tree)]);
}

// \( \), \[ \], $$ $$ and $x$ (not "costs $5 and $10"), as in Markdown.tsx
const FORMULA = /\\\(([\s\S]+?)\\\)|\\\[([\s\S]+?)\\\]|\$\$([\s\S]+?)\$\$|\$(?=[^\s$])([^$\n]*?[^\s$\\])\$(?![\d$])/g;

/** Replace the children of `target` with `text`, its formulas drawn as math. Text stays text (textContent rules). */
export function renderMathText(target: Element, text: string): void {
  target.textContent = "";
  let last = 0;
  for (const m of text.matchAll(FORMULA)) {
    if (m.index > last) target.appendChild(document.createTextNode(text.slice(last, m.index)));
    if (m[1] !== undefined) target.appendChild(formulaElement(m[1], false, ["\\(", "\\)"]));
    else if (m[2] !== undefined) target.appendChild(formulaElement(m[2], true, ["\\[", "\\]"]));
    else if (m[3] !== undefined) target.appendChild(formulaElement(m[3], true, ["$$", "$$"]));
    else target.appendChild(formulaElement(m[4]!, false, ["$", "$"]));
    last = m.index + m[0].length;
  }
  if (last < text.length) target.appendChild(document.createTextNode(text.slice(last)));
}
