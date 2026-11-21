# 06 — UI/UX Specification: Sage Study

## Tone and experience

**English-only interface.** Calm, airy, legible, professional but warm. Learning is the center, not configuration. No overstimulating gamification, gradients, giant cards, or decorative visuals. Light mode first; user chose **Sage Study** over blue and warm-paper alternatives.

## Design tokens (starting point; validate contrast)

```css
:root {
  color-scheme: light;
  --bg: #FFFFFF;
  --surface: #EDF7F4;
  --surface-elevated: #F8FBF9;
  --primary: #0F766E;
  --primary-hover: #115E59;
  --ink: #24332F;
  --muted: #52645C;
  --border: #CBDDD6;
  --warning: #A56A3A;
  --danger: #B42318;
  --focus: #0F766E;
  --radius-card: 16px;
  --radius-control: 10px;
  --space: 4px;
}
```

All text/action contrast must meet WCAG 2.2 AA; change tones as needed.

**Themes** (owner decision 2026-11-21; Settings → Appearance, saved on the device in `rs-theme`, `theme.ts`): **RecallSpring White** (the tokens above, default) and **RecallSpring Dark**, plus four popular open-source schemes chosen to differ from each other: **Solarized Light** (warm cream, low glare), **Nord** (cool blue-grey, calm), **Dracula** (vivid purple, high contrast) and **Gruvbox Dark** (warm retro). "Match my computer" follows the system with White or Dark. Each theme is only a set of the same tokens under `:root[data-theme=…]`, so every page and every visual follows it. Text, muted text, links, buttons, warnings and errors meet 4.5:1 on their backgrounds in every theme (checked when the palettes were made; original Solarized tones were darkened for this); the progress ramp stays one hue from light to dark; course colours use the light or dark validated set. Use readable system font fallback, 16px base, generous line height, limited measure on reading view. Keyboard focus visible, labels on all controls, reduced-motion support, touch targets >=44 CSS px where practical.

## Navigation hierarchy

**Desktop (optional left rail)**: `Home`, `Courses`, `Study`, `Review`, `Insights`, `Library`, `Settings`. The rail can be hidden (button next to the logo or `Ctrl+\`, remembered on the device in `rs-rail`) so the page uses the whole width; a small button at the top left brings it back and takes the keyboard focus. On phones the rail is a top bar and cannot be hidden.  
**Mobile** (deferred — desktop-first by owner decision; keep layouts responsive where cheap): bottom nav with `Home`, `Study`, `Review`, `Library` + overflow `More`; keyboard shortcuts not required for core use.

### Home dashboard: the three obvious actions

1. **Continue learning** (last session/topic).
2. **Review knowledge** (due count + honest estimate).
3. **Add material** (drag-and-drop zone; click-to-browse fallback).

Below: `Today's plan` with explainable 2–5 tasks, `Needs attention` and a brief progress snapshot. Include quota status only when relevant; never interrupt learner with admin chores.

### Study Workspace

Desktop split view: readable source/notes at left, tutor conversation at right; adjustable sizes and focus mode. In Mode A the right pane is a `Study with Claude` panel (connector status, how to start, questions/attempts/assessments Claude recorded in this session); in Mode B it is the in-app tutor. Mobile: switcher tabs `Source`, `Notes`, `Tutor` and a persistent save indicator. Learner can hide sources during retrieval and reveal them afterward.

Components:
- Note editor with autosave and revision history; copy/quote source anchors.
- Topic context card linking to syllabus, sources and last practiced date.
- Tutor controls: `Explain`, `Give an example`, `Show a visual`, `Quiz me`, `Check my reasoning`, `Next question`.
- Question bar: `Bloom level 3–5`, `Mixed / Progressive`, `Closed notes / Open notes`, optional `Hint`.
- Attempt composer autosaves drafts but **submission is explicit**. Assessment feedback distinguished from model-generated suggestions.
- `Why this question?` link reveals concepts, difficulty rationale and source coverage.

### Reviews

`Today / Upcoming / Overdue` filtered lists, recommended small batches (e.g. 5–10 questions). User sees questions one at a time with a clear progress counter, source-free answering by default, rich feedback only after submission. No flashcard-maintenance dashboard. Allow a one-click `Snooze`, `Mark uncertain`, or `Challenge evaluation`.

### Library

Dropzone with progress, duplicates indicator, type/size constraints, extraction state `Processing`, `Ready`, `Needs attention`, `Failed`. Each parsed page/heading available for citation. Unsupported scanned PDFs clearly flagged; do not invent extracted text.

Implemented (2026-11-21, ADR-008):

- **Two ways to browse.** *By course* groups material automatically: university › semester › course, then kind (Material, Notes, Exercises, Past papers, Photos, Chats). *Folders* shows the learner's own folders inside a course, nested up to five levels. Folders are optional: nothing has to be filed, and material without a folder sits at the course's top level. A breadcrumb, a filter by kind and search work in both views.
- **Folders:** new, rename, move, archive and remove (only when empty; soft delete, audited). Files are moved with a checkbox selection and "Move to…". Upload goes into the folder you are in. A dropped or picked **folder** keeps its sub-folders, so does a **.zip** (up to 500 files at a time). Deeper levels are joined into one name ("Week 3 - Lab - Raw"), and anything skipped is listed with the reason.
- **Archived** (`/library/archived`, linked from Library, Courses and the course page): one page for everything archived, grouped as Semesters and other groups, Courses, Folders and Files. Each has a **Restore** button and shows when it was archived. Archived material is hidden from the library and from search (Claude's course outline marks it hidden), but kept and still citable.
- **Move in** (`/library/import`, the Library's "Move in" link) brings over what the learner did in ChatGPT, in three parts:
  1. *Your instructions and memory:* paste custom instructions and saved memories into **Study preferences**. Claude reads them at the start of a session. When an export contains them, they are offered as a suggestion; nothing is saved until the learner presses Save.
  2. *Chats:* upload the data export ZIP. The picker lists the conversations, with search, a project filter and a word-for-word preview. The learner chooses which to save, and into which course and folder (default "Chats from ChatGPT"). Each saved chat becomes searchable, citable material (kind *Chats*).
  3. *Project files:* attachments found in the export are saved alongside the chats (optional), or dropped as files/folders/ZIPs.

  The upload is kept 7 days for picking, then deleted ("Remove upload" deletes it sooner).
- **Chat** (`/chat`, `/chat/:id`, in the main navigation; owner decision 2026-11-21): ChatGPT conversations on their own page.
  - One window-high page (owner request 2026-11-21): a compact header (usage, link to sign-in and privacy) and one panel with the conversation list on the left and the conversation on the right. The list and the thread scroll on their own; the thread keeps a reading width of about 780 px; the composer stays at the bottom. On phones it becomes an ordinary page with the composer sticky at the bottom.
  - Conversations are listed on the left with search and Recently deleted (Restore within 30 days). On phones the list opens with a "Conversations" button.
  - The composer is one box: the text field, then `Material`, `Visuals`, the model (remembered) and Send. Enter sends, Shift+Enter adds a new line.
  - **Material** (owner request 2026-11-21): the learner chooses which of their files ChatGPT may use in this conversation (a dialog listing courses and their files, with search, "Choose all" per course, up to 20 files; files without text are shown but cannot be chosen). It says plainly that only matching parts of these files are sent with each message and nothing else from RecallSpring. Chosen files show as chips above the text field. Under each message, "Sent with N excerpts from …" opens the list of what was sent (S1, S2, … with file and page). In a reply, `[S2]` becomes a small link to that file in the Library and a "sources cited" list follows the reply; a reference that was never sent stays plain text. A visual based on excerpts says "based on S2 from your material · values not checked".
  - Each conversation can be renamed or deleted (deleting is confirmed).
  - Replies are shown with formatting by `components/Markdown.tsx`. It supports paragraphs, headings, lists, quotes, tables, code, bold, italic and http(s) links, and builds React elements only. HTML, scripts or styles in a reply stay visible text and are never run.
  - **Visuals** (owner decision 2026-11-21): a `Visuals` checkbox by the composer (on by default, remembered on this device) lets ChatGPT add up to two diagrams per reply. They are drawn by `components/Visual.tsx` from data the server checked; only six kinds exist: a top-to-bottom process flow (a loop back is dashed), a concept map (the most linked idea in the middle), a comparison table, a timeline, a line/bar/scatter chart (with its data table) and a slider over one of four built-in formulas (straight line, exponential decay, parabola, unit circle). Each has its title, an `Illustrative example` label when numbers are examples (always for ChatGPT charts), the line "Drawn by RecallSpring from data ChatGPT sent · not checked against your material" and a `Text description` (the alt text, also the SVG's accessible name). A block that fails the checks says "This visual could not be shown: <reason>", keeps the text answer, and shows what was sent as plain text.
  - Under each reply is one quiet line: model and version, time, duration and tokens. Clicking it shows the model chosen, the model that answered, the exact time, input (cached) / output (reasoning) / total tokens, the account and the response ID.
  - A message that got no reply says why. The header shows usage over the last 24 hours and 30 days.
  - When signed out, conversations stay readable and a `Sign in with ChatGPT` button is shown.
- **Settings → ChatGPT (preview):** the connection only. It holds `Sign in with ChatGPT` per OpenAI's UI guidelines, the privacy notes, the account, plan usage, Open Chat, Sign in again and Sign out (confirmed). It states clearly when sign-in is unavailable (not on 127.0.0.1, or turned off).

### Focus (Pomodoro timer)

Built (owner decision 2026-11-21). `/focus` in the main menu.

- **Cycle:** focus blocks with a short break after each and a long break after the last block of a cycle. Defaults are 45 min focus, 10 min short break, 15 min long break, 4 blocks per cycle. All four can be changed (focus 1–180 min, breaks 1–60 / 1–90 min, 1–12 blocks); a new length applies from the next phase that has not started.
- **Controls:** Start / Pause / Resume (on the Focus page, Start and Resume open focus mode, so only the timer fills the browser window; owner 2026-11-21: the window, not the whole screen), Skip (ends the phase; never starts the next one by itself), Reset (back to block 1), Focus mode. Optional: start the next phase automatically, a chime (Web Audio, no sound files), a desktop notification (asked for only when the learner turns it on).
- **Six clock faces** (Settings are per device): Default, Flip Clock, Progress Bar, Dot Matrix (one dot per minute, up to 60), Pie and Ring (a pie with a hole, the time in the middle). The bright part is the time left, so every face empties as the phase runs. Faces are visual only (`aria-hidden`); screen readers get the phase and whole minutes left, and phase changes are announced once.
- **Focus mode:** the timer alone over a background the learner picks: the theme, five colour backgrounds (Night, Forest, Dusk, Ocean, Sand) or their own image. The timer on the Focus page shows the chosen background too, so a choice is visible at once. The image is chosen with a real file field (a label around it; a script click on a hidden file input does nothing in some browsers). The image (PNG, JPEG, WebP, AVIF or GIF, up to 20 MB) stays in this browser (IndexedDB) and is never uploaded or backed up; a "Darken the image" slider keeps the time readable. Space starts or pauses, `F` opens focus mode from the Focus page, `Esc` exits; focus stays inside the dialog and returns to where it was. Optional browser full screen.
- **Start focus from the plan:** each item in Today's plan has `Start focus` (owner 2026-11-21). It starts a focus block for that item's course at once and shows only the timer over the window. During a break the break ends early (breaks are never saved); a focus block already under way continues and counts for that course. While that course's block runs, the button reads `Show focus`.
- **Keeps running:** the timer is a timestamp in this browser, so it survives reloads, page changes and other tabs (they follow each other). While a phase is under way a small timer with a pause button sits in the menu, or beside Show menu when the menu is hidden. The browser tab title shows the time left.
- **Study time:** the learner may pick a course. A focus block that runs to the end, or is stopped after at least a minute, is saved as study time (pauses excluded); breaks are not. A block is kept in the browser first and sent when RecallSpring is reachable, so none is lost offline. Focus time shows on the Focus page (today, the last 7 days by day and by course, the latest blocks), on Today, in History ("Focus block finished" / "stopped early") and to Claude in `get_study_context` as `focus_time`. It is labelled as effort only, never as learning or mastery.

### Insights

Course coverage, due forecasts, recurring misconceptions, evidence per topic, exam-date planning. Avoid mastery percentages unless they are clearly labeled approximations with evidence. `Learning history` should show exactly when an answer was saved, evaluated, scheduled and corrected.

Implemented:

- **Exam readiness** (`/exams/:id`, linked from Exams and the course's Exams tab): a five-part bar (Not studied
  yet, Weak, Studied not practised, Getting there, Solid; weak uses the warning colour, the rest the green ramp)
  with a legend and counts, the time check, next steps, the weakest concepts with what was missing in their last
  answer and where to read again, simulations, and the material groups as collapsible blocks (open while anything
  in them is not yet "Getting there" or "Solid"). It ends with "not a prediction of your grade".
- **Weekly review** (`/week`, and a "This week" card on Today): plain summary sentences, numbers, a 0-4 grade
  distribution as a labelled table, per course, reviews, exams in the next three weeks; earlier weeks one click
  back.

## Visual learning principle

**Use a visual only when it simplifies a concept.** Supported v1 blocks:

- `process_flow` — processes and causal chains;
- `comparison` — two or more alternatives, aligned criteria;
- `timeline` — chronological sequences;
- `concept_map` — a bounded graph of relationships;
- `data_chart` — numeric data with specified units/source;
- `interactive_parameter` — safe bounded slider controlling a **predefined** formula/visual behavior.

Render each via React components with a textual accessible alternative. Model returns validated JSON specs, not executable frontend snippets. Interactive elements must not be able to call AI or mutate learning records without explicit app action. If visual spec is invalid or pedagogically questionable, render plain-language explanation instead.

## Keyboard shortcuts and `@` actions

Do not hide primary features behind keyboard commands. Optional:
- `@course` / `@topic` / `@source` in tutor composer opens a searchable context picker.
- `/explain`, `/visual`, `/quiz`, `/review` optional command palette.
- `Ctrl/Cmd+K` opens global search; `Esc` closes dialogs.
- `Ctrl/Cmd+\` hides or shows the menu rail (built).
- On the Focus page: `Space` starts or pauses the timer, `F` opens focus mode, `Esc` leaves it (built).

Provide full mouse/touch alternatives. In-context help should be short, not a tutorial maze.

## Empty, loading and failure states

- New user: friendly empty state with `Add your first course` and sample workflow.
- No reviews due: `You're caught up. Continue a topic or browse your library.`
- AI limit reached: `<Provider> is at its usage limit. Your notes and answers are saved. You can continue reading and writing.` For SIWC follow OpenAI's wording (`Usage limit reached`, `Manage usage` link); for API keys say `Monthly AI budget reached ($X of $Y)`; for RecallSpring's own daily limit say so explicitly.
- Pending evaluation: `Answer saved. Feedback is still processing.`
- Offline: `You're offline. Drafts will sync when connected.`
- Sync conflict: compare side by side; no silent overwrite.
- Source parser failed: `Text couldn't be extracted. Try a text-based PDF or paste the content.`

## Security and privacy UI

- Distinguish RecallSpring login from AI connections: `Claude connector` (connector token, last used, revoke, setup steps for Claude Desktop), `Sign in with ChatGPT` (SIWC, per OpenAI UI guidelines; preview card in Settings, see Library above), `Claude API key` (masked, never re-displayed).
- Show AI permission state, connected account (limited identity), per-task model choice (tutor default Sonnet), monthly USD limit for API keys and daily request limit (1–100 %) for plan-based providers, with current usage.
- Explicit `Allow background AI requests` opt-in OFF by default; explain quotas and ability to revoke; do not hide consent in T&Cs.
- Destructive action dialog includes exact scope and recoverability period. Exports and backups explained in settings.

## Demo screens agents must build

1. Onboarding + connection status.
2. Home with three primary actions.
3. New study workspace and note autosave.
4. Answer submission, grading/uncertainty panel and source references.
5. Review batch and next-due explanation.
6. Interactive process flow / comparison visual.
7. Settings: theme, timezone, AI connections and limits, export, deletion.
8. `Study with Claude` panel: connector status and the records Claude created.

Demo data must be labeled as such; screenshots used for acceptance before production integration.
