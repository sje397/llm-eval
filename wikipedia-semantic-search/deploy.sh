#!/bin/bash
# Deploy the wikipedia semantic-search service to the live Mímir host.
#
# Copies this repo's service.py (the source of truth) over the live
# /Users/sje/wikipedia/service.py, backs up the previous file, and restarts
# the launchd daemon so the running process picks up the new code.
#
# MUST run on Mímir (the deployment host). Options:
#   ./deploy.sh            deploy + restart + smoke-test
#   ./deploy.sh --dry-run  show what would happen, touch nothing
#   ./deploy.sh --skip-smoke   deploy + restart, skip the post checks
#
# Restart method: com.lex.wikipedia-service is a system LaunchDaemon
# (KeepAlive=true). `launchctl kickstart -k system/com.lex.wikipedia-service`
# works if run with sufficient privilege (root); as the non-root `sje` user we
# fall back to killing the processes launchd is supervising — KeepAlive
# respawns them immediately with the new file.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_SERVICE="$REPO_DIR/service.py"

LIVE_DIR="${WIKI_LIVE_DIR:-/Users/sje/wikipedia}"
LIVE_SERVICE="$LIVE_DIR/service.py"
SERVICE_LABEL="com.lex.wikipedia-service"
BASE_URL="${WIKI_SERVICE_URL:-http://127.0.0.1:21500}"

DRY_RUN=0
SKIP_SMOKE=0
for arg in "$@"; do
  case "$arg" in
    --dry-run)    DRY_RUN=1 ;;
    --skip-smoke) SKIP_SMOKE=1 ;;
  esac
done

log() { echo "==> $*"; }
warn() { echo "!!! $*" >&2; }

# --- sanity checks ---------------------------------------------------------
[[ -f "$SRC_SERVICE" ]] || { warn "missing $SRC_SERVICE"; exit 1; }
[[ "$(uname -s)" == "Darwin" ]] || { warn "this script deploys to Mímir; run it on Mímir"; exit 1; }
[[ -d "$LIVE_DIR" ]] || { warn "live dir $LIVE_DIR not found on this host"; exit 1; }

# --- back up the currently-running file -----------------------------------
BACKUP="$LIVE_DIR/service.py.bak-$(date +%Y%m%d-%H%M%S)"
[ "$DRY_RUN" -eq 1 ] || cp -p "$LIVE_SERVICE" "$BACKUP"
log "backup: $LIVE_SERVICE -> $BACKUP"

# --- install the new file -------------------------------------------------
log "install: $SRC_SERVICE -> $LIVE_SERVICE"
if [ "$DRY_RUN" -eq 0 ]; then
  cp -p "$SRC_SERVICE" "$LIVE_SERVICE"
  if ! cmp -s "$SRC_SERVICE" "$LIVE_SERVICE"; then
    warn "copy did not match source; aborting (service left as-is)"
    exit 1
  fi
  log "verified: live service.py == repo service.py"
fi

# --- restart the daemon ---------------------------------------------------
restart_daemon() {
  log "restart: $SERVICE_LABEL"
  # Prefer launchctl kickstart (root/system domain); fall back to kill+KeepAlive.
  if launchctl kickstart -k "system/$SERVICE_LABEL" 2>/dev/null; then
    log "restarted via launchctl kickstart"
    return 0
  fi
  # Non-root fallback: terminate the supervised processes; KeepAlive respawns them.
  PIDS=$(pgrep -f "wikipedia/service.py" || true)
  if [ -z "$PIDS" ]; then
    warn "no running wikipedia service process found; relying on RunAtLoad"
    return 0
  fi
  log "killing supervised pids: $PIDS (KeepAlive will respawn)"
  for p in $PIDS; do kill -9 "$p" 2>/dev/null || true; done
}

if [ "$DRY_RUN" -eq 1 ]; then
  log "dry-run complete (no changes made)"
  exit 0
fi

restart_daemon

# --- wait for launchd to bring the service back ---------------------------
log "waiting for $SERVICE_LABEL to come back..."
for i in $(seq 1 15); do
  if pgrep -f "wikipedia/service.py" >/dev/null 2>&1; then
    log "service running (pid $(pgrep -f 'wikipedia/service.py' | head -1))"
    break
  fi
  sleep 1
done

# --- smoke test -------------------------------------------------------------
if [ "$SKIP_SMOKE" -eq 1 ]; then
  log "smoke test skipped"
  exit 0
fi

log "smoke: GET /health"
H=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health")
echo "health HTTP $H"; [ "$H" = "200" ] || { warn "health check failed"; exit 1; }

log "smoke: /search 'The Great Leap Forward' (text) -> expect exact Great Leap Forward"
curl -s -X POST "$BASE_URL/search" -H 'Content-Type: application/json' \
  -d '{"query":"The Great Leap Forward","lang":"en","mode":"text"}' \
  | python3 -c 'import sys,json; r=json.load(sys.stdin)["results"]; t=r[0]; print("  top:", t["title"], "exact=", t.get("exact"), "score=", t.get("score"))'

log "smoke: /extract Great_Leap_Forward (underscore form) -> expect resolved"
curl -s -X POST "$BASE_URL/extract" -H 'Content-Type: application/json' \
  -d '{"titles":["Great_Leap_Forward"],"lang":"en"}' \
  | python3 -c 'import sys,json; a=json.load(sys.stdin)["articles"]; print("  ", a[0].get("title"), "chars=", len(a[0].get("extract","")))'

log "deploy complete"
