from __future__ import annotations

import shutil
from dataclasses import dataclass

from rich.panel import Panel
from rich.table import Table

from daran_proxy_stack.lib.models import WarpConfig
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


def detect_server_ip() -> str | None:
    result = run(["bash", "-lc", "hostname -I | awk '{print $1}'"])
    if result.ok and result.stdout:
        return result.stdout.strip()
    return None


def detect_os_release() -> str:
    result = run(["bash", "-lc", ". /etc/os-release && printf '%s %s' \"$ID\" \"$VERSION_ID\""])
    return result.stdout or "unknown"


def collect_diagnostics() -> WarpDiagnostics:
    warp_cli_path = shutil.which("warp-cli")
    cloudflared_path = shutil.which("cloudflared")
    systemctl_path = shutil.which("systemctl")

    warp_status = "not installed"
    if warp_cli_path:
        status_result = run([warp_cli_path, "--accept-tos", "status"])
        if status_result.ok:
            warp_status = status_result.stdout or "installed"
        elif status_result.stderr:
            warp_status = status_result.stderr

    recommended_backend = "warp-cli" if warp_cli_path else "cloudflared"

    return WarpDiagnostics(
        os_release=detect_os_release(),
        warp_cli_path=warp_cli_path,
        cloudflared_path=cloudflared_path,
        systemctl_path=systemctl_path,
        server_ip=detect_server_ip(),
        warp_status=warp_status,
        recommended_backend=recommended_backend,
    )


def render_summary(config: WarpConfig, diagnostics: WarpDiagnostics | None = None) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_row("Mode", config.mode)
    table.add_row("SOCKS host", config.socks_host)
    table.add_row("SOCKS port", str(config.socks_port))
    if diagnostics is None:
        table.add_row("Status", "planned / not installed yet")
    else:
        table.add_row("OS", diagnostics.os_release)
        table.add_row("Server IP", diagnostics.server_ip or "unknown")
        table.add_row("warp-cli", diagnostics.warp_cli_path or "not found")
        table.add_row("cloudflared", diagnostics.cloudflared_path or "not found")
        table.add_row("systemctl", diagnostics.systemctl_path or "not found")
        table.add_row("WARP status", diagnostics.warp_status)
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
