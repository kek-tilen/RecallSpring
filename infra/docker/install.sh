#!/bin/sh
# RecallSpring with Docker, in one command (docs/install-docker.md). Linux, macOS, or Windows with Docker:
#
#   curl -fsSL https://github.com/kek-tilen/RecallSpring/releases/latest/download/install.sh | sh
#   curl -fsSL https://github.com/kek-tilen/RecallSpring/releases/latest/download/install.sh | sh -s -- --dir ~/RecallSpring --full
#
# Prefer to read it first? Download install.sh from a release on GitHub, read it, then run `sh install.sh`.
#
# What it does: checks Docker, disk space and ports; says what it will do and asks; downloads the release's
# compose.yml, images.env and `recallspring` command and checks them against the hashes of that release; writes them
# with a random database password into one folder; starts RecallSpring; prints a one-time link for your account.
# It changes nothing outside that folder (and the sync folder you name) and Docker's "recallspring" project. It never
# installs Docker, never uses sudo, and every port is on 127.0.0.1 only.
set -eu

RS_REPO="kek-tilen/RecallSpring"
# Filled in when a release is built (scripts in the repository have the placeholders and check SHA256SUMS instead).
RS_RELEASE="@RS_VERSION@"
RS_SUMS_SHA256="@SUMS_SHA256@"

usage() {
  cat <<'EOF'
Usage: install.sh [options]

  --dir DIR           where RecallSpring keeps its settings and backups (default: ~/RecallSpring)
  --port N            the web app's port on 127.0.0.1 (default 4318)
  --mcp-port N        the connector's port for Codex and Antigravity (default 4319)
  --backups DIR       where nightly backups go (default: DIR/backups); another disk is safer
  --sync-folder DIR   a folder a sync app uploads (iCloud Drive, Nextcloud, ...): encrypted backups and learners'
                      copies go into DIR/RecallSpring once encryption is on
  --full              the larger image with LibreOffice (shows whole Word and PowerPoint pages)
  --version vX.Y.Z    this release instead of the newest
  --beta              the newest release including pre-releases
  --project NAME      Docker's project name (default: recallspring)
  --yes               do not ask before installing
  --from DIR          use compose.yml, images.env and recallspring from DIR (testing; not checked)
  --image IMAGE       use this image instead of the release's (testing)
  -h, --help          this help
EOF
}

say() { printf '%s\n' "$*"; }
ok() { printf '  \342\234\223 %s\n' "$*"; }
fail() {
  printf '\nRecallSpring was not installed: %s\n' "$*" >&2
  exit 1
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | cut -d' ' -f1
  else
    fail "neither sha256sum nor shasum is available to check the downloads"
  fi
}

fetch() { # url file
  curl -fsSL --proto '=https' --tlsv1.2 --retry 2 -o "$2" "$1" || fail "could not download $1"
}

value_of() { # KEY file -> value of KEY=value (no shell evaluation)
  sed -n "s/^$1=//p" "$2" | head -n 1
}

port_free() { # a port is free when nothing answers there (curl exit 7: connection refused; Windows takes ~2 s)
  rc=0
  curl -s -o /dev/null --max-time 5 "http://127.0.0.1:$1/" || rc=$?
  [ "$rc" -eq 7 ]
}

ask() { # question -> 0 for yes
  [ "$YES" = 1 ] && return 0
  if ! { exec 3</dev/tty; } 2>/dev/null; then
    fail "no terminal to ask in. Run again with --yes to install without asking."
  fi
  printf '%s [y/N] ' "$1"
  read -r answer <&3 || answer=""
  exec 3<&-
  case "$answer" in y | Y | yes | YES | Yes) return 0 ;; *) return 1 ;; esac
}

time_zone() {
  if [ -n "${TZ:-}" ]; then
    printf '%s' "$TZ"
  elif [ -r /etc/timezone ]; then
    head -n 1 /etc/timezone
  elif [ -L /etc/localtime ]; then
    readlink /etc/localtime | sed 's|.*/zoneinfo/||'
  else
    printf 'UTC'
  fi
}

latest_release() {
  if [ "$BETA" = 1 ]; then
    url="https://api.github.com/repos/$RS_REPO/releases?per_page=1"
  else
    url="https://api.github.com/repos/$RS_REPO/releases/latest"
  fi
  tag=$(curl -fsSL --proto '=https' --tlsv1.2 "$url" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1) ||
    fail "could not ask GitHub for the newest release"
  [ -n "$tag" ] || fail "no release of RecallSpring was found"
  printf '%s' "$tag"
}

get_release_files() { # into $WORK
  if [ -n "$FROM" ]; then
    for f in compose.yml images.env recallspring; do
      [ -f "$FROM/$f" ] || fail "$FROM/$f is missing"
      cp "$FROM/$f" "$WORK/$f"
    done
    say "  ! files from $FROM, not checked against a release"
    return
  fi
  base="https://github.com/$RS_REPO/releases/download/$VERSION"
  fetch "$base/SHA256SUMS" "$WORK/SHA256SUMS"
  case "$RS_SUMS_SHA256" in
    @*@) ;; # a copy from the repository: SHA256SUMS is checked against GitHub's own copy only
    *)
      [ "$(sha256_of "$WORK/SHA256SUMS")" = "$RS_SUMS_SHA256" ] ||
        fail "the release's SHA256SUMS does not match this install script; nothing was changed"
      ;;
  esac
  for f in compose.yml images.env recallspring; do
    fetch "$base/$f" "$WORK/$f"
    want=$(awk -v f="$f" '$2 == f || $2 == "*" f { print $1 }' "$WORK/SHA256SUMS")
    [ -n "$want" ] && [ "$(sha256_of "$WORK/$f")" = "$want" ] ||
      fail "$f does not match the release's SHA256SUMS; nothing was changed"
  done
  ok "compose.yml, images.env and recallspring match release $VERSION (SHA-256 checked)"
}

main() {
  DIR="${HOME:?}/RecallSpring"
  PORT=4318
  MCP_PORT=4319
  BACKUPS=""
  SYNC=""
  FULL=0
  VERSION=""
  BETA=0
  PROJECT=recallspring
  YES=0
  FROM=""
  IMAGE=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --dir) DIR="${2:?--dir needs a folder}"; shift 2 ;;
      --port) PORT="${2:?--port needs a number}"; shift 2 ;;
      --mcp-port) MCP_PORT="${2:?--mcp-port needs a number}"; shift 2 ;;
      --backups) BACKUPS="${2:?--backups needs a folder}"; shift 2 ;;
      --sync-folder) SYNC="${2:?--sync-folder needs a folder}"; shift 2 ;;
      --full) FULL=1; shift ;;
      --version) VERSION="${2:?--version needs a release, e.g. v0.1.0}"; shift 2 ;;
      --beta) BETA=1; shift ;;
      --project) PROJECT="${2:?--project needs a name}"; shift 2 ;;
      --yes | -y) YES=1; shift ;;
      --from) FROM="${2:?--from needs a folder}"; shift 2 ;;
      --image) IMAGE="${2:?--image needs an image}"; shift 2 ;;
      -h | --help) usage; exit 0 ;;
      *) usage >&2; fail "unknown option $1" ;;
    esac
  done
  case "$PORT$MCP_PORT" in *[!0-9]*) fail "ports are numbers" ;; esac
  case "$PROJECT" in *[!a-z0-9_-]* | "") fail "--project may use a-z, 0-9, - and _ only" ;; esac
  for p in "$DIR" "$BACKUPS" "$SYNC"; do
    case "$p" in *'"'* | *'$'* | *'`'* | *'\'*) fail "folder names with \" \$ \` or \\ are not supported: $p" ;; esac
  done
  case "$DIR" in /* | [A-Za-z]:/*) ;; *) DIR="$(pwd)/$DIR" ;; esac
  if command -v cygpath >/dev/null 2>&1; then # Git Bash on Windows: Docker needs C:/... paths in .env
    DIR=$(cygpath -m "$DIR")
    [ -z "$BACKUPS" ] || BACKUPS=$(cygpath -m "$BACKUPS")
    [ -z "$SYNC" ] || SYNC=$(cygpath -m "$SYNC")
  fi
  [ -n "$BACKUPS" ] || BACKUPS="$DIR/backups"
  if [ -z "$VERSION" ] && [ -z "$FROM" ]; then
    case "$RS_RELEASE" in @*@) VERSION=$(latest_release) ;; *) VERSION="$RS_RELEASE" ;; esac
  fi

  say ""
  say "RecallSpring ${VERSION:-from $FROM} · install with Docker"

  # ---------------------------------------------------------------- checks (nothing changes yet)
  command -v curl >/dev/null 2>&1 || fail "curl is needed"
  command -v docker >/dev/null 2>&1 ||
    fail "Docker is needed. Install Docker Desktop (Windows, macOS) or Docker Engine (Linux), start it, then run this again."
  docker info >/dev/null 2>&1 ||
    fail "Docker is installed but not running (or this user may not use it). Start Docker, then run this again."
  docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is needed (the \"docker compose\" command)."
  [ "$(id -u)" != 0 ] || fail "run this as your normal user, not as root or with sudo."
  arch=$(docker info --format '{{.OSType}}/{{.Architecture}}' 2>/dev/null || echo unknown)
  ok "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?') is running ($arch)"

  [ ! -e "$DIR/.env" ] || fail "RecallSpring is installed in $DIR already. Update it with: $DIR/recallspring update"
  if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]; then
    fail "Docker already has a project called \"$PROJECT\". Choose another with --project."
  fi
  parent="$DIR"
  while [ ! -d "$parent" ]; do parent=$(dirname "$parent"); done
  free_kb=$(df -Pk "$parent" | awk 'NR == 2 { print $4 }')
  [ "${free_kb:-0}" -ge 4194304 ] || fail "about 4 GB of free disk space is needed in $parent."
  ok "$((free_kb / 1048576)) GB free in $parent · 4 GB is enough to begin"
  mem=$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)
  [ "${mem:-0}" -ge 1900000000 ] || fail "Docker has less than 2 GB of memory. Give it more (Docker Desktop: Settings > Resources)."
  port_free "$PORT" || fail "port $PORT on this computer is in use. Choose another with --port."
  port_free "$MCP_PORT" || fail "port $MCP_PORT on this computer is in use. Choose another with --mcp-port."
  ok "Ports $PORT and $MCP_PORT are free on this computer"
  if [ -n "$SYNC" ]; then
    [ -d "$SYNC" ] || fail "the sync folder $SYNC is not there. Is the sync app running and signed in?"
  fi

  say ""
  say "This will:"
  say "  · make the folder $DIR (settings, the \`recallspring\` command, backups)"
  [ "$BACKUPS" = "$DIR/backups" ] || say "  · put backups in $BACKUPS"
  [ -z "$SYNC" ] || say "  · make $SYNC/RecallSpring for encrypted backups and learners' copies"
  if [ "$FULL" = 1 ]; then
    say "  · download RecallSpring with LibreOffice and PostgreSQL 16, about 1 GB"
  else
    say "  · download RecallSpring and PostgreSQL 16, about 500 MB"
  fi
  say "  · start them, reachable from this computer only (127.0.0.1)"
  say "Nothing outside that folder and Docker's \"$PROJECT\" project is changed."
  say ""
  ask "Continue?" || fail "you chose not to continue. Nothing was changed."
  say ""

  # ---------------------------------------------------------------- files
  WORK=$(mktemp -d 2>/dev/null || mktemp -d -t recallspring)
  trap 'rm -rf "$WORK"' EXIT
  get_release_files
  release_version=$(value_of RS_VERSION "$WORK/images.env")
  if [ -n "$IMAGE" ]; then
    image="$IMAGE"
  elif [ "$FULL" = 1 ]; then
    image=$(value_of RS_IMAGE_FULL "$WORK/images.env")
  else
    image=$(value_of RS_IMAGE_BASE "$WORK/images.env")
  fi
  [ -n "$image" ] || fail "images.env names no image"

  umask 077
  mkdir -p "$DIR/data/storage" "$DIR/data/run" "$DIR/data/secrets" "$DIR/data/home" "$BACKUPS" ||
    fail "could not make $DIR"
  cp "$WORK/compose.yml" "$WORK/images.env" "$DIR/"
  cp "$WORK/recallspring" "$DIR/recallspring"
  chmod 700 "$DIR/recallspring"
  password=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
  [ ${#password} -eq 48 ] || fail "could not make a random password"
  cat >"$DIR/.env" <<EOF
# RecallSpring with Docker (docs/install-docker.md). Made by install.sh; readable by you only. Keep it private.
COMPOSE_PROJECT_NAME=$PROJECT
RS_VERSION=${release_version:-unknown}
RS_IMAGE=$image
RS_FULL=$FULL
RS_DB_PASSWORD=$password
RS_UID=$(id -u)
RS_GID=$(id -g)
RS_PORT=$PORT
RS_MCP_PORT=$MCP_PORT
RS_TIMEZONE=$(time_zone)
RS_BACKUP_HOST_DIR=$BACKUPS
EOF
  if [ -n "$SYNC" ]; then
    mkdir -p "$SYNC/RecallSpring/Backups" "$SYNC/RecallSpring/Material" || fail "could not make $SYNC/RecallSpring"
    cat >"$DIR/compose.local.yml" <<EOF
# Made by install.sh for --sync-folder (docs/install-docker.md): encrypted backups go to Backups once encryption is on;
# each learner who chooses "Use a synced folder" gets a subfolder of Material.
services:
  api: &sync
    volumes:
      - "$SYNC/RecallSpring:/sync"
    environment:
      RS_CLOUD_FOLDER_DIR: /sync/Backups
      RS_DRIVE_FOLDER_DIR: /sync/Material
  worker: *sync
EOF
  fi
  ok "Settings made in $DIR: a random database password, never printed"

  # ---------------------------------------------------------------- start
  if [ -z "$IMAGE" ]; then
    "$DIR/recallspring" pull || fail "could not download the images. Check the internet connection and run this again."
    ok "Images pulled, each one by its fixed digest"
  fi
  "$DIR/recallspring" up || fail "RecallSpring did not start. See: $DIR/recallspring logs"
  i=0
  until curl -fs -o /dev/null --max-time 3 "http://127.0.0.1:$PORT/api/v1/health/ready"; do
    i=$((i + 1))
    [ "$i" -lt 90 ] || fail "RecallSpring did not become ready in 3 minutes. See: $DIR/recallspring logs"
    sleep 2
  done
  ok "RecallSpring is running"

  say ""
  "$DIR/recallspring" setup-link || say "Make the link for your account with: $DIR/recallspring setup-link"
  say ""
  say "Every day:  $DIR/recallspring status | update | logs | stop | start"
  say "Backups go to $BACKUPS every night. Keep a copy somewhere else too."
}

main "$@"
