"""Host-level discovery.

Detects OS family/version, public IP, hostname, and BBR status.
Never raises — every failure is captured in the returned HostState.
"""
from __future__ import annotations

import socket

from daran_proxy_stack.discovery.schema import HostState
from daran_proxy_stack.lib.shell import run


def _detect_os() -> tuple[str, str]:
    """Return (os_id, version) from /etc/os-release."""
    result = run([
        "bash", "-c",
        ". /etc/os-release 2>/dev/null && printf '%s\\t%s' "
        '"${ID:-unknown}" "${VERSION_ID:-}"',
    ])
    if result.ok and result.stdout.strip():
        parts = result.stdout.strip().split("\t", 1)
        os_id = parts[0] or "unknown"
        version = parts[1] if len(parts) > 1 else ""
        return os_id, version
    return "unknown", ""


def _detect_public_ip() -> str | None:
    """Try multiple fast methods to get public IP; return None if all fail."""
    # Method 1: curl checkip services (first that responds)
    for svc in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"):
        result = run(["curl", "-fsSL", "--max-time", "3", svc])
        if result.ok and result.stdout.strip():
            candidate = result.stdout.strip().splitlines()[0].strip()
            if _looks_like_ip(candidate):
                return candidate

    # Method 2: hostname -I first address
    result = run(["bash", "-c", "hostname -I 2>/dev/null | awk '{print $1}'"])
    if result.ok and result.stdout.strip():
        candidate = result.stdout.strip()
        if _looks_like_ip(candidate):
            return candidate

    return None


def _looks_like_ip(s: str) -> bool:
    """Very basic IP check — avoids importing ipaddress for a simple guard."""
    parts = s.split(".")
    if len(parts) == 4:
        try:
            return all(0 <= int(p) <= 255 for p in parts)
        except ValueError:
            pass
    return False


def _detect_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _detect_bbr() -> bool | None:
    """Check if BBR is the active TCP congestion control algorithm."""
    result = run(["bash", "-c", "sysctl net.ipv4.tcp_congestion_control 2>/dev/null"])
    if result.ok and "bbr" in result.stdout.lower():
        return True
    if result.ok:
        return False
    return None  # sysctl not available or failed


def discover_host() -> HostState:
    """Run host-level detection, return HostState. Never raises."""
    try:
        os_id, version = _detect_os()
    except Exception:
        os_id, version = "unknown", ""

    try:
        public_ip = _detect_public_ip()
    except Exception:
        public_ip = None

    try:
        hostname = _detect_hostname()
    except Exception:
        hostname = "unknown"

    try:
        bbr_enabled = _detect_bbr()
    except Exception:
        bbr_enabled = None

    return HostState(
        os=os_id,
        version=version,
        public_ip=public_ip,
        hostname=hostname,
        bbr_enabled=bbr_enabled,
    )
