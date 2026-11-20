# RecallSpring web app

The browser view of everything RecallSpring stores: today's plan, courses with their exams and concepts, review
schedule, kolokvij simulations with answers and grades, your material and its extracted text, notes with
revisions, the full learning history, and settings (study time, Claude connector limit and tokens, theme).

It also organises: courses grouped by university › faculty › semester (archive a semester when it ends), course
colours, an exam timeline where dates are moved by dragging (or arrow keys) with undo, a calendar (.ics) export,
simulations answered in the browser (open answers wait for Claude; copy the ID), and photos of notes and
exercises filed by category.

Studying itself happens in Claude (Mode A). The web app is where you check, correct and organise what was saved.

- React + TypeScript + Vite, TanStack Query, React Router. Sage Study tokens in `src/styles.css`, light first,
  dark variant (system or chosen in Settings).
- Same-origin only: the API serves the built app from `apps/web/dist` at `http://127.0.0.1:4318/`, so the
  session cookie stays `HttpOnly` + `SameSite=Strict` and writes send the `rs_csrf` double-submit token and an
  `Idempotency-Key`.
- Strict Content-Security-Policy (`script-src 'self'`, no inline scripts or styles, `frame-ancestors 'none'`).
  Learner and model text is always rendered as text, never as HTML.
- Reads use the owner-only overview routes (`/api/v1/dashboard`, `/overview/courses`, `/courses/{id}/overview`,
  `/concepts/{id}/detail`, `/quizzes`, `/attempts`, `/history`); connector tokens cannot reach them.

## Build and run

```bash
npm ci
npm run build      # typecheck + production build into dist/
npm test           # unit tests (vitest, jsdom)
```

Then start (or restart) the local API: `scripts/start-local.ps1 -Restart` and open `http://127.0.0.1:4318/`.

For UI work with hot reload run `npm run dev`: Vite serves `http://127.0.0.1:4317` and proxies `/api` to the API
on port 4318.
