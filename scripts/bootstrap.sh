#!/usr/bin/env bash
# scripts/bootstrap.sh — idempotent bootstrap for daran-proxy-stack
#
# Usage:
#   bash scripts/bootstrap.sh [REPO_URL] [TARGET_DIR]
#
# Defaults:
#   REPO_URL   — skipped if already inside the repo checkout
#   TARGET_DIR — current directory if it looks like the repo, else ~/daran-proxy-stack
#
# What it does:
#   1. Clone or git-pull the repository
#   2. Create / reuse a Python ≥3.12 virtual environment in .venv/
#   3. Install the package with dev extras (pip install -e ".[dev]")
#   4. Run smoke tests (pytest)
#   5. Print how to start the panel
#
# Environment variables (all optional):
#   DARAN_REPO_URL   — override repo URL
#   DARAN_TARGET_DIR — override target directory
#   DARAN_VENV_DIR   — venv path relative to target (default: .venv)
#   DARAN_PANEL_HOST — panel bind host printed in the final hint (default: 127.0.0.1)
#   DARAN_PANEL_PORT — panel bind port printed in the final hint (default: 7331)

set -euo pipefail

# ── colour helpers ──────────────────────────────────────────────────────────
_bold="\033[1m"; _reset="\033[0m"
_green="\033[32m"; _yellow="\033[33m"; _red="\033[31m"; _cyan="\033[36m"
info()    { echo -e "${_bold}${_cyan}[bootstrap]${_reset} $*"; }
success() { echo -e "${_bold}${_green}[bootstrap]${_reset} $*"; }
warn()    { echo -e "${_bold}${_yellow}[bootstrap]${_reset} $*"; }
die()     { echo -e "${_bold}${_red}[bootstrap] ERROR:${_reset} $*" >&2; exit 1; }

# ── configuration ───────────────────────────────────────────────────────────
REPO_URL="${DARAN_REPO_URL:-${1:-}}"
PANEL_HOST="${DARAN_PANEL_HOST:-127.0.0.1}"
PANEL_PORT="${DARAN_PANEL_PORT:-7331}"
VENV_SUBDIR="${DARAN_VENV_DIR:-.venv}"

# Detect if we're already inside the repo
_detect_repo_root() {
    local dir="${1:-$(pwd)}"
    if [[ -f "$dir/pyproject.toml" ]] && grep -q 'name.*daran-proxy-stack' "$dir/pyproject.toml" 2>/dev/null; then
        echo "$dir"
        return 0
    fi
    return 1
}

# ── 1. Locate / clone the repository ────────────────────────────────────────
if _detect_repo_root "$(pwd)" &>/dev/null; then
    TARGET_DIR="$(pwd)"
    info "Already inside repo at ${TARGET_DIR}"
elif [[ -n "${DARAN_TARGET_DIR:-}" ]]; then
    TARGET_DIR="$DARAN_TARGET_DIR"
elif [[ -n "${2:-}" ]]; then
    TARGET_DIR="$2"
else
    TARGET_DIR="${HOME}/daran-proxy-stack"
fi

if [[ -d "$TARGET_DIR/.git" ]]; then
    if _detect_repo_root "$TARGET_DIR" &>/dev/null; then
        info "Repo found at ${TARGET_DIR} — pulling latest changes"
        git -C "$TARGET_DIR" pull --ff-only || warn "git pull failed (skipping — you may have local changes)"
    else
        die "Directory ${TARGET_DIR} is a git repo but doesn't look like daran-proxy-stack"
    fi
else
    [[ -n "$REPO_URL" ]] || die "No repo URL provided. Pass it as the first argument or set DARAN_REPO_URL."
    info "Cloning ${REPO_URL} → ${TARGET_DIR}"
    git clone "$REPO_URL" "$TARGET_DIR"
fi

cd "$TARGET_DIR"
info "Working directory: $(pwd)"

# ── 2. Resolve Python ≥ 3.12 ────────────────────────────────────────────────
_find_python() {
    for py in python3.12 python3.13 python3.14 python3; do
        if command -v "$py" &>/dev/null; then
            local ver
            ver="$("$py" -c 'import sys; print(sys.version_info[:2])')"
            # ver is a tuple string like (3, 12)
            local major minor
            major="$("$py" -c 'import sys; print(sys.version_info.major)')"
            minor="$("$py" -c 'import sys; print(sys.version_info.minor)')"
            if (( major >= 3 && minor >= 12 )); then
                echo "$py"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON="$(\_find_python)" || die "Python ≥ 3.12 not found. Install it and re-run."
info "Using Python: ${PYTHON} ($(${PYTHON} --version))"

# ── 3. Create / reuse virtual environment ───────────────────────────────────
VENV_DIR="${TARGET_DIR}/${VENV_SUBDIR}"

if [[ -f "${VENV_DIR}/bin/activate" ]]; then
    info "Virtual environment already exists at ${VENV_DIR}"
else
    info "Creating virtual environment at ${VENV_DIR}"
    "$PYTHON" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
success "Activated venv: $(python --version)"

# ── 4. Install / upgrade the package ────────────────────────────────────────
info "Upgrading pip + build tools"
pip install --quiet --upgrade pip setuptools wheel

info "Installing daran-proxy-stack[dev] (editable)"
pip install --quiet -e ".[dev]"

success "Package installed: $(pip show daran-proxy-stack | grep '^Version:')"

# ── 5. Smoke tests ──────────────────────────────────────────────────────────
info "Running smoke tests"
if pytest --tb=short -q; then
    success "All smoke tests passed"
else
    warn "Some tests failed — check output above. The panel may still work."
fi

# ── 6. Done — print startup hint ────────────────────────────────────────────
echo
echo -e "${_bold}${_green}Bootstrap complete.${_reset}"
echo
echo -e "  ${_bold}Start the panel (development):${_reset}"
echo -e "    source ${VENV_DIR}/bin/activate"
echo -e "    daran-net panel --host ${PANEL_HOST} --port ${PANEL_PORT}"
echo
echo -e "  ${_bold}Or use the run script:${_reset}"
echo -e "    DARAN_PANEL_HOST=${PANEL_HOST} DARAN_PANEL_PORT=${PANEL_PORT} bash scripts/run-panel.sh"
echo
echo -e "  ${_bold}Panel URL:${_reset}  http://${PANEL_HOST}:${PANEL_PORT}"
echo -e "  ${_bold}API docs:${_reset}   http://${PANEL_HOST}:${PANEL_PORT}/api/docs"
echo
