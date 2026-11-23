# ADR-012 — Forms last, formulas in questions, a calmer home, Study in…, Chat folders, Plain and Ghost chats

Status: accepted 2026-11-23 (owner in chat); rolled out in steps, see Rollout (step 1 done 2026-11-23). Extends ADR-010 and ADR-011.

## Context

Using RecallSpring daily brought up five things that slow the learner down:

- In Claude Desktop, ChatGPT desktop and Antigravity a form sometimes appears in the middle of the assistant's
  message, with more explanation under it.
- Questions written in LaTeX (`\(-0{,}4_{10}\)`) are shown as source text in the answer form.
- The home page shows a lot at once and reads like a dashboard.
- Starting to study a course in the learner's own assistant takes several steps.
- Chat conversations pile up in one list; there is no way to file them, and no way to talk without the chat being
  kept.

## Decision

### 1. Form last, formulas everywhere a question is shown

- Assistants are told: explain first, open the form as the very last step, write nothing after it (instructions and
  each form tool's result). External apps place a form where the tool is called, so this is guidance, not a
  guarantee. RecallSpring's own Chat always draws a turn's forms under all of its text.
- Question text and expected points are drawn with RecallSpring's own LaTeX → MathML renderer wherever they appear:
  web pages, Chat forms and the MCP forms. The MCP forms get the same parser as a self-contained script built from
  the web app's source; it builds elements through the DOM (never `innerHTML`). Unsupported TeX stays visible as
  source text.

### 2. A calmer home (variant A)

Top to bottom: a warm greeting by time of day with one sentence about today (the nearest exam and today's work);
one next step as text with one button; a quiet "This week" row (upcoming dates, reviews today, focused time); the
rest of today's home folded under "More". Typography only for now. No streaks or other pressure counters.

### 3. Study in… (Courses)

Each course gets a "Study" button with a choice of the learner's own assistants (Settings → Assistants); the last
choice is remembered. Chat opens a new conversation for the course. Codex and Antigravity open the course's study
folder when the app supports a link for it. Claude Desktop and ChatGPT desktop: open the app when possible and copy a
starting message to the clipboard ("Let's study <course> (course_id …)"), which works in a new or an existing
conversation; "Copy only" is offered too.

### 4. Chat folders

- Any number of top-level folders, each with any number of subfolders; no deeper nesting (refused by the server). A
  conversation is in at most one folder.
- A folder has a name, an icon (default: a minimal folder; others from a small set, agreed separately) and a colour
  (an accessible palette or a custom colour). A folder linked to a course takes the course's colour when courses get
  one, and the learner can change it. Only folders have icons.
- Folders are sorted alphabetically, pinned folders first. Conversations move with "Move to…" (no drag and drop).
- A new conversation goes to a course's folder automatically only when exactly one folder is linked to that course.
- Deleting a folder never deletes conversations: after confirmation they move to the parent folder or to "No
  folder".

### 5. Plain chat and Ghost chat (Chat only)

- **Plain chat**: a third choice next to a course and "Planning (all courses)": a normal ChatGPT conversation with no
  course and no RecallSpring tools.
- **Ghost**: a switch for any of the three. A deliberate exception, chosen by the learner, to "persist raw learner
  input before model inference": the conversation lives only in the browser tab; the server passes each turn to
  ChatGPT (`store: false`, full history in the request) and keeps nothing, neither in the database nor in logs, except
  token usage without content. Ghost can read the learner's material, plan and notes but cannot write anything
  (no questions, grades, notes, forms) and has no attachments. Closing the tab or "End" discards it; "Keep this chat"
  turns it into a normal saved conversation from that moment. A ghost chat never appears in the list.

## Rollout

Each step with tests and docs: (1) form last and formulas; (2) home; (3) Chat folders; (4) Plain and Ghost chats;
(5) Study in… on Courses.

## Consequences

- Fewer interruptions while studying; external apps can still place a form early, which the instructions reduce.
- Ghost chats leave no learning evidence by design; their feedback cannot be graded or recovered.
- The MCP forms carry a built copy of the math parser, which must be rebuilt when the parser changes.
