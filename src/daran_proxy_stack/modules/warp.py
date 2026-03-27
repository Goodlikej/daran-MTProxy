from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from daran_proxy_stack.lib.models import WarpConfig
from daran_proxy_stack.lib.files import write_text
from daran_proxy_stack.lib.shell import run


@dataclass
class WarpDiagnostics:
    os_release: str
    warp_cli_path: str | None
    cloudflared_path: str | None
    systemctl_path: str | None
    server_ip: str | None
    warp_status: str
    recommended_backend: str
    connected: bool
    socks_running: bool


@dataclass
class WarpActionResult:
    ok: bool
    title: str
    body: str


def detect_server_ip() -> str | None:
    result = run(["bash", "-lc", "hostname -I | awk '{print $1}'"])
    if result.ok and result.stdout:
        return result.stdout.strip()
    return None


def detect_os_release() -> str:
    result = run(["bash", "-lc", ". /etc/os-release && printf '%s %s' \"$ID\" \"$VERSION_ID\""])
    return result.stdout or "unknown"


def _detect_os_info() -> tuple[str, str]:
    """Return (os_id, version_codename) parsed from /etc/os-release."""
    result = run([
        "bash", "-lc",
        ". /etc/os-release && printf '%s %s' \"${ID:-}\" \"${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}\"",
    ])
    if result.ok and result.stdout:
        parts = result.stdout.strip().split()
        return (parts[0] if parts else "unknown"), (parts[1] if len(parts) > 1 else "")
    return "unknown", ""


def _supported_install_os() -> bool:
    os_id, _ = _detect_os_info()
    return os_id in ("debian", "ubuntu")


def _parse_warp_status_text(status_text: str) -> bool:
    lowered = status_text.lower()
    return "connected" in lowered or "warp is on" in lowered


def _socks_pid_path(config: WarpConfig) -> Path:
    return Path(config.state_dir) / "warp-socks.pid"


def _ensure_runtime_dirs(config: WarpConfig) -> None:
    Path(config.state_dir).mkdir(parents=True, exist_ok=True)
    Path(config.log_dir).mkdir(parents=True, exist_ok=True)


def _generated_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "artifacts" / "generated" / "warp"


def _is_pid_running(pid: int) -> bool:
    return Path(f"/proc/{pid}").exists()


def is_socks_running(config: WarpConfig) -> bool:
    pid_path = _socks_pid_path(config)
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        return False
    return _is_pid_running(pid)


def collect_diagnostics(config: WarpConfig) -> WarpDiagnostics:
    warp_cli_path = shutil.which("warp-cli")
    cloudflared_path = shutil.which("cloudflared")
    systemctl_path = shutil.which("systemctl")

    warp_status = "not installed"
    connected = False
    if warp_cli_path:
        status_result = run([warp_cli_path, "--accept-tos", "status"])
        if status_result.ok:
            warp_status = status_result.stdout or "installed"
            connected = _parse_warp_status_text(warp_status)
        elif status_result.stderr:
            warp_status = status_result.stderr

    if config.backend == "auto":
        recommended_backend = "warp-cli" if warp_cli_path else "cloudflared"
    else:
        recommended_backend = config.backend

    return WarpDiagnostics(
        os_release=detect_os_release(),
        warp_cli_path=warp_cli_path,
        cloudflared_path=cloudflared_path,
        systemctl_path=systemctl_path,
        server_ip=detect_server_ip(),
        warp_status=warp_status,
        recommended_backend=recommended_backend,
        connected=connected,
        socks_running=is_socks_running(config),
    )


def render_summary(config: WarpConfig, diagnostics: WarpDiagnostics | None = None) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_row("Mode", config.mode)
    table.add_row("SOCKS host", config.socks_host)
    table.add_row("SOCKS port", str(config.socks_port))
    table.add_row("Backend", config.backend)
    table.add_row("State dir", config.state_dir)
    table.add_row("Log dir", config.log_dir)
    if diagnostics is None:
        table.add_row("Status", "planned / not installed yet")
    else:
        table.add_row("OS", diagnostics.os_release)
        table.add_row("Server IP", diagnostics.server_ip or "unknown")
        table.add_row("warp-cli", diagnostics.warp_cli_path or "not found")
        table.add_row("cloudflared", diagnostics.cloudflared_path or "not found")
        table.add_row("systemctl", diagnostics.systemctl_path or "not found")
        table.add_row("WARP status", diagnostics.warp_status)
        table.add_row("Connected", "yes" if diagnostics.connected else "no")
        table.add_row("SOCKS running", "yes" if diagnostics.socks_running else "no")
        table.add_row("Recommended backend", diagnostics.recommended_backend)
    return Panel(table, title="WARP module", border_style="cyan")


def render_xray_outbound(config: WarpConfig) -> str:
    return (
        '{\n'
        '  "protocol": "socks",\n'
        '  "settings": {\n'
        '    "servers": [\n'
        '      {\n'
        f'        "address": "{config.socks_host}",\n'
        f'        "port": {config.socks_port}\n'
        '      }\n'
        '    ]\n'
        '  },\n'
        '  "tag": "warp-out"\n'
        '}'
    )




def save_xray_artifact(config: WarpConfig) -> Path:
    path = _generated_dir() / "xray-outbound.json"
    return write_text(path, render_xray_outbound(config))

def render_backend_plan(config: WarpConfig, diagnostics: WarpDiagnostics) -> str:
    effective_backend = diagnostics.recommended_backend if config.backend == "auto" else config.backend
    parts = [
        f"configured backend: {config.backend}",
        f"effective backend: {effective_backend}",
        f"socks endpoint: {config.socks_host}:{config.socks_port}",
    ]
    if effective_backend == "warp-cli" and diagnostics.warp_cli_path:
        parts.append("use warp-cli for registration/connect/disconnect")
    elif effective_backend == "warp-cli":
        parts.append("install warp-cli first")
    if effective_backend == "cloudflared" and diagnostics.cloudflared_path:
        parts.append("cloudflared available for local socks")
    elif effective_backend == "cloudflared":
        parts.append("install cloudflared for local socks proxy")
    return "\n".join(parts)


def install_warp_cli() -> WarpActionResult:
    if shutil.which("warp-cli"):
        return WarpActionResult(True, "WARP install", "warp-cli already installed")

    if not _supported_install_os():
        return WarpActionResult(
            False,
            "WARP install unsupported",
            "automatic install currently supports Debian/Ubuntu only; install cloudflare-warp manually for this OS",
        )

    cmd = (
        "set -e; "
        "curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | "
        "gpg --dearmor | sudo tee /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg >/dev/null; "
        "echo 'deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] "
        "https://pkg.cloudflareclient.com/ bookworm main' | "
        "sudo tee /etc/apt/sources.list.d/cloudflare-client.list >/dev/null; "
        "sudo apt-get update; sudo apt-get install -y cloudflare-warp"
    )
    result = run(["bash", "-lc", cmd])
    if result.ok:
        return WarpActionResult(True, "WARP install", "cloudflare-warp installed")
    return WarpActionResult(False, "WARP install failed", result.stderr or result.stdout or "unknown error")


def connect_warp(config: WarpConfig) -> WarpActionResult:
    _ensure_runtime_dirs(config)
    warp_cli_path = shutil.which("warp-cli")
    if not warp_cli_path:
        return WarpActionResult(False, "WARP connect failed", "warp-cli not found")

    commands = [
        f"{warp_cli_path} --accept-tos registration new || true",
        f"{warp_cli_path} --accept-tos connect",
        f"{warp_cli_path} --accept-tos status",
    ]
    result = run(["bash", "-lc", "set -e; " + "; ".join(commands)])
    if result.ok:
        return WarpActionResult(True, "WARP connected", result.stdout or "connected")
    return WarpActionResult(False, "WARP connect failed", result.stderr or result.stdout or "unknown error")


def disconnect_warp(config: WarpConfig) -> WarpActionResult:
    warp_cli_path = shutil.which("warp-cli")
    if not warp_cli_path:
        return WarpActionResult(False, "WARP disconnect failed", "warp-cli not found")
    result = run([warp_cli_path, "--accept-tos", "disconnect"])
    if result.ok:
        return WarpActionResult(True, "WARP disconnected", result.stdout or "disconnected")
    return WarpActionResult(False, "WARP disconnect failed", result.stderr or result.stdout or "unknown error")


def start_local_socks(config: WarpConfig) -> WarpActionResult:
    _ensure_runtime_dirs(config)
    if config.socks_host != "127.0.0.1":
        return WarpActionResult(False, "WARP SOCKS failed", "only 127.0.0.1 is supported for local SOCKS in current MVP")
    cloudflared_path = shutil.which("cloudflared")
    if not cloudflared_path:
        return WarpActionResult(False, "WARP SOCKS failed", "cloudflared not found")
    if is_socks_running(config):
        return WarpActionResult(True, "WARP SOCKS", f"already running at {config.socks_host}:{config.socks_port}")

    pid_path = _socks_pid_path(config)
    log_path = Path(config.log_dir) / "warp-socks.log"
    command = (
        f"nohup {cloudflared_path} access tcp --hostname 127.0.0.1 --url socks://{config.socks_host}:{config.socks_port} "
        f">>{log_path} 2>&1 & echo $!"
    )
    result = run(["bash", "-lc", command])
    if result.ok and result.stdout:
        pid_path.write_text(result.stdout.strip(), encoding="utf-8")
        return WarpActionResult(True, "WARP SOCKS started", f"SOCKS endpoint ready at {config.socks_host}:{config.socks_port}")
    return WarpActionResult(False, "WARP SOCKS failed", result.stderr or result.stdout or "unknown error")


def stop_local_socks(config: WarpConfig) -> WarpActionResult:
    pid_path = _socks_pid_path(config)
    if not pid_path.exists():
        return WarpActionResult(True, "WARP SOCKS", "no running SOCKS pid file")
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        pid_path.unlink(missing_ok=True)
        return WarpActionResult(False, "WARP SOCKS stop failed", "invalid pid file")

    result = run(["bash", "-lc", f"kill {pid}"])
    pid_path.unlink(missing_ok=True)
    if result.ok:
        return WarpActionResult(True, "WARP SOCKS stopped", f"stopped pid {pid}")
    return WarpActionResult(False, "WARP SOCKS stop failed", result.stderr or result.stdout or "unknown error")


def render_result_panel(action: WarpActionResult) -> Panel:
    return Panel.fit(
        action.body,
        title=action.title,
        border_style="green" if action.ok else "red",
    )


def render_debug_json(config: WarpConfig, diagnostics: WarpDiagnostics) -> str:
    return json.dumps(
        {
            "config": {
                "mode": config.mode,
                "backend": config.backend,
                "socks_host": config.socks_host,
                "socks_port": config.socks_port,
                "state_dir": config.state_dir,
                "log_dir": config.log_dir,
            },
            "diagnostics": {
                "os_release": diagnostics.os_release,
                "warp_cli_path": diagnostics.warp_cli_path,
                "cloudflared_path": diagnostics.cloudflared_path,
                "systemctl_path": diagnostics.systemctl_path,
                "server_ip": diagnostics.server_ip,
                "warp_status": diagnostics.warp_status,
                "recommended_backend": diagnostics.recommended_backend,
                "connected": diagnostics.connected,
                "socks_running": diagnostics.socks_running,
            },
        },
        indent=2,
        ensure_ascii=False,
    )
