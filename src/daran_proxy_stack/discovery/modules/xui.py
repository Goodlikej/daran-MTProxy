"""3x-ui observed-state detector.

Detects: binary presence, systemd unit, running process, web UI availability.

3x-ui is an Xray-based web panel. It is NOT a daran-proxy-stack native module —
it runs independently and is managed through its own systemd service or process.

Detection strategy (in priority order):
  1. systemd unit  «x-ui»  (most reliable)
  2. process name  «x-ui»  (process-only installs)
  3. binary at known paths (/usr/local/x-ui/x-ui, /usr/bin/x-ui)
  4. web UI probe on default port 2053  (confirms the panel is actually serving)

Per observed-state-model.md health rules:
  healthy:       installed + systemd/process running + web UI responds
  degraded:      running but web UI not responding, OR web UI up but service
                 not detected as active by systemd
  stopped:       installed but nothing running, web UI silent
  not_installed: no binary, no unit, no process
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from daran_proxy_stack.discovery.schema import (
    BaseModuleState,
    DiscoveryConfidence,
    ModuleHealth,
    ModuleManager,
    PortEntry,
    PortProtocol,
)
from daran_proxy_stack.lib.shell import run


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_XUI_DEFAULT_WEB_PORT = 2053
_XUI_KNOWN_BINARY_PATHS = [
    "/usr/local/x-ui/x-ui",
    "/usr/bin/x-ui",
]
_XUI_SYSTEMD_UNIT = "x-ui"


# ---------------------------------------------------------------------------
# Detection primitives
# ---------------------------------------------------------------------------

def _detect_xui_binary() -> str | None:
    """Return the first existing x-ui binary path, or None."""
    for p in _XUI_KNOWN_BINARY_PATHS:
        if Path(p).exists():
            return p
    which = shutil.which("x-ui")
    if which:
        return which
    return None


def _detect_xui_systemd() -> tuple[bool, bool]:
    """Return (unit_exists, is_active) for the x-ui systemd unit."""
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False, False
    r = run([systemctl, "status", _XUI_SYSTEMD_UNIT, "--no-pager"])
    if r.returncode == 4:  # unit not found
        return False, False
    unit_exists = r.returncode in (0, 3)   # 0=active, 3=inactive/dead
    is_active = r.returncode == 0
    return unit_exists, is_active


def _detect_xui_service_enabled() -> bool:
    """Return True if the x-ui systemd unit is enabled for auto-start."""
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False
    r = run([systemctl, "is-enabled", "--quiet", _XUI_SYSTEMD_UNIT])
    return r.returncode == 0


def _detect_xui_process() -> bool:
    """Return True if an x-ui process is currently running."""
    pgrep = shutil.which("pgrep")
    if pgrep:
        r = run([pgrep, "-f", "x-ui"])
        return r.ok and bool(r.stdout.strip())
    # fallback: pidof
    r = run(["pidof", "x-ui"])
    return r.ok and bool(r.stdout.strip())


def _probe_web_ui(port: int = _XUI_DEFAULT_WEB_PORT) -> bool:
    """Return True if something is listening on localhost:<port>."""
    r = run([
        "bash", "-c",
        f"timeout 1 bash -c 'echo >/dev/tcp/127.0.0.1/{port}' 2>/dev/null"
        " && echo ok || echo fail",
    ])
    return r.ok and "ok" in (r.stdout or "")


def _detect_xui_version(binary: str) -> str | None:
    """Attempt to read the 3x-ui version from the binary."""
    r = run([binary, "version"])
    if r.ok and r.stdout.strip():
        return r.stdout.strip().splitlines()[0]
    # fallback: check a version file that some installers write
    ver_file = Path("/usr/local/x-ui/bin/version")
    if ver_file.exists():
        try:
            return ver_file.read_text().strip()
        except OSError:
            pass
    return None


# ---------------------------------------------------------------------------
# XuiState
# ---------------------------------------------------------------------------

@dataclass
class XuiState(BaseModuleState):
    """Observed state for the 3x-ui panel."""
    binary_path: str | None = None
    web_ui_responding: bool = False
    web_ui_port: int = _XUI_DEFAULT_WEB_PORT

    def to_dict(self) -> dict:
        d = self._base_dict()
        d["binary_path"] = self.binary_path
        d["web_ui_responding"] = self.web_ui_responding
        d["web_ui_port"] = self.web_ui_port
        return d


# ---------------------------------------------------------------------------
# Public detector
# ---------------------------------------------------------------------------

def detect_xui() -> XuiState:
    """Detect 3x-ui installation and runtime state. Never raises."""
    now = datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []
    errors: list[str] = []
    confidence = DiscoveryConfidence.full
    confidence_reasons: list[str] = []

    binary = _detect_xui_binary()

    # ── systemd ───────────────────────────────────────────────────────────
    unit_exists = False
    is_active = False
    enabled = False
    try:
        unit_exists, is_active = _detect_xui_systemd()
        if unit_exists:
            enabled = _detect_xui_service_enabled()
    except Exception as exc:
        warnings.append(f"systemd probe failed: {exc}")
        confidence = DiscoveryConfidence.partial
        confidence_reasons.append("systemd probe error")

    # ── process ───────────────────────────────────────────────────────────
    process_running = False
    try:
        process_running = _detect_xui_process()
    except Exception as exc:
        warnings.append(f"process probe failed: {exc}")
        confidence = DiscoveryConfidence.partial
        confidence_reasons.append("process probe error")

    # ── installation check ────────────────────────────────────────────────
    installed = bool(binary or unit_exists)

    if not installed:
        return XuiState(
            installed=False,
            enabled=False,
            running=False,
            health=ModuleHealth.not_installed,
            version=None,
            manager=ModuleManager.none,
            binary_path=None,
            web_ui_responding=False,
            web_ui_port=_XUI_DEFAULT_WEB_PORT,
            confidence=DiscoveryConfidence.full,
            last_checked_at=now,
        )

    # ── version ───────────────────────────────────────────────────────────
    version: str | None = None
    if binary:
        try:
            version = _detect_xui_version(binary)
        except Exception:
            pass  # version is nice-to-have, not critical

    # ── web UI probe ──────────────────────────────────────────────────────
    web_ui_port = _XUI_DEFAULT_WEB_PORT
    web_up = False
    try:
        web_up = _probe_web_ui(web_ui_port)
    except Exception as exc:
        warnings.append(f"web UI probe failed: {exc}")
        confidence = DiscoveryConfidence.partial
        confidence_reasons.append("web UI probe error")

    running = is_active or process_running

    # ── manager ───────────────────────────────────────────────────────────
    if unit_exists:
        manager = ModuleManager.systemd
    elif process_running:
        manager = ModuleManager.process
    else:
        manager = ModuleManager.none

    # ── ports ─────────────────────────────────────────────────────────────
    ports: list[PortEntry] = []
    if web_up:
        ports.append(PortEntry(
            bind="127.0.0.1",
            port=web_ui_port,
            protocol=PortProtocol.tcp,
            purpose="web-ui",
        ))

    # ── health classification ─────────────────────────────────────────────
    if not running and not web_up:
        health = ModuleHealth.stopped
    elif running and web_up:
        health = ModuleHealth.healthy
    elif running and not web_up:
        # Service appears to be up but web UI is not accessible
        health = ModuleHealth.degraded
        warnings.append(
            f"x-ui process/service running but web UI not responding on port {web_ui_port}"
        )
    else:
        # web_up but no process/service detected — unusual but possible if
        # x-ui embeds in another process or runs under a different name
        health = ModuleHealth.degraded
        warnings.append(
            "Web UI is responding but x-ui service/process not detected via systemd/pgrep"
        )

    return XuiState(
        installed=installed,
        enabled=enabled,
        running=running,
        health=health,
        version=version,
        manager=manager,
        binary_path=binary,
        web_ui_responding=web_up,
        web_ui_port=web_ui_port,
        ports=ports,
        warnings=warnings,
        errors=errors,
        confidence=confidence,
        confidence_reasons=confidence_reasons,
        last_checked_at=now,
    )
