"""MTProxy observed-state detector.

Detects Docker and official native/systemd MTProxy installs, including
public endpoint, secret presence, and generated client artifacts.
"""
from __future__ import annotations

import re
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

_OFFICIAL_INSTALL_DIR = Path("/opt/MTProxy")
_OFFICIAL_NATIVE_BINARY = _OFFICIAL_INSTALL_DIR / "objs" / "bin" / "mtproto-proxy"
_SYSTEMD_UNIT_PATH = Path("/etc/systemd/system/MTProxy.service")


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


_GENERATED_CANDIDATES = [
    Path("/opt/daran-proxy-stack/artifacts/generated/mtproxy"),
    Path("/var/lib/daran-proxy-stack/generated/mtproxy"),
]

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
    official_secret = _OFFICIAL_INSTALL_DIR / "proxy-secret"
    if official_secret.exists():
        try:
            return official_secret.read_text(encoding="utf-8").strip() or None
        except OSError:
            pass
    return None


def _read_fake_tls_host(generated_dir: Path | None) -> str | None:
    if generated_dir is None:
        return None
    compose = generated_dir / "docker-compose.yml"
    if not compose.exists():
        return None
    try:
        text = compose.read_text(encoding="utf-8")
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


_MTPROXY_IMAGES = ["telegrammessenger/proxy", "ghcr.io/telegramdesktop/mtproto-proxy"]
_DEFAULT_CONTAINER_NAME = "mtproxy"


def _docker_find_container(docker: str) -> tuple[str | None, str | None, str | None, str | None]:
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


def _systemd_unit_exists(systemctl: str | None) -> bool:
    if systemctl:
        result = run([systemctl, "cat", "MTProxy"])
        if result.ok:
            return True
    return _SYSTEMD_UNIT_PATH.exists()


def _read_systemd_unit_text(systemctl: str | None) -> str:
    if systemctl:
        result = run([systemctl, "cat", "MTProxy"])
        if result.ok and result.stdout.strip():
            return result.stdout
    if _SYSTEMD_UNIT_PATH.exists():
        try:
            return _SYSTEMD_UNIT_PATH.read_text(encoding="utf-8")
        except OSError:
            return ""
    return ""


def _parse_mtproxy_port_from_text(text: str) -> int | None:
    if not text:
        return None
    match = re.search(r"(?:^|\s)-H\s+(\d+)(?:\s|$)", text)
    if match:
        return int(match.group(1))
    return None


def _resolve_native_binary() -> str | None:
    binary = shutil.which("mtproto-proxy")
    if binary:
        return binary
    if _OFFICIAL_NATIVE_BINARY.exists():
        return str(_OFFICIAL_NATIVE_BINARY)
    return None


def detect_mtproxy() -> MTProxyState:
    """Detect MTProxy installation and runtime state. Never raises."""
    docker = shutil.which("docker")
    systemctl = shutil.which("systemctl")
    native = _resolve_native_binary()
    unit_exists = _systemd_unit_exists(systemctl)

    now = datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []
    errors: list[str] = []
    confidence = DiscoveryConfidence.full
    confidence_reasons: list[str] = []

    if not docker and not native and not unit_exists:
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

    container_name: str | None = None
    container_running = False
    version: str | None = None
    observed_port: int | None = None
    observed_bind: str | None = None
    manager = ModuleManager.none
    config_paths: list[str] = []

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

    if native and manager == ModuleManager.none:
        manager = ModuleManager.systemd if unit_exists else ModuleManager.process
        unit_text = _read_systemd_unit_text(systemctl)
        if unit_text:
            config_paths.append(str(_SYSTEMD_UNIT_PATH))
            observed_port = _parse_mtproxy_port_from_text(unit_text) or observed_port

        if systemctl and unit_exists:
            sc = run([systemctl, "is-active", "--quiet", "MTProxy"])
            container_running = sc.returncode == 0
        else:
            container_running = False

        ver = run([native, "--version"])
        if ver.ok and ver.stdout.strip():
            version = ver.stdout.strip().splitlines()[0]
        elif Path(native).exists():
            version = Path(native).name

        if observed_port is None:
            generated_dir = _find_generated_dir()
            if generated_dir is not None:
                service_text = (generated_dir / "MTProxy.service")
                if service_text.exists():
                    try:
                        observed_port = _parse_mtproxy_port_from_text(service_text.read_text(encoding="utf-8"))
                    except OSError:
                        pass

    listen_port = observed_port
    port_listening = False
    if listen_port:
        port_listening = _tcp_port_listening("0.0.0.0", listen_port) or _tcp_port_listening("127.0.0.1", listen_port)
    elif container_running:
        warnings.append("runtime is active but listen port could not be determined")
        confidence = DiscoveryConfidence.partial
        confidence_reasons.append("listen port not determinable")

    generated_dir = _find_generated_dir()
    secret = _read_secret(generated_dir)
    fake_tls_host = _read_fake_tls_host(generated_dir)
    server_ip = _detect_server_ip()

    if generated_dir:
        compose = generated_dir / "docker-compose.yml"
        if compose.exists():
            config_paths.append(str(compose))
        generated_service = generated_dir / "MTProxy.service"
        if generated_service.exists() and str(generated_service) not in config_paths:
            config_paths.append(str(generated_service))

    tg_link: str | None = None
    if server_ip and listen_port and secret:
        tg_link = _build_tg_link(server_ip, listen_port, secret)
    elif not secret and container_running:
        warnings.append("secret not found in generated artifacts; tg:// link unavailable")
        confidence = DiscoveryConfidence.partial
        confidence_reasons.append("secret missing from artifacts")

    ports: list[PortEntry] = []
    if listen_port:
        ports.append(PortEntry(
            bind=observed_bind or "0.0.0.0",
            port=listen_port,
            protocol=PortProtocol.tcp,
            purpose="telegram-mtproxy",
        ))

    installed = bool(container_name is not None or native or unit_exists)

    if not installed:
        health = ModuleHealth.not_installed
    elif container_running and port_listening and secret:
        health = ModuleHealth.healthy
    elif container_running and (not port_listening or not secret):
        health = ModuleHealth.degraded
    elif installed and not container_running:
        health = ModuleHealth.stopped
    else:
        health = ModuleHealth.broken
        errors.append("MTProxy install found but runtime state unresolvable")

    enabled = container_running
    if systemctl and unit_exists:
        enabled_result = run([systemctl, "is-enabled", "--quiet", "MTProxy"])
        enabled = enabled_result.returncode == 0 or container_running

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
