# Install RecallSpring on Windows

For one person on their own Windows 10 or 11 computer. Everything stays on that computer: your account, material,
notes, grades and backups. Nothing is sent to the RecallSpring authors. (Decision 2026-11-21: Windows first,
the database keeps running in Docker; docs/10.)

Just want to use RecallSpring, without the code? The Docker install needs one command and no Python, Node.js or Git:
[install-docker.md](install-docker.md). This guide is for running it from a checkout of the code.

## 1. What you need

Install these yourself (the installer checks them but installs none):

| Program | Why | Get it |
| --- | --- | --- |
| Python 3.12 or newer | RecallSpring's server | python.org, or `winget install Python.Python.3.12` |
| Node.js 22 or newer (LTS) | builds the web app | nodejs.org, or `winget install OpenJS.NodeJS.LTS` |
| Docker Desktop | runs the database (reachable from this computer only) | docker.com, or `winget install Docker.DockerDesktop` |
| Git | gets and updates the code | git-scm.com, or `winget install Git.Git` |

Start Docker Desktop and wait until it says *Engine running*. About 3 GB of free disk space is enough to begin.

## 2. Get the code and install

In PowerShell, in the folder where RecallSpring should live:

```powershell
git clone <repository URL> recallspring
cd recallspring
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

The installer (`scripts/install.ps1`) changes nothing outside this folder and Docker's `recallspring-dev` project:

1. checks Python, Node and Docker;
2. makes the settings files `infra\.env` (a random database password) and `services\api\.env`, only if they are
   missing (they are Git-ignored, never overwritten, and the password is never printed);
3. starts the database (`127.0.0.1:55432`, this computer only) and waits for it;
4. installs RecallSpring's Python packages from the hashed lock files into `services\api\.venv` and
   `services\mcp\.venv` (the connector for Claude Desktop and Codex);
5. creates or updates the database structure, after a backup when it already holds data;
6. builds the web app;
7. starts RecallSpring and opens `http://127.0.0.1:4318/`.

`-NoStart` does everything except step 7.

## 3. First visit: your account and your assistant

The first visit to `http://127.0.0.1:4318/` asks you to create your account: a username, a password of at least 12
characters (there is no e-mail reset, so keep it in your password manager) and your time zone (taken from this
computer). This works only on the computer RecallSpring runs on and only while no account exists; afterwards the page
is the normal sign-in. `services\api\.venv\Scripts\recallspring create-owner --username <name> [--timezone <zone>]`
does the same from the command line. A forgotten password is set again on this computer with
`services\api\.venv\Scripts\recallspring reset-password --username <name>` (it signs out every session). To sign in
with one tap instead of typing, add a passkey in Settings › Account & system › Sign-in; passkeys work at
`http://localhost:4318/`, not at 127.0.0.1.

Then RecallSpring asks which assistants you study with (tick one or more). For the apps with a connector it shows one
command, `scripts\install-connectors.ps1 -Assistants claude,codex -Username <you>`, which runs the scripts below in turn. RecallSpring itself keeps your records and plans your reviews;
the assistant tutors you with them. Grades from any of them count the same and show who gave them.

| Assistant | You need | Set up |
| --- | --- | --- |
| **Claude** (Claude Desktop) | Claude Desktop from the Microsoft Store, a paid Claude plan | `recallspring connector-token --username <you>`, then `scripts\install-claude-desktop-connector.ps1` (docs/connector-setup.md) |
| **Codex** | Codex (app, CLI or IDE extension), signed in with your ChatGPT plan | `scripts\install-codex-connector.ps1 -Username <you>` (docs/codex-setup.md) |
| **ChatGPT in RecallSpring** (preview) | a ChatGPT Plus or Pro plan | Sign in with ChatGPT on the welcome page or in Settings → Assistants, then Chat |
| Decide later | nothing | material, notes, reviews and plans work without an assistant |

With ChatGPT in RecallSpring, a new Chat conversation with **Planning (all courses)** picked under Study sets up your
courses, their concepts, midterm and exam dates; a conversation with one course picked is for learning it. Your
material goes in through Library.

**Settings → Assistants** shows which assistants you use and which are connected, when each was last used, and sets
each one up, manages its tokens or disconnects it; you can use several at once. The time zone is in **Settings → Profile**.

## 4. Every day

- After a restart of the computer: start Docker Desktop, then `scripts\start-local.ps1`. The API and the worker run
  in the background without a window; Settings → Running in the background shows whether both run.
- The worker backs up the database and your files every night into `local-data\backups` (Settings → How often changes that). That is
  on the same disk: choose another disk or a synced folder in Settings → Data & backups → Where backups go (or set
  `RS_BACKUP_DIR` in `services\api\.env`) for real protection. Restore steps: docs/08 → Backups.

### Running in the background

| Command | What it does |
| --- | --- |
| `scripts\start-local.ps1` | starts the database, API and worker (anything already running is left alone) |
| `scripts\start-local.ps1 -Status` | shows whether the API and the worker run, the API's health and the worker's heartbeat |
| `scripts\start-local.ps1 -Restart` | stops the API and the worker and starts them again (e.g. after an update) |
| `scripts\start-local.ps1 -Stop` | stops them; the database keeps running in Docker |
| `scripts\logs.ps1` | the last 40 lines of the API log, then new lines until Ctrl+C (`-Worker`, `-Lines 200`, `-NoFollow`) |

The logs are `local-data\logs\api.log` and `worker.log`, rotated at 5 MB with three old files kept (about 20 MB at
most each). They stay on this computer, like everything in `local-data`. The worker writes a heartbeat every 30
seconds to `local-data\run`; after two minutes without one, Settings shows it as stopped (imports and automatic
backups then wait). Docker for the API and worker is planned for the home server, where the ChatGPT sign-in is kept in
a 0600 file; on Windows it stays protected with DPAPI by running as your user.

## 5. Updating

```powershell
git pull
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

The installer stops the RecallSpring API and worker first (Windows does not let running programs be replaced), backs up
your data before changing the database, and starts RecallSpring again. With Claude Desktop, quit and reopen it
afterwards so it loads the new connector; with Codex, start a new session.

## Troubleshooting

| Message | What to do |
| --- | --- |
| *Python 3.12 or newer is needed* / *Node.js 22* | install it (table above), open a new PowerShell window, run the installer again |
| *Docker Desktop is installed but not running* | start it, wait for *Engine running*, run the installer again |
| *The database did not become ready* | Docker Desktop → Containers → `recallspring-dev` → logs |
| *RecallSpring did not start* | `scripts\logs.ps1 -NoFollow` shows the error at the end of the API log |
| Port 4318 or 55432 is in use | another program uses it; stop that program (RecallSpring does not change ports by itself) |
| *For safety, the first account can only be created on the computer RecallSpring runs on* | open `http://127.0.0.1:4318/` on that computer |

Uninstalling: `scripts\start-local.ps1 -Stop`, then
`docker compose -p recallspring-dev -f infra\compose.dev.yml --env-file infra\.env down` (keeps the data volume;
add `-v` only if you really want to delete all your data, after copying `local-data\backups` somewhere safe), then
delete the folder. The Codex and Claude Desktop scripts have their own removal options.
