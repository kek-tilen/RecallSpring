# Remote connector: an assistant on another computer

Decided 2026-11-27. When RecallSpring runs on one computer (for example a home server) and you study on another,
the assistant connects to RecallSpring's address instead of a connector installed next to it. Nothing is installed on
the computer you study on.

| Assistant | Connects from | What it needs |
| --- | --- | --- |
| Codex | the computer it runs on | an address that computer can reach (home network, VPN or internet) |
| Antigravity | the computer it runs on | the same |
| Claude (Desktop, claude.ai, phone) | Anthropic's cloud | an address reachable from the internet over HTTPS on port 443 |

The local connector (a process started by Claude Desktop, Codex or Antigravity on the computer RecallSpring runs on)
stays for installs on one computer; the remote one does not replace it.

## How it works

- `recallspring-mcp --http` serves the same tools at `http://127.0.0.1:4319/mcp` over MCP streamable HTTP (JSON
  responses). The proxy that serves RecallSpring's address sends `/mcp` there and everything else to the API.
- Every request needs a connector token in `Authorization: Bearer rsc_…`. The process checks a new token with the API
  (`GET /api/v1/connector/hello`, counted like any connector request) and remembers an accepted one for 5 minutes;
  each tool call is checked again by the API. A revoked token stops working at once for tools and within 5 minutes
  for new connections.
- An MCP session belongs to the token that began it; a request with another token gets 404.
- Tokens are the normal connector tokens: per assistant, stored by the API only as a hash, revocable in
  Settings › Assistants, counted towards the daily request limit, and the assistant's grades are labelled with its
  name. The remote process keeps no token file and no secret of its own.
- DNS rebinding protection stays on: only the public address and this computer may call.
- No OAuth yet (Codex keeps the token in an environment variable, Antigravity in its config file, Claude in its
  connector settings).

## Server settings

In `services/api/.env` and for the remote process:

| Setting | Meaning |
| --- | --- |
| `RS_REMOTE_URL` | the address other computers use, for example `https://study.example.org` (no path). Settings then shows `…/mcp` and the "From another computer" steps. Empty: the connector works on this computer only. |
| `RS_REMOTE_FROM_INTERNET` | `true` only when that address is reachable from the internet over HTTPS on port 443; Settings then shows the Claude steps. |
| `RS_API_URL` | for the remote process: where the API listens (default `http://127.0.0.1:4318`). |

Start it next to the API:

```powershell
$env:RS_REMOTE_URL = "https://study.example.org"
services\mcp\.venv\Scripts\recallspring-mcp --http --port 4319
```

The proxy route (nginx example; an additive `location`, validated with `nginx -t` and reloaded gracefully):

```nginx
location /mcp {
    proxy_pass http://127.0.0.1:4319;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
    limit_req zone=recallspring_mcp burst=20;  # define the zone in the http block
}
```

Opening an address to the internet is an infrastructure step on the server and proxy: it needs its own approval and
changes nothing on other sites served there.

## Set up an assistant

Settings › Assistants › the assistant › Set up (or Manage › Set up again or on another computer) ›
**From another computer**:

1. **Make a token** for the assistant. It is shown once.
2. **Codex:** `setx RECALLSPRING_TOKEN "<the token>"` in PowerShell on the computer you study on (only your Windows
   account can read it), then add to `~/.codex/config.toml` and restart Codex:

   ```toml
   [mcp_servers.recallspring]
   url = "https://study.example.org/mcp"
   bearer_token_env_var = "RECALLSPRING_TOKEN"
   ```

   **Antigravity:** add `"recallspring": {"serverUrl": "https://study.example.org/mcp", "headers": {"Authorization":
   "Bearer <the token>"}}` under `mcpServers` in `~/.gemini/config/mcp_config.json`, then restart Antigravity.

   **Claude** (only with `RS_REMOTE_FROM_INTERNET=true`): Settings › Connectors › Add custom connector, the URL, no
   sign in, and the request header `Authorization: Bearer <the token>`. A free Claude plan allows one custom connector.
3. **Check connection** waits for the assistant's first request (the token's "last used" time) and then says
   Connected.

Disconnect in Settings revokes all of an assistant's tokens at once (recorded in History); unticking an assistant
asks whether to disconnect it too.
