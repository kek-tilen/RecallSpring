import type { Band, StudyStatus } from "./types";

// Dates are shown in the learner's own timezone (from the session), never the browser's guess.
let zone = "Europe/Ljubljana";

export function setTimezone(tz: string): void {
  zone = tz;
}

function fmt(options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat("en-GB", { timeZone: zone, ...options });
}

function dayKey(d: Date): string {
  return fmt({ year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
}

/** Whole local days from today to `iso` (negative = past). Date-only strings are calendar dates. */
export function daysFromToday(iso: string): number {
  const today = dayKey(new Date()).split("/").reverse().join("-");
  const day = iso.length === 10 ? iso : dayKey(new Date(iso)).split("/").reverse().join("-");
  return Math.round((Date.parse(day) - Date.parse(today)) / 86_400_000);
}

export function dateLabel(iso: string): string {
  if (iso.length === 10) {
    const [y, m, d] = iso.split("-").map(Number) as [number, number, number];
    return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(
      new Date(Date.UTC(y, m - 1, d)),
    );
  }
  return fmt({ day: "numeric", month: "short", year: "numeric" }).format(new Date(iso));
}

export function dateTime(iso: string): string {
  return fmt({ day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export function timeOnly(iso: string): string {
  return fmt({ hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export function dayHeading(iso: string): string {
  const n = daysFromToday(iso);
  if (n === 0) return "Today";
  if (n === -1) return "Yesterday";
  return fmt({ weekday: "long", day: "numeric", month: "long", year: "numeric" }).format(new Date(iso));
}

export function relativeDay(iso: string): string {
  const n = daysFromToday(iso);
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n === -1) return "yesterday";
  return n > 0 ? `in ${n} days` : `${-n} days ago`;
}

export function longToday(): string {
  return fmt({ weekday: "long", day: "numeric", month: "long" }).format(new Date());
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 / 1024).toFixed(n % (1024 * 1024) === 0 ? 0 : 1)} MB`;
  return `${(n / 1024 ** 3).toFixed(n % 1024 ** 3 === 0 ? 0 : 1)} GB`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export const STUDY_LABEL: Record<StudyStatus, string> = {
  not_studied: "Not studied",
  studied: "Studied",
  known: "Known",
};

export const BAND_LABEL: Record<Band, string> = {
  not_started: "Not started",
  emerging: "Emerging",
  developing: "Developing",
  reliable: "Reliable",
};

export const GRADE_LABEL = ["No evidence", "Fragile", "Partial", "Solid", "Transfer"] as const;

export function gradeLabel(grade: number | null | undefined): string {
  return grade === null || grade === undefined ? "Not graded" : `${grade}/4 · ${GRADE_LABEL[grade] ?? ""}`;
}

export function gradedBy(kind: string | null | undefined): string {
  switch (kind) {
    case "ai":
      return "Claude";
    case "deterministic":
      return "RecallSpring (answer key)";
    case "human":
      return "You";
    default:
      return kind ?? "—";
  }
}

export const CAPTURED_VIA: Record<string, string> = {
  answer_form: "Your form",
  assistant_transcription: "Copied from chat by Claude",
  app_ui: "Web app",
};

export const DIFFICULTY_SOURCE: Record<string, string> = {
  observed: "from your results",
  learner: "your rating",
  claude: "Claude's estimate",
  default: "default",
};

export const STUDY_SOURCE: Record<string, string> = {
  session: "learning session",
  self_report: "you said you know it",
  diagnostic: "diagnostic pre-test",
};

export const TARGET_KIND: Record<string, string> = { kolokvij: "Kolokvij", izpit: "Exam", other: "Other" };

export const ATTEMPT_KIND: Record<string, string> = { answer: "Answered", dont_know: "I don't know", skip: "Skipped" };

/** Today's calendar date (YYYY-MM-DD) in the learner's timezone. */
export function todayIso(): string {
  return dayKey(new Date()).split("/").reverse().join("-");
}

/** Calendar arithmetic on YYYY-MM-DD strings (timezone-free). */
export function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

export function daysBetween(fromIso: string, toIso: string): number {
  return Math.round((Date.parse(toIso) - Date.parse(fromIso)) / 86_400_000);
}

export const SOURCE_KIND: Record<string, string> = {
  pdf: "PDF",
  docx: "Word",
  pptx: "PowerPoint",
  xlsx: "Excel",
  odt: "Text document (ODF)",
  odp: "Presentation (ODF)",
  ods: "Spreadsheet (ODF)",
  markdown: "Markdown",
  text: "Text",
  csv: "CSV table",
  subtitles: "Subtitles",
  notebook: "Notebook",
  code: "Code",
  latex: "LaTeX",
  image: "Photo",
};

/** What the page count means for each kind (Word and text files have no fixed pages). */
export const COUNT_LABEL: Record<string, string> = {
  pdf: "Pages",
  pptx: "Slides",
  odp: "Slides",
  xlsx: "Sheets",
  ods: "Sheets",
  csv: "Rows",
  notebook: "Cells",
  code: "Lines",
};

/** Extraction notes from the server, in plain words. Unknown notes are shown as they are. */
export function parseNoteLabel(note: string): string {
  const [code, value = ""] = note.split(/:(.*)/s, 2) as [string, string?];
  const list = value.split(",").join(", ");
  switch (code) {
    case "pictures_not_extracted": {
      const n = Number(value);
      const verb = n === 1 ? "is" : "are";
      return `${plural(n, "picture")} inside the file ${verb} not part of the text. Claude can look at ${n === 1 ? "it" : "them"} on request.`;
    }
    case "pages_without_text":
      return `Pages without text (possibly scanned): ${list}. Claude can look at them on request.`;
    case "slides_without_text":
      return `Slides with little or no text: ${list}. Claude can look at their pictures on request.`;
    case "pictures_only":
      return "Only pictures, no text. Claude can look at them on request.";
    case "hidden_sheets":
      return `${plural(Number(value), "hidden sheet")} skipped.`;
    case "truncated":
      return "Only the beginning was extracted because the file is very large.";
    case "image":
      return "Photo: no text is extracted. Claude can look at it on request.";
    case "decoded_as":
      return "Read as Windows-1250 (Central European) text because the file is not UTF-8. If letters look wrong, save it as UTF-8 and upload it again.";
    case "includes_not_resolved": {
      const n = Number(value);
      return `Includes ${plural(n, "other file")} (\\input or \\include) that ${n === 1 ? "is" : "are"} not part of this one: upload ${n === 1 ? "it" : "them"} too.`;
    }
    default:
      return note;
  }
}

export const CATEGORY_LABEL: Record<string, string> = {
  material: "Lecture material",
  notes: "My notes",
  exercises: "Exercises",
  past_paper: "Past papers",
  chat: "Chats",
  other: "Other",
};
