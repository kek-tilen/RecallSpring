import type { ReactNode } from "react";

/**
 * Formulas written in LaTeX (`\( … \)`, `\[ … \]`, `$ … $`, `$$ … $$`) shown as MathML, which the browser draws
 * itself. The TeX is parsed here into a small tree and rendered as React elements only: no HTML string, no model
 * markup is ever inserted or run (AGENTS.md), and no attribute value comes from the formula. A formula that uses
 * something this subset does not know is shown as its source text instead of being guessed.
 */

import { parseTex, type MathNode } from "./mathParse";

export { parseTex };

function render(n: MathNode, key?: number | string): ReactNode {
  switch (n.t) {
    case "mi":
      return (
        <mi key={key} mathvariant={n.normal && [...n.v].length === 1 ? "normal" : undefined} className={n.bold ? "m-bold" : undefined}>
          {n.v}
        </mi>
      );
    case "mn":
      return (
        <mn key={key} className={n.bold ? "m-bold" : undefined}>
          {n.v}
        </mn>
      );
    case "mtext":
      return (
        <mtext key={key} className={n.bold ? "m-bold" : undefined}>
          {n.v}
        </mtext>
      );
    case "mo":
      return (
        <mo
          key={key}
          stretchy={n.stretchy === undefined ? undefined : String(n.stretchy)}
          movablelimits={n.movable ? "true" : undefined}
          largeop={n.movable && n.v.length === 1 ? "true" : undefined}
          minsize={n.size}
          maxsize={n.size}
          symmetric={n.size ? "true" : undefined}
          form={n.prefix ? "prefix" : undefined}
          className={n.bold ? "m-bold" : undefined}
        >
          {n.v}
        </mo>
      );
    case "row":
      return (
        <mrow key={key} className={n.cls}>
          {n.c.map((c, i) => render(c, i))}
        </mrow>
      );
    case "frac":
      return (
        <mfrac key={key} linethickness={n.thin ? "0" : undefined}>
          {render(n.n)}
          {render(n.d)}
        </mfrac>
      );
    case "sqrt":
      return n.idx ? (
        <mroot key={key}>
          {render(n.c)}
          {render(n.idx)}
        </mroot>
      ) : (
        <msqrt key={key}>{render(n.c)}</msqrt>
      );
    case "scripts": {
      const base = render(n.base);
      if (n.under) {
        if (n.sub && n.sup) return <munderover key={key}>{base}{render(n.sub)}{render(n.sup)}</munderover>;
        if (n.sub) return <munder key={key}>{base}{render(n.sub)}</munder>;
        return <mover key={key}>{base}{render(n.sup!)}</mover>;
      }
      if (n.sub && n.sup) return <msubsup key={key}>{base}{render(n.sub)}{render(n.sup)}</msubsup>;
      if (n.sub) return <msub key={key}>{base}{render(n.sub)}</msub>;
      return <msup key={key}>{base}{render(n.sup!)}</msup>;
    }
    case "over":
      return n.under ? (
        <munder key={key} accentunder={n.accent ? "true" : undefined}>
          {render(n.c)}
          {render(n.acc)}
        </munder>
      ) : (
        <mover key={key} accent={n.accent ? "true" : undefined}>
          {render(n.c)}
          {render(n.acc)}
        </mover>
      );
    case "space":
      return <mspace key={key} width={n.w} />;
    case "table":
      return (
        <mtable key={key} className={n.cls}>
          {n.rows.map((r, i) => (
            <mtr key={i}>
              {r.map((c, j) => (
                <mtd key={j}>{render(c)}</mtd>
              ))}
            </mtr>
          ))}
        </mtable>
      );
    case "phantom":
      return <mphantom key={key}>{render(n.c)}</mphantom>;
  }
}

/** One formula; `display` puts it on its own centred line. Unsupported TeX is shown as its source text. */
export function Formula({ tex, display = false, delims }: { tex: string; display?: boolean; delims?: [string, string] }) {
  const tree = parseTex(tex.trim());
  if (!tree) {
    const [open, close] = delims ?? (display ? ["\\[", "\\]"] : ["\\(", "\\)"]);
    return (
      <code className={display ? "math-raw math-raw-block" : "math-raw"} title="This formula could not be shown as math, so its source is shown.">
        {`${open}${tex}${close}`}
      </code>
    );
  }
  return (
    <math display={display ? "block" : undefined} className={display ? "math-block" : "math-inline"}>
      {render(tree)}
    </math>
  );
}
