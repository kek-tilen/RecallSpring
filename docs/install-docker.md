# Install RecallSpring with Docker

One command installs RecallSpring on any computer with Docker: Linux, macOS, or Windows with Docker Desktop. Everything
runs and stays on that computer: your account, material, notes, grades and backups. Nothing is sent to the RecallSpring
authors. (Decision 2026-11-28: Docker first, a Windows bundle without Docker later; docs/10.)

Prefer running it from the code on Windows, without the image? See [install-windows.md](install-windows.md).

## 1. What you need

- **Docker** with Compose v2 (the `docker compose` command): Docker Desktop on Windows and macOS
  (docker.com, or `winget install Docker.DockerDesktop`), Docker Engine on Linux. Start it before you install.
  The install never installs Docker, never uses sudo and never needs administrator rights.
- **About 4 GB of free disk space** and at least **2 GB of memory for Docker** (Docker Desktop: Settings > Resources).
- On Linux and macOS: `curl` (almost always there). On Windows: PowerShell, which every Windows has.

Without Docker on Linux or macOS there is no install yet; on Windows, use install-windows.md.

## 2. Install

Linux and macOS (a terminal), or Windows in Git Bash:

```sh
curl -fsSL https://github.com/kek-tilen/RecallSpring/releases/latest/download/install.sh | sh
```

Windows (PowerShell):

```powershell
irm https://github.com/kek-tilen/RecallSpring/releases/latest/download/install.ps1 | iex
```

Prefer to read it before it runs? Download `install.sh` or `install.ps1` from the
[latest release](https://github.com/kek-tilen/RecallSpring/releases/latest), read it, then run
`sh install.sh` or `powershell -ExecutionPolicy Bypass -File install.ps1`.

The script first checks Docker, disk space, memory and the two ports, then says exactly what it will do and **asks
before it changes anything**. Then it:

1. downloads that release's `compose.yml`, `images.env` and the `recallspring` command and checks each one against
   the release's `SHA256SUMS` (whose own hash is written into the install script when the release is built);
2. makes one folder (`~/RecallSpring`, on Windows `%USERPROFILE%\RecallSpring`) with these files and a `.env` that
   holds a random database password, readable by you only and never printed;
3. downloads the images, each by its fixed digest, and starts RecallSpring;
4. prints a **one-time link** for your account (section 3).

Options (PowerShell uses the same names, e.g. `-Dir`, `-Full`, `-SyncFolder`):

| Option | What it does |
| --- | --- |
| `--dir <folder>` | install somewhere else than `~/RecallSpring` |
| `--full` | the image with LibreOffice, so Word, PowerPoint and OpenDocument pages are shown as they look (about 1 GB instead of 500 MB) |
| `--backups <folder>` | put the nightly backups in this folder (default: `backups` in the install folder) |
| `--sync-folder <folder>` | a folder your sync app (iCloud Drive, OneDrive, Dropbox, ...) uploads; see section 6 |
| `--port <n>`, `--mcp-port <n>` | other ports than 4318 (web app) and 4319 (assistant connector) |
| `--version vX.Y.Z`, `--beta` | a particular release, or the newest pre-release |
| `--yes` | do not ask (for scripts) |

With options, pipe into `sh -s --`, e.g. `curl -fsSL <url> | sh -s -- --full --dir ~/Study/RecallSpring`. In
PowerShell: `& ([scriptblock]::Create((irm <url>))) -Full -Dir D:\RecallSpring`.

Everything listens on 127.0.0.1 only: RecallSpring is reachable from this computer and from nobody else.

## 3. Your first account

The install prints a link like `http://127.0.0.1:4318/login#setup=ABCD-EFGH-JKMN`. Open it in your browser on the
same computer: it lets you create the first account (the owner) once, within 24 hours. The code after `#setup=` never
reaches a server log, and RecallSpring keeps only its hash. Without the link, nobody can create the first account.

Lost the link, or it expired? `~/RecallSpring/recallspring setup-link` prints a new one (the old one stops working).
Once an account exists, no new link is made.

## 4. Every day

The `recallspring` command lives in the install folder (on Windows `recallspring.cmd`, which runs `recallspring.ps1`
for that command only, whatever the execution policy). It only talks to Docker's project for that folder.

| Command | What it does |
| --- | --- |
| `recallspring status` | version, what runs, whether the web app answers, and whether a newer release exists |
| `recallspring update` | update to the newest release (section 5); `--beta` for pre-releases |
| `recallspring logs` | follow the API log; `--worker`, `--mcp` or `--db` for the others |
| `recallspring stop`, `recallspring start` | stop it, start it again |
| `recallspring backup` | back up now (it also runs every night) |
| `recallspring setup-link` | a new one-time link for the first account |
| `recallspring admin <command>` | an admin command, e.g. `admin reset-password --username ana` |
| `recallspring uninstall` | remove the containers (section 8) |

RecallSpring starts again by itself when Docker starts (after a restart of the computer, start Docker Desktop).
It looks for a newer release only when you run `status` or `update`, never in the background.

## 5. Updates

`recallspring update`:

1. asks GitHub for the newest release, downloads its files and checks them against its `SHA256SUMS`;
2. shows the version and its release notes, and asks;
3. **backs up first** (and stops if the backup fails, so nothing changes);
4. keeps the old `compose.yml` and `.env` as `*.previous`, downloads the new images and starts them; the database
   structure is updated as its own step (the `migrate` service) before the new version starts, with one more backup
   when the database holds data;
5. if the new version does not become ready, it goes back to the old one by itself. If the old one cannot start
   either (the database structure was already changed), follow section 7.

## 6. Backups and the synced folder

Backups run every night into the backups folder (`--backups`, default `backups` in the install folder). In a Docker
install **the folders are chosen by the install command and shown read-only in Settings**: the containers can only
write to folders they were given. The schedule, encryption and the cloud copy (Google Drive, Dropbox, OneDrive) are
still set in Settings > Backups. Keep a copy somewhere else too: one disk is not a backup.

`--sync-folder <folder>` gives RecallSpring a folder that a sync app uploads (e.g. iCloud Drive or your OneDrive
folder). It makes `RecallSpring/Backups` there for encrypted backups (the cloud copy turns on by itself once encryption
is on) and `RecallSpring/Material`, where each learner who chooses *Use a synced folder* gets a subfolder. It is written
to `compose.local.yml` in the install folder. To add or change it later, install again in a new folder, or edit
`compose.local.yml` (see the one the install makes) and run `recallspring start`.

## 7. Going back (restore a backup)

A restore never overwrites anything: it goes into a **new** database, and you switch to it yourself.

```sh
cd ~/RecallSpring          # on Windows: cd $env:USERPROFILE\RecallSpring, and .\recallspring instead of ./recallspring
ecallspring instead of ./recallspring
ecallspring instead of ./recallspring
./recallspring admin backup-status
./recallspring admin backup-restore --database recallspring_restored --storage /data/storage-restored
```

Add `--snapshot <name>` for an older snapshot than the newest, and `--key /data/<file>` for an encrypted backup (put
the recovery key file in the install folder's `data` folder first). It restores, compares the row counts with the
backup and prints what to switch. Then:

1. `./recallspring stop`
2. add these two lines to `.env` in the install folder:
   ```
   RS_DB_NAME=recallspring_restored
   RS_STORAGE_DIR=/data/storage-restored
   ```
3. after a failed update, also put the old image back: copy the `RS_IMAGE` and `RS_VERSION` lines from
   `.env.previous` into `.env`, and `compose.yml.previous` over `compose.yml`;
4. `./recallspring start`, then sign in and check your material.

The old database stays until you are sure; it is never deleted by a restore.

## 8. Uninstall

`recallspring uninstall` stops RecallSpring and removes its containers. Your data stays (Docker's volume and the
install folder), so installing again in the same folder brings everything back. Only when you then type
`delete my data` does it delete the database and the `data` folder. Backups are always kept; delete them yourself when
you are sure.

## What the containers may do

- One image for the API, the worker, the connector and the one-time `migrate` step, plus PostgreSQL 16; base images
  are pinned by digest, Python packages by hash.
- Every container runs as a normal user (never root), with a read-only file system, no Linux capabilities,
  `no-new-privileges`, and memory and process limits. No host network, no privileged mode, no Docker socket.
- The database is on an internal network with no way out and no port on your computer.
- They can write only to the install folder's `data` folder, the backups folder and the sync folder you named.
- The image runs in production mode (no API docs page; the first account needs the setup link) and makes no model
  calls of its own: tutoring happens in your assistant (Claude, Codex, ...), as in every RecallSpring install.

## Assistants

The connector for Codex and Antigravity listens at `http://127.0.0.1:4319/mcp` (or your `--mcp-port`); Settings >
Assistants shows the address and makes its token. See [codex-setup.md](codex-setup.md) and
[antigravity-setup.md](antigravity-setup.md). Claude Desktop's connector ([connector-setup.md](connector-setup.md))
runs a program from the code checkout; with Docker it is not set up or tested yet.

## How a release is made

Pushing a version tag (`v0.4.0`, or `v0.4.0-beta.1` for a pre-release) runs `.github/workflows/release.yml`: it
builds both images for amd64 and arm64, pushes them to GitHub Packages with build provenance, and publishes the
release files: `compose.yml`, `images.env` (both images by digest), `recallspring`, `recallspring.ps1`, `SHA256SUMS`,
and `install.sh` / `install.ps1` with the version and the hash of `SHA256SUMS` written in. Check an image with
`gh attestation verify oci://<image> --owner kek-tilen`.

## Not tested yet

Tested locally on 2026-11-28: the install from Git Bash and from Windows PowerShell, the setup link, backups and a
restore with the switch to it, the worker, the connector over HTTP, and both images built: LibreOffice converting a
document inside the hardened full image, and the arm64 image starting under emulation. Not tested yet: arm64 on real
hardware (e.g. a Mac with Apple silicon), Claude Desktop, ChatGPT sign-in from inside Docker, iCloud Drive as the
sync folder, and `update` from one release to the next. Report what you find.
