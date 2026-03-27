from __future__ import annotations

from dataclasses import dataclass

from rich.panel import Panel
from rich.table import Table

from daran_proxy_stack.lib.models import CascadeConfig
from daran_proxy_stack.lib.shell import run


@dataclass
class CascadeDiagnostics:
    note: str = "cascade module not yet implemented"
    config_present: bool = False
    relay_reachable: bool = False
    upstream_reachable: bool = False


def _port_open(host: str, port: int) -> bool:
    result = run(["bash", "-lc", f"timeout 1 bash -c 'echo >/dev/tcp/{host}/{port}' 2>/dev/null && echo ok || echo fail"])
    return result.ok and "ok" in (result.stdout or "")


def collect_diagnostics(config: CascadeConfig | None = None) -> CascadeDiagnostics:
    if config is None:
        return CascadeDiagnostics()

    relay_reachable = _port_open(config.relay_host, config.relay_port) if config.enabled else False
    upstream_reachable = _port_open(config.upstream_socks_host, config.upstream_socks_port) if config.enabled else False

    return CascadeDiagnostics(
        note="enabled — checking connectivity" if config.enabled else "disabled in config",
        config_present=True,
        relay_reachable=relay_reachable,
        upstream_reachable=upstream_reachable,
    )


def render_summary(config: CascadeConfig, diagnostics: CascadeDiagnostics | None = None) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_row("Mode", config.mode)
    table.add_row("Relay", f"{config.relay_host}:{config.relay_port}")
    table.add_row("Upstream SOCKS", f"{config.upstream_socks_host}:{config.upstream_socks_port}")
    table.add_row("Enabled", "yes" if config.enabled else "no")
    if diagnostics is not None:
        table.add_row("Status", diagnostics.note)
        table.add_row("Relay reachable", "yes" if diagnostics.relay_reachable else "no")
        table.add_row("Upstream reachable", "yes" if diagnostics.upstream_reachable else "no")
    else:
        table.add_row("Status", "not checked")
    return Panel(table, title="Cascade module", border_style="yellow")
