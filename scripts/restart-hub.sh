#!/usr/bin/env bash
# Restart Hub with latest code.
#
# Usage:
#   ./scripts/restart-hub.sh [--model MODEL] [--autopilot] [--cwd DIR]
#                            [--timeout N] [--skip-pull] [-v]
#
# Settings are loaded from .env (COPILOT_MODEL, COPILOT_AUTOPILOT).
# CLI args override .env values.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- Defaults (overridden by .env, then by CLI args) ----------------------
MODEL=""
AUTOPILOT=""
CWD_OPT=""
TIMEOUT=60
SKIP_PULL=false
VERBOSE=""

# --- Parse CLI args -------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)      MODEL="$2";               shift 2 ;;
        --autopilot)  AUTOPILOT="--autopilot";   shift ;;
        --cwd)        CWD_OPT="--cwd $2";       shift 2 ;;
        --timeout)    TIMEOUT="$2";              shift 2 ;;
        --skip-pull)  SKIP_PULL=true;            shift ;;
        -v|--verbose) VERBOSE="--verbose";       shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# --- Load .env ------------------------------------------------------------
ENV_FILE="$REPO_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
    echo "[INFO] Loading .env ..."
    set -o allexport
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +o allexport
else
    echo "[WARN] .env not found: $ENV_FILE" >&2
fi

# --- Validate required vars -----------------------------------------------
# Hub falls back to TELEGRAM_BOT_TOKEN if HUB token is not set
BOT_TOKEN="${TELEGRAM_HUB_BOT_TOKEN:-${TELEGRAM_BOT_TOKEN:-}}"
CHAT_ID="${TELEGRAM_CHAT_ID:-}"
if [[ -z "$BOT_TOKEN" || -z "$CHAT_ID" ]]; then
    echo "[ERROR] Required: TELEGRAM_BOT_TOKEN (or TELEGRAM_HUB_BOT_TOKEN) + TELEGRAM_CHAT_ID" >&2
    exit 1
fi

# --- Resolve model/autopilot from .env or CLI args ------------------------
if [[ -z "$MODEL" ]]; then
    MODEL="${COPILOT_MODEL:-claude-opus-4.6}"
fi
if [[ -z "$AUTOPILOT" ]]; then
    case "${COPILOT_AUTOPILOT:-}" in
        true|1|yes) AUTOPILOT="--autopilot" ;;
    esac
fi

echo ""
echo "=== Hub Restart ==="
echo "  Model    : $MODEL"
echo "  Autopilot: ${AUTOPILOT:-(off)}"
echo "  Timeout  : ${TIMEOUT} min"
echo ""

# --- [1/4] git pull -------------------------------------------------------
if [[ "$SKIP_PULL" = false ]]; then
    echo "[1/4] git pull --ff-only ..."
    cd "$REPO_ROOT"
    git pull --ff-only
else
    echo "[1/4] git pull ... SKIPPED"
fi

# --- [2/4] pip install ----------------------------------------------------
echo "[2/4] pip install -e . ..."
cd "$REPO_ROOT"
python -m pip install -e . --quiet

# --- [3/4] Stop existing Hub (singleton lock release) ---------------------
echo "[3/4] Stopping existing Hub ..."
LOCK_PORT="${HUB_LOCK_PORT:-47732}"

# Find process listening on lock port
LOCK_PID=$(ss -tlnp "sport = :$LOCK_PORT" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1 || true)
if [[ -n "$LOCK_PID" ]]; then
    echo "  Stopping Hub PID $LOCK_PID (lock port $LOCK_PORT)"
    kill "$LOCK_PID" 2>/dev/null || true
    sleep 2
else
    # Fallback: find by command line
    PIDS=$(pgrep -f "telegram_copilot_bridge.*--hub" 2>/dev/null || true)
    if [[ -n "$PIDS" ]]; then
        echo "  Stopping PIDs: $PIDS"
        kill $PIDS 2>/dev/null || true
        sleep 2
    else
        echo "  No running Hub found"
    fi
fi

# --- [4/4] Start Hub ------------------------------------------------------
echo "[4/4] Starting Hub ..."
CMD="python -m telegram_copilot_bridge --hub --model $MODEL --timeout $TIMEOUT $AUTOPILOT $CWD_OPT $VERBOSE"
echo "  $CMD"
echo ""
cd "$REPO_ROOT"
exec $CMD
