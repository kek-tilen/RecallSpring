import { IconBooks } from "@tabler/icons-react";
import { describe, expect, it } from "vitest";
import { isActive } from "./components/Layout";

// The shell (UI direction, 2026-11-27): pages that moved into an area keep that area highlighted.
describe("shell areas", () => {
  const today = { to: "/", label: "Today", icon: IconBooks, also: ["/week"] };
  const courses = { to: "/courses", label: "Courses", icon: IconBooks, also: ["/library", "/notes", "/concepts"] };

  it("matches Today only on its own page and the weekly review", () => {
    expect(isActive("/", today)).toBe(true);
    expect(isActive("/week", today)).toBe(true);
    expect(isActive("/review", today)).toBe(false);
  });

  it("keeps Courses active for its course, Library, Notes and concept pages", () => {
    for (const path of ["/courses", "/courses/abc", "/library/course/abc", "/notes/n1", "/concepts/c1"]) {
      expect(isActive(path, courses)).toBe(true);
    }
    expect(isActive("/coursesx", courses)).toBe(false);
    expect(isActive("/exams", courses)).toBe(false);
  });
});
