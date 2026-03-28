"""Discovery / inventory module.

Detects installed stack components and their runtime state.
Supported targets: MTProxy, WARP, Xray, AmneziaWG.

Each detector returns a ServiceInventory dataclass.  No exceptions propagate
to callers — every error is captured into `meta["error"]` and the status is
set to "unknown".
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field

from daran_proxy_stack.lib.shell import run


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ServiceInventory:
    name: str                        # machine key, e.g. "mtproxy"
    label: str                       # human label, e.g. "MTProxy (Telegram)"
    detected: bool                   # binary / image / kernel module found
    version: str | None              # detected version string, or None
    runtime_status: str              # "running" | "stopped" | "not_installed" | "unknown"
    config_path: str | None = None   # path to primary config file if found
    endpoint: str | None = None      # host:port if determinable
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "detected": self.detected,
            "version": self.version,
            "runtime_status": self.runtime_status,
            "config_path": self.config_path,
            "endpoint": self.endpoint,
            "meta": self.meta,
        }


# ---------------------------------------------------------------------------
# MTProxy detector
# ---------------------------------------------------------------------------

def _detect_mtproxy() -> ServiceInventory:
    docker = shutil.which("docker")
    native = shutil.which("mtproto-proxy")
    detected = bool(docker or native)
    version: str | None = None
    runtime_status = "not_installed"
    endpoint: str | None = None
    meta: dict = {}

    if docker:
        try:
            # List all containers (running + stopped) with the official image
            ps = run([
                docker, "ps", "-a",
                "--filter", "ancestor=telegrammessenger/proxy",
                "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}",
            ])
            if ps.ok and ps.stdout.strip():
                first = ps.stdout.strip().splitlines()[0]
                parts = first.split("\t")
                cname = parts[0].strip() if parts else ""
                cstatus = parts[1].strip() if len(parts) > 1 else ""
                cports = parts[2].strip() if len(parts) > 2 else ""
                meta["container"] = cname
                meta["docker_status"] = cstatus

                if cstatus.lower().startswith("up"):
                    runtime_status = "running"
                    # Inspect image tag for version
                    insp = run([docker, "inspect", cname, "--format", "{{.Config.Image}}"])
                    if insp.ok and insp.stdout.strip():
                        version = insp.stdout.strip()
                    # Parse mapped port from e.g. "0.0.0.0:443->443/tcp"
                    if cports:
                        endpoint = _parse_docker_ports(cports)
                else:
                    runtime_status = "stopped"
                    # Try to get version from stopped container image
                    insp = run([docker, "inspect", cname, "--format", "{{.Config.Image}}"])
                    if insp.ok and insp.stdout.strip():
                        version = insp.stdout.strip()
            else:
                # No matching container — check if image is pulled
                images = run([
                    docker, "images", "telegrammessenger/proxy",
                    "--format", "{{.Repository}}:{{.Tag}}",
                ])
                if images.ok and images.stdout.strip():
                    runtime_status = "stopped"
                    version = images.stdout.strip().splitlines()[0]
                elif docker:
                    # Docker present but image not pulled and container absent
                    runtime_status = "not_installed"
        except Exception as exc:
            meta["error"] = str(exc)
            runtime_status = "unknown"

    if native and runtime_status == "not_installed":
        runtime_status = "unknown"
        meta["native_binary"] = native
        # Try to get native version
        ver = run([native, "--version"])
        if ver.ok and ver.stdout.strip():
            version = ver.stdout.strip().splitlines()[0]

    return ServiceInventory(
        name="mtproxy",
        label="MTProxy (Telegram)",
        detected=detected,
        version=version,
        runtime_status=runtime_status,
        endpoint=endpoint,
        meta=meta,
    )


def _parse_docker_ports(ports_str: str) -> str | None:
    """Extract first host:port from docker port mapping like '0.0.0.0:443->443/tcp'."""
    for token in ports_str.split(","):
        token = token.strip()
        if "->" in token:
            host_part = token.split("->")[0]
            # host_part could be "0.0.0.0:443" or ":::443"
            if ":" in host_part:
                host_port = host_part.rsplit(":", 1)
                if len(host_port) == 2 and host_port[1].isdigit():
                    return f"0.0.0.0:{host_port[1]}"
    return None


# ---------------------------------------------------------------------------
# WARP detector
# ---------------------------------------------------------------------------

def _detect_warp() -> ServiceInventory:
    warp_cli = shutil.which("warp-cli")
    cloudflared = shutil.which("cloudflared")
    detected = bool(warp_cli or cloudflared)
    version: str | None = None
    runtime_status = "not_installed"
    meta: dict = {}

    if warp_cli:
        meta["warp_cli"] = warp_cli
        # Version
        ver = run([warp_cli, "--version"])
        if ver.ok and ver.stdout.strip():
            version = ver.stdout.strip().splitlines()[0]
        # Status
        status = run([warp_cli, "--accept-tos", "status"])
        raw = (status.stdout or status.stderr or "").lower()
        # Check "disconnected" before "connected" to avoid substring false-positive.
        if "disconnected" in raw:
            runtime_status = "stopped"
        elif "connected" in raw or "warp is on" in raw:
            runtime_status = "running"
        elif status.returncode == 0:
            runtime_status = "stopped"
        else:
            runtime_status = "stopped"
        meta["warp_status"] = (status.stdout or "").strip()

    if cloudflared:
        meta["cloudflared"] = cloudflared
        if not version:
            ver = run([cloudflared, "--version"])
            if ver.ok and ver.stdout.strip():
                version = ver.stdout.strip().splitlines()[0]
        if runtime_status == "not_installed":
            runtime_status = "stopped"

    return ServiceInventory(
        name="warp",
        label="Cloudflare WARP",
        detected=detected,
        version=version,
        runtime_status=runtime_status,
        meta=meta,
    )


# ---------------------------------------------------------------------------
# Xray detector
# ---------------------------------------------------------------------------

_XRAY_SEARCH_PATHS = [
    "/usr/local/bin/xray",
    "/usr/bin/xray",
    "/opt/xray/xray",
]


def _detect_xray() -> ServiceInventory:
    xray_bin = shutil.which("xray")
    if not xray_bin:
        for p in _XRAY_SEARCH_PATHS:
            try:
                import os
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    xray_bin = p
                    break
            except Exception:
                pass

    detected = xray_bin is not None
    version: str | None = None
    runtime_status = "not_installed"
    meta: dict = {}

    if xray_bin:
        meta["binary"] = xray_bin
        # Version: `xray version` outputs "Xray X.Y.Z ..."
        ver = run([xray_bin, "version"])
        if ver.ok and ver.stdout.strip():
            version = ver.stdout.strip().splitlines()[0]
        elif ver.stdout.strip():
            version = ver.stdout.strip().splitlines()[0]

        # Runtime: check pgrep first, then systemctl
        pgrep = run(["pgrep", "-x", "xray"])
        if pgrep.ok and pgrep.stdout.strip():
            runtime_status = "running"
            pids = pgrep.stdout.strip().splitlines()
            meta["pids"] = pids
        else:
            systemctl = shutil.which("systemctl")
            if systemctl:
                sc = run([systemctl, "is-active", "--quiet", "xray"])
                runtime_status = "running" if sc.returncode == 0 else "stopped"
            else:
                runtime_status = "stopped"

    return ServiceInventory(
        name="xray",
        label="Xray",
        detected=detected,
        version=version,
        runtime_status=runtime_status,
        meta=meta,
    )


# ---------------------------------------------------------------------------
# AmneziaWG detector
# ---------------------------------------------------------------------------

_AWG_SEARCH_PATHS = [
    "/usr/bin/awg",
    "/usr/local/bin/awg",
    "/usr/sbin/awg",
]


def _detect_amneziawg() -> ServiceInventory:
    awg_bin = shutil.which("awg") or shutil.which("awg-quick")
    if not awg_bin:
        for p in _AWG_SEARCH_PATHS:
            try:
                import os
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    awg_bin = p
                    break
            except Exception:
                pass

    detected = awg_bin is not None
    version: str | None = None
    runtime_status = "not_installed"
    config_path: str | None = None
    meta: dict = {}

    if awg_bin:
        meta["binary"] = awg_bin
        # Version
        ver = run([awg_bin, "--version"])
        if ver.returncode == 0 and ver.stdout.strip():
            version = ver.stdout.strip().splitlines()[0]
        elif ver.stderr.strip():
            # Some versions print to stderr
            first_line = ver.stderr.strip().splitlines()[0]
            if "amnezia" in first_line.lower() or "wireguard" in first_line.lower():
                version = first_line

        # Active interfaces: `awg show interfaces`
        ifaces = run([awg_bin, "show", "interfaces"])
        if ifaces.returncode == 0 and ifaces.stdout.strip():
            active = ifaces.stdout.strip().split()
            if active:
                runtime_status = "running"
                meta["interfaces"] = active
            else:
                runtime_status = "stopped"
        else:
            runtime_status = "stopped"

        # Config path hint
        import os
        for candidate in ["/etc/amnezia/amneziawg", "/etc/wireguard"]:
            if os.path.isdir(candidate):
                config_path = candidate
                break

    return ServiceInventory(
        name="amneziawg",
        label="AmneziaWG",
        detected=detected,
        version=version,
        runtime_status=runtime_status,
        config_path=config_path,
        meta=meta,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect_inventory() -> list[ServiceInventory]:
    """Run all detectors and return a list of ServiceInventory entries.

    Never raises — each detector catches its own exceptions.
    """
    # (service_name, detector_fn) — name is explicit so fallback doesn't
    # depend on __name__ being available (e.g. when a detector is mocked).
    detectors: list[tuple[str, callable]] = [
        ("mtproxy",    _detect_mtproxy),
        ("warp",       _detect_warp),
        ("xray",       _detect_xray),
        ("amneziawg",  _detect_amneziawg),
    ]
    results = []
    for svc_name, det in detectors:
        try:
            results.append(det())
        except Exception as exc:
            # Defensive catch — individual detectors should not raise, but just in case
            results.append(ServiceInventory(
                name=svc_name,
                label=svc_name.title(),
                detected=False,
                version=None,
                runtime_status="unknown",
                meta={"error": str(exc)},
            ))
    return results


def inventory_dict(entries: list[ServiceInventory] | None = None) -> dict:
    """Return JSON-serializable inventory snapshot."""
    from datetime import datetime, timezone
    if entries is None:
        entries = collect_inventory()
    return {
        "services": [e.to_dict() for e in entries],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "count": len(entries),
        "detected_count": sum(1 for e in entries if e.detected),
        "running_count": sum(1 for e in entries if e.runtime_status == "running"),
    }
