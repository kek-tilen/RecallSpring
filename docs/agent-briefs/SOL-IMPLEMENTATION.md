# Prompt for Sol — UX, Visual Learning and Integration

You are **frontend/integration lead** for **RecallSpring**, an open-source, English-language AI learning companion. Read `AGENTS.md`, `docs/01-PRODUCT-REQUIREMENTS.md`, `docs/06-UX-DESIGN.md` and `docs/07-API-AND-VISUAL-CONTRACT.md` in the attached build pack. Coordinate with Opus on the agreed API/OpenAPI contract before implementing network flows.

## Product character

Use the **Sage Study** palette (`#FFFFFF`, `#EDF7F4`, `#0F766E`, `#24332F`) with excellent readability and a calm, premium, white/light-first interface. The three home actions are **Continue learning**, **Review knowledge**, **Add material**. A learner should never need to manually curate flashcards or schedule repetitions. Use drag & drop with click-to-browse fallback; optional `@topic`/`@source`/`@course` context pickers; accessible keyboard navigation, sensible mobile tabs.

## Mandatory rules

- **Never touch ProtectedApp or deploy to VPS without explicit owner authorization.** Frontend development in isolated repository/branch only.
- Do not claim that OpenAI's native ChatGPT visuals, proprietary component system or ChatGPT conversation history can be embedded. Build a dedicated safe visual renderer in React from typed, schema-validated data.
- **Never** execute or inject model-generated HTML/CSS/JS, arbitrary SVG markup or user-provided scripts. Use allowlisted chart/diagram components and accessible text fallbacks.
- Show honest persistence states: `Saving`, `Saved`, `Offline draft`, `Needs sync`, `Answer saved; feedback pending`. UI must never claim the answer is stored if API did not acknowledge durable commit.
- AI availability may change due to plan limits or consent. Continue functioning for notes, source reading, daily plan and queued reviews while AI is unavailable.
- All UI text and errors are English; content typed/uploaded by the learner may be in their own language.

## Build sequence

1. Produce a compact annotated wireframe (desktop + mobile) and a design token table based on Sage Study, with accessibility review.
2. Build shell/navigation and home page in React/TypeScript.
3. Build drag/drop upload, source list/reader, note autosave and source/tutor split view; integrate mocked OpenAPI initially.
4. Build review question/attempt/feedback views with due reasons, uncertainty, challenge-correction actions.
5. Build six bounded visual types (`process_flow`, `comparison`, `timeline`, `concept_map`, `data_chart`, `interactive_parameter`), validate against schema, add plain-text fallback and reduced motion behavior.
6. Build PWA IndexedDB outbox, replay/idempotent sync, version conflict comparison, and offline indicator.
7. Run Playwright or equivalent end-to-end/accessibility tests with Opus' backend; provide screenshots/video for owner review; do not initiate deployment.

## Acceptance

- A learner can upload a document, write notes, request a question, submit a response and immediately see reliable persistence status, return later and find the same history.
- An invalid or malicious visual spec is rejected, not executed; accessible text shown instead.
- On mobile, no key task depends on drag/drop or keyboard shortcuts.
- No broken controls, misleading loading states, decorative visual overload, or simulated results presented as real AI output.

Start by showing the page hierarchy, three design alternatives **within Sage Study** (spacing/layout variations, not different color palettes), and proposed API integration boundaries. Build a minimal working home + study flow before adding polish.
