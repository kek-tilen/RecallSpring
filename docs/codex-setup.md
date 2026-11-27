# Study with Codex: connector setup (local)

RecallSpring works with **Codex** (the Codex app, the `codex` CLI and the IDE extension) as well as with Claude
Desktop. Codex runs on your own ChatGPT plan and starts RecallSpring's connector (the same local MCP server Claude
Desktop uses) to read your plan, material and notes and to save questions, answers and grades. RecallSpring never
sees your ChatGPT sign-in; you sign in to Codex yourself. Grades from Codex count exactly like Claude's and are
labelled "Codex" with the model it reported (owner decision 2026-11-21).

Checked against OpenAI's Codex docs on 2026-11-21 (docs/10 → research log). Codex reads MCP servers from
`config.toml` in the Codex home (`%USERPROFILE%\.codex`, or `CODEX_HOME`), shared by the app, CLI and IDE extension.

## 1. Before you start

- RecallSpring runs locally (`scripts\start-local.ps1`) and you have an account (docs/connector-setup.md steps 1-2).
- The connector is installed: `services\mcp\.venv` exists (docs/connector-setup.md step 3).
- Codex is installed and you are signed in to it.

## 2. Run the installer

```powershell
scripts\install-codex-connector.ps1 -Username <you>
```

It does three things and changes nothing else:

1. **A Codex token** in its own file, `%LOCALAPPDATA%\RecallSpring\codex-connector-token` (never printed). Claude
   Desktop keeps its own token, so revoking one never disconnects the other. Pass `-NewToken` to replace it.
2. **One block in Codex's `config.toml`**, between `# >>> recallspring` and `# <<< recallspring`: the connector
   command, `RS_API_URL`, the token file's path (not the token), startup 20 s and tool timeout 120 s (imports and
   page images take longer than Codex's default 60 s). A backup `config.toml.bak-before-recallspring` is made once.
   The script refuses to touch the file if it is not valid TOML or already has an `[mcp_servers.recallspring]` entry
   it did not write. Running it again replaces only its own block.
3. **Study folders** in `Documents\RecallSpring Study`: `Planning` plus one folder per course or interest, each with
   - `AGENTS.md`: what Codex does there (the same study flow as the Claude projects, docs/claude-projects.md), with
     that course's ID;
   - `.codex\config.toml`: `sandbox_mode = "read-only"`, `approval_policy = "on-request"`. Codex applies it only
     after you trust the folder.
   Run the installer again after adding courses. A file whose first line you deleted is treated as your own and kept.

Then restart Codex.

### Codex on another computer

When RecallSpring runs elsewhere (a home server with an address), Codex connects to that address instead and nothing is installed next to Codex: Settings › Assistants › Codex › Set up › From another computer gives the token, the `setx RECALLSPRING_TOKEN` command and the `config.toml` lines (docs/remote-connector.md).

## 3. Study

1. Open a course folder in Codex (the app: open the folder as a project; CLI: `cd` into it and run `codex`) and
   trust it when Codex asks.
2. Check that the connector runs: `/mcp` in the CLI lists `recallspring`.
3. Write "Start studying." Codex follows `AGENTS.md`: study context, plan, learn first, then practice.

**Forms.** Claude Desktop, Codex and Antigravity show answer, summary and simulation forms inside the chat (MCP Apps;
Codex and Antigravity seen by the owner on 2026-11-22). When an app does not
announce MCP Apps support, RecallSpring's tools return a link instead, e.g. `http://127.0.0.1:4318/answer/<id>`.
You answer on that RecallSpring page, so your exact words are saved before Codex sees them; then tell Codex you are
done, and it reads the answer with `get_answer` or `get_quiz_results`. Simulations use the existing Simulations page;
summaries the new `/summary` page. Drafts stay in your browser until saved.

**Approvals.** RecallSpring's tools only read or add records; none delete anything or change settings. By default
(`-ToolApproval writes`) Codex asks before each RecallSpring tool that is not read-only (saving a question, an
answer copied from chat, a grade). Codex's docs define only this mode, so it is the default; `prompt`, `auto` and
`approve` are passed to Codex unchanged if you choose them.

**Shell and files.** Codex is a coding agent and can run commands. In the study folders it stays read-only and asks
before anything else; `AGENTS.md` tells it to use only RecallSpring tools, except `import_file` with a path you give.

## 4. Remove

```powershell
scripts\install-codex-connector.ps1 -Uninstall
```

This removes only RecallSpring's block from `config.toml`. Revoke the Codex token in RecallSpring → Settings →
Assistant connector. Study folders and the token file stay until you delete them.

## Smoke test 2026-11-22 (owner, Codex in the ChatGPT desktop app)

Passed: the connector loaded from `config.toml`; the summary and answer forms showed inside the chat (MCP Apps);
the summary was saved as a note and its concepts marked studied; three Bloom-2 questions were created; the answer was
saved verbatim from the form before grading; the grade was recorded as `codex_app` with the model Codex reported,
and RecallSpring set the next review. The CLI and IDE extension may still lack forms; they get the link fallback.

Images: verified by the owner on 2026-11-22 in the Codex desktop app: `view_page` returned a page of a PDF and Codex
described the figure on it correctly.
