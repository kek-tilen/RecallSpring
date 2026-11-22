import type { ReactNode } from "react";

/**
 * Formulas written in LaTeX (`\( … \)`, `\[ … \]`, `$ … $`, `$$ … $$`) shown as MathML, which the browser draws
 * itself. The TeX is parsed here into a small tree and rendered as React elements only: no HTML string, no model
 * markup is ever inserted or run (AGENTS.md), and no attribute value comes from the formula. A formula that uses
 * something this subset does not know is shown as its source text instead of being guessed.
 */

type MathNode =
  | {
      t: "mi" | "mn" | "mo" | "mtext";
      v: string;
      normal?: boolean;
      bold?: boolean;
      stretchy?: boolean;
      movable?: boolean;
      size?: string;
      prefix?: boolean;
    }
  | { t: "row"; c: MathNode[]; cls?: string }
  | { t: "frac"; n: MathNode; d: MathNode; thin?: boolean }
  | { t: "sqrt"; c: MathNode; idx?: MathNode }
  | { t: "scripts"; base: MathNode; sub?: MathNode; sup?: MathNode; under: boolean }
  | { t: "over"; c: MathNode; acc: MathNode; under: boolean; accent: boolean }
  | { t: "space"; w: string }
  | { t: "table"; rows: MathNode[][]; cls?: string }
  | { t: "phantom"; c: MathNode };

class Unsupported extends Error {}

const GREEK: Record<string, string> = {
  alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ϵ", varepsilon: "ε", zeta: "ζ", eta: "η", theta: "θ",
  vartheta: "ϑ", iota: "ι", kappa: "κ", lambda: "λ", mu: "μ", nu: "ν", xi: "ξ", pi: "π", varpi: "ϖ", rho: "ρ",
  varrho: "ϱ", sigma: "σ", varsigma: "ς", tau: "τ", upsilon: "υ", phi: "ϕ", varphi: "φ", chi: "χ", psi: "ψ",
  omega: "ω", Gamma: "Γ", Delta: "Δ", Theta: "Θ", Lambda: "Λ", Xi: "Ξ", Pi: "Π", Sigma: "Σ", Upsilon: "Υ", Phi: "Φ",
  Psi: "Ψ", Omega: "Ω",
};

/** Letter-like symbols (identifiers). */
const IDENT: Record<string, string> = {
  infty: "∞", partial: "∂", nabla: "∇", ell: "ℓ", hbar: "ℏ", emptyset: "∅", varnothing: "∅", aleph: "ℵ", Re: "ℜ",
  Im: "ℑ", top: "⊤", bot: "⊥", imath: "ı", jmath: "ȷ", wp: "℘",
};

/** Operators, relations, arrows and punctuation. */
const OPS: Record<string, string> = {
  times: "×", cdot: "⋅", pm: "±", mp: "∓", div: "÷", ast: "∗", star: "⋆", circ: "∘", bullet: "∙", setminus: "∖",
  le: "≤", leq: "≤", ge: "≥", geq: "≥", leqslant: "⩽", geqslant: "⩾", ne: "≠", neq: "≠", approx: "≈", equiv: "≡",
  sim: "∼", simeq: "≃", cong: "≅", propto: "∝", ll: "≪", gg: "≫", prec: "≺", succ: "≻", doteq: "≐",
  to: "→", rightarrow: "→", leftarrow: "←", gets: "←", leftrightarrow: "↔", Rightarrow: "⇒", Leftarrow: "⇐",
  Leftrightarrow: "⇔", implies: "⟹", impliedby: "⟸", iff: "⟺", mapsto: "↦", longrightarrow: "⟶",
  longleftarrow: "⟵", longleftrightarrow: "⟷", Longrightarrow: "⟹", Longleftarrow: "⟸", Longleftrightarrow: "⟺",
  uparrow: "↑", downarrow: "↓", updownarrow: "↕", Uparrow: "⇑", Downarrow: "⇓", nearrow: "↗", searrow: "↘",
  rightleftharpoons: "⇌", hookrightarrow: "↪",
  in: "∈", notin: "∉", ni: "∋", subset: "⊂", subseteq: "⊆", supset: "⊃", supseteq: "⊇", subsetneq: "⊊",
  cup: "∪", cap: "∩", land: "∧", wedge: "∧", lor: "∨", vee: "∨", neg: "¬", lnot: "¬", oplus: "⊕", ominus: "⊖",
  otimes: "⊗", odot: "⊙", oslash: "⊘", forall: "∀", exists: "∃", nexists: "∄", vdash: "⊢", models: "⊨",
  perp: "⊥", parallel: "∥", mid: "∣", nmid: "∤", angle: "∠", triangle: "△", square: "□", checkmark: "✓",
  therefore: "∴", because: "∵", ldots: "…", dots: "…", dotsc: "…", dotsb: "⋯", cdots: "⋯", vdots: "⋮", ddots: "⋱",
  colon: ":", prime: "′", degree: "°", lbrace: "{", rbrace: "}", langle: "⟨", rangle: "⟩", lfloor: "⌊",
  rfloor: "⌋", lceil: "⌈", rceil: "⌉", vert: "|", lvert: "|", rvert: "|", Vert: "‖", lVert: "‖", rVert: "‖",
  backslash: "∖", dagger: "†", ddagger: "‡", wr: "≀", amalg: "⨿", sqcup: "⊔", sqcap: "⊓", uplus: "⊎",
  "{": "{", "}": "}", "|": "‖", "%": "%", $: "$", "#": "#", _: "_", "&": "&",
};

/** Large operators and limits: their scripts go under and over in display formulas. */
const BIG: Record<string, string> = {
  sum: "∑", prod: "∏", coprod: "∐", int: "∫", iint: "∬", iiint: "∭", oint: "∮", bigcup: "⋃", bigcap: "⋂",
  bigvee: "⋁", bigwedge: "⋀", bigoplus: "⨁", bigotimes: "⨂", bigsqcup: "⨆",
  lim: "lim", liminf: "lim inf", limsup: "lim sup", max: "max", min: "min", sup: "sup", inf: "inf", det: "det",
  gcd: "gcd", Pr: "Pr", argmax: "arg max", argmin: "arg min",
};
const INTEGRALS = new Set(["int", "iint", "iiint", "oint"]);

const FUNCS = new Set([
  "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh", "coth", "log", "ln",
  "lg", "exp", "dim", "ker", "deg", "arg", "hom", "mod", "sgn", "tg", "ctg", "arctg", "arcctg",
]);

const SPACES: Record<string, string> = {
  ",": "0.1667em", thinspace: "0.1667em", ":": "0.2222em", ">": "0.2222em", medspace: "0.2222em",
  ";": "0.2778em", thickspace: "0.2778em", " ": "0.25em", enspace: "0.5em", quad: "1em", qquad: "2em",
};

/** \overline-style accents: the mark and whether it stretches over its base. */
const ACCENTS: Record<string, { v: string; stretchy: boolean; under?: boolean }> = {
  overline: { v: "‾", stretchy: true }, bar: { v: "¯", stretchy: false }, hat: { v: "^", stretchy: false },
  widehat: { v: "^", stretchy: true }, tilde: { v: "~", stretchy: false }, widetilde: { v: "~", stretchy: true },
  vec: { v: "→", stretchy: false }, dot: { v: "˙", stretchy: false }, ddot: { v: "¨", stretchy: false },
  check: { v: "ˇ", stretchy: false }, breve: { v: "˘", stretchy: false }, acute: { v: "´", stretchy: false },
  grave: { v: "`", stretchy: false }, overrightarrow: { v: "→", stretchy: true },
  overleftarrow: { v: "←", stretchy: true }, overbrace: { v: "⏞", stretchy: true },
  underline: { v: "_", stretchy: true, under: true }, underbrace: { v: "⏟", stretchy: true, under: true },
};

const DOUBLE_STRUCK: Record<string, string> = { C: "ℂ", H: "ℍ", N: "ℕ", P: "ℙ", Q: "ℚ", R: "ℝ", Z: "ℤ" };
const SCRIPT_HOLES: Record<string, string> = { B: "ℬ", E: "ℰ", F: "ℱ", H: "ℋ", I: "ℐ", L: "ℒ", M: "ℳ", R: "ℛ" };

const DELIMS: Record<string, string> = {
  "(": "(", ")": ")", "[": "[", "]": "]", "|": "|", "/": "/", "<": "⟨", ">": "⟩",
  "\\{": "{", "\\}": "}", "\\|": "‖", "\\langle": "⟨", "\\rangle": "⟩", "\\lfloor": "⌊", "\\rfloor": "⌋",
  "\\lceil": "⌈", "\\rceil": "⌉", "\\vert": "|", "\\lvert": "|", "\\rvert": "|", "\\Vert": "‖", "\\lVert": "‖",
  "\\rVert": "‖", "\\lbrace": "{", "\\rbrace": "}", "\\backslash": "∖", "\\uparrow": "↑", "\\downarrow": "↓",
};

const BIG_SIZES: Record<string, string> = {
  big: "1.2em", bigl: "1.2em", bigr: "1.2em", bigm: "1.2em", Big: "1.8em", Bigl: "1.8em", Bigr: "1.8em", Bigm: "1.8em",
  bigg: "2.4em", biggl: "2.4em", biggr: "2.4em", biggm: "2.4em", Bigg: "3em", Biggl: "3em", Biggr: "3em", Biggm: "3em",
};

const FENCED: Record<string, [string, string]> = {
  pmatrix: ["(", ")"], bmatrix: ["[", "]"], Bmatrix: ["{", "}"], vmatrix: ["|", "|"], Vmatrix: ["‖", "‖"],
};
const ENVS = new Set([
  "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "smallmatrix", "cases", "array", "aligned", "align",
  "align*", "alignat", "alignat*", "gathered", "gather", "gather*", "split", "equation", "equation*", "multline",
  "multline*", "eqnarray", "eqnarray*",
]);

const row = (c: MathNode[], cls?: string): MathNode => (c.length === 1 && !cls ? c[0]! : { t: "row", c, cls });
const mo = (v: string, extra: Partial<{ stretchy: boolean; movable: boolean; size: string }> = {}): MathNode => ({ t: "mo", v, ...extra });

class Parser {
  p = 0;
  constructor(private s: string) {}

  private ws() {
    while (this.p < this.s.length && /\s/.test(this.s[this.p]!)) this.p++;
  }

  /** The command name at the cursor (`\frac` → "frac", `\,` → ","), without moving. */
  private cmd(): string | null {
    if (this.s[this.p] !== "\\") return null;
    const m = /^\\([A-Za-z]+\*?|[\s\S])/.exec(this.s.slice(this.p));
    return m ? m[1]! : null;
  }

  private takeCmd(): string {
    const c = this.cmd()!;
    this.p += c.length + 1;
    return c;
  }

  /** The raw text of a `{…}` group (nested braces kept), or of a single character. */
  private raw(): string {
    this.ws();
    if (this.s[this.p] !== "{") {
      const c = this.s[this.p] ?? "";
      this.p++;
      return c;
    }
    let depth = 0;
    const start = this.p + 1;
    for (; this.p < this.s.length; this.p++) {
      const ch = this.s[this.p];
      if (ch === "\\") {
        this.p++;
        continue;
      }
      if (ch === "{") depth++;
      else if (ch === "}" && --depth === 0) {
        this.p++;
        return this.s.slice(start, this.p - 1);
      }
    }
    throw new Unsupported("unclosed group");
  }

  /** An optional `[…]` argument's raw text. */
  private optional(): string | null {
    this.ws();
    if (this.s[this.p] !== "[") return null;
    const end = this.s.indexOf("]", this.p);
    if (end < 0) throw new Unsupported("unclosed [");
    const text = this.s.slice(this.p + 1, end);
    this.p = end + 1;
    return text;
  }

  /** A whole formula: rows split by `\\` become a stacked table. */
  formula(): MathNode {
    const rows = this.rows(null);
    if (this.p < this.s.length) throw new Unsupported(`unexpected ${this.s.slice(this.p, this.p + 8)}`);
    if (rows.length === 1 && rows[0]!.length === 1) return rows[0]![0]!;
    return { t: "table", rows, cls: "m-gather" };
  }

  /** Rows of cells until `\end{env}` (or the end of the formula when env is null). */
  private rows(env: string | null): MathNode[][] {
    const rows: MathNode[][] = [];
    let cells: MathNode[] = [];
    for (;;) {
      cells.push(row(this.expr()));
      this.ws();
      const ch = this.s[this.p];
      if (ch === "&") {
        this.p++;
        continue;
      }
      const c = this.cmd();
      if (c === "\\" || c === "cr") {
        this.takeCmd();
        this.optional();
        rows.push(cells);
        cells = [];
        continue;
      }
      if (env !== null && c === "end") {
        this.takeCmd();
        const name = this.raw();
        if (name !== env) throw new Unsupported(`\\end{${name}} for ${env}`);
        break;
      }
      if (this.p >= this.s.length) {
        if (env !== null) throw new Unsupported(`no \\end{${env}}`);
        break;
      }
      if (ch === "}") throw new Unsupported("unmatched }");
      throw new Unsupported(`unexpected \\${c}`);
    }
    if (cells.length > 1 || (cells[0] && !(cells[0].t === "row" && cells[0].c.length === 0))) rows.push(cells);
    return rows.length ? rows : [[row([])]];
  }

  /** Items until `}`, `&`, `\\`, `\right` or `\end` (left for the caller). */
  private expr(): MathNode[] {
    const items: MathNode[] = [];
    for (;;) {
      this.ws();
      if (this.p >= this.s.length) break;
      const ch = this.s[this.p]!;
      if (ch === "}" || ch === "&") break;
      const c = this.cmd();
      if (c === "\\" || c === "cr" || c === "right" || c === "end") break;
      if (ch === "^" || ch === "_") {
        this.p++;
        this.script(items, ch === "^" ? "sup" : "sub", this.arg());
      } else if (ch === "'") {
        let primes = "";
        while (this.s[this.p] === "'") {
          primes += "′";
          this.p++;
        }
        this.script(items, "sup", mo(primes));
      } else {
        const a = this.atom();
        if (a && a.t === "mo" && (a.v === "−" || a.v === "+" || a.v === "±" || a.v === "∓")) {
          const prev = items[items.length - 1];
          if (!prev || (prev.t === "mo" && !")]}|⟩⌋⌉‖".includes(prev.v) && !prev.movable)) a.prefix = true;
        }
        if (a) items.push(a);
      }
    }
    return items;
  }

  private script(items: MathNode[], kind: "sub" | "sup", arg: MathNode) {
    const last = items.pop() ?? row([]);
    if (last.t === "scripts" && !last[kind]) {
      last[kind] = arg;
      items.push(last);
      return;
    }
    if (last.t === "scripts" && kind === "sup" && arg.t === "mo" && arg.v.startsWith("′") && last.sup) {
      throw new Unsupported("double superscript");
    }
    if (last.t === "scripts" && last[kind]) throw new Unsupported(`double ${kind}script`);
    const under = (last.t === "mo" && !!last.movable) || (last.t === "over" && /[⏞⏟]/.test(last.acc.t === "mo" ? last.acc.v : ""));
    items.push({ t: "scripts", base: last, [kind]: arg, under });
  }

  /** One argument: a group, a command or a single character. */
  private arg(): MathNode {
    this.ws();
    const ch = this.s[this.p];
    if (ch === undefined) throw new Unsupported("missing argument");
    if (ch === "{") {
      this.p++;
      const items = this.expr();
      if (this.s[this.p] !== "}") throw new Unsupported("unclosed {");
      this.p++;
      return row(items);
    }
    if (ch === "\\") {
      const a = this.atom();
      if (!a) throw new Unsupported("empty argument");
      return a;
    }
    this.p++;
    return this.char(ch);
  }

  private char(ch: string): MathNode {
    if (/\d/.test(ch)) return { t: "mn", v: ch };
    if (/\p{L}/u.test(ch)) return { t: "mi", v: ch };
    if (ch === "-") return mo("−");
    if (ch === "*") return mo("∗");
    if ("()[]|".includes(ch)) return mo(ch, { stretchy: false });
    if (ch === "~") return { t: "space", w: "0.25em" };
    if (ch === "$" || ch === "#" || ch === "%") throw new Unsupported(`bare ${ch}`);
    return mo(ch);
  }

  private atom(): MathNode | null {
    const ch = this.s[this.p]!;
    if (ch === "{") {
      this.p++;
      const items = this.expr();
      if (this.s[this.p] !== "}") throw new Unsupported("unclosed {");
      this.p++;
      // {,} is the decimal comma: no operator spacing.
      if (items.length === 1 && items[0]!.t === "mo" && items[0]!.v === ",") return { t: "mn", v: "," };
      return { t: "row", c: items };
    }
    if (/\d/.test(ch)) {
      const m = /^\d+(?:(?:\.|\{,\})\d+)*/.exec(this.s.slice(this.p))!;
      this.p += m[0].length;
      return { t: "mn", v: m[0].replaceAll("{,}", ",") };
    }
    if (ch === "\\") return this.command(this.takeCmd());
    this.p++;
    return this.char(ch);
  }

  private delimiter(): string {
    this.ws();
    const c = this.cmd();
    if (c) {
      this.takeCmd();
      const d = DELIMS[`\\${c}`];
      if (d === undefined) throw new Unsupported(`delimiter \\${c}`);
      return d;
    }
    const ch = this.s[this.p++] ?? "";
    if (ch === ".") return "";
    const d = DELIMS[ch];
    if (d === undefined) throw new Unsupported(`delimiter ${ch}`);
    return d;
  }

  private styled(raw: string, style: "normal" | "bold" | "bb" | "cal"): MathNode {
    if (style === "bb" || style === "cal") {
      return row(
        [...raw.replace(/\s/g, "")].map((l) => {
          const code = l.charCodeAt(0);
          if (style === "bb" && DOUBLE_STRUCK[l]) return { t: "mi", v: DOUBLE_STRUCK[l]! } as MathNode;
          if (style === "cal" && /[A-Z]/.test(l)) {
            return { t: "mi", v: SCRIPT_HOLES[l] ?? String.fromCodePoint(0x1d49c + code - 65) } as MathNode;
          }
          return { t: "mi", v: l, normal: true, bold: style === "bb" } as MathNode;
        }),
      );
    }
    const node = new Parser(raw).formula();
    const mark = (n: MathNode): void => {
      if (n.t === "mi" || n.t === "mn" || n.t === "mo" || n.t === "mtext") {
        if (n.t === "mi") n.normal = true;
        if (style === "bold") n.bold = true;
      } else if (n.t === "row") n.c.forEach(mark);
      else if (n.t === "scripts") mark(n.base);
    };
    mark(node);
    return node;
  }

  private command(name: string): MathNode | null {
    if (name in GREEK) {
      const v = GREEK[name]!;
      return { t: "mi", v, normal: /[Α-Ω]/.test(v) };
    }
    if (name in IDENT) return { t: "mi", v: IDENT[name]! };
    if (name in BIG) {
      const integral = INTEGRALS.has(name);
      return mo(BIG[name]!, { movable: !integral, stretchy: false });
    }
    if (FUNCS.has(name)) return { t: "mi", v: name };
    if (name in OPS) return mo(OPS[name]!, "{}|".includes(OPS[name]!) || "⟨⟩⌊⌋⌈⌉‖".includes(OPS[name]!) ? { stretchy: false } : {});
    if (name in SPACES) return { t: "space", w: SPACES[name]! };
    if (name === "overline" || name === "underline") return row([this.arg()], name === "overline" ? "m-overline" : "m-underline");
    if (name in ACCENTS) {
      const a = ACCENTS[name]!;
      return { t: "over", c: this.arg(), acc: mo(a.v, { stretchy: a.stretchy }), under: !!a.under, accent: true };
    }
    if (name in BIG_SIZES) return mo(this.delimiter() || "", { stretchy: true, size: BIG_SIZES[name] });
    switch (name) {
      case "frac":
      case "dfrac":
      case "tfrac":
      case "cfrac":
        return { t: "frac", n: this.arg(), d: this.arg() };
      case "binom":
      case "dbinom":
      case "tbinom":
        return row([mo("(", { stretchy: true }), { t: "frac", n: this.arg(), d: this.arg(), thin: true }, mo(")", { stretchy: true })]);
      case "sqrt": {
        const idx = this.optional();
        return { t: "sqrt", c: this.arg(), idx: idx === null ? undefined : new Parser(idx).formula() };
      }
      case "text":
      case "textrm":
      case "textnormal":
      case "textup":
      case "textit":
      case "textsf":
      case "texttt":
      case "mbox":
      case "hbox":
        return { t: "mtext", v: this.raw().replace(/\\([%&$#_{} ])/g, "$1").replace(/~/g, " ") };
      case "textbf":
        return { t: "mtext", v: this.raw(), bold: true };
      case "mathrm":
      case "operatorname":
      case "operatorname*":
      case "mathup":
      case "mathsf":
      case "mathtt":
        return this.styled(this.raw(), "normal");
      case "mathbf":
      case "boldsymbol":
      case "bm":
      case "pmb":
        return this.styled(this.raw(), "bold");
      case "mathbb":
        return this.styled(this.raw(), "bb");
      case "mathcal":
      case "mathscr":
        return this.styled(this.raw(), "cal");
      case "mathit":
      case "mathnormal":
      case "mathfrak":
        return row(new Parser(this.raw()).expr());
      case "left": {
        const open = this.delimiter();
        const inner = this.expr();
        if (this.cmd() !== "right") throw new Unsupported("\\left without \\right");
        this.takeCmd();
        const close = this.delimiter();
        return {
          t: "row",
          c: [...(open ? [mo(open, { stretchy: true })] : []), ...inner, ...(close ? [mo(close, { stretchy: true })] : [])],
        };
      }
      case "middle":
        return mo(this.delimiter(), { stretchy: true });
      case "overset":
      case "stackrel": {
        const top = this.arg();
        return { t: "over", c: this.arg(), acc: top, under: false, accent: false };
      }
      case "underset": {
        const bottom = this.arg();
        return { t: "over", c: this.arg(), acc: bottom, under: true, accent: false };
      }
      case "boxed":
      case "fbox":
        return row([this.arg()], "m-boxed");
      case "phantom":
      case "hphantom":
      case "vphantom":
        return { t: "phantom", c: this.arg() };
      case "color":
        this.raw();
        return null;
      case "textcolor":
      case "colorbox":
        this.raw();
        return this.arg();
      case "displaystyle":
      case "textstyle":
      case "scriptstyle":
      case "limits":
      case "nolimits":
      case "nonumber":
      case "notag":
      case "!":
      case "allowbreak":
        return null;
      case "tag":
      case "label":
        this.raw();
        return null;
      case "hspace":
      case "hskip":
      case "kern":
      case "mkern":
        this.raw();
        return { t: "space", w: "0.5em" };
      case "not": {
        const next = this.arg();
        if (next.t !== "mo") throw new Unsupported("\\not");
        const negated: Record<string, string> = { "=": "≠", "∈": "∉", "⊂": "⊄", "⊆": "⊈", "≡": "≢", "<": "≮", ">": "≯", "∼": "≁" };
        return mo(negated[next.v] ?? `${next.v}̸`);
      }
      case "bmod":
        return mo("mod");
      case "pmod": {
        const n = this.arg();
        return row([{ t: "space", w: "0.5em" }, mo("("), mo("mod"), { t: "space", w: "0.3333em" }, n, mo(")")]);
      }
      case "begin": {
        const env = this.raw();
        if (!ENVS.has(env)) throw new Unsupported(`environment ${env}`);
        if (env === "array" || env.startsWith("alignat")) this.raw(); // column spec / column count
        const rows = this.rows(env);
        if (env.startsWith("equation")) return rows.length === 1 && rows[0]!.length === 1 ? rows[0]![0]! : { t: "table", rows };
        const cls = env === "cases" ? "m-cases" : /^(align|split|eqnarray)/.test(env) ? "m-align" : env.startsWith("gather") ? "m-gather" : undefined;
        const table: MathNode = { t: "table", rows, cls };
        if (env === "cases") return row([mo("{", { stretchy: true }), table]);
        const fence = FENCED[env];
        return fence ? row([mo(fence[0], { stretchy: true }), table, mo(fence[1], { stretchy: true })]) : table;
      }
      default:
        throw new Unsupported(`\\${name}`);
    }
  }
}

/** The formula's tree, or null when it uses something not supported here (it is then shown as text). */
export function parseTex(tex: string): MathNode | null {
  if (tex.length > 4000) return null;
  try {
    return new Parser(tex).formula();
  } catch (e) {
    if (e instanceof Unsupported || e instanceof RangeError) return null;
    throw e;
  }
}

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
