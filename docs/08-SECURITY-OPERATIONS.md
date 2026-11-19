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

**Files:** MIME sniffing, extension allowlist, max upload size (proposed 30 MiB file, 250 MiB per initial library, tune for disk), path traversal defense, no inline active HTML/SVG, malware scanning as availability permits, no arbitrary archive extraction, CPU and memory quotas for PDF parser, never execute document scripts. Source text is untrusted prompt content and cannot override tutor rules.

**AI:** no secrets in browser. Provider secrets (Anthropic API key, SIWC credential files) only in a protected owner-controlled runtime path, chmod 0600 / owner-only ACL on Windows, app-user ownership, written atomically; never in the database in plaintext, exports, logs or backups sent to third parties. Connector tokens are stored hashed, scoped to `connector`, revocable and shown once. Confirm the exact SIWC self-hosted VM method in the current official guide; do not fabricate OAuth redirects. No transcript sharing with other users. Implement model request concurrency bound, timeout, quota and USD-limit handling and separate background AI consent. A remote Claude connector (Claude web/mobile) needs public HTTPS plus OAuth on the MCP endpoint — deferred (desktop-only decision).

**Observability:** structured request ids, metrics for error/latency/queue, sanitized logs; never log submitted source content, complete answers, prompt bodies or OAuth tokens by default. Provide audit records of deletion and grade overrides.

**Supply chain:** dependency lockfiles, container base image pinning, vulnerability scans, CI tests, backup/restore tests, no secrets in build args, non-root containers, migrations with rollback plan.

## Backups

- Daily encrypted PostgreSQL logical backup plus source-file backup, both copied **off VPS** to owner-approved destination; periodic restore drill to disposable environment.
- Document retention (e.g. 7 daily / 4 weekly / 3 monthly backups) is a proposal, not an owner-approved storage policy.
- Never keep only backups on the same 38 GB root disk. Never include OAuth tokens unless explicitly planned in a secure user-controlled recovery method.

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
