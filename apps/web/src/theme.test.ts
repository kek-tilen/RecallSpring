import { afterEach, describe, expect, it } from "vitest";
import { applyTheme, readTheme, saveTheme, THEMES } from "./theme";

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("Themes", () => {
  it("offers eight named themes, the RecallSpring pair first", () => {
    expect(THEMES.map((t) => t.name)).toEqual([
      "RecallSpring White",
      "RecallSpring Dark",
      "Solarized Light",
      "Snow Storm",
      "Nord",
      "Dracula",
      "Gruvbox Dark",
      "OLED Dark",
    ]);
  });

  it("remembers a choice on this device and applies it", () => {
    saveTheme("nord");
    expect(readTheme()).toBe("nord");
    expect(document.documentElement.getAttribute("data-theme")).toBe("nord");
    saveTheme("system");
    expect(readTheme()).toBe("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("ignores unknown stored values", () => {
    localStorage.setItem("rs-theme", "<script>");
    expect(readTheme()).toBe("system");
    applyTheme();
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });
});
