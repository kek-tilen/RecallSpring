import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Markdown, parseBlocks } from "./components/Markdown";

afterEach(cleanup);

describe("Markdown", () => {
  it("renders the common structure of a reply", () => {
    const text = [
      "## Zagotavljanje kakovosti",
      "",
      "Je **sistem** načrtovanih postopkov z `testi` in *pregledi*.",
      "",
      "- preprečevanje napak",
      "- odkrivanje napak",
      "",
      "1. načrt",
      "2. izvedba",
      "",
      "| Pojem | Pomen |",
      "|---|---|",
      "| QA | proces |",
      "",
      "```python",
      "print('hi')",
      "```",
    ].join("\n");
    const { container } = render(<Markdown text={text} />);
    expect(container.querySelector("h3")?.textContent).toBe("Zagotavljanje kakovosti");
    expect(container.querySelector("strong")?.textContent).toBe("sistem");
    expect(container.querySelector("p code")?.textContent).toBe("testi");
    expect(container.querySelector("em")?.textContent).toBe("pregledi");
    expect(container.querySelectorAll("ul li")).toHaveLength(2);
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
    expect(container.querySelector("td")?.textContent).toBe("QA");
    expect(container.querySelector("pre code")?.textContent).toBe("print('hi')");
  });

  it("never turns HTML, scripts or unsafe links into elements", () => {
    const text = '<script>alert(1)</script>\n\n<img src=x onerror="alert(1)">\n\n[click](javascript:alert(1)) [ok](https://example.com)';
    const { container } = render(<Markdown text={text} />);
    expect(container.querySelector("script, img, style, iframe")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0]!.getAttribute("href")).toBe("https://example.com/");
    expect(links[0]!.getAttribute("rel")).toContain("noopener");
  });

  it("keeps an unclosed code fence as code", () => {
    expect(parseBlocks("```\nconst a = 1;")).toEqual([{ kind: "code", lang: "", text: "const a = 1;" }]);
  });
});
