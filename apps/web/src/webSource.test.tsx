import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { WebOrigin } from "./pages/Library";
import type { Source } from "./types";

afterEach(cleanup);

const SOURCE: Source = {
  id: "s9",
  course_id: "c1",
  filename: "From the web - nmap -A.md",
  kind: "markdown",
  mime_type: "text/markdown",
  byte_size: 400,
  origin: "web",
  category: "material",
  folder_id: null,
  folder: null,
  archived: false,
  hidden: false,
  archived_at: null,
  duplicate_of_id: null,
  parse_state: "ready",
  parse_message: null,
  parse_notes: [],
  page_count: null,
  version: 1,
  section_count: 1,
  uploaded_at: "2026-11-25T10:00:00Z",
  parsed_at: "2026-11-25T10:00:05Z",
  web_links: [
    { url: "https://nmap.org/book/man-misc-options.html", title: "Nmap reference", read_on: "2026-11-25" },
    { url: "javascript:alert(1)", title: "Not a page", read_on: "2026-11-25" },
  ],
};

describe("a source added from the web", () => {
  it("says it is not course material and links only to http(s) pages", () => {
    render(<WebOrigin source={SOURCE} />);
    expect(screen.getByRole("note").textContent).toContain("From the web, not your course material.");
    const link = screen.getByRole("link", { name: "Nmap reference" });
    expect(link.getAttribute("href")).toBe("https://nmap.org/book/man-misc-options.html");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.queryByRole("link", { name: "Not a page" })).toBeNull();
    expect(screen.getByText("Not a page")).toBeTruthy();
  });

  it("shows nothing for course material", () => {
    const { container } = render(<WebOrigin source={{ ...SOURCE, origin: "upload", web_links: [] }} />);
    expect(container.textContent).toBe("");
  });
});
