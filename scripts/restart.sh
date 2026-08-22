#!/usr/bin/env bash
# Restarts the production stack: llama-server, the FastAPI hub, and Tailscale Funnel.
# Does not stop tailscaled. Funnel is re-applied so https://<node>.<tailnet>.ts.net
# keeps proxying to the hub on port 9000.
#
# Usage:
#   bash scripts/restart.sh            # llama-server + hub + funnel
#   bash scripts/restart.sh --hub-only # hub + funnel (skip the slow model reload)
#
# Optional: put HUB_ADMIN_TOKEN in a gitignored .env in the repo root, or export
# it in the shell. If neither is set, the script tries to reuse the token from
# the currently running hub process.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HUB_PORT="${HUB_PORT:-9000}"
LLM_PORT="${LLM_PORT:-8081}"
LOG_DIR="${HUB_TMP_DIR:-/tmp/llm-api-hub}"
HUB_ONLY=0

for arg in "$@"; do
    case "$arg" in
        --hub-only) HUB_ONLY=1 ;;
        -h|--help)
            sed -n '2,14p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg (try --hub-only)" >&2
            exit 1
            ;;
    esac
done

mkdir -p "$LOG_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.env"
    set +a
    echo "Loaded $ROOT_DIR/.env"
fi

if [[ -f "$ROOT_DIR/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.venv/bin/activate"
fi

pids_on_port() {
    local port="$1"
    local pids=""
    if command -v lsof >/dev/null 2>&1; then
        pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    fi
    if [[ -z "$pids" ]] && command -v fuser >/dev/null 2>&1; then
        pids="$(fuser "${port}/tcp" 2>/dev/null || true)"
    fi
    if [[ -z "$pids" ]] && command -v ss >/dev/null 2>&1; then
        pids="$(ss -lptn "sport = :${port}" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | sort -u)"
    fi
    # trim whitespace
    echo "$pids" | xargs echo
}

salvage_admin_token() {
    [[ -n "${HUB_ADMIN_TOKEN:-}" ]] && return 0
    local pids
    pids="$(pids_on_port "$HUB_PORT")"
    [[ -z "$pids" ]] && return 0
    local pid
    for pid in $pids; do
        if [[ -r "/proc/${pid}/environ" ]]; then
            local token
            token="$(tr '\0' '\n' < "/proc/${pid}/environ" | sed -n 's/^HUB_ADMIN_TOKEN=//p' | head -n 1)"
            if [[ -n "$token" ]]; then
                export HUB_ADMIN_TOKEN="$token"
                echo "Reusing HUB_ADMIN_TOKEN from running hub (pid ${pid})"
                return 0
            fi
        fi
    done
}

stop_port() {
    local port="$1"
    local name="$2"
    local pids
    pids="$(pids_on_port "$port")"
    if [[ -z "$pids" ]]; then
        echo "${name}: nothing listening on :${port}"
        return 0
    fi
    echo "${name}: stopping pid ${pids} on :${port}"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    local i
    for i in $(seq 1 20); do
        sleep 0.25
        pids="$(pids_on_port "$port")"
        [[ -z "$pids" ]] && echo "${name}: stopped" && return 0
    done
    echo "${name}: still up, sending SIGKILL"
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
    sleep 0.5
}

wait_http() {
    local url="$1"
    local name="$2"
    local seconds="${3:-60}"
    local i
    for i in $(seq 1 "$seconds"); do
        if curl -sf --max-time 2 "$url" >/dev/null 2>&1; then
            echo "${name}: ready (${url})"
            return 0
        fi
        sleep 1
    done
    echo "${name}: did not become ready at ${url} after ${seconds}s" >&2
    return 1
}

start_background() {
    local name="$1"
    local logfile="$2"
    local pidfile="$3"
    shift 3
    nohup "$@" >>"$logfile" 2>&1 &
    echo $! >"$pidfile"
    echo "${name}: started pid $(cat "$pidfile") (logs: ${logfile})"
}

apply_funnel() {
    if ! command -v tailscale >/dev/null 2>&1; then
        echo "WARNING: tailscale not on PATH — skipped Funnel. Hub is only on :${HUB_PORT}." >&2
        return 0
    fi
    if ! tailscale status >/dev/null 2>&1; then
        echo "WARNING: Tailscale is not up. Run 'tailscale up' then: tailscale funnel --bg ${HUB_PORT}" >&2
        return 0
    fi

    echo "Re-applying Tailscale Funnel -> http://127.0.0.1:${HUB_PORT}"
    # --bg persists across logout/reboot; --yes skips the ACL/cert prompt if already enabled.
    if ! tailscale funnel --bg --yes "$HUB_PORT"; then
        echo "WARNING: 'tailscale funnel --bg ${HUB_PORT}' failed. Current Funnel status:" >&2
        tailscale funnel status || true
        return 0
    fi
    echo "----- Tailscale Funnel -----"
    tailscale funnel status || true
    echo "----------------------------"
}

salvage_admin_token

echo "== Stopping =="
stop_port "$HUB_PORT" "hub"
if [[ "$HUB_ONLY" -eq 0 ]]; then
    stop_port "$LLM_PORT" "llama-server"
fi

echo "== Starting =="
if [[ "$HUB_ONLY" -eq 0 ]]; then
    start_background "llama-server" "$LOG_DIR/llm.log" "$LOG_DIR/llm.pid" \
        bash "$ROOT_DIR/scripts/start_llm.sh"
fi

if [[ -z "${HUB_ADMIN_TOKEN:-}" ]]; then
    echo "WARNING: HUB_ADMIN_TOKEN is not set. /v1 keys in hub.db still work; /admin will return 503."
    echo "         export HUB_ADMIN_TOKEN=... or put it in ${ROOT_DIR}/.env and re-run."
fi

start_background "hub" "$LOG_DIR/hub.log" "$LOG_DIR/hub.pid" \
    bash "$ROOT_DIR/scripts/start_hub.sh"

echo "== Waiting =="
if ! wait_http "http://127.0.0.1:${HUB_PORT}/health" "hub" 30; then
    echo "----- hub.log (last 40 lines) -----"
    tail -n 40 "$LOG_DIR/hub.log" || true
    exit 1
fi

if [[ "$HUB_ONLY" -eq 0 ]]; then
    if ! wait_http "http://127.0.0.1:${LLM_PORT}/health" "llama-server" 90; then
        echo "----- llm.log (last 40 lines) -----"
        tail -n 40 "$LOG_DIR/llm.log" || true
        echo "Hub is up but llama-server is not. Text generation will fail until it is."
    fi
fi

echo "== Public URL =="
apply_funnel

echo "Done. Local health: http://127.0.0.1:${HUB_PORT}/health"
curl -sS "http://127.0.0.1:${HUB_PORT}/health" || true
echo
