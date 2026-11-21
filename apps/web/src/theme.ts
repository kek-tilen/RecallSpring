/**
 * Themes (docs/06 → Visual identity). The choice is kept on this device only. "system" follows the computer's
 * light or dark setting with RecallSpring White or RecallSpring Dark. Colours live in styles.css as tokens per
 * `data-theme`; the swatches here only preview them in Settings.
 */

export type ThemeId = "system" | "light" | "dark" | "solarized-light" | "nord" | "dracula" | "gruvbox";

export interface ThemeInfo {
  id: Exclude<ThemeId, "system">;
  name: string;
  note: string;
  dark: boolean;
  /** Background, surface, text, accent and the progress ramp's strongest step, for the preview. */
  swatch: [string, string, string, string, string];
}

export const THEMES: ThemeInfo[] = [
  { id: "light", name: "RecallSpring White", note: "Light sage, the default", dark: false, swatch: ["#ffffff", "#edf7f4", "#24332f", "#0f766e", "#0b4a44"] },
  { id: "dark", name: "RecallSpring Dark", note: "Dark sage", dark: true, swatch: ["#111916", "#18231f", "#e4eeea", "#5fc4b4", "#c3ede4"] },
  { id: "solarized-light", name: "Solarized Light", note: "Warm cream, low glare", dark: false, swatch: ["#fdf6e3", "#eee8d5", "#073642", "#1f6a9e", "#0d4f4a"] },
  { id: "nord", name: "Nord", note: "Cool arctic blue-grey, calm", dark: true, swatch: ["#2e3440", "#3b4252", "#eceff4", "#88c0d0", "#d2e6f3"] },
  { id: "dracula", name: "Dracula", note: "Vivid purple and pink, high contrast", dark: true, swatch: ["#282a36", "#383a4c", "#f8f8f2", "#bd93f9", "#ece0ff"] },
  { id: "gruvbox", name: "Gruvbox Dark", note: "Warm retro browns and greens", dark: true, swatch: ["#282828", "#3c3836", "#ebdbb2", "#8ec07c", "#d5ebc7"] },
];

const KEY = "rs-theme";
const IDS = new Set<string>(THEMES.map((t) => t.id));

export function readTheme(): ThemeId {
  try {
    const t = localStorage.getItem(KEY);
    return t && IDS.has(t) ? (t as ThemeId) : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme: ThemeId = readTheme()): void {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

export function saveTheme(theme: ThemeId): void {
  try {
    if (theme === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
  applyTheme(theme);
}
