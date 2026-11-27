# 08 — Security, Deployment and Operations Runbook

## Production protection policy

**ProtectedApp must remain online.** Any step that risks ProtectedApp downtime, any global Nginx change, resource contention, container recreation, Docker daemon restart, firewall alteration, certificate action affecting existing hosts, or pruning requires explicit owner review. A procedure described here is **not** authorization to execute it.

## Known starting state (private snapshot)

The owner provided a dated system and Docker snapshot for a Linux VPS: limited memory and disk, active ProtectedApp Compose services and host Nginx. **Precise hostnames, existing Compose paths, container IDs, current port binds and firewall forwarding topology are in `private/INFRASTRUCTURE-OWNER-ONLY.md`**, which must not be pushed to a public repository. Live state must be verified before any authorized deployment.

## Safe host inspection: read-only commands

```bash
uname -a
free -h
df -h /
docker compose ls
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker system df
ss -lntp | grep -E ':(80|443|3000|8000|4317)\b' || true
nginx -t
ufw status verbose
```

**Avoid copying sensitive environment values, certificates, or private keys into issue trackers or chats.** `nginx -T` may expose confidential hostnames and upstream details; redact before sharing.

## Space recovery (manual owner-approved operation only)

`docker builder prune` targets unused build cache (not running containers). It might slow next ProtectedApp rebuild; do not run during a build or without explicit owner approval. **Never** issue broad `docker system prune -a --volumes`, `docker volume prune`, `docker compose down` or unscoped deletion. After any cleanup, record `df -h /` and `docker system df`; do not rely on cache-reclaimable numbers alone. Suggested launch gate: **>=10 GiB** free after cleanup, with external backup provisioned and additional reserve for documents/migrations; reconsider on actual projected workload.

## Application isolation

- Project files: `/opt/recallspring` (or another new owner-approved path); no writes to the protected application's directory (see private operator snapshot).
- Compose project name `recallspring` specified explicitly. Backend, worker and db bound only to internal network; only frontend uses host `127.0.0.1:4317:80`.
- No Docker socket or host mount broad access; images pinned, drop privileges/capabilities, read-only FS where possible, per-service resource limits and health checks.
- Postgres volume and source file volume exclusively RecallSpring; database not exposed to host internet. Application database role has least privilege; migration role separated if feasible.
- Host Nginx new vhost for approved FQDN; host proxy to `http://127.0.0.1:4317`. No changes to the existing enabled site (see private operator snapshot).
- Since Docker port publishing can bypass ordinary UFW handling, explicitly test the external reachability of every published port before concluding it is protected; don't fix without a downtime-reviewed procedure.
- HTTPS: wait for owned domain, DNS and certificate; do not launch login or OAuth over plain public HTTP.

## Security controls

**Identity:** single-user app private login (Argon2id, 2FA optional but recommended, secure HttpOnly SameSite cookies, session expiry), distinct from any AI provider connection or connector token. Rate-limit login and consent requests, CSRF protection on state-changing routes, no public account sign-up. CORS closed by default. Restrict admin actions to authenticated owner.

**Files:** MIME sniffing, extension allowlist, max upload size per kind of file (100 MiB documents, 10 MiB text, 20 MiB photos, 2 GiB per library, uploads pause below 2 GiB free disk; all configurable), path traversal defense, no inline active HTML/SVG, malware scanning as availability permits, no arbitrary archive extraction, CPU and memory quotas for PDF parser, never execute document scripts. Office Open XML (.docx/.pptx/.xlsx) is read as a ZIP of XML parts only: the ZIP index is checked before opening (at most 10 000 entries, no ZIP64), each part is capped at 64 MiB and the total at 256 MiB uncompressed, XML with DTD or entity declarations is refused, relationship targets must stay inside the package, and macros, OLE objects, pictures and external links are never opened. Extraction runs in a separate `python -I` process with a timeout and, on Linux, a 2 GiB address-space limit. Page images for Claude are rendered by PDFium (pypdfium2, pinned with hashes) in the same kind of isolated, time-limited process; pictures embedded in Office/OpenDocument files and notebooks are passed on as they are when their first bytes show PNG/JPEG/GIF/WebP within 4.5 MB and 8000 px; anything else (TIFF, BMP, oversized photos) is decoded only by Pillow (pinned with hashes) inside that isolated process, with a 60-megapixel limit against decompression bombs. Vector drawings are never decoded. OpenDocument packages get the same ZIP/XML guards as Office files; an encrypted manifest is refused. CSV, subtitles, notebooks, LaTeX and code are read as text only: notebook HTML outputs are skipped and nothing is executed. The optional LibreOffice page renderer (`ingest/renderer.py`) converts the learner's own file to PDF in a throwaway profile (macros disabled, untrusted links blocked) with a timeout that kills the process tree; in production run it without network access, or switch it off with `RS_OFFICE_RENDERER=off`. Rendered PDFs are cached under `storage_dir/renders` by content hash. Source text is untrusted prompt content and cannot override tutor rules.

**AI:** no secrets in browser. Provider secrets (Anthropic API key, SIWC credential files) only in a protected owner-controlled runtime path, chmod 0600 / owner-only ACL on Windows, app-user ownership, written atomically; never in the database in plaintext, exports, logs or backups sent to third parties. Connector tokens are stored hashed, scoped to `connector`, revocable and shown once. Confirm the exact SIWC self-hosted VM method in the current official guide; do not fabricate OAuth redirects. No transcript sharing with other users. Implement model request concurrency bound, timeout, quota and USD-limit handling and separate background AI consent. A remote Claude connector (Claude web/mobile) needs public HTTPS plus OAuth on the MCP endpoint — deferred (desktop-only decision).

**Implemented: Sign in with ChatGPT credentials (2026-11-21).** They are kept in `RS_SECRETS_DIR` (default `local-data/secrets`, inside the Git-ignored `local-data/`), one file per learner (`chatgpt-<user id>.bin`), plus `chatgpt-host.json` with this computer's `ext_agent_host_id` (not a secret). On Windows each record is encrypted with DPAPI (CryptProtectData, bound to the Windows account, extra entropy, no UI). Elsewhere it is a 0600 file in a 0700 folder, as OpenAI's guide describes. Files are written atomically. A file copied to another Windows account cannot be read; it counts as signed out and is replaced by the next sign-in. Tokens never reach the database, the browser, API responses, the audit log or backups (backups copy only uploaded material by content hash). The OAuth callback's `code` and `state` are replaced by `[redacted]` in the uvicorn access log. Sign out revokes at OpenAI and deletes the tokens. Saved ChatGPT conversations (`ai_conversations`, `ai_messages`) are learner data in the database, so they are in backups, unlike the tokens. They hold the text, models, times, token counts and the ChatGPT account address, and the audit log never holds message text. Ghost chats (ADR-012 §5) are not stored at all: only `ai_ghost_usage` (model, token counts, outcome); their text lives in the browser tab and is gone when it closes. **Material sent to OpenAI:** only when the learner chose files for a conversation, and then only excerpts of those files (≤ 30 000 characters per message, with `store: false`); which sections went with each message is recorded in `ai_messages.context`, and the choice of files is audited. Excerpts are framed as quoted material so text inside a file is not treated as instructions. Sign-in is only offered on loopback hosts; a server deployment needs the official self-hosted VM procedure first (not built).

**Implemented: imports (2026-11-21).**
- **ChatGPT data exports** are staged under `storage_dir/imports/<user id>/<import id>/`: the ZIP, a parsed index and the rendered chats. Staging is not part of backups. It is deleted when the learner removes it, or by the worker after 7 days (`RS_IMPORT_RETENTION_DAYS`, audited `import.chatgpt_expired`).
- **Limits:** 1 GiB per export, 300 MB for `conversations.json`, 50 000 ZIP entries, 20 000 chats, 200 saved per request; uploads refuse below the free-disk gate. The export is parsed as JSON only; HTML in it (`chat.html`) is never opened or rendered.
- **Untrusted content:** chats and memories are the learner's own but untrusted content. A saved chat is ordinary material (wrapped as document content for Claude). Study preferences are presented to Claude as preferences that cannot override tutor or grading rules (R18).
- **ZIP uploads** (`/sources/zip`) and attachments from exports go through the same per-file checks as a normal upload (sniffing, allowlist, size, Office guards). Paths are only used to name folders, never as file-system paths, and nothing is extracted to disk except into content-addressed storage.

**Implemented: first run (2026-11-21, Phase 3).** A new install creates its first account on the first visit instead
of the command line. `POST /auth/setup` is accepted only while no account exists (checked under a PostgreSQL advisory
lock, so two tabs cannot both create one), only from a loopback client (127.0.0.1 / ::1), never when the request
comes from another site (`Sec-Fetch-Site: cross-site` or a non-loopback `Origin`; there is no session or CSRF cookie
yet), and never in production or with `RS_FIRST_RUN_ENABLED=false` (there: `recallspring create-owner`). The password
rules are the login's (≥ 12 characters, Argon2id); the account creation is audited (`user.created`, via first_run).
It is not self-signup: after the first account the endpoint answers 409.

**Implemented: Windows installer (2026-11-21, Phase 3).** `scripts/install.ps1` installs only from the hashed lock
files (`--require-hashes`, `npm ci`), writes the Git-ignored `.env` files only when missing (random database password
from `secrets`, never printed), keeps the database on 127.0.0.1, changes nothing outside the repository and Docker's
`recallspring-dev` project, stops only the two RecallSpring windows it replaces, and backs up before every database
migration. It installs no system software and makes no scheduled tasks.

**Observability:** structured request ids, metrics for error/latency/queue, sanitized logs; never log submitted source content, complete answers, prompt bodies or OAuth tokens by default. Provide audit records of deletion and grade overrides.

**Supply chain:** dependency lockfiles, container base image pinning, vulnerability scans, CI tests, backup/restore tests, no secrets in build args, non-root containers, migrations with rollback plan.

## Backups

- Daily encrypted PostgreSQL logical backup plus source-file backup, both copied **off VPS** to owner-approved destination; periodic restore drill to disposable environment.
- Document retention (e.g. 7 daily / 4 weekly / 3 monthly backups) is a proposal, not an owner-approved storage policy.
- Never keep only backups on the same 38 GB root disk. Never include OAuth tokens unless explicitly planned in a secure user-controlled recovery method.

### Implemented: automatic local backups (`backup.py`)

What a backup holds: a `pg_dump` (custom format) of the whole RecallSpring database and a copy of every uploaded
original (including soft-deleted sources, which can still be restored). Connector tokens are in the database only as
hashes; no OAuth credential, `.env` file or password is copied. The page-render cache is left out (it is rebuilt).

- **When (2026-11-27):** on a schedule: every `RS_BACKUP_EVERY_DAYS` (1) days at `RS_BACKUP_TIME` (03:00) in the
  first account's time zone (UTC before there is one). Settings → Data & backups → *How often* chooses daily, every
  3 days, weekly, every 2 weeks, monthly (on that day of the month; the last day of a shorter month) or every 1-90
  days, and the time; kept in `RS_BACKUP_SETTINGS_FILE` like the folder, first account only, locked by
  `RS_BACKUP_SETTINGS_FROM_WEB=false`, audited as `backup.schedule_changed`. Every N days counts from the day of
  the last good backup. The worker checks every 10 minutes, so a backup missed while RecallSpring was off runs as
  soon as it runs again; after a failure it waits an hour. *Back up now* in Settings → Backups and
  `recallspring backup` make one at once. One backup at a time (PostgreSQL advisory lock). No model calls.
- **Consistent:** row counts and the file list are read in the same REPEATABLE READ transaction whose snapshot
  `pg_dump --snapshot` uses, so the backup describes one moment.
- **Checked:** every backup is restored into a throwaway database `<db>_restore_check`, every table's row count must
  match, then that database is dropped (never the real one; the name always ends in `_restore_check`). Without
  permission to create databases (a hosted server) the dump is only read back, and Settings says so. Every file is
  checked against its SHA-256 while it is copied.
- **Chosen in Settings (2026-11-27):** Settings → Data & backups → *Where backups go* takes a folder on the computer
  RecallSpring runs on (typed or pasted: a browser cannot browse the server's folders). *Check folder* creates nothing
  and refuses what cannot hold backups: a relative path, a whole drive or top-level folder, system folders, a file,
  the uploads or secrets folder or a folder holding them, a folder RecallSpring cannot write to. It reports the free
  room, whether it is another disk than the uploads, and a sync app recognised from the path (Dropbox, OneDrive,
  Google Drive, iCloud Drive; a hint only). The choice is kept in `RS_BACKUP_SETTINGS_FILE` (default
  `local-data/backup-settings.json`, not learner data) and replaces `RS_BACKUP_DIR`; *Use the server's folder* goes
  back. Backups already made stay in the old folder (restore from there with `backup-restore --from <old folder>`). Only the
  first account may change it, because a backup holds the whole installation; `RS_BACKUP_SETTINGS_FROM_WEB=false`
  keeps the folder to the server settings (a hosted operator). Refused while a backup runs (same advisory lock);
  audited as `backup.folder_changed` with the old and new folder.
- **Where:** the folder chosen in Settings, else `RS_BACKUP_DIR`, default `local-data/backups` (gitignored), next to
  the uploaded files:
  `snapshots/<YYYYMMDD-HHMMSS UTC>/{db.dump, manifest.json}`, `files/<user>/<ab>/<sha256>` (shared by all snapshots,
  copied once) and `status.json`. Other files in that folder (e.g. hand-made `recallspring-pre-*.dump`) are never
  touched.
- **Kept:** daily backups: the newest of each of the last `RS_BACKUP_KEEP_DAILY` (7) days and of the newest
  `RS_BACKUP_KEEP_WEEKLY` (4) weeks. Less frequent ones: the last `RS_BACKUP_KEEP_LAST` (7), so monthly backups
  reach 7 months back (2026-11-27). The newest is always kept. Files no kept backup needs are removed; if any
  manifest cannot be read, every file is kept.
- **Seen:** Settings → Backups (last backup, what it holds, check, next, folder, size); Today → Needs attention when
  the last attempt failed, there is none yet, or none a day after the scheduled time; History lists backups started from the web
  app; every attempt is audited (`backup.created`, `backup.failed`). Error messages never contain the database
  password (redacted, 300 characters at most).
- **Tools:** `pg_dump`/`pg_restore` from `RS_BACKUP_PG_BIN`, else `PATH`, else, in development and tests only,
  `docker exec` into `RS_BACKUP_DOCKER_CONTAINER` (`recallspring-dev-db-1`, local socket, no password). Production
  images must ship the client tools of the server's major version; the Docker socket is never mounted.
- **Same disk:** the default folder protects against mistakes, a bad migration and a damaged database, not against a
  broken disk or a lost computer. Settings warns while the backup folder is on the same disk as the uploads. Choose
  another disk or a synced folder in Settings (or `RS_BACKUP_DIR`), or copy the folder elsewhere now and then. Without
  encryption, keep backups in places only you can read.
- **Encrypted with a recovery key (2026-11-27):** Settings → Data & backups → *Encryption* → *Turn on* makes an age
  X25519 key pair (pyrage 1.4.0, bindings to rage; `POST /settings/backup/key`, `Cache-Control: no-store`, nothing
  stored, no idempotency record). The private half (`AGE-SECRET-KEY-1…`) is shown once to be downloaded or copied; the
  learner ticks that it is kept off this computer and types its last 4 characters; only then is the public half
  (`age1…`) saved in `RS_BACKUP_SETTINGS_FILE` (`PUT /settings/backup/encryption`). The server can therefore lock
  backups but never open them, and a lost key means those backups cannot be restored by anyone. From then on a
  snapshot holds `db.dump.age` and `secret.json.age` (row counts per table and which sealed file is which upload)
  next to a plain `manifest.json` with totals, the key id and the dump's SHA-256; uploads are sealed once as
  `sealed/<HMAC>.age` (names keyed per installation and key, so they say nothing about the file). The dump is made
  and test-restored in a temporary folder under `RS_RUN_DIR` (`backup-work/`), never in the backup folder, and
  removed afterwards. *New key* replaces the key for new backups; older ones still need the key they were made
  with (the manifest names it). Older unencrypted backups are kept (they age out with the usual retention) or,
  when the learner chooses so and confirms, deleted after the first encrypted one (`backup.unencrypted_removed`).
  Audited as `backup.encryption_on` / `backup.key_replaced` with the key id only; no key ever reaches the
  database, the audit log, a log file or a backup. Encryption cannot be turned off from Settings.

#### Restore procedure (never overwrites)

1. `recallspring backup-status` lists the backups (newest first).
2. `recallspring backup-restore --database recallspring_restored --storage <empty folder>` (add
   `--key <recovery key file>` for an encrypted backup and `--from <folder>` for backups in a folder used before;
   a wrong key is refused before anything is created; optionally
   `--snapshot <name>`; default `latest`). It refuses the database RecallSpring uses, any database that exists, the
   storage folder in use and any folder that is not empty. It restores, compares the row counts with the manifest,
   copies the files with their checksums checked and prints what to change.
3. Look at the restored copy if you like (e.g. start a second API on another port with the new
   `RS_DATABASE_URL`/`RS_STORAGE_DIR`).
4. To switch: stop RecallSpring (close the API and worker windows), set `RS_DATABASE_URL` (and
   `RS_STORAGE_DIR`) in `services/api/.env`, run `alembic upgrade head`, start again (`scripts/start-local.ps1`). Keep the old database until you
   are sure; switching back is the same edit.

Restore drill, 2026-11-22 (owner's local install): the newest snapshot was restored into a throwaway database and
folder: 36 tables, every row count equal to the manifest, Alembic revision matching, all 27 files with correct
checksums, that day's answers and notes present, and the API started and answered `ready` on the copy. The throwaway
database and folder were then removed.

### FSRS-6 shadow report (ADR-014 §5)

`recallspring shadow-report [--username <name>] [--save]` prints what FSRS-6 in shadow would have done, for the
owner's checkpoint before phase B. It only reads (no model calls, nothing changes). `--save` also writes Markdown
and JSON to `local-data/reports/` next to the uploaded files: private learner data, never committed, never sent
anywhere. After installing migration 0033 run `recallspring recompute-reviews` once, so the shadow covers answers
given before it existed. A failure in the shadow is logged without learner data and never stops an answer or a grade.

Still required before a VPS release: an encrypted copy **off the VPS** to an owner-approved destination (owner choice
2 in docs/10) and a restore drill there; the local backups above do not replace it.

## Rollout stages with approval gates

**Stage A — Offline/local development**: unit/integration tests, ephemeral Postgres, fake AI adapter, no ProtectedApp access.  
**Stage B — Local AI feasibility**: validate the Claude Desktop connector locally; later SIWC OAuth/streams and, optionally, an Anthropic API key smoke test with a USD limit — all without production deployment.  
**Stage C — Isolated VPS private deployment**: only after owner approval, disk/memory check, offsite backup; new project isolated, loopback only, without host Nginx change.  
**Stage D — External HTTPS**: after approved DNS/FQDN and certificate plan, add *new* Nginx vhost, `nginx -t`, approved graceful reload, external TLS test.  
**Stage E — Monitoring**: compare before/after ProtectedApp health, CPU/memory/disk, requests, uptime; roll back RecallSpring immediately if ProtectedApp degrades.

Even a reload normally considered graceful is a change to shared host infrastructure and requires approval. Do not promise mathematically guaranteed zero downtime; the engineering objective is **zero intentional interruption** plus tightly controlled rollout and safe rollback.

## Baseline and verification checklist

1. Capture running ProtectedApp container IDs and uptime (read-only), and identify owner-provided health URLs (do not guess them).
2. Record `df -h`, `free -h`, `docker stats --no-stream`, `ss -lntp`, Docker projects and Nginx syntax validation.
3. Deploy ONLY `recallspring` with explicit Compose file and project flags once approved.
4. Validate RecallSpring health via `curl http://127.0.0.1:4317/...` from host.
5. Confirm ProtectedApp container IDs unchanged, response health unchanged, Nginx existing site unchanged and no new public bind except allowed Nginx HTTPS.
6. Roll back RecallSpring changes alone on resource pressure or degraded ProtectedApp latency. Do not stop ProtectedApp, Docker daemon, or global Nginx service.
7. After SSL and DNS changes, repeat external functional, security and backup restore checks.

## Rollback

Owner-authorized rollback must stop/disable **only RecallSpring** services and remove only newly added RecallSpring Nginx site/cert hooks. Preserve database/volumes by default; never delete learner data as part of a rollback. Host Nginx can be gracefully reloaded after approval and a valid config test. Re-verify existing production app.

## Security release blockers

No secure auth, unencrypted public login, exposed DB port, missing offsite backup, failing restoration, an enabled AI provider whose official terms or eligibility are unverified, active prompt injection into tools, executable AI-generated HTML/JS, or ProtectedApp impact => **no production release**.
