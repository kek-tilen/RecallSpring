import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeAll, expect, it } from "vitest";
import { PhotoViewer, type ViewerPhoto } from "./components/PhotoViewer";

beforeAll(() => {
  // jsdom has no <dialog> methods.
  Object.assign(HTMLDialogElement.prototype, {
    showModal(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    },
    close(this: HTMLDialogElement) {
      this.removeAttribute("open");
    },
  });
});

afterEach(cleanup);

const PHOTOS: ViewerPhoto[] = [
  { src: "/a.png", name: "a.png", download: "/a.png" },
  { src: "/b.png", name: "b.png", download: "/b.png" },
  { src: "/c.png", name: "c.png", download: "/c.png" },
];

function Harness() {
  const [i, setI] = useState(0);
  return <PhotoViewer photos={PHOTOS} index={i} onIndex={setI} onClose={() => {}} />;
}

it("moves between several photos with buttons and arrow keys, wrapping round", () => {
  render(<Harness />);
  const viewer = screen.getByRole("dialog", { name: "Photo viewer" });
  const shown = () => (viewer.querySelector("img") as HTMLImageElement).getAttribute("src");
  expect(screen.getByText("Photo 1 of 3")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Next photo" }));
  expect(shown()).toBe("/b.png");
  fireEvent.keyDown(viewer, { key: "ArrowRight" });
  expect(shown()).toBe("/c.png");
  fireEvent.keyDown(viewer, { key: "ArrowRight" });
  expect(shown()).toBe("/a.png");
  fireEvent.click(screen.getByRole("button", { name: "Previous photo" }));
  expect(shown()).toBe("/c.png");
  expect(screen.getByText("Photo 3 of 3")).toBeTruthy();
});

it("says so when a photo cannot be shown and still offers the download", () => {
  render(<Harness />);
  fireEvent.error(screen.getByAltText("Photo 1: a.png"));
  expect(screen.getByText(/cannot be shown here; you can still download it/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Actual size" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Next photo" }));
  expect(screen.getByAltText("Photo 2: b.png")).toBeTruthy();
});
