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

All text/action contrast must meet WCAG 2.2 AA; change tones as needed. Use readable system font fallback, 16px base, generous line height, limited measure on reading view. Keyboard focus visible, labels on all controls, reduced-motion support, touch targets >=44 CSS px where practical.

## Navigation hierarchy

**Desktop (optional left rail)**: `Home`, `Courses`, `Study`, `Review`, `Insights`, `Library`, `Settings`.  
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

- Distinguish RecallSpring login from AI connections: `Claude connector` (connector token, last used, revoke, setup steps for Claude Desktop), `Continue with ChatGPT` (SIWC, per OpenAI UI guidelines), `Claude API key` (masked, never re-displayed).
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
