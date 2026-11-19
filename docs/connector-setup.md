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

Expected: `Connector started with 15 tools.` … `Connector OK.`

## 4. Add it to Claude Desktop

Claude Desktop → **Settings → Developer → Edit Config** opens `claude_desktop_config.json`. Add (use your absolute repository path, with doubled backslashes on Windows):

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

Fully quit and restart Claude Desktop. RecallSpring appears in the chat's tools menu; Claude asks your permission the first time it uses a tool.

## 5. Study

Start a chat, choose your model (Sonnet by default, Opus for demanding material), and say for example *"Let's do today's RecallSpring review"* or *"Quiz me on glycolysis at Bloom 4 using my lecture notes."* Claude will:

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
