import { cleanup, render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { Markdown, parseBlocks } from "./components/Markdown";
import { Formula, parseTex } from "./components/Math";

afterEach(cleanup);

const md = (text: string) =>
  render(
    <MemoryRouter>
      <Markdown text={text} />
    </MemoryRouter>,
  ).container;

const MATHML = "http://www.w3.org/1998/Math/MathML";

describe("formulas", () => {
  it("draws inline \\( \\) and $ $ formulas as MathML", () => {
    const c = md("Normalised: \\(0{,}011_2 = 1{,}1_2 \\times 2^{-2}\\) and $E = e + 127$.");
    const maths = c.querySelectorAll("math");
    expect(maths).toHaveLength(2);
    expect(maths[0]!.namespaceURI).toBe(MATHML);
    expect(maths[0]!.getAttribute("display")).toBeNull();
    expect([...maths[0]!.querySelectorAll("mn")].map((n) => n.textContent)).toContain("0,011");
    expect(maths[0]!.querySelectorAll("msub")).toHaveLength(2);
    expect(maths[0]!.querySelector("msup mrow")?.textContent).toBe("−2");
    expect(c.textContent).not.toContain("\\(");
  });

  it("draws \\[ \\] on its own lines as a display formula, also over several lines", () => {
    const text = "Value:\n\\[\n(-1)^{S} \\cdot \\left(1 + \\frac{M}{2^{23}}\\right) \\cdot 2^{E-127}\n\\]\nDone.";
    const blocks = parseBlocks(text);
    expect(blocks.map((b) => b.kind)).toEqual(["p", "math", "p"]);
    const c = md(text);
    const m = c.querySelector("math")!;
    expect(m.getAttribute("display")).toBe("block");
    expect(m.querySelector("mfrac")).toBeTruthy();
    expect([...m.querySelectorAll("mo[stretchy=true]")].map((o) => o.textContent)).toEqual(["(", ")"]);
  });

  it("keeps money, code and unknown commands as text", () => {
    const c = md("It costs $5 and $10. Code: `\\(x\\)`. Odd: \\(\\foo{x}\\)");
    expect(c.querySelectorAll("math")).toHaveLength(0);
    expect(c.querySelector("code")?.textContent).toBe("\\(x\\)");
    const raw = c.querySelector(".math-raw");
    expect(raw?.textContent).toBe("\\(\\foo{x}\\)");
  });

  it("an underscore in a formula is not italics", () => {
    const c = md("word_a and \\(x_1 + y_2\\)");
    expect(c.querySelector("em")).toBeNull();
    expect(c.querySelectorAll("msub")).toHaveLength(2);
  });

  it("knows Boolean algebra, roots, sums, cases and matrices", () => {
    expect(parseTex("\\overline{A \\cdot B} = \\overline{A} + \\overline{B}")).not.toBeNull();
    expect(parseTex("\\sqrt[3]{x} + \\sum_{i=1}^{n} i^2")).not.toBeNull();
    expect(parseTex("f(x) = \\begin{cases} 1 & x > 0 \\\\ 0 & \\text{otherwise} \\end{cases}")).not.toBeNull();
    expect(parseTex("\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}")).not.toBeNull();
    expect(parseTex("x \\equiv 3 \\pmod{7}, \\; \\mathbb{R}, \\alpha \\le \\beta")).not.toBeNull();
    expect(parseTex("\\left( x")).toBeNull();
    expect(parseTex("a^b^c")).toBeNull();
    expect(parseTex("\\begin{tikzpicture}\\end{tikzpicture}")).toBeNull();
  });

  it("draws a NOT bar over the whole term and a leading minus as a sign", () => {
    const c = render(<Formula tex="\overline{A \cdot B} = (-1)^S - x" />).container;
    expect(c.querySelector("mrow.m-overline")?.textContent).toBe("A⋅B");
    const minus = [...c.querySelectorAll("mo")].filter((o) => o.textContent === "−");
    expect(minus.map((o) => o.getAttribute("form"))).toEqual(["prefix", null]);
  });

  it("puts limits under a sum and text stays upright", () => {
    const c = render(<Formula tex="\sum_{k=0}^{n} k \text{ times}" display />).container;
    const sum = c.querySelector("munderover")!;
    expect(sum.firstElementChild?.textContent).toBe("∑");
    expect(sum.firstElementChild?.getAttribute("movablelimits")).toBe("true");
    expect(c.querySelector("mtext")?.textContent).toBe(" times");
  });
});
