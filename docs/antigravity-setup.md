# Study with Google Antigravity: connector setup (local)

RecallSpring works with **Google Antigravity** (the Antigravity app and its CLI) the same way it works with Codex:
Antigravity starts RecallSpring's connector (the local MCP server Claude Desktop and Codex use) to read your plan,
material and notes and to save questions, answers and grades. You sign in to Antigravity with your own Google
account; RecallSpring never sees that sign-in and uses no API key. Grades from Antigravity count like any
assistant's and are labelled "Antigravity" with the model it reported (owner decision 2026-11-22).

Checked against Google's Antigravity docs on 2026-11-22 (docs/10 → research log): the app and CLI read MCP servers
from `~/.gemini/config/mcp_config.json` (`{"mcpServers": {...}}`, local `command`/`args`/`env` servers supported),
and read `AGENTS.md` (or `GEMINI.md`) in the workspace folder and its parents as always-on rules. Which Google plan
includes how much Antigravity use is Google's to decide; the docs name free, Pro and Ultra, and Google AI Plus for
students included it for the owner. Re-check the docs if Antigravity changes these paths.

## 1. Before you start

- RecallSpring runs locally (`scripts\start-local.ps1`) and you have an account (docs/connector-setup.md steps 1-2).
- The connector is installed: `services\mcp\.venv` exists (docs/connector-setup.md step 3).
- Antigravity is installed and you are signed in to it.

## 2. Run the installer

```powershell
scripts\install-antigravity-connector.ps1 -Username <you>
```

It does three things and changes nothing else:

1. **An Antigravity token** in its own file, `%LOCALAPPDATA%\RecallSpring\antigravity-connector-token` (never
   printed). Claude Desktop and Codex keep their own tokens, so revoking one never disconnects another. Pass
   `-NewToken` to replace it.
2. **One `recallspring` entry in `mcp_config.json`**: the connector command, `RS_API_URL`, the token file's path
   (not the token) and `timeoutSeconds: 300` (imports and page images take a while). Every other server and setting
   is kept; a backup `mcp_config.json.bak-before-recallspring` is made once. The script refuses to touch the file if
   it is not valid JSON or already has a `recallspring` server it did not write. Running it again replaces only its
   own entry. Use `-ConfigFile` if your Antigravity keeps the file elsewhere.
3. **Study folders** in `Documents\RecallSpring Study`: `Planning` plus one folder per course or interest, each with
   an `AGENTS.md` (the study flow with that course's ID). They are the same folders Codex uses, so if you use both,
   both read the same instructions. The `.codex` subfolder is for Codex only; Antigravity ignores it.
   Run the installer again after adding courses. A file whose first line you deleted is treated as your own and kept.

Then quit and reopen Antigravity.

## 3. Study

1. Open a course folder (or `Planning`) as the workspace.
2. In the agent panel, `…` → **MCP Servers** should list `recallspring` with its tools.
3. Write “Start studying”. Antigravity asks before each RecallSpring tool until you allow it; keep asking on for the
   tools that save something (grades, questions) if you want to see each one.

Answer questions on RecallSpring's own pages when Antigravity gives you a link, then tell it you are done.

## 4. Remove

```powershell
scripts\install-antigravity-connector.ps1 -Uninstall
```

This removes only RecallSpring's entry. Then revoke the Antigravity token in RecallSpring → Settings → Assistant
connector. The study folders and the token file stay; delete them yourself if you like.

## Troubleshooting

- `recallspring` is missing from MCP Servers: check `scripts\antigravity_setup.py config check` prints `present`,
  then restart Antigravity.
- Tools fail with “unauthorised”: the token was revoked; run the installer with `-NewToken`.
- RecallSpring was updated: quit and reopen Antigravity so it starts the new connector.
