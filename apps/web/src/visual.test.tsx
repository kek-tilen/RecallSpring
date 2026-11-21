import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Markdown } from "./components/Markdown";
import { hub, levels, ticks, wrap, type VisualBlock, type VisualResult } from "./components/Visual";

afterEach(cleanup);

const graph = {
  nodes: [
    { id: "a", label: "Načrtuj" },
    { id: "b", label: "Izvedi" },
    { id: "c", label: "Preveri" },
  ],
  edges: [
    { from: "a", to: "b" },
    { from: "b", to: "c" },
    { from: "c", to: "a" },
  ],
};

const blocks: VisualBlock[] = [
  { type: "process_flow", title: "Krog PDCA", alt_text: "Three steps in a loop.", data: graph },
  { type: "concept_map", title: "Pojmi", alt_text: "Three related ideas.", data: graph },
  {
    type: "comparison",
    title: "QA in QC",
    alt_text: "QA is about the process, QC about the product.",
    data: { columns: ["QA", "QC"], rows: [{ criterion: "Fokus", values: ["proces", "izdelek"] }] },
  },
  {
    type: "timeline",
    title: "Zgodovina",
    alt_text: "Two events.",
    data: { events: [{ label: "1950", description: "Deming" }, { label: "1987", description: "ISO 9000" }] },
  },
  {
    type: "data_chart",
    title: "Napake",
    alt_text: "Defects fall over weeks.",
    illustrative: true,
    data: { chart: "line", x_label: "Teden", y_label: "Napake", points: [{ x: 1, y: 12 }, { x: 2, y: 7 }, { x: 3, y: 4 }] },
  },
  {
    type: "interactive_parameter",
    title: "Razpad",
    alt_text: "Exponential decay with rate k.",
    data: { parameter: "k", minimum: 0.1, maximum: 2, step: 0.1, initial: 1, preset: "exponential_decay" },
  },
];

const fence = (n: number) => Array.from({ length: n }, () => "```recallspring-visual\n{}\n```").join("\n\n");

describe("Visual blocks", () => {
  it("draws every allowed type from the checked copy, with its description", () => {
    const visuals: VisualResult[] = blocks.map((block) => ({ ok: true, block }));
    const { container } = render(<Markdown text={`Uvod.\n\n${fence(blocks.length)}`} visuals={visuals} source="ChatGPT" />);
    expect(container.querySelectorAll("figure.viz")).toHaveLength(6);
    for (const b of blocks) expect(screen.getByText(b.title, { selector: "figcaption strong" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Three steps in a loop." })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "QC" })).toBeTruthy();
    expect(screen.getByText("Deming")).toBeTruthy();
    expect(screen.getByText("Illustrative example")).toBeTruthy();
    expect(screen.getAllByText(/not checked against your material/)).toHaveLength(6);
    expect(container.querySelector("script, foreignObject, iframe")).toBeNull();
  });

  it("moves a slider over a predefined formula", () => {
    render(<Markdown text={fence(1)} visuals={[{ ok: true, block: blocks[5]! }]} />);
    expect(screen.getByText("y = e^(−1 · x)")).toBeTruthy();
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0.5" } });
    expect(screen.getByText("y = e^(−0.5 · x)")).toBeTruthy();
  });

  it("explains a block that could not be shown and keeps its text as text", () => {
    const raw = '<svg onload="alert(1)"></svg>';
    const { container } = render(
      <Markdown text={"```recallspring-visual\n" + raw + "\n```"} visuals={[{ ok: false, error: "The visual is not valid JSON." }]} source="ChatGPT" />,
    );
    expect(screen.getByText(/This visual could not be shown: The visual is not valid JSON/)).toBeTruthy();
    expect(container.querySelector("svg")).toBeNull();
    expect(container.textContent).toContain(raw);
  });

  it("shows the fence as code when visuals are not given", () => {
    const { container } = render(<Markdown text={fence(1)} />);
    expect(container.querySelector("figure")).toBeNull();
    expect(container.querySelector("pre.md-code")).toBeTruthy();
  });

  it("lays out flows, ticks and labels sensibly", () => {
    const { level, back } = levels(graph);
    expect([level.get("a"), level.get("b"), level.get("c")]).toEqual([0, 1, 2]);
    expect(back.size).toBe(1);
    expect(hub(graph)).toBeNull();
    const star = {
      nodes: ["m", "a", "b", "c"].map((id) => ({ id, label: id })),
      edges: ["a", "b", "c"].map((to) => ({ from: "m", to })),
    };
    expect(hub(star)).toBe("m");
    expect(ticks(0, 12)).toEqual([0, 2.5, 5, 7.5, 10, 12.5]);
    expect(wrap("a very long label that keeps going and going on", 10, 2)).toHaveLength(2);
  });
});
