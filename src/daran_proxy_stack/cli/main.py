from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from daran_proxy_stack import __version__
from daran_proxy_stack.lib.config import load_config
from daran_proxy_stack.lib.models import AppConfig, MTProxyConfig
from daran_proxy_stack.lib.shell import run
from daran_proxy_stack.modules.mtproxy import (
    collect_diagnostics as collect_mtproxy_diagnostics,
    is_port_free,
    render_install_command_sequence,
    render_management_commands,
    render_official_doctor_report,
    render_summary as render_mtproxy_summary,
    render_tg_link,
    save_generated_files,
    suggest_free_ports,
)
from daran_proxy_stack.modules.warp import (
    collect_diagnostics,
    connect_warp,
    disconnect_warp,
    install_warp_cli,
    render_backend_plan,
    render_debug_json,
    render_result_panel,
    render_summary,
    render_xray_outbound,
    save_xray_artifact,
    start_local_socks,
    stop_local_socks,
)

app = typer.Typer(help="Daran network toolkit for MTProxy, WARP, and relay/cascade scenarios.")
warp_app = typer.Typer(help="Manage Cloudflare WARP helper services.")
mtproxy_app = typer.Typer(help="Manage Telegram MTProxy helpers.")
app.add_typer(warp_app, name="warp")
app.add_typer(mtproxy_app, name="mtproxy")
console = Console()
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve_mtproxy_config(base_cfg: AppConfig, port: int | None = None, stats_port: int | None = None) -> AppConfig:
    mtproxy_data = base_cfg.mtproxy.model_dump()
    if port is not None:
        mtproxy_data["listen_port"] = port
    if stats_port is not None:
        mtproxy_data["stats_port"] = stats_port
    return AppConfig(paths=base_cfg.paths, warp=base_cfg.warp, mtproxy=MTProxyConfig(**mtproxy_data))


def _pick_port_or_prompt(port: int | None, prompt_text: str = "MTProxy listen port", default: int = 443) -> int:
    if port is not None:
        return port
    return typer.prompt(prompt_text, default=default, type=int)


def _validate_requested_port(port: int) -> str | None:
    if port < 1 or port > 65535:
        return "Port must be in range 1..65535"
    if not is_port_free(port):
        suggested = suggest_free_ports()
        suffix = f" Suggested free ports: {', '.join(str(p) for p in suggested)}" if suggested else ""
        return f"Port {port} is busy.{suffix}"
    return None


def _mtproxy_generated_compose_path() -> Path:
    return PROJECT_ROOT / "artifacts" / "generated" / "mtproxy" / "docker-compose.yml"


def _mtproxy_generated_secret_path() -> Path:
    return PROJECT_ROOT / "artifacts" / "generated" / "mtproxy" / "secret.txt"


def _mtproxy_existing_secret() -> str | None:
    secret_path = _mtproxy_generated_secret_path()
    return secret_path.read_text(encoding="utf-8").strip() if secret_path.exists() else None


@app.callback()
def main() -> None:
    return None


@app.command()
def version() -> None:
    console.print(f"daran-proxy-stack v{__version__}")


@app.command()
def doctor(config: Optional[Path] = typer.Option(None, help="Optional config path.")) -> None:
    cfg = load_config(config)
    console.print(Panel.fit("Project skeleton is alive. Modules are growing teeth.", title="doctor", border_style="green"))
    console.print(render_summary(cfg.warp, collect_diagnostics(cfg.warp)))
    console.print(render_mtproxy_summary(cfg.mtproxy, collect_mtproxy_diagnostics(cfg.mtproxy)))


@warp_app.command("status")
def warp_status(config: Optional[Path] = typer.Option(None, help="Optional config path.")) -> None:
    cfg = load_config(config)
    console.print(render_summary(cfg.warp, collect_diagnostics(cfg.warp)))


@warp_app.command("xray-json")
def warp_xray_json(config: Optional[Path] = typer.Option(None, help="Optional config path."), save: bool = typer.Option(False, "--save", help="Save generated outbound to artifacts/generated/warp/xray-outbound.json.")) -> None:
    cfg = load_config(config)
    content = render_xray_outbound(cfg.warp)
    console.print(content)
    if save:
        path = save_xray_artifact(cfg.warp)
        console.print(Panel.fit(f"saved to {path}", title="WARP xray artifact", border_style="green"))


@warp_app.command("plan")
def warp_plan() -> None:
    console.print(Panel.fit(
        "Next WARP MVP steps:\n"
        "1. dependency detection\n"
        "2. warp-cli/cloudflared strategy selection\n"
        "3. install helpers\n"
        "4. local SOCKS state + status\n"
        "5. Xray outbound JSON generation",
        title="WARP MVP plan",
        border_style="yellow",
    ))

@warp_app.command("install")
def warp_install() -> None:
    console.print(render_result_panel(install_warp_cli()))


@warp_app.command("connect")
def warp_connect(config: Optional[Path] = typer.Option(None, help="Optional config path.")) -> None:
    cfg = load_config(config)
    console.print(render_result_panel(connect_warp(cfg.warp)))


@warp_app.command("disconnect")
def warp_disconnect(config: Optional[Path] = typer.Option(None, help="Optional config path.")) -> None:
    cfg = load_config(config)
    console.print(render_result_panel(disconnect_warp(cfg.warp)))


@warp_app.command("socks-up")
def warp_socks_up(config: Optional[Path] = typer.Option(None, help="Optional config path.")) -> None:
    cfg = load_config(config)
    console.print(render_result_panel(start_local_socks(cfg.warp)))


@warp_app.command("socks-down")
def warp_socks_down(config: Optional[Path] = typer.Option(None, help="Optional config path.")) -> None:
    cfg = load_config(config)
    console.print(render_result_panel(stop_local_socks(cfg.warp)))


@warp_app.command("backend-plan")
def warp_backend_plan(config: Optional[Path] = typer.Option(None, help="Optional config path.")) -> None:
    cfg = load_config(config)
    diagnostics = collect_diagnostics(cfg.warp)
    console.print(Panel.fit(render_backend_plan(cfg.warp, diagnostics), title="WARP backend plan", border_style="cyan"))


@warp_app.command("debug-json")
def warp_debug_json(config: Optional[Path] = typer.Option(None, help="Optional config path.")) -> None:
    cfg = load_config(config)
    diagnostics = collect_diagnostics(cfg.warp)
    console.print(render_debug_json(cfg.warp, diagnostics))


@mtproxy_app.command("status")
def mtproxy_status(
    config: Optional[Path] = typer.Option(None, help="Optional config path."),
    port: Optional[int] = typer.Option(None, "--port", help="Override MTProxy listen port for this run."),
    stats_port: Optional[int] = typer.Option(None, "--stats-port", help="Override MTProxy stats port for this run."),
) -> None:
    cfg = _resolve_mtproxy_config(load_config(config), port=port, stats_port=stats_port)
    console.print(render_mtproxy_summary(cfg.mtproxy, collect_mtproxy_diagnostics(cfg.mtproxy)))


@mtproxy_app.command("tg-link")
def mtproxy_tg_link(
    config: Optional[Path] = typer.Option(None, help="Optional config path."),
    public_ip: Optional[str] = typer.Option(None, help="Override public IP or hostname for tg:// link."),
) -> None:
    cfg = load_config(config)
    console.print(render_tg_link(cfg.mtproxy, public_ip=public_ip, secret=_mtproxy_existing_secret()))


@mtproxy_app.command("qr")
def mtproxy_qr(
    config: Optional[Path] = typer.Option(None, help="Optional config path."),
    public_ip: Optional[str] = typer.Option(None, help="Override public IP or hostname for tg:// link."),
) -> None:
    cfg = load_config(config)
    paths = save_generated_files(PROJECT_ROOT, cfg.mtproxy, public_ip=public_ip)
    console.print((paths["qr"]).read_text(encoding="utf-8"))


@mtproxy_app.command("spec")
def mtproxy_spec(
    config: Optional[Path] = typer.Option(None, help="Optional config path."),
    public_ip: Optional[str] = typer.Option(None, help="Override public IP or hostname for tg:// link."),
) -> None:
    cfg = load_config(config)
    paths = save_generated_files(PROJECT_ROOT, cfg.mtproxy, public_ip=public_ip)
    console.print(Panel.fit(
        "Generated files:\n"
        f"- compose: {paths['compose']}\n"
        f"- secret: {paths['secret']}\n"
        f"- tg-link: {paths['tg_link']}\n"
        f"- qr: {paths['qr']}\n"
        f"- official notes: {paths['official_notes']}\n"
        f"- official fetch script: {paths['official_fetch']}\n"
        f"- official build script: {paths['official_build']}\n"
        f"- official bootstrap script: {paths['official_bootstrap']}\n"
        f"- official run cmd: {paths['official_run']}\n"
        f"- systemd unit: {paths['systemd']}\n"
        f"- proxy-secret stub: {paths['proxy_secret']}\n"
        f"- proxy-multi.conf stub: {paths['proxy_multi_conf']}",
        title="MTProxy spec",
        border_style="cyan",
    ))


@mtproxy_app.command("apply")
def mtproxy_apply(
    config: Optional[Path] = typer.Option(None, help="Optional config path."),
    public_ip: Optional[str] = typer.Option(None, help="Optional public IP/hostname for generated link."),
    yes: bool = typer.Option(False, "--yes", help="Actually run docker compose up -d."),
) -> None:
    cfg = load_config(config)
    diagnostics = collect_mtproxy_diagnostics(cfg.mtproxy)
    paths = save_generated_files(PROJECT_ROOT, cfg.mtproxy, public_ip=public_ip or cfg.mtproxy.public_host)
    commands = render_management_commands(paths["compose"], cfg.mtproxy)

    if not diagnostics.docker_path:
        console.print(Panel.fit("docker not found. Install Docker first, then rerun apply.", title="MTProxy apply blocked", border_style="red"))
        return

    if not yes:
        console.print(Panel.fit(
            "Dry run. Generated spec successfully.\n\n"
            "Note: official MTProxy repo says Docker image is outdated; production-preferred path is official build + systemd.\n\n"
            f"Legacy Docker command if you still want it:\n{commands['up']}\n\n"
            "Re-run with --yes to actually launch the container anyway.",
            title="MTProxy apply",
            border_style="yellow",
        ))
        return

    result = run(["bash", "-lc", commands["up"]])
    if result.ok:
        console.print(Panel.fit(
            "Legacy Docker launch command executed.\n\n"
            "Remember: official MTProxy docs prefer source build/systemd, Docker image is marked outdated.\n\n"
            f"stdout:\n{result.stdout or '(empty)'}",
            title="MTProxy apply complete",
            border_style="green",
        ))
    else:
        console.print(Panel.fit(
            f"Command failed:\n{commands['up']}\n\n"
            f"stderr:\n{result.stderr or '(empty)'}",
            title="MTProxy apply failed",
            border_style="red",
        ))


@mtproxy_app.command("official-doctor")
def mtproxy_official_doctor(
    config: Optional[Path] = typer.Option(None, help="Optional config path."),
    port: Optional[int] = typer.Option(None, "--port", help="Override MTProxy listen port for this run."),
    stats_port: Optional[int] = typer.Option(None, "--stats-port", help="Override MTProxy stats port for this run."),
) -> None:
    cfg = _resolve_mtproxy_config(load_config(config), port=port, stats_port=stats_port)
    paths = save_generated_files(PROJECT_ROOT, cfg.mtproxy, public_ip=cfg.mtproxy.public_host)
    diagnostics = collect_mtproxy_diagnostics(cfg.mtproxy)
    generated_dir = paths["compose"].parent
    console.print(Panel.fit(
        render_official_doctor_report(cfg.mtproxy, diagnostics, generated_dir),
        title="MTProxy official doctor",
        border_style="cyan",
    ))


@mtproxy_app.command("official-fetch")
def mtproxy_official_fetch(
    config: Optional[Path] = typer.Option(None, help="Optional config path."),
    yes: bool = typer.Option(False, "--yes", help="Actually fetch proxy-secret and proxy-multi.conf to /opt/MTProxy."),
) -> None:
    cfg = load_config(config)
    paths = save_generated_files(PROJECT_ROOT, cfg.mtproxy, public_ip=cfg.mtproxy.public_host)
    command = paths["official_fetch"].read_text(encoding="utf-8").strip()
    if not yes:
        console.print(Panel.fit(
            f"Dry run.\n\nCommand to execute:\n{command}\n\nRe-run with --yes to actually fetch the files.",
            title="MTProxy official fetch",
            border_style="yellow",
        ))
        return
    result = run(["bash", "-lc", command])
    if result.ok:
        console.print(Panel.fit("Fetched official MTProxy runtime files.", title="MTProxy official fetch complete", border_style="green"))
    else:
        console.print(Panel.fit(f"stderr:\n{result.stderr or '(empty)'}", title="MTProxy official fetch failed", border_style="red"))


@mtproxy_app.command("official-build")
def mtproxy_official_build(
    config: Optional[Path] = typer.Option(None, help="Optional config path."),
    yes: bool = typer.Option(False, "--yes", help="Actually clone/pull/build official MTProxy in /opt/MTProxy."),
) -> None:
    cfg = load_config(config)
    paths = save_generated_files(PROJECT_ROOT, cfg.mtproxy, public_ip=cfg.mtproxy.public_host)
    command = paths["official_build"].read_text(encoding="utf-8").strip()
    if not yes:
        console.print(Panel.fit(
            f"Dry run.\n\nCommand to execute:\n{command}\n\nRe-run with --yes to actually build official MTProxy.",
            title="MTProxy official build",
            border_style="yellow",
        ))
        return
    result = run(["bash", "-lc", command])
    if result.ok:
        console.print(Panel.fit("Official MTProxy build command completed.", title="MTProxy official build complete", border_style="green"))
    else:
        console.print(Panel.fit(f"stderr:\n{result.stderr or '(empty)'}", title="MTProxy official build failed", border_style="red"))


@mtproxy_app.command("official-install")
def mtproxy_official_install(
    config: Optional[Path] = typer.Option(None, help="Optional config path."),
    port: Optional[int] = typer.Option(None, "--port", help="Override MTProxy listen port for this run."),
    stats_port: Optional[int] = typer.Option(None, "--stats-port", help="Override MTProxy stats port for this run."),
    yes: bool = typer.Option(False, "--yes", help="Actually run build+fetch+systemd enable sequence."),
) -> None:
    base_cfg = load_config(config)
    selected_port = _pick_port_or_prompt(port, default=base_cfg.mtproxy.listen_port)
    port_error = _validate_requested_port(selected_port)
    if port_error:
        console.print(Panel.fit(port_error, title="MTProxy port check failed", border_style="red"))
        raise typer.Exit(code=2)
    selected_stats_port = stats_port or base_cfg.mtproxy.stats_port
    cfg = _resolve_mtproxy_config(base_cfg, port=selected_port, stats_port=selected_stats_port)
    paths = save_generated_files(PROJECT_ROOT, cfg.mtproxy, public_ip=cfg.mtproxy.public_host)
    command = render_install_command_sequence(cfg.mtproxy, str(paths["systemd"]))
    if not yes:
        console.print(Panel.fit(
            f"Dry run.\n\nCommand to execute:\n{command}\n\nRe-run with --yes to actually install official MTProxy service.",
            title="MTProxy official install",
            border_style="yellow",
        ))
        return
    result = run(["bash", "-lc", command])
    if result.ok:
        console.print(Panel.fit("Official MTProxy install sequence completed.", title="MTProxy official install complete", border_style="green"))
    else:
        console.print(Panel.fit(f"stderr:\n{result.stderr or '(empty)'}", title="MTProxy official install failed", border_style="red"))


@mtproxy_app.command("bootstrap")
def mtproxy_bootstrap(
    config: Optional[Path] = typer.Option(None, help="Optional config path."),
    public_ip: Optional[str] = typer.Option(None, help="Optional public IP/hostname for generated link."),
    port: Optional[int] = typer.Option(None, "--port", help="Override MTProxy listen port for this run."),
    stats_port: Optional[int] = typer.Option(None, "--stats-port", help="Override MTProxy stats port for this run."),
) -> None:
    base_cfg = load_config(config)
    selected_port = _pick_port_or_prompt(port, default=base_cfg.mtproxy.listen_port)
    port_error = _validate_requested_port(selected_port)
    if port_error:
        console.print(Panel.fit(port_error, title="MTProxy port check failed", border_style="red"))
        raise typer.Exit(code=2)
    cfg = _resolve_mtproxy_config(base_cfg, port=selected_port, stats_port=stats_port or base_cfg.mtproxy.stats_port)
    paths = save_generated_files(PROJECT_ROOT, cfg.mtproxy, public_ip=public_ip or cfg.mtproxy.public_host)
    console.print(Panel.fit(
        f"Official bootstrap script generated at:\n{paths['official_bootstrap']}\n\n"
        f"Fetch helper:\n{paths['official_fetch']}\n\n"
        f"Build helper:\n{paths['official_build']}\n\n"
        "This is the preferred direction over Docker.",
        title="MTProxy official bootstrap",
        border_style="green",
    ))


@mtproxy_app.command("systemd-apply")
def mtproxy_systemd_apply(
    config: Optional[Path] = typer.Option(None, help="Optional config path."),
    yes: bool = typer.Option(False, "--yes", help="Actually install the systemd unit to /etc/systemd/system."),
) -> None:
    cfg = load_config(config)
    paths = save_generated_files(PROJECT_ROOT, cfg.mtproxy, public_ip=cfg.mtproxy.public_host)
    service_path = paths["systemd"]
    command = (
        f"install -m 0644 {service_path} /etc/systemd/system/MTProxy.service && "
        "systemctl daemon-reload && systemctl enable MTProxy.service"
    )
    if not yes:
        console.print(Panel.fit(
            "Dry run. Generated systemd unit successfully.\n\n"
            f"Command to execute:\n{command}\n\n"
            "Re-run with --yes to actually install/enable the unit.",
            title="MTProxy systemd apply",
            border_style="yellow",
        ))
        return
    result = run(["bash", "-lc", command])
    if result.ok:
        console.print(Panel.fit(
            f"systemd unit installed/enabled.\n\nstdout:\n{result.stdout or '(empty)'}",
            title="MTProxy systemd apply complete",
            border_style="green",
        ))
    else:
        console.print(Panel.fit(
            f"Command failed:\n{command}\n\n"
            f"stderr:\n{result.stderr or '(empty)'}",
            title="MTProxy systemd apply failed",
            border_style="red",
        ))


@mtproxy_app.command("up")
def mtproxy_up(config: Optional[Path] = typer.Option(None, help="Optional config path.")) -> None:
    cfg = load_config(config)
    paths = save_generated_files(PROJECT_ROOT, cfg.mtproxy, public_ip=cfg.mtproxy.public_host)
    commands = render_management_commands(paths["compose"], cfg.mtproxy)
    console.print(Panel.fit(commands["up"], title="Run this to start MTProxy", border_style="green"))


@mtproxy_app.command("down")
def mtproxy_down(config: Optional[Path] = typer.Option(None, help="Optional config path.")) -> None:
    cfg = load_config(config)
    commands = render_management_commands(_mtproxy_generated_compose_path(), cfg.mtproxy)
    console.print(Panel.fit(commands["down"], title="Run this to stop MTProxy", border_style="yellow"))


@mtproxy_app.command("restart")
def mtproxy_restart(config: Optional[Path] = typer.Option(None, help="Optional config path.")) -> None:
    cfg = load_config(config)
    commands = render_management_commands(_mtproxy_generated_compose_path(), cfg.mtproxy)
    console.print(Panel.fit(commands["restart"], title="Run this to restart MTProxy", border_style="yellow"))


@mtproxy_app.command("remove")
def mtproxy_remove(config: Optional[Path] = typer.Option(None, help="Optional config path.")) -> None:
    cfg = load_config(config)
    commands = render_management_commands(_mtproxy_generated_compose_path(), cfg.mtproxy)
    console.print(Panel.fit(commands["remove"], title="Run this to remove MTProxy", border_style="red"))


@mtproxy_app.command("logs")
def mtproxy_logs(config: Optional[Path] = typer.Option(None, help="Optional config path.")) -> None:
    cfg = load_config(config)
    commands = render_management_commands(_mtproxy_generated_compose_path(), cfg.mtproxy)
    console.print(Panel.fit(commands["logs"], title="Run this to inspect MTProxy logs", border_style="blue"))


@mtproxy_app.command("suggest-ports")
def mtproxy_suggest_ports() -> None:
    suggested = suggest_free_ports()
    if not suggested:
        console.print(Panel.fit("No suggested free ports found in the current candidate list.", title="MTProxy port suggestions", border_style="yellow"))
        return
    console.print(Panel.fit(", ".join(str(p) for p in suggested), title="MTProxy suggested free ports", border_style="cyan"))


@mtproxy_app.command("plan")
def mtproxy_plan() -> None:
    console.print(Panel.fit(
        "Next MTProxy MVP steps:\n"
        "1. official source-build flow\n"
        "2. proxy-secret + proxy-multi.conf fetch helpers\n"
        "3. systemd unit generation/apply\n"
        "4. tg://proxy link + QR helper\n"
        "5. basic firewall and diagnostics\n"
        "6. keep Docker only as secondary compatibility path",
        title="MTProxy MVP plan",
        border_style="yellow",
    ))


@app.command("menu")
def menu_cmd() -> None:
    """Interactive terminal menu: discover system, view module statuses."""
    from daran_proxy_stack.cli.menu import run_menu
    run_menu()


@app.command("discover")
def discover_cmd() -> None:
    """Run discovery and print observed system state (non-interactive)."""
    from daran_proxy_stack.cli.menu import render_full_discovery
    from daran_proxy_stack.discovery.runner import run_discovery
    state = run_discovery()
    render_full_discovery(state)


@app.command("panel")
def panel(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(7331, help="Bind port"),
    reload: bool = typer.Option(False, help="Enable auto-reload (dev mode)"),
) -> None:
    """Start the web management panel (FastAPI/uvicorn)."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn is not installed — run: pip install 'daran-proxy-stack[dev]'[/red]")
        raise typer.Exit(1)
    console.print(Panel(
        f"Web panel → [link]http://{host}:{port}[/link]\n"
        f"API docs  → [link]http://{host}:{port}/api/docs[/link]\n\n"
        "Views: Overview · Servers · MTProxy · WARP · Jobs\n"
        "Press Ctrl-C to stop.",
        title="Daran Proxy Stack · Panel",
        border_style="cyan",
    ))
    uvicorn.run(
        "daran_proxy_stack.web.app:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    app()
