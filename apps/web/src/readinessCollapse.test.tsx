import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { MaterialCard } from "./pages/Readiness";
import type { ExamReadiness } from "./types";

afterEach(cleanup);

const counts = { not_studied: 1, weak: 0, not_practised: 0, developing: 0, solid: 0 };
const group = (id: string, title: string) => ({
  kind: "source" as const,
  id,
  title,
  pages: null,
  counts,
  concepts: [{ id: `c-${id}`, term: `Concept of ${title}`, state: "not_studied" as const, due: false, last_grade: null, exam_weight: null, citations: [] }],
});
const READINESS = { groups: [group("s1", "Intro.pdf"), group("s2", "Windows.pptx")] } as unknown as ExamReadiness;

describe("By material: collapse and expand all (owner 2026-11-25)", () => {
  it("closes every block at once and opens them again", () => {
    const { container } = render(
      <MemoryRouter>
        <MaterialCard r={READINESS} />
      </MemoryRouter>,
    );
    const blocks = () => Array.from(container.querySelectorAll("details")).map((d) => d.open);
    expect(blocks()).toEqual([true, true]);
    fireEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    expect(blocks()).toEqual([false, false]);
    fireEvent.click(screen.getByRole("button", { name: "Expand all" }));
    expect(blocks()).toEqual([true, true]);
  });
});
