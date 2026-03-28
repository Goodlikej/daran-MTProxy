"""Terminal-first interactive menu for daran-proxy-stack.

Entry point: ``daran-net menu``

Main menu options:
  1. Re-discover current system
  2. View detected modules / statuses
  0. Exit

No curses/TUI library required — uses rich + plain input() loop.
All rendering goes through render_* helpers so they're testable.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Callable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from daran_proxy_stack.discovery.runner import run_discovery
from daran_proxy_stack.discovery.schema import (
    DiscoveryConfidence,
    ModuleHealth,
    ObservedState,
)

console = Console()

# ---------------------------------------------------------------------------
# Colour / style helpers
# ---------------------------------------------------------------------------

_HEALTH_STYLE: dict[str, str] = {
    ModuleHealth.healthy.value: "bold green",
    ModuleHealth.degraded.value: "yellow",
    ModuleHealth.broken.value: "bold red",
    ModuleHealth.stopped.value: "dim",
    ModuleHealth.not_installed.value: "dim",
    ModuleHealth.unknown.value: "dim white",
}

_CONFIDENCE_STYLE: dict[str, str] = {
    DiscoveryConfidence.full.value: "green",
    DiscoveryConfidence.partial.value: "yellow",
    DiscoveryConfidence.none.value: "red",
}


def _health_text(health_val: str) -> Text:
    style = _HEALTH_STYLE.get(health_val, "white")
    return Text(health_val, style=style)


def _confidence_text(conf_val: str) -> Text:
    style = _CONFIDENCE_STYLE.get(conf_val, "white")
    return Text(conf_val, style=style)


# ---------------------------------------------------------------------------
# Render helpers (pure — take data, return renderable or string)
# ---------------------------------------------------------------------------

def render_host_summary(state: ObservedState) -> Panel:
    """Render a single-line host summary panel."""
    h = state.host
    ip = h.public_ip or "unknown"
    bbr = " BBR:on" if h.bbr_enabled else (" BBR:off" if h.bbr_enabled is False else "")
    text = f"[bold]{h.hostname}[/bold]  OS: {h.os} {h.version}  IP: {ip}{bbr}"
    return Panel(text, title="Host", border_style="cyan", expand=False)


def render_modules_table(state: ObservedState) -> Table:
    """Render modules as a compact table."""
    table = Table(
        title="Detected Modules",
        show_header=True,
        header_style="bold magenta",
        border_style="dim",
        expand=False,
    )
    table.add_column("Module", style="bold", min_width=10)
    table.add_column("Health", min_width=12)
    table.add_column("Running", min_width=7)
    table.add_column("Manager", min_width=9)
    table.add_column("Version", min_width=12)
    table.add_column("Confidence", min_width=10)

    module_map = {
        "warp": state.warp,
        "mtproxy": state.mtproxy,
        "cascade": state.cascade,
    }
    for name, mod in module_map.items():
        if mod is None:
            table.add_row(name, Text("no data", style="dim"), "-", "-", "-", "-")
            continue
        d = mod.to_dict()
        running_icon = "✓" if d.get("running") else "✗"
        running_style = "green" if d.get("running") else "dim"
        table.add_row(
            name,
            _health_text(d.get("health", "unknown")),
            Text(running_icon, style=running_style),
            d.get("manager", "-"),
            d.get("version") or "-",
            _confidence_text(d.get("confidence", "none")),
        )
    return table


def render_discovery_meta(state: ObservedState) -> Panel:
    """Render discovery run metadata."""
    m = state.discovery
    ts = m.last_run_at
    status_style = "green" if m.status == "ok" else "yellow"
    lines = [f"Status: [{status_style}]{m.status}[/{status_style}]  Run at: {ts}"]
    if m.warnings:
        lines.append("[yellow]Warnings:[/yellow]")
        for w in m.warnings:
            lines.append(f"  • {w}")
    if m.partial_modules:
        lines.append(f"[yellow]Partial:[/yellow] {', '.join(m.partial_modules)}")
    return Panel("\n".join(lines), title="Discovery", border_style="dim", expand=False)


def render_module_detail(name: str, mod_state) -> Panel:
    """Render expanded details for a single module."""
    if mod_state is None:
        return Panel(f"No data for {name}", title=name, border_style="red")
    d = mod_state.to_dict()
    lines: list[str] = []

    health_val = d.get("health", "unknown")
    health_style = _HEALTH_STYLE.get(health_val, "white")
    lines.append(f"Health:    [{health_style}]{health_val}[/{health_style}]")
    lines.append(f"Installed: {d.get('installed')}")
    lines.append(f"Running:   {d.get('running')}")
    lines.append(f"Enabled:   {d.get('enabled')}")
    lines.append(f"Manager:   {d.get('manager', '-')}")
    lines.append(f"Version:   {d.get('version') or '-'}")
    lines.append(f"Confidence: {d.get('confidence', '-')}")

    ports = d.get("ports", [])
    if ports:
        lines.append("Ports:")
        for p in ports:
            lines.append(f"  {p['bind']}:{p['port']}/{p['protocol']}  [{p['purpose']}]")

    # Module-specific extras
    if name == "mtproxy":
        ep = d.get("public_endpoint")
        ca = d.get("client_artifacts")
        rt = d.get("runtime")
        if ep:
            lines.append(f"Endpoint:  {ep.get('ip')}:{ep.get('port')}")
        if ca:
            lines.append(f"Secret:    {'present' if ca.get('secret_present') else 'missing'}")
            if ca.get("tg_link"):
                lines.append(f"tg link:   {ca['tg_link']}")
        if rt:
            lines.append(f"Container: {rt.get('container_name') or '-'}  running={rt.get('container_running')}")

    if name == "warp":
        reg = d.get("registration")
        net = d.get("network")
        if reg:
            lines.append(f"Registered:{reg.get('registered')}  type={reg.get('account_type') or '-'}")
        if net:
            lines.append(f"Server IP: {net.get('server_ip') or '-'}")
            lines.append(f"Egress IP: {net.get('warp_ip') or '-'}")
            lines.append(f"Egress changed: {net.get('egress_changed')}")

    warnings = d.get("warnings", [])
    errors = d.get("errors", [])
    if warnings:
        lines.append("[yellow]Warnings:[/yellow]")
        for w in warnings:
            lines.append(f"  • {w}")
    if errors:
        lines.append("[red]Errors:[/red]")
        for e in errors:
            lines.append(f"  • {e}")

    return Panel("\n".join(lines), title=f"Module: {name}", border_style="dim", expand=False)


def render_full_discovery(state: ObservedState) -> None:
    """Print full discovery output to console."""
    console.print()
    console.print(render_host_summary(state))
    console.print(render_discovery_meta(state))
    console.print(render_modules_table(state))


# ---------------------------------------------------------------------------
# Menu actions
# ---------------------------------------------------------------------------

def cmd_rediscover() -> ObservedState:
    """Run discovery and render results. Returns the new state."""
    console.print("\n[bold cyan]Running discovery…[/bold cyan]")
    state = run_discovery()
    render_full_discovery(state)
    return state


def cmd_view_modules(state: ObservedState | None) -> None:
    """Show module details. If no state yet, prompt to run discovery first."""
    if state is None:
        console.print("[yellow]No discovery data yet. Run Re-discover first.[/yellow]")
        return
    console.print()
    for name in ("warp", "mtproxy", "cascade"):
        mod = getattr(state, name, None)
        console.print(render_module_detail(name, mod))


# ---------------------------------------------------------------------------
# Main menu loop
# ---------------------------------------------------------------------------

_MENU_ITEMS = [
    ("1", "Re-discover current system"),
    ("2", "View detected modules / statuses"),
    ("0", "Exit"),
]


def _print_main_menu() -> None:
    lines = [""]
    for key, label in _MENU_ITEMS:
        lines.append(f"  [{key}] {label}")
    lines.append("")
    console.print(Panel(
        "\n".join(lines),
        title="[bold]daran-proxy-stack[/bold]  main menu",
        border_style="cyan",
        expand=False,
    ))


def run_menu(
    input_fn: Callable[[], str] | None = None,
    once: bool = False,
) -> None:
    """Run the interactive menu loop.

    Args:
        input_fn: Injectable input function (for testing). Defaults to input().
        once:     If True, exit after a single iteration (for testing).
    """
    _input = input_fn or (lambda: input("  choice > ").strip())
    last_state: ObservedState | None = None

    while True:
        _print_main_menu()
        try:
            choice = _input()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Exiting.[/dim]")
            break

        if choice == "1":
            last_state = cmd_rediscover()
        elif choice == "2":
            cmd_view_modules(last_state)
        elif choice == "0":
            console.print("[dim]Goodbye.[/dim]")
            break
        else:
            console.print(f"[red]Unknown choice: {choice!r}[/red]")

        if once:
            break
