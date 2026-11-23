import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MathText } from "./components/Markdown";
import { renderMathText } from "./components/mathDom";

afterEach(cleanup);

const PROMPT = String.raw`Pretvori \(-0{,}4_{10}\) v 32-bitni zapis IEEE 754.`;
const UNKNOWN = String.raw`\(\unknowncommand{1}\)`;

describe("formulas in question text (ADR-012)", () => {
  it("draws them on web pages and keeps the decimal comma", () => {
    const { container } = render(<MathText text={PROMPT} />);
    const math = container.querySelector("math");
    expect(math).toBeTruthy();
    expect(math!.textContent).toContain("0,4");
    expect(container.textContent).toContain("Pretvori ");
    expect(container.textContent).not.toContain(String.raw`\(`);
  });

  it("draws them in the MCP forms through the DOM only", () => {
    const target = document.createElement("p");
    renderMathText(target, `${PROMPT} <b>not markup</b> $x^2$ and ${UNKNOWN}`);
    const maths = target.querySelectorAll("math");
    expect(maths.length).toBe(2);
    expect(maths[0]!.namespaceURI).toBe("http://www.w3.org/1998/Math/MathML");
    expect(maths[0]!.textContent).toContain("0,4");
    expect(target.querySelector("b")).toBeNull(); // text stays text
    expect(target.textContent).toContain("<b>not markup</b>");
    expect(target.querySelector("code.math-raw")!.textContent).toBe(UNKNOWN);
  });
});
