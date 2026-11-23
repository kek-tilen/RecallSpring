# ADR-011 — Answers and notes given in the chat

Status: accepted 2026-11-23 (owner in chat); implemented 2026-11-23. Extends ADR-004 (Claude connector), ADR-006
(learning first) and ADR-010 (ways to practise).

## Context

In an assistant app (Claude Desktop, Codex, Antigravity, or ChatGPT in RecallSpring's Chat) the learner often answers
check questions and writes a summary directly in the chat instead of in RecallSpring's forms, sometimes with a photo
of handwritten notes. In a real session this happened and nothing reached RecallSpring:

- the assistant gave good feedback, but recorded no answer, grade or note, and did not say so;
- it described the learner's progress from the conversation history instead of reading RecallSpring (it called a
  diagnostic quiz pending that had been submitted the day before);
- it did not ask whether the learner's notes from the photo should be kept.

The connector already has `submit_chat_answer` (exact chat answer, `captured_via = assistant_transcription`), but the
instructions allow it only when a form cannot be shown. There is no tool for a note or summary written in the chat:
summaries are saved only by the summary form. An MCP tool receives text only, so the assistant cannot hand a photo
from the chat to RecallSpring.

## Decision

### 1. Always the current state

At the start of a conversation and when the learner returns after a pause, the assistant reads RecallSpring first
(`get_study_context`, and the plan or results it needs). It never states progress, dates or the state of a quiz from
the conversation history.

### 2. Chat answers can count

- When the learner answers a question in the chat, the assistant asks once per session whether answers given in the
  chat should count ("Should answers you give here in the chat count in RecallSpring?"). The answer holds for the
  session; the learner can change it at any time.
- When they count: if the question is not in RecallSpring yet, the assistant creates it first (`create_questions`,
  expected points from sections it read; no expected points, no grade). Then `submit_chat_answer` with the learner's
  words copied exactly, and the grade by the usual scale (`record_assessment`). The answer stays marked as transcribed
  in RecallSpring, where the learner can see it.
- When they do not count: feedback in the chat only.
- The answer form stays the first choice; this is for answers already written in the chat.
- In RecallSpring's own Chat (ChatGPT) the answer form is always shown under the message, so a chat answer that
  should count is pasted into that form (`open_answer_form`), which saves the learner's exact words; Chat has no
  `submit_chat_answer`.

### 3. Notes and summaries from the chat (new tool)

- New connector tool `save_chat_note` (append): a note in a course with the text the learner wrote or the assistant
  transcribed, saved only after the learner confirmed it.
- **Transcription of a photo:** word for word, without corrections or additions; unreadable words marked `[?]`. Before
  saving, the assistant shows the transcription and asks once whether it is correct; the learner's corrections are
  applied exactly. The note is labelled "Transcribed by your assistant from a chat or a photo: check it against
  your original" (on the note, and "Transcribed" in the list).
- The photo itself cannot be passed through the connector. The assistant offers the Library link so the learner can
  upload the original and link it to the note.
- **Summary of a learning chunk:** with `concept_ids`, the note is saved the same way as from the summary form (the
  learner's text exactly) and those concepts become *studied*. Without them it is an ordinary note.

### 4. Say when nothing was saved

When a reply gives feedback on the learner's work but nothing was recorded, the assistant says so in one line
("Nothing was saved to RecallSpring.").

### Not included

No tool to pause or stop a simulation's timer: the time limit is part of the simulation.

## Data (one migration)

`notes.captured_via` (`app_ui` default, `summary_form`, `assistant_transcription`), with a check constraint; existing
notes get `app_ui` (or `summary_form` where the record shows the summary form saved them). The web app shows the
transcription label on such notes. Downgrade drops the column.

## Interfaces (outline; details in docs/07 when implemented)

- Connector `POST /connector/notes` `{course_id, title, text, concept_ids?, transcribed_from_photo, client_request_id}`:
  idempotent; recorded as a `note.created` learning event (origin `chat` or `chat_photo`) without the text;
  `concept_ids` must be concepts of the course.
- MCP `save_chat_note`. In the ChatGPT Chat study set `save_chat_note` takes the place of `get_quiz_results`:
  `get_answer` reads a simulation's results with `quiz_id`, so the set stays within its limit of 20 tools.
- Instructions (MCP server, Chat, Codex and Antigravity setup): sections 1, 2 and 4; `submit_chat_answer` is no longer
  "fallback only".

## Consequences

- More of the learner's work reaches RecallSpring, always exact or clearly marked as transcribed.
- Transcribed answers and notes can contain reading mistakes; the label and the check before saving reduce, but do not
  remove, that risk. Grades of transcribed answers are study feedback like every AI grade.
- The assistant asks a little more (once per session for answers, once per transcription).
