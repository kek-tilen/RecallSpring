# Study with Claude — connector setup (Claude Desktop, local)

RecallSpring's Mode A: you study in the official **Claude Desktop** app on your own Claude plan, and Claude uses the RecallSpring connector (a local MCP server) to read your plan, sources and notes and to record questions, answers and grades. RecallSpring never sees your Claude login, and the connector has no tools that delete anything or change settings.

## 1. Run RecallSpring locally

From the repository root (Windows paths; use `.venv/bin/` elsewhere):

```bash
docker compose -p recallspring-dev -f infra/compose.dev.yml --env-file infra/.env up -d
```

```bash
cd services/api && .venv/Scripts/uvicorn recallspring_api.main:app --host 127.0.0.1 --port 4318
```

```bash
cd services/api && .venv/Scripts/recallspring worker
```

Or run `scripts/start-local.ps1`, which does all three.

## 2. Create your account (once) and a connector token

```bash
cd services/api && .venv/Scripts/recallspring create-owner --username <you>
```

```bash
cd services/api && .venv/Scripts/recallspring connector-token --username <you>
```

The token is written to `%LOCALAPPDATA%\RecallSpring\connector-token` (`~/.config/recallspring/connector-token` elsewhere) and is never printed. It only works on RecallSpring's connector routes. Run the command again to replace it; revoke tokens in RecallSpring settings (`POST /api/v1/settings/connector/tokens/{id}/revoke`).

## 3. Install the connector and check it

```bash
cd services/mcp && python -m venv .venv && .venv/Scripts/python -m pip install --require-hashes -r requirements.lock && .venv/Scripts/python -m pip install --no-deps --no-build-isolation -e .
```

```bash
services/mcp/.venv/Scripts/python services/mcp/scripts/check_connector.py
```

Expected: `Connector started with 20 tools.` … `Connector OK.`

## 4. Add it to Claude Desktop

**Windows (Microsoft Store build):** the running app keeps its settings in memory and rewrites `claude_desktop_config.json` (under `%LOCALAPPDATA%\Claude-Data\claude_<id>\`), so an edit made while it runs is lost. Run

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-claude-desktop-connector.ps1
```

then quit Claude Desktop (tray icon → Quit). The script waits until the app has closed, adds only the `recallspring` entry (backup: `claude_desktop_config.json.bak-before-recallspring`) and starts Claude Desktop again. Log: `%LOCALAPPDATA%\RecallSpring\install-connector.log`. To remove the entry later: `python -I scripts/claude_desktop_config.py remove --config <path>` while the app is closed.

**Manually** (other platforms): Claude Desktop → **Settings → Developer → Edit Config** opens `claude_desktop_config.json`. Add (use your absolute repository path, with doubled backslashes on Windows), then fully quit and restart:

```json
{
  "mcpServers": {
    "recallspring": {
      "command": "<repo>\\services\\mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "recallspring_mcp"],
      "env": { "RS_API_URL": "http://127.0.0.1:4318" }
    }
  }
}
```

After the restart, RecallSpring appears in the chat's tools menu; Claude asks your permission the first time it uses a tool.

## 5. Study

Start a chat and choose your model (Sonnet by default, Opus for demanding material).

**First, build your library** (no web UI yet): *"Create a RecallSpring course 'Biology' and import C:\Users\me\Documents\lecture-1.pdf."* `import_file` sends the file straight from your disk to RecallSpring (it does not pass through the chat, so it does not use your Claude plan) and waits for extraction; only files in your Documents, Downloads or Desktop folders are allowed (`RS_IMPORT_ROOTS` overrides). Then: *"Propose the key concepts and link them to the sections."*

**Then study**, for example *"Let's do today's RecallSpring review"* or *"Quiz me on glycolysis at Bloom 4 using my lecture notes."* Claude will:

1. read your plan and material,
2. write a question and show the **answer form** in the chat,
3. wait for you — your exact answer is saved in RecallSpring when you press *Submit answer*,
4. grade it with evidence from your sources and tell you when it comes back for review.

If the form cannot be shown, Claude asks in chat and saves your answer marked *transcribed*, so you can check the stored text in RecallSpring.

## Limits and privacy

- Usage counts against your Claude plan's limits, which RecallSpring cannot see. RecallSpring's own daily connector limit (default 600 requests/day) can be scaled 1–100 % with `PUT /api/v1/settings/connector`.
- The chat transcript stays in your Claude account; RecallSpring stores the learning record.
- Material you share with Claude is processed under your Claude plan's terms.

## Troubleshooting

| Message from Claude | Fix |
|---|---|
| `RecallSpring is not reachable at http://127.0.0.1:4318` | Start the API (step 1). |
| `No connector token found at …` | Run `recallspring connector-token` (step 2). |
| `[401 connector_token_invalid]` | The token was revoked or replaced; create a new one. |
| `[429 connector_daily_limit]` | Raise the limit percentage or continue tomorrow. |
| Sources show `needs_attention`/`failed` | The worker is not running, or the PDF is scanned; paste the text instead. |
