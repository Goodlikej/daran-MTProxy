"""WARP observed-state detector.

Detects: binary/service presence, WARP registration, SOCKS5 endpoint,
current egress IP vs server IP, generates xray outbound JSON.

Per observed-state-model.md health rules:
  healthy:  local SOCKS alive + registration ok + WARP egress confirmed
  degraded: installed but SOCKS not listening, or egress verification uncertain
  broken:   registration missing/corrupt or runtime repeatedly failing
  stopped:  installed but intentionally disabled
  not_installed: no binaries found
"""
from __future__ import annotations

import json
import shutil
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
# Network port check
# ---------------------------------------------------------------------------

def _tcp_port_listening(host: str, port: int) -> bool:
    """Check whether a TCP port is open by attempting a connection."""
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# WARP state
# ---------------------------------------------------------------------------

@dataclass
class WarpRegistration:
    registered: bool
    account_type: str | None = None  # "free" | "team" | None

    def to_dict(self) -> dict:
        return {
            "registered": self.registered,
            "account_type": self.account_type,
        }


@dataclass
class WarpNetwork:
    server_ip: str | None
    warp_ip: str | None
    egress_changed: bool  # True if warp_ip != server_ip

    def to_dict(self) -> dict:
        return {
            "server_ip": self.server_ip,
            "warp_ip": self.warp_ip,
            "egress_changed": self.egress_changed,
        }


@dataclass
class WarpXrayArtifacts:
    socks_outbound_json: str

    def to_dict(self) -> dict:
        return {"socks_outbound_json": self.socks_outbound_json}


@dataclass
class WarpState(BaseModuleState):
    backend: str = "unknown"  # "warp-cli" | "cloudflared" | "unknown"
    registration: WarpRegistration | None = None
    network: WarpNetwork | None = None
    xray_artifacts: WarpXrayArtifacts | None = None

    def to_dict(self) -> dict:
        d = self._base_dict()
        d["backend"] = self.backend
        d["registration"] = self.registration.to_dict() if self.registration else None
        d["network"] = self.network.to_dict() if self.network else None
        d["xray_artifacts"] = self.xray_artifacts.to_dict() if self.xray_artifacts else None
        return d


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _detect_warp_cli_status(warp_cli: str) -> tuple[bool, bool, str]:
    """Return (connected, registered, raw_status_text)."""
    status = run([warp_cli, "--accept-tos", "status"])
    raw = (status.stdout or status.stderr or "").lower()
    # "Disconnected" contains the substring "connected" — check negative first.
    disconnected = "disconnected" in raw or "warp is off" in raw
    connected = (not disconnected) and ("connected" in raw or "warp is on" in raw)
    registered = "registration missing" not in raw and "not registered" not in raw
    return connected, registered, (status.stdout or "").strip()


def _detect_socks5_listen(host: str, port: int) -> bool:
    """Return True if SOCKS5 port is accepting connections."""
    return _tcp_port_listening(host, port)


def _detect_warp_egress_ip() -> str | None:
    """Ask an external service what our current egress IP is."""
    result = run(["curl", "-fsSL", "--max-time", "4", "https://api.ipify.org"])
    if result.ok and result.stdout.strip():
        return result.stdout.strip().splitlines()[0].strip()
    return None


def _detect_server_ip() -> str | None:
    result = run(["bash", "-c", "hostname -I 2>/dev/null | awk '{print $1}'"])
    if result.ok and result.stdout.strip():
        return result.stdout.strip()
    return None


def _render_xray_outbound(socks_host: str, socks_port: int) -> str:
    obj = {
        "protocol": "socks",
        "settings": {
            "servers": [{"address": socks_host, "port": socks_port}]
        },
        "tag": "warp-out",
    }
    return json.dumps(obj, indent=2)


def _default_socks_port() -> int:
    return 40000


def _default_socks_host() -> str:
    return "127.0.0.1"


# ---------------------------------------------------------------------------
# Public detector
# ---------------------------------------------------------------------------

def detect_warp() -> WarpState:
    """Detect WARP installation and runtime state. Never raises."""
    warp_cli = shutil.which("warp-cli")
    cloudflared = shutil.which("cloudflared")

    now = datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []
    errors: list[str] = []
    confidence = DiscoveryConfidence.full
    confidence_reasons: list[str] = []

    # ── Not installed ──────────────────────────────────────────────────────
    if not warp_cli and not cloudflared:
        return WarpState(
            installed=False,
            enabled=False,
            running=False,
            health=ModuleHealth.not_installed,
            version=None,
            manager=ModuleManager.none,
            last_checked_at=now,
            confidence=DiscoveryConfidence.full,
        )

    # ── Detect version ─────────────────────────────────────────────────────
    version: str | None = None
    backend_used = "warp-cli" if warp_cli else "cloudflared"
    binary_path = warp_cli or cloudflared
    ver_result = run([binary_path, "--version"])
    if ver_result.ok and ver_result.stdout.strip():
        version = ver_result.stdout.strip().splitlines()[0]

    # ── Determine manager ─────────────────────────────────────────────────
    systemctl = shutil.which("systemctl")
    manager = ModuleManager.none
    service_enabled = False
    if systemctl and warp_cli:
        sc_active = run([systemctl, "is-active", "--quiet", "warp-svc"])
        sc_enabled = run([systemctl, "is-enabled", "--quiet", "warp-svc"])
        if sc_active.returncode == 0 or sc_enabled.returncode == 0:
            manager = ModuleManager.systemd
            service_enabled = sc_enabled.returncode == 0

    # ── warp-cli status and registration ──────────────────────────────────
    connected = False
    registered = False
    raw_status = ""
    if warp_cli:
        try:
            connected, registered, raw_status = _detect_warp_cli_status(warp_cli)
        except Exception as exc:
            errors.append(f"warp-cli status error: {exc}")
            confidence = DiscoveryConfidence.partial
            confidence_reasons.append("warp-cli status failed")

    # ── SOCKS5 port ────────────────────────────────────────────────────────
    socks_host = _default_socks_host()
    socks_port = _default_socks_port()
    socks_listening = _detect_socks5_listen(socks_host, socks_port)

    ports: list[PortEntry] = []
    if socks_listening:
        ports.append(PortEntry(
            bind=socks_host,
            port=socks_port,
            protocol=PortProtocol.tcp,
            purpose="local-socks5",
        ))

    # ── Network egress check ───────────────────────────────────────────────
    server_ip = None
    warp_ip = None
    egress_changed = False
    network: WarpNetwork | None = None

    if connected:
        try:
            server_ip = _detect_server_ip()
            warp_ip = _detect_warp_egress_ip()
            if server_ip and warp_ip:
                egress_changed = server_ip != warp_ip
            else:
                confidence = DiscoveryConfidence.partial
                confidence_reasons.append("could not verify egress IP change")
            network = WarpNetwork(
                server_ip=server_ip,
                warp_ip=warp_ip,
                egress_changed=egress_changed,
            )
        except Exception as exc:
            warnings.append(f"egress check failed: {exc}")
            confidence = DiscoveryConfidence.partial
            confidence_reasons.append("egress verification error")

    # ── Registration state ─────────────────────────────────────────────────
    registration = WarpRegistration(
        registered=registered,
        account_type=None,  # would need `warp-cli account` parsing
    ) if warp_cli else None

    # ── Xray artifact ─────────────────────────────────────────────────────
    xray_artifacts = WarpXrayArtifacts(
        socks_outbound_json=_render_xray_outbound(socks_host, socks_port)
    )

    # ── Health classification ──────────────────────────────────────────────
    if warp_cli or cloudflared:
        if not connected and not socks_listening:
            health = ModuleHealth.stopped
        elif connected and socks_listening and (egress_changed or warp_ip is None):
            # egress_changed=True means traffic is routing through WARP.
            # warp_ip=None means we couldn't verify — degrade.
            health = (
                ModuleHealth.healthy
                if warp_ip is not None
                else ModuleHealth.degraded
            )
        elif connected and not socks_listening:
            health = ModuleHealth.degraded
            warnings.append("WARP is connected but SOCKS5 port is not listening")
        elif not connected and socks_listening:
            health = ModuleHealth.degraded
            warnings.append("SOCKS5 port is open but WARP is not connected")
        elif not registered and warp_cli:
            health = ModuleHealth.broken
            errors.append("WARP registration missing or corrupt")
        else:
            health = ModuleHealth.stopped
    else:
        health = ModuleHealth.not_installed

    return WarpState(
        installed=True,
        enabled=service_enabled,
        running=connected or socks_listening,
        health=health,
        version=version,
        manager=manager,
        backend=backend_used,
        ports=ports,
        registration=registration,
        network=network,
        xray_artifacts=xray_artifacts,
        warnings=warnings,
        errors=errors,
        confidence=confidence,
        confidence_reasons=confidence_reasons,
        last_checked_at=now,
    )
