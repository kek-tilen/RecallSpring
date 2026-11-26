# 06 — UI/UX Specification: Sage Study

## Tone and experience

**English-only interface.** Calm, airy, legible, professional but warm. Learning is the center, not configuration. No overstimulating gamification, gradients, giant cards, or decorative visuals. Light mode first; user chose **Sage Study** over blue and warm-paper alternatives.

## Brand symbol

The RecallSpring symbol (owner's pack, 2026-11-22) lives in `assets/brand/` (favicon.ico/svg, PNGs 16-512,
apple-touch-icon, PWA 192/512, a 1024 master; see its README). The web app uses it for the favicon, the web
manifest and next to the name in the menu, sign-in and welcome pages (`BrandMark`, inline SVG). Light themes show
the brand teal `#087465`; dark themes a lighter teal `#5fc4b4` for contrast (`--brand-mark`). Future Claude and
Codex plugins/extensions take their icons from `assets/brand/`, not new artwork.

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

**Themes** (owner decision 2026-11-21; Settings → Appearance, saved on the device in `rs-theme`, `theme.ts`): **RecallSpring White** (the tokens above, default) and **RecallSpring Dark**, plus popular open-source schemes chosen to differ from each other: **Solarized Light** (warm cream, low glare), **Snow Storm** (Nord's light palette, added 2026-11-22 at the owner's request; Nord's Frost blue darkened to #4a6a93 for 4.5:1), **Nord** (cool blue-grey, calm), **Dracula** (vivid purple, high contrast), **Gruvbox Dark** (warm retro) and **OLED Dark** (true black #000000 with RecallSpring's sage accents, added 2026-11-23 at the owner's request; surfaces just above black, input borders 3:1). "Match my computer" follows the system with White or Dark. Each theme is only a set of the same tokens under `:root[data-theme=…]`, so every page and every visual follows it. Text, muted text, links, buttons, warnings and errors meet 4.5:1 on their backgrounds in every theme (checked when the palettes were made; original Solarized tones were darkened for this); the progress ramp stays one hue from light to dark; course colours use the light or dark validated set. Scrollbars are thin and take the theme's border tone (page and inner panes such as Chat). The English UI calls a kolokvij a **midterm exam** (owner 2026-11-22; the stored kind stays `kolokvij`, assistants' instructions and Slovenian prompts keep the word). Use readable system font fallback, 16px base, generous line height, limited measure on reading view. Keyboard focus visible, labels on all controls, reduced-motion support, touch targets >=44 CSS px where practical.

## Navigation hierarchy

**Desktop (optional left rail)**: `Home`, `Courses`, `Study`, `Review`, `Insights`, `Library`, `Settings`. The rail can be hidden (button next to the logo or `Ctrl+\`, remembered on the device in `rs-rail`) so the page uses the whole width; a small button at the top left brings it back and takes the keyboard focus. On phones the rail is a top bar and cannot be hidden.  
**Mobile** (deferred — desktop-first by owner decision; keep layouts responsive where cheap): bottom nav with `Home`, `Study`, `Review`, `Library` + overflow `More`; keyboard shortcuts not required for core use.

### Exams that are behind the learner (owner 2026-11-23)

- Marking an exam **Passed** or **Cancelled** when its course is in focus and has no other exam coming up asks: "<course> is in focus until <date>. … End the focus now?" with `Keep until <date>` and `End focus`. Failed does not ask (a retake usually follows). Ending it is the same audited change as `End focus` on the course.
- **Sections open and close** (owner 2026-11-23): on Courses every university, faculty and semester with something in
  it, `Not filed`, `Interests` (when there are some) and `Archived` (when something is in it) has a heading button
  with an arrow (`aria-expanded`). Closed, it shows what it holds ("2 courses", "1 interest", "3 items"); closing a
  university hides everything inside. Closed sections are remembered on the device; Edit, Add inside and Archive stay
  usable while closed.
- **Study in…** (ADR-012 §3, 2026-11-23): each active course card has `Study in…`, which always opens a menu (owner
  2026-11-23: a choice every time, never a default launch; the last one used is marked `last used` and focused): the
  learner's connected assistants (else the welcome page's choice or mix, else
  all four) and `Copy the start message only`. Chat opens a new conversation with the course chosen; Claude Desktop and
  Codex open a new chat with "Let's study <course> (course_id …)" in the composer, never sent; Antigravity copies it
  with a note to open the course's study folder. The message is always copied as well, for an existing conversation;
  a short status line says what happened.
- A course card with no exam coming up shows the latest one behind the learner ("1. Kolokvij on 23 Nov · passed · no exam coming up"; failed reads "not passed yet", a date gone without a result "result not recorded") instead of "No exam or midterm set yet".

### Old paper next to its analysis (owner 2026-11-23)

An exam's "Exam style from an old paper" starts with **Old paper**: the linked file (opens in the Library viewer, `Unlink`), or "The old paper was only shared in a chat, so RecallSpring has no copy of it." with `Add old paper` (the course's Materials with the upload set to Past papers and scrolled into view) and, when the course has files, "Analysed from [file] Link" (past papers first). Linking changes only the link, never the analysis.

### Home: calm first (ADR-012, variants A1 + A2, owner 2026-11-23)

Typography first, no streaks or other pressure counters.

- **Top, two columns** (one column below 900 px). Left: the date, a greeting by time of day ("Good evening", or "Good evening, <name>"
  with the name set in Settings → Profile, "What should Home call you?"; none by default), one sentence about
  today (the nearest exam or midterm and about how many minutes are planned), a quiet "Which assistant…" line while
  none is chosen, **one next step** (the first plan item as text, the assistant hint except for reviews, and one
  button: `Start reviews`, `Open Chat` for ChatGPT, else `Open concept`; a quiet `Why?` after it when the item works
  towards an exam, ADR-013 §4) and "Then today" with the next two items. Below it, while today has a plan,
  `Go through today's plan in…` (owner 2026-11-26): the same menu as Study in…, not a primary button, with "Let's
  go through today's plan in RecallSpring: all my courses, and how to split my time today." (no course_id). Chat
  opens a new planning conversation (`/chat/new?message=…`) with the message in the box, never sent; Codex and
  Antigravity say to use the Planning study folder. The assistant then proposes how to split today's minutes
  (blocks in order, about how long, why, short breaks) and the learner decides.
  Right, **This week**: a strip of the next seven days (today marked, a dot on days with an exam or midterm), the
  dates within seven days ("today", "tomorrow", "Mon 30 Nov"), reviews due today, minutes focused this week, and a
  link to the weekly review.
- **Today in detail**, open by default; `Hide` / `Show` is remembered on this device and a hidden section loads
  nothing: today's plan with `Start focus` and a quiet "Why this plan:" line linking each exam it works towards
  (`/exams/:id#why`), next to exams and midterms (status On track / Tight / At risk), then
  Needs attention, recent activity and Add material, and one line with what RecallSpring holds.
- Before the first course: the greeting, the first-course hint, then Today in detail.
Include quota status only when relevant; never interrupt the learner with admin chores.

### Study Workspace

Desktop split view: readable source/notes at left, tutor conversation at right; adjustable sizes and focus mode. In Mode A the right pane is a `Study with Claude` panel (connector status, how to start, questions/attempts/assessments Claude recorded in this session); in Mode B it is the in-app tutor. Mobile: switcher tabs `Source`, `Notes`, `Tutor` and a persistent save indicator. Learner can hide sources during retrieval and reveal them afterward.

Components:
- Note editor with autosave and revision history; copy/quote source anchors.
- **Files in notes** (owner 2026-11-21): `Write` / `Preview` above the text and `Insert file`. The dialog has `From Library` (search by name or folder; the note's course first, other courses marked) and `Upload new` (the usual upload, saved in the Library under the note's course). The link goes in at the cursor: a picture as `![name](source:<id>)` on its own line, any other file as `[name](source:<id>)`. Preview shows pictures (a picture that cannot be loaded becomes a link saying so) and links other files to their Library page; a deleted file shows `name (missing file)`. `Linked files:` under the text lists them. The note list shows file names instead of the raw links.
- **Course → Answers** (owner 2026-11-22): the question opens a row with the learner's exact answer (from memory or
  with notes), the grade that counts with who gave it, confidence and how many passages of the material it rests on,
  the feedback, *What was good*, *What was missing*, *Next step*, earlier grades, and the reminder that AI grades
  are study feedback, not a validated score.
- **Photos of work on paper** (owner 2026-11-22): every answer form (Chat, the RecallSpring answer page) invites,
  optionally, "Solved it on paper? A photo of your work counts as your answer": `Add a photo`, Ctrl+V or drag and
  drop, up to 4, thumbnails with remove and Saving/Saved. Each photo is saved first as an image in the course
  Library, folder `Answer photos` (category notes), then linked to the answer; a photo alone is enough. Course →
  Answers shows them with the answer. In Chat the photos stay visible after saving: the form message ("I saved my
  answer … with a photo of my work") carries them as thumbnails; every thumbnail opens a photo viewer in the page
  (owner 2026-11-22: a new tab only offered a download): large on a dark stage, `Actual size` / `Fit to screen`
  (or click the photo) to read handwriting, previous/next buttons and arrow keys when there are several, Download,
  Close / Escape / a click beside the photo. A picture that cannot be shown becomes a `Download photo N` link. ChatGPT gets each photo once. The Chat message box also takes pasted or dropped images (folder
  `Chat images`; a planning chat asks to choose a course first); ChatGPT sees them with that message. The forms
  that Claude and Codex show inline do not take photos yet: the RecallSpring link (answer page) does.
- **Summary check** (owner 2026-11-22): after a summary is saved, the assistant reads it and says what is correct,
  what is wrong and what is missing compared with the material, with page citations. It is feedback, not a grade,
  and the note is never rewritten.
- **Read again** (2026-11-22): a material list with files that could not be read shows how many and `Read these N files again`; a failed or partly read file has `Read the text again` on its page. It extracts again with the current reader; earlier citations stay.
- **New course** (owner 2026-11-22): Courses → `New course` opens a form with the name (any language, kept as
  typed), the type (university course or personal interest with an optional goal), the semester, an optional colour
  and long-term review; it opens the new course. A taken name shows the server's message. Editing stays in
  `Edit course`.
- **Deleting a course** (owner 2026-11-22): `Delete course…` in the edit dialog. The dialog lists everything that
  goes with it (material, folders, concepts, notes, exams and midterms, simulations, questions, answers with their
  grades, Chat conversations, focus blocks; zero counts left out) and says it can be restored for 30 days under
  Courses → `Recently deleted`. The learner must tick "I understand that everything in this course will be deleted"
  and then type the course name in a text area; `Delete course` stays disabled until the box is ticked and the text
  matches the name exactly (capitals, spaces, accents). The server checks the name again.
- **Deleting a note** (owner 2026-11-21): `Delete note` on the note; a dialog names the note and says it can be restored for 30 days and that linked files stay in the Library; only `Delete note` in the dialog deletes it. Notes → `Recently deleted` lists them with `Restore`.
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
- **Folders:** new, rename, move, archive and remove (only when empty; soft delete, audited). Files are moved with a checkbox selection and "Move to…"; the material table header has a select-all checkbox and Photos a `Select all` / `Deselect all` button (owner 2026-11-25). Upload goes into the folder you are in. A dropped or picked **folder** keeps its sub-folders, so does a **.zip** (up to 500 files at a time). Deeper levels are joined into one name ("Week 3 - Lab - Raw"), and anything skipped is listed with the reason.
- **Counts include subfolders** (owner 2026-11-23): `All` and each kind count every file under the current place, subfolders included (folders nest at most 5 levels). Without a filter the list shows this level only, with one quiet line when all files are in the folders above; picking a kind (e.g. Past papers) lists matching files from every subfolder with a Folder column.
- **Archived** (`/library/archived`, linked from Library, Courses and the course page): one page for everything archived, grouped as Semesters and other groups, Courses, Folders and Files. Each has a **Restore** button and shows when it was archived. Archived material is hidden from the library and from search (Claude's course outline marks it hidden), but kept and still citable.
- **Move in** (`/library/import`, the Library's "Move in" link) brings over what the learner did in ChatGPT, in three parts:
  1. *Your instructions and memory:* paste custom instructions and saved memories into **Study preferences**. Claude reads them at the start of a session. When an export contains them, they are offered as a suggestion; nothing is saved until the learner presses Save.
  2. *Chats:* upload the data export ZIP. The picker lists the conversations, with search, a project filter and a word-for-word preview. The learner chooses which to save, and into which course and folder (default "Chats from ChatGPT"). Each saved chat becomes searchable, citable material (kind *Chats*).
  3. *Project files:* attachments found in the export are saved alongside the chats (optional), or dropped as files/folders/ZIPs.

  The upload is kept 7 days for picking, then deleted ("Remove upload" deletes it sooner).
- **Chat** (`/chat`, `/chat/:id`, in the main navigation; owner decision 2026-11-21): ChatGPT conversations on their own page.
  - One window-high page (owner request 2026-11-21): a compact header (usage, link to sign-in and privacy) and one panel with the conversation list on the left and the conversation on the right. The list and the thread scroll on their own; the thread keeps a reading width of about 780 px; the composer stays at the bottom. On phones it becomes an ordinary page with the composer sticky at the bottom.
  - Conversations are listed on the left with search and Recently deleted (Restore within 30 days). On phones the list opens with a "Conversations" button.
  - **Full page** (owner request 2026-11-22: chat over the whole page, without the menu or the conversation list beside it): a `Full page` button in the header (remembered per browser) hides the main menu and the list; the header becomes a thin bar with `Conversations` (opens the list as a drawer over the thread; Escape or a click beside it closes it) and `Exit full page`. The thread keeps a reading width of about 900 px. Not offered on phones, where the chat already fills the screen.
  - The composer is one rounded box (owner request 2026-11-21: more modern, after the look of Codex's composer): the chosen material as file chips on top, a text field that grows with the text (up to about 40 % of the window), and one row underneath with a round `+` button for Material (with a count), a `Visuals` switch (a pill, `aria-pressed`), the model as a quiet pill (remembered) and a round Send button with an arrow (a spinner while waiting). A one-line hint under the box: Enter sends, Shift+Enter adds a new line.
  - **Folders** (ADR-012 §4, owner 2026-11-23): a folder button next to `New conversation` creates a folder; each
    folder row opens and closes (remembered on the device, and the folder of the open conversation is always open),
    with `+` for a subfolder and `⋯` for its settings: name, one of 16 icons (only folders have icons), a colour
    (8 accessible ones, `Default`, or `Custom…`; on dark themes every folder colour is shown lightened by mixing 45%
    white in OKLab, at least 3:1 on every dark surface), a course (a new conversation about it goes there when it is the
    only folder linked to the course), `Inside` (top level or one top-level folder; no deeper) and `Pin to the top`.
    Folders are sorted alphabetically, pinned first; counts include subfolders. Conversations without a folder are
    listed under `No folder`; a search lists matches from every folder with the folder's name. `Move to…` in a
    conversation's title bar files it (no drag and drop). `Delete folder` asks first and says where its
    conversations go (the parent folder or No folder; subfolders to the top level); no conversation is deleted.
  - **Plain and Ghost chats** (ADR-012 §5, owner 2026-11-23): a new conversation's choice offers `Planning (all
    courses)`, `Study: <course>` and `Plain chat (no RecallSpring)`, which hides the RecallSpring switch and is
    marked `Plain chat` in the title bar. The `Ghost` button next to it (a small ghost, no checkbox; owner
    2026-11-23: on hover its eyes look right, up and left in a loop and its hem flutters, none with reduced
    motion; when on, the ghost is filled with ink and its eyes turn light, `aria-pressed`) works with all three: a note says the chat
    lives only in this tab and is not saved, reads but writes nothing, and takes no attachments (the `+` and
    paperclip buttons and pasting images are gone). The thread gets a faint diagonal pattern; the bar shows
    `Keep this chat` (saves it as a normal conversation from then on) and `End` (asks, then discards). Leaving it
    for another conversation or closing the tab asks first. A ghost chat never appears in the list; its token
    usage counts in the totals.
  - **Material** (owner request 2026-11-21): the learner chooses which of their files ChatGPT may use in this conversation (a dialog listing courses and their files, with search, "Choose all" per course, up to 20 files; files without text are shown but cannot be chosen). It says plainly that only matching parts of these files are sent with each message and nothing else from RecallSpring. **Upload files** (a paperclip next to `+`, owner request 2026-11-21) opens the Library's upload box in a dialog: the study conversation's course is used, a planning or new conversation asks for the course; the same types, limits and checks as Library, folders and ZIPs included. Uploaded files are saved in the Library and added to the conversation's material (up to 20); while RecallSpring reads them the chip says "reading…" and a line above the box says ChatGPT can use them in a moment (the conversation is checked every 3 s until then). Photos are kept, but ChatGPT in Chat cannot see pictures yet. Chosen files show as chips above the text field. Under each message, "Sent with N excerpts from …" opens the list of what was sent (S1, S2, … with file and page). In a reply, `[S2]` becomes a small link to that file in the Library and a "sources cited" list follows the reply; a reference that was never sent stays plain text. A visual based on excerpts says "based on S2 from your material · values not checked".
  - Each conversation can be renamed or deleted (deleting is confirmed).
  - Replies are shown with formatting by `components/Markdown.tsx`. It supports paragraphs, headings, lists, quotes, tables, code, bold, italic and http(s) links, and builds React elements only. HTML, scripts or styles in a reply stay visible text and are never run. Formulas in LaTeX (owner 2026-11-22) are drawn
    as MathML by `components/Math.tsx`: `\( … \)` and `$ … $` inside a line, `\[ … \]` and `$$ … $$` on lines of
    their own (also over several lines). It is a small parser written here (no new dependency), again React elements
    only: fractions, roots, sub/superscripts, sums and integrals with limits, `\overline` (Boolean NOT over a whole
    term), accents, `\left…\right`, Greek letters and the usual symbols, `\text`, `\mathbb`, cases, matrices and
    aligned rows. A formula using anything else is shown as its source text, never guessed; prices such as "$5 and
    $10" stay text. Chat tells ChatGPT to write formulas this way; notes' Preview shows them too.
    Question text, expected points and choice options are drawn the same way wherever a question is shown (answer
    pages and Chat forms, simulations, self-assessment, history; ADR-012, `MathText`). A turn's forms in Chat
    always come under all of its text.
  - **Visuals** (owner decision 2026-11-21): a `Visuals` switch in the composer (on by default, remembered on this device) lets ChatGPT add up to two diagrams per reply. They are drawn by `components/Visual.tsx` from data the server checked; only six kinds exist: a top-to-bottom process flow (a loop back is dashed), a concept map (the most linked idea in the middle), a comparison table, a timeline, a line/bar/scatter chart (with its data table) and a slider over one of four built-in formulas (straight line, exponential decay, parabola, unit circle). Each has its title, an `Illustrative example` label when numbers are examples (always for ChatGPT charts), the line "Drawn by RecallSpring from data ChatGPT sent · not checked against your material" and a `Text description` (the alt text, also the SVG's accessible name). A block that fails the checks says "This visual could not be shown: <reason>", keeps the text answer, and shows what was sent as plain text.
  - Under each reply is one quiet line: model and version, time, duration and tokens. Clicking it shows the model chosen, the model that answered, the exact time, input (cached) / output (reasoning) / total tokens, the account and the response ID.
  - A message that got no reply says why. The header shows usage over the last 24 hours and 30 days.
  - **RecallSpring** (plan-without-claude.md Phase 2, 2026-11-21): a `RecallSpring` switch in the composer (a pill next to Visuals, on by default, remembered on this device) lets ChatGPT read the learner's courses, material, notes and plan and save questions and feedback; its tooltip says it cannot delete anything or change settings. For a new conversation, `Study` picks a course (or "Planning (all courses)", see docs/04); the conversation then shows "Studying <course>" under its title. Under the learner's message, `Used RecallSpring: N steps · M saved · K not done` opens the list ("✓ Read the course outline", "+ Saved 1 question", "! Not done: …"; the marks are aria-hidden, the words carry the meaning). Forms ChatGPT asks for appear under its reply in a bordered card: the answer form (question, `Your answer`, `I used my notes or the material`, `Save and send to ChatGPT`, `I don't know`) and the summary form (topics, `Your summary`, `Save and send to ChatGPT`), both with drafts kept in the browser; a simulation shows `Open the simulation`. Saving tells ChatGPT with a `[RecallSpring] I saved my answer …` message. Only the newest turn's forms can be filled in; older ones link to the answer or summary page. While ChatGPT works: "Saved · waiting for ChatGPT (it may read or save in RecallSpring)…".
  - When signed out, conversations stay readable and a `Sign in with ChatGPT` button is shown.
- **First run and Welcome (Phase 3 of docs/plan-without-claude.md):** while an install has no account, the sign-in page is
  *Welcome to RecallSpring*: username, password and repeat (at least 12 characters, no e-mail reset), time zone (from
  the browser, a list of IANA zones). Only on the computer RecallSpring runs on; elsewhere the page says where to do
  it. Then **/welcome** (*Choose your assistant*): Claude (Claude Desktop), Codex, ChatGPT in RecallSpring, **Mix** or Decide
  later, each with what it needs; after saving, the next steps for that assistant with copyable commands. Mix (owner
  2026-11-22) shows checkboxes for the three; Save needs at least two ("Choose at least two."), and the next steps
  come for each one chosen. Home shows a
  short nudge while none is chosen.
- **Settings layout** (owner 2026-11-23): one long page in five sections, each with a one-line purpose: **Study** (study time and balance, study preferences), **Assistants** (your assistants, ChatGPT preview, assistant connector), **Data & backups** (backups, History), **Appearance** (theme) and **Account & system** (profile, running in the background). Contents beside the page (a row of tabs on narrow screens) link to the sections and mark the one being read (`aria-current`); the owner preferred this to sub-pages because the left rail is already full. Old links (`/settings#chatgpt`, `#profile`, `#service`, `#connector`, `#assistants`) still open at their card or section; `#backups` is new.
- **Settings → Profile:** username, session end and editable time zone. Saving a new time zone reloads every view,
  because "today" depends on it.
- **Settings → Assistants** (owner 2026-11-22, replaces the assistant picker in Profile): Claude, Codex and ChatGPT,
  each `Connected` / `Not connected` from RecallSpring's own records (an active connector token; the ChatGPT
  sign-in), where it is used and when it was last used, with the next step: `Manage` (the token below), `Set up`
  (opens the setup steps under that row), `Sign in` (the ChatGPT card) or `Open Chat`. With a mix, its assistants are
  listed first with `In your mix`. A line says which name the tips use; `Change your choice` goes to /welcome.
- **Assistant wording:** pages name the assistant in use (the only connected one; "your assistant" when several are; the welcome choice while none is) where it helps (Home's start and continue hints, Review,
  waiting-for-grade notices, the Guide); otherwise "your assistant". The Guide's setup card follows the choice (Claude
  Projects, Codex study folders, or Chat's planning and course conversations) and shows Claude's + menu shortcuts
  only to Claude users. Chat's Study picker offers **Planning (all courses)** (default) or one course. Factual connector text (Claude Desktop, Codex tokens) stays.
- **Settings → ChatGPT (preview):** the connection only. It holds `Sign in with ChatGPT` per OpenAI's UI guidelines, the privacy notes, the account, plan usage, Open Chat, Sign in again and Sign out (confirmed). It states clearly when sign-in is unavailable (not on 127.0.0.1, or turned off).

### Answering from another assistant (Codex)

Built 2026-11-21 (plan-without-claude.md, Phase 0). When an assistant cannot show RecallSpring's forms in its chat, it gives the learner a link:

- **`/answer/:questionId`:** the question (never the rubric), a text field, `I used my notes or the material`, `Save answer` and `I don't know`. A note says when the question was answered before (a new answer is another attempt). After saving: the time and "Go back to your assistant and tell it you are done".
- **`/summary`:** the chunk's title, what was covered and the topics (only topics of that course; an incomplete link says so), a text field (may stay empty) and `Save summary`. Saved exactly as the learner's note; the topics count as studied.
- Both keep a draft in the browser until it is saved and reuse one request key, so a retry never saves twice.
- **Settings → Assistant connector:** `New token for Claude Desktop` / `New token for Codex`; the token table shows which assistant each token is for. Feedback on concepts and simulations reads "Feedback from Codex · model".

### Focus (Pomodoro timer)

Built (owner decision 2026-11-21). `/focus` in the main menu.

- **Cycle:** focus blocks with a short break after each and a long break after the last block of a cycle. Defaults are 45 min focus, 10 min short break, 15 min long break, 4 blocks per cycle. All four can be changed (focus 1–180 min, breaks 1–60 / 1–90 min, 1–12 blocks); a new length applies from the next phase that has not started.
- **Controls:** Start / Pause / Resume (on the Focus page, Start and Resume open focus mode, so only the timer fills the browser window; owner 2026-11-21: the window, not the whole screen), Skip (ends the phase; never starts the next one by itself), Reset (back to block 1), Focus mode. A block skipped or reset while paused ends at its pause (owner 2026-11-25): pausing in the evening and resetting the next morning counts the time on the evening's day. Optional: start the next phase automatically, a chime (Web Audio, no sound files), a desktop notification (asked for only when the learner turns it on).
- **Six clock faces** (Settings are per device): Default, Flip Clock, Progress Bar, Dot Matrix (one dot per minute, up to 60), Pie and Ring (a pie with a hole, the time in the middle). The bright part is the time left, so every face empties as the phase runs. Faces are visual only (`aria-hidden`); screen readers get the phase and whole minutes left, and phase changes are announced once.
- **Focus mode:** the timer alone over a background the learner picks: the theme, five colour backgrounds (Night, Forest, Dusk, Ocean, Sand) or their own image. The timer on the Focus page shows the chosen background too, so a choice is visible at once. The image is chosen with a real file field (a label around it; a script click on a hidden file input does nothing in some browsers). The image (PNG, JPEG, WebP, AVIF or GIF, up to 20 MB) stays in this browser (IndexedDB) and is never uploaded or backed up; a "Darken the image" slider keeps the time readable. Space starts or pauses, `F` opens focus mode from the Focus page, `Esc` exits; focus stays inside the dialog and returns to where it was. Optional browser full screen.
- **Start focus from the plan:** each item in Today's plan has `Start focus` (owner 2026-11-21). It starts a focus block for that item's course at once and shows only the timer over the window. During a break the break ends early (breaks are never saved); a focus block already under way continues and counts for that course. While that course's block runs, the button reads `Show focus`.
- **Day times and a block's course afterwards** (owner 2026-11-22): hovering a day's bar (or Tab to it) shows a
  small tip with the day ("Today" or "Fri 20 Nov") and its time ("45 min", "1 h 15 min", "2 h") and blocks. Each of
  the latest blocks shows its course as a quiet dropdown (`No course` or a course); choosing another counts the
  block for that course at once (totals by course update). History records it as audited `focus.course_changed`.
- **Removing a wrong block** (owner 2026-11-21): each of the latest blocks has `Remove`. A dialog shows the block (minutes, course, when) and says it will no longer count and can be restored for 30 days; only `Remove` in the dialog removes it. Removed blocks are listed under `Recently removed` with `Restore` for 30 days. History shows `Focus block removed` / `restored`; the note that the block was recorded stays.
- **Keeps running:** the timer is a timestamp in this browser, so it survives reloads, page changes and other tabs (they follow each other). While a phase is under way a small timer with a pause button sits in the menu, or beside Show menu when the menu is hidden. The browser tab title shows the time left.
- **Study time:** the learner may pick a course. A focus block that runs to the end, or is stopped after at least a minute, is saved as study time (pauses excluded); breaks are not. A block is kept in the browser first and sent when RecallSpring is reachable, so none is lost offline. Focus time shows on the Focus page (today, the last 7 days by day and by course, the latest blocks), on Today, in History ("Focus block finished" / "stopped early") and to Claude in `get_study_context` as `focus_time`. It is labelled as effort only, never as learning or mastery.

### Insights

Course coverage, due forecasts, recurring misconceptions, evidence per topic, exam-date planning. Avoid mastery percentages unless they are clearly labeled approximations with evidence. `Learning history` should show exactly when an answer was saved, evaluated, scheduled and corrected.

Implemented:

- **Exam readiness** (`/exams/:id`, linked from Exams and the course's Exams tab): a five-part bar (Not studied
  yet, Weak, Studied not practised, Getting there, Solid; weak uses the warning colour, the rest the green ramp)
  with a legend and counts, the time check, next steps, the weakest concepts with what was missing in their last
  answer and where to read again, simulations, and the material groups as collapsible blocks (collapsed by default,
  owner 2026-11-25, with progress bar and counts visible; `Collapse all` / `Expand all` on the card, owner 2026-11-25). Below, **Why this plan** (ADR-013 §4, `#why`, from
  `GET /targets/{id}/rationale`, nothing written by a model): the old papers (linked when RecallSpring has a copy,
  else "no copy"; a paper of several files, e.g. photos, lists and links each file; on the course's Exams tab
  the same list replaces the single "Old paper" link once a newer analysis names files; the exam each was for and "Style only" when only its kind of questions counts), the assistant's
  note on the analysis (labelled as its words), whether the analysis is confirmed with `It matches the paper` while it is not (corrections go
  through the assistant, which reads the paper again), coverage by points and a table of the topics (points or
  share, where on the paper, on how many papers, each concept with its state, "From the web" and "Not in your
  material" marked), the kinds of questions on the paper against what was practised and the practice limit,
  today's work for this course tied to its topics with "How RecallSpring orders the work" folded, the time check,
  and "What this cannot tell you" (the server's limits). It ends with "not a prediction of your grade".
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
