"""MTProxy observed-state detector.

Detects: Docker container state, listening port, secret presence,
fake TLS host, tg:// link availability.

Per observed-state-model.md health rules:
  healthy:     container running + port listening + secret present
  degraded:    install exists but one artifact missing
  broken:      config exists but container dead or required data missing
  stopped:     installed but intentionally not running
  not_installed: no Docker container and no native binary
"""
from __future__ import annotations

import shutil
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

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
# MTProxy-specific sub-structures
# ---------------------------------------------------------------------------

@dataclass
class MTProxyPublicEndpoint:
    ip: str | None
    port: int | None

    def to_dict(self) -> dict:
        return {"ip": self.ip, "port": self.port}


@dataclass
class MTProxyClientArtifacts:
    tg_link: str | None
    secret_present: bool
    fake_tls_host: str | None

    def to_dict(self) -> dict:
        return {
            "tg_link": self.tg_link,
            "secret_present": self.secret_present,
            "fake_tls_host": self.fake_tls_host,
        }


@dataclass
class MTProxyRuntime:
    container_name: str | None
    container_running: bool

    def to_dict(self) -> dict:
        return {
            "container_name": self.container_name,
            "container_running": self.container_running,
        }


@dataclass
class MTProxyState(BaseModuleState):
    public_endpoint: MTProxyPublicEndpoint | None = None
    client_artifacts: MTProxyClientArtifacts | None = None
    runtime: MTProxyRuntime | None = None

    def to_dict(self) -> dict:
        d = self._base_dict()
        d["public_endpoint"] = self.public_endpoint.to_dict() if self.public_endpoint else None
        d["client_artifacts"] = self.client_artifacts.to_dict() if self.client_artifacts else None
        d["runtime"] = self.runtime.to_dict() if self.runtime else None
        return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Well-known artifacts path (relative to project root fallback; real deployments
# use /opt/daran-proxy-stack or similar — we probe common locations).
_GENERATED_CANDIDATES = [
    Path("/opt/daran-proxy-stack/artifacts/generated/mtproxy"),
    Path("/var/lib/daran-proxy-stack/generated/mtproxy"),
]

# Also check relative to this file's repo root (dev mode).
_HERE = Path(__file__).resolve()
for _p in _HERE.parents:
    _candidate = _p / "artifacts" / "generated" / "mtproxy"
    if _candidate.exists():
        _GENERATED_CANDIDATES.insert(0, _candidate)
        break


def _find_generated_dir() -> Path | None:
    for p in _GENERATED_CANDIDATES:
        if p.exists():
            return p
    return None


def _read_secret(generated_dir: Path | None) -> str | None:
    if generated_dir is None:
        return None
    secret_file = generated_dir / "secret.txt"
    if secret_file.exists():
        try:
            return secret_file.read_text(encoding="utf-8").strip() or None
        except OSError:
            pass
    return None


def _read_fake_tls_host(generated_dir: Path | None) -> str | None:
    """Try to extract fake TLS host from docker-compose.yml if present."""
    if generated_dir is None:
        return None
    compose = generated_dir / "docker-compose.yml"
    if not compose.exists():
        return None
    try:
        text = compose.read_text(encoding="utf-8")
        # Look for -d <hostname> pattern
        import re
        m = re.search(r"-d\s+([\w.\-]+)", text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _build_tg_link(public_ip: str, port: int, secret: str) -> str:
    query = urlencode({"server": public_ip, "port": str(port), "secret": secret})
    return f"tg://proxy?{query}"


def _tcp_port_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _detect_server_ip() -> str | None:
    result = run(["bash", "-c", "hostname -I 2>/dev/null | awk '{print $1}'"])
    if result.ok and result.stdout.strip():
        return result.stdout.strip()
    return None


# ---------------------------------------------------------------------------
# Docker container inspection
# ---------------------------------------------------------------------------

# Container image names we recognise
_MTPROXY_IMAGES = ["telegrammessenger/proxy", "ghcr.io/telegramdesktop/mtproto-proxy"]
# Default container name we write; user may have renamed it.
_DEFAULT_CONTAINER_NAME = "mtproxy"


def _docker_find_container(docker: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Find any mtproxy container by image or name.

    Returns (container_name, docker_status, ports_str, image_tag) or all None.
    """
    # Try by image ancestor first
    for image in _MTPROXY_IMAGES:
        result = run([
            docker, "ps", "-a",
            "--filter", f"ancestor={image}",
            "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}",
        ])
        if result.ok and result.stdout.strip():
            line = result.stdout.strip().splitlines()[0]
            parts = line.split("\t")
            name = parts[0].strip() if parts else None
            status = parts[1].strip() if len(parts) > 1 else None
            ports = parts[2].strip() if len(parts) > 2 else None
            img = parts[3].strip() if len(parts) > 3 else None
            if name:
                return name, status, ports, img

    # Fallback: try well-known container name
    result = run([
        docker, "ps", "-a",
        "--filter", f"name={_DEFAULT_CONTAINER_NAME}",
        "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}",
    ])
    if result.ok and result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            name = parts[0].strip() if parts else None
            if name and _DEFAULT_CONTAINER_NAME in name:
                status = parts[1].strip() if len(parts) > 1 else None
                ports = parts[2].strip() if len(parts) > 2 else None
                img = parts[3].strip() if len(parts) > 3 else None
                return name, status, ports, img

    return None, None, None, None


def _parse_docker_port(ports_str: str) -> tuple[str | None, int | None]:
    """Extract (bind, port) from docker port mapping like '0.0.0.0:443->443/tcp'."""
    if not ports_str:
        return None, None
    for token in ports_str.split(","):
        token = token.strip()
        if "->" in token:
            host_part = token.split("->")[0]
            if ":" in host_part:
                parts = host_part.rsplit(":", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    return parts[0], int(parts[1])
    return None, None


# ---------------------------------------------------------------------------
# Public detector
# ---------------------------------------------------------------------------

def detect_mtproxy() -> MTProxyState:
    """Detect MTProxy installation and runtime state. Never raises."""
    docker = shutil.which("docker")
    native = shutil.which("mtproto-proxy")

    now = datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []
    errors: list[str] = []
    confidence = DiscoveryConfidence.full
    confidence_reasons: list[str] = []

    # ── Not installed ──────────────────────────────────────────────────────
    if not docker and not native:
        return MTProxyState(
            installed=False,
            enabled=False,
            running=False,
            health=ModuleHealth.not_installed,
            version=None,
            manager=ModuleManager.none,
            last_checked_at=now,
            confidence=DiscoveryConfidence.full,
        )

    # ── Docker path ────────────────────────────────────────────────────────
    container_name: str | None = None
    container_running = False
    version: str | None = None
    observed_port: int | None = None
    observed_bind: str | None = None
    manager = ModuleManager.none

    if docker:
        try:
            cname, cstatus, cports, cimage = _docker_find_container(docker)
            if cname:
                manager = ModuleManager.docker
                container_name = cname
                version = cimage
                container_running = bool(cstatus and cstatus.lower().startswith("up"))
                if cports:
                    observed_bind, observed_port = _parse_docker_port(cports)
        except Exception as exc:
            errors.append(f"docker inspect error: {exc}")
            confidence = DiscoveryConfidence.partial
            confidence_reasons.append("docker inspection failed")

    # ── Native binary fallback ─────────────────────────────────────────────
    if native and manager == ModuleManager.none:
        manager = ModuleManager.process
        container_name = None
        # Try systemd
        systemctl = shutil.which("systemctl")
        if systemctl:
            sc = run([systemctl, "is-active", "--quiet", "MTProxy"])
            container_running = sc.returncode == 0
        ver = run([native, "--version"])
        if ver.ok and ver.stdout.strip():
            version = ver.stdout.strip().splitlines()[0]

    # ── Port listen check ──────────────────────────────────────────────────
    listen_port = observed_port
    port_listening = False
    if listen_port:
        port_listening = _tcp_port_listening("0.0.0.0", listen_port) or \
                         _tcp_port_listening("127.0.0.1", listen_port)
    elif container_running:
        warnings.append("container running but no port mapping detected")
        confidence = DiscoveryConfidence.partial
        confidence_reasons.append("port not determinable from container info")

    # ── Artifacts ─────────────────────────────────────────────────────────
    generated_dir = _find_generated_dir()
    secret = _read_secret(generated_dir)
    fake_tls_host = _read_fake_tls_host(generated_dir)
    server_ip = _detect_server_ip()

    tg_link: str | None = None
    if server_ip and listen_port and secret:
        tg_link = _build_tg_link(server_ip, listen_port, secret)
    elif not secret:
        if container_running or (native and container_running):
            warnings.append("secret not found in generated artifacts; tg:// link unavailable")
            confidence = DiscoveryConfidence.partial
            confidence_reasons.append("secret missing from artifacts")

    # ── Config paths ───────────────────────────────────────────────────────
    config_paths: list[str] = []
    if generated_dir:
        compose = generated_dir / "docker-compose.yml"
        if compose.exists():
            config_paths.append(str(compose))

    # ── Ports list ─────────────────────────────────────────────────────────
    ports: list[PortEntry] = []
    if listen_port:
        ports.append(PortEntry(
            bind=observed_bind or "0.0.0.0",
            port=listen_port,
            protocol=PortProtocol.tcp,
            purpose="telegram-mtproxy",
        ))

    # ── Health ────────────────────────────────────────────────────────────
    installed = bool(container_name is not None or (native and manager != ModuleManager.none))

    if not installed and not docker:
        health = ModuleHealth.not_installed
    elif container_running and port_listening and secret:
        health = ModuleHealth.healthy
    elif container_running and (not port_listening or not secret):
        health = ModuleHealth.degraded
    elif installed and not container_running:
        health = ModuleHealth.stopped
    elif installed:
        health = ModuleHealth.broken
        errors.append("MTProxy install found but runtime state unresolvable")
    else:
        health = ModuleHealth.not_installed

    # systemd enabled check (for docker-managed mtproxy, not typical)
    enabled = container_running  # docker containers auto-restart=unless-stopped counts as enabled

    return MTProxyState(
        installed=installed,
        enabled=enabled,
        running=container_running,
        health=health,
        version=version,
        manager=manager,
        config_paths=config_paths,
        ports=ports,
        public_endpoint=MTProxyPublicEndpoint(ip=server_ip, port=listen_port),
        client_artifacts=MTProxyClientArtifacts(
            tg_link=tg_link,
            secret_present=bool(secret),
            fake_tls_host=fake_tls_host,
        ),
        runtime=MTProxyRuntime(
            container_name=container_name,
            container_running=container_running,
        ),
        warnings=warnings,
        errors=errors,
        confidence=confidence,
        confidence_reasons=confidence_reasons,
        last_checked_at=now,
    )
