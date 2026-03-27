#!/usr/bin/env bash
# scripts/run-panel.sh — activate venv and start the daran-proxy-stack web panel
#
# Usage:
#   bash scripts/run-panel.sh
#
# Environment variables (all optional):
#   DARAN_VENV_DIR   — path to the virtual environment (default: <repo-root>/.venv)
#   DARAN_PANEL_HOST — bind address (default: 127.0.0.1)
#   DARAN_PANEL_PORT — bind port    (default: 7331)
#   DARAN_RELOAD     — set to "1" to enable uvicorn --reload (dev mode)
#
# The script resolves the repo root as the directory containing this file's
# parent, so it works from any working directory.

set -euo pipefail

# ── resolve paths ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

VENV_DIR="${DARAN_VENV_DIR:-${REPO_ROOT}/.venv}"
HOST="${DARAN_PANEL_HOST:-127.0.0.1}"
PORT="${DARAN_PANEL_PORT:-7331}"
RELOAD="${DARAN_RELOAD:-0}"

# ── sanity checks ─────────────────────────────────────────────────────────────
[[ -f "${VENV_DIR}/bin/activate" ]] || {
    echo "ERROR: virtual environment not found at ${VENV_DIR}" >&2
    echo "       Run  bash scripts/bootstrap.sh  first." >&2
    exit 1
}

# ── activate ─────────────────────────────────────────────────────────────────
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

# ── build uvicorn args ────────────────────────────────────────────────────────
UVICORN_ARGS=(
    "daran_proxy_stack.web.app:app"
    "--host" "$HOST"
    "--port" "$PORT"
)
[[ "$RELOAD" == "1" ]] && UVICORN_ARGS+=("--reload")

# ── launch ────────────────────────────────────────────────────────────────────
echo "[run-panel] Starting daran-proxy-stack panel"
echo "[run-panel]   URL  : http://${HOST}:${PORT}"
echo "[run-panel]   Docs : http://${HOST}:${PORT}/api/docs"
[[ "$RELOAD" == "1" ]] && echo "[run-panel]   Mode : development (--reload)"
echo

exec uvicorn "${UVICORN_ARGS[@]}"
