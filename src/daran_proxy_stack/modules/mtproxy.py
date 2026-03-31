from __future__ import annotations

import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import qrcode
from rich.panel import Panel
from rich.table import Table

from daran_proxy_stack.lib.files import ensure_dir, write_text
from daran_proxy_stack.lib.models import MTProxyConfig
from daran_proxy_stack.lib.shell import run

OFFICIAL_REPO = "https://github.com/TelegramMessenger/MTProxy"
PROXY_SECRET_URL = "https://core.telegram.org/getProxySecret"
PROXY_CONFIG_URL = "https://core.telegram.org/getProxyConfig"
OFFICIAL_INSTALL_DIR = "/opt/MTProxy"


@dataclass
class MTProxyDiagnostics:
    docker_path: str | None
    docker_compose_path: str | None
    systemctl_path: str | None
    ufw_path: str | None
    ss_path: str | None
    git_path: str | None
    curl_path: str | None
    make_path: str | None
    gcc_path: str | None
    server_ip: str | None
    container_status: str
    port_status: str
    compose_exists: bool
    run_user_exists: bool


def detect_server_ip() -> str | None:
    result = run(["bash", "-lc", "hostname -I | awk '{print $1}'"])
    if result.ok and result.stdout:
        return result.stdout.strip()
    return None


def detect_port_status(port: int) -> str:
    ss_path = shutil.which("ss")
    if not ss_path:
        return "ss not found"
    result = run([ss_path, "-ltnp", f"( sport = :{port} )"])
    if not result.ok:
        return result.stderr or "unable to inspect"
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if len(lines) <= 1:
        return "free"
    return "occupied by some listener"


def is_port_free(port: int) -> bool:
    return detect_port_status(port) == "free"


def suggest_free_ports(preferred: list[int] | None = None, limit: int = 5) -> list[int]:
    candidates = preferred or [443, 8443, 9443, 2053, 2083, 2087, 2096, 30000, 35000, 40000]
    found: list[int] = []
    for port in candidates:
        if is_port_free(port):
            found.append(port)
        if len(found) >= limit:
            break
    return found


def collect_diagnostics(config: MTProxyConfig) -> MTProxyDiagnostics:
    docker_path = shutil.which("docker")
    docker_compose_path = shutil.which("docker-compose")
    systemctl_path = shutil.which("systemctl")
    ufw_path = shutil.which("ufw")
    ss_path = shutil.which("ss")
    git_path = shutil.which("git")
    curl_path = shutil.which("curl")
    make_path = shutil.which("make")
    gcc_path = shutil.which("gcc")

    container_status = "not installed"
    if docker_path:
        result = run([
            docker_path,
            "ps",
            "-a",
            "--filter",
            f"name={config.container_name}",
            "--format",
            "{{.Names}}\t{{.Status}}",
        ])
        if result.ok:
            container_status = result.stdout or "not installed"
        elif result.stderr:
            container_status = result.stderr

    compose_exists = False
    if (Path.cwd() / "artifacts" / "generated" / "mtproxy" / "docker-compose.yml").exists():
        compose_exists = True

    run_user_check = run(["bash", "-lc", f"id -u {config.run_user}"])

    return MTProxyDiagnostics(
        docker_path=docker_path,
        docker_compose_path=docker_compose_path,
        systemctl_path=systemctl_path,
        ufw_path=ufw_path,
        ss_path=ss_path,
        git_path=git_path,
        curl_path=curl_path,
        make_path=make_path,
        gcc_path=gcc_path,
        server_ip=detect_server_ip(),
        container_status=container_status,
        port_status=detect_port_status(config.listen_port),
        compose_exists=compose_exists,
        run_user_exists=run_user_check.ok,
    )


def build_secret(config: MTProxyConfig, existing_secret: str | None = None) -> str:
    if config.secret:
        return config.secret
    if existing_secret:
        return existing_secret.strip()
    return secrets.token_hex(16)


def render_summary(config: MTProxyConfig, diagnostics: MTProxyDiagnostics | None = None) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_row("Listen host", config.listen_host)
    table.add_row("Listen port", str(config.listen_port))
    table.add_row("Stats port", str(config.stats_port))
    table.add_row("Run user", config.run_user)
    table.add_row("Workers", str(config.workers))
    table.add_row("Ad tag", config.ad_tag or "not set")
    table.add_row("Container", config.container_name)
    table.add_row("Image", config.image)
    if diagnostics is None:
        table.add_row("Status", "planned / not installed yet")
    else:
        table.add_row("Server IP", diagnostics.server_ip or "unknown")
        table.add_row("docker", diagnostics.docker_path or "not found")
        table.add_row("docker-compose", diagnostics.docker_compose_path or "not found")
        table.add_row("git", diagnostics.git_path or "not found")
        table.add_row("curl", diagnostics.curl_path or "not found")
        table.add_row("make", diagnostics.make_path or "not found")
        table.add_row("gcc", diagnostics.gcc_path or "not found")
        table.add_row("systemctl", diagnostics.systemctl_path or "not found")
        table.add_row("ufw", diagnostics.ufw_path or "not found")
        table.add_row("ss", diagnostics.ss_path or "not found")
        table.add_row("Run user exists", "yes" if diagnostics.run_user_exists else "no")
        table.add_row("Compose generated", "yes" if diagnostics.compose_exists else "no")
        table.add_row("Container status", diagnostics.container_status)
        table.add_row("Port status", diagnostics.port_status)
    return Panel(table, title="MTProxy module", border_style="magenta")


def render_tg_link(config: MTProxyConfig, public_ip: str | None = None, secret: str | None = None) -> str:
    server = public_ip or config.public_host or "YOUR_SERVER_IP"
    query = urlencode(
        {
            "server": server,
            "port": str(config.listen_port),
            "secret": build_secret(config, existing_secret=secret),
        }
    )
    return f"tg://proxy?{query}"


def render_compose_yaml(config: MTProxyConfig, secret: str | None = None) -> str:
    actual_secret = build_secret(config, existing_secret=secret)
    command = (
        f"./mtproto-proxy -u {config.run_user} -p {config.stats_port} -H {config.listen_port} "
        f"-S {actual_secret} --aes-pwd /data/proxy-secret /data/proxy-multi.conf -M {config.workers}"
    )
    if config.ad_tag:
        command += f" -P {config.ad_tag}"
    if config.use_host_network:
        network_block = "    network_mode: host\n"
        ports_block = ""
    else:
        network_block = ""
        ports_block = (
            f"    ports:\n"
            f"      - \"{config.listen_port}:{config.listen_port}/tcp\"\n"
            f"      - \"127.0.0.1:{config.stats_port}:{config.stats_port}/tcp\"\n"
        )
    return f"""services:
  mtproxy:
    image: {config.image}
    container_name: {config.container_name}
    restart: unless-stopped
{network_block}{ports_block}    working_dir: /mtproxy
    command: >-
      sh -lc '{command}'
    volumes:
      - ./data:/data
"""


def render_management_commands(compose_path: Path, config: MTProxyConfig) -> dict[str, str]:
    compose_cmd = f"docker compose -f {compose_path}"
    return {
        "up": f"{compose_cmd} up -d",
        "down": f"{compose_cmd} down",
        "restart": f"{compose_cmd} restart",
        "remove": f"{compose_cmd} down --remove-orphans",
        "logs": f"{compose_cmd} logs --tail=100",
        "status": f"docker ps -a --filter name={config.container_name}",
    }


def render_qr_ascii(data: str) -> str:
    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    dark = "██"
    light = "  "
    lines = []
    for row in matrix:
        lines.append("".join(dark if cell else light for cell in row))
    return "\n".join(lines)


def render_official_run_command(config: MTProxyConfig, install_dir: str = OFFICIAL_INSTALL_DIR, secret: str | None = None) -> str:
    actual_secret = build_secret(config, existing_secret=secret)
    command = (
        f"{install_dir}/objs/bin/mtproto-proxy -u {config.run_user} -p {config.stats_port} -H {config.listen_port} "
        f"-S {actual_secret} --aes-pwd {install_dir}/proxy-secret {install_dir}/proxy-multi.conf -M {config.workers}"
    )
    if config.ad_tag:
        command += f" -P {config.ad_tag}"
    return command


def render_systemd_service(config: MTProxyConfig, secret: str | None = None, install_dir: str = OFFICIAL_INSTALL_DIR) -> str:
    exec_start = render_official_run_command(config, install_dir=install_dir, secret=secret)
    return f"""[Unit]
Description=MTProxy
After=network.target

[Service]
Type=simple
WorkingDirectory={install_dir}
ExecStart={exec_start}
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""


def render_official_setup_notes(config: MTProxyConfig) -> str:
    lines = [
        f"Official source: {OFFICIAL_REPO}",
        "Canonical flow:",
        "1. Clone/build official MTProxy from source.",
        f"2. Download proxy-secret from {PROXY_SECRET_URL}",
        f"3. Download proxy-multi.conf from {PROXY_CONFIG_URL}",
        "4. Run mtproto-proxy with listen port + stats port + user secret.",
        "5. Optionally register ad tag with @MTProxybot and add -P.",
        "6. Generate tg://proxy link for clients.",
        "7. Prefer systemd for production; Docker is secondary/legacy here.",
    ]
    if config.ad_tag:
        lines.append(f"Configured ad tag: {config.ad_tag}")
    return "\n".join(lines)


def render_fetch_commands(install_dir: str = OFFICIAL_INSTALL_DIR) -> str:
    return (
        f"mkdir -p {install_dir} && cd {install_dir}\n"
        f"curl -fsSL {PROXY_SECRET_URL} -o proxy-secret\n"
        f"curl -fsSL {PROXY_CONFIG_URL} -o proxy-multi.conf"
    )


def render_install_command_sequence(config: MTProxyConfig, service_path: str, install_dir: str = OFFICIAL_INSTALL_DIR) -> str:
    build = render_build_commands(install_dir=install_dir)
    fetch = render_fetch_commands(install_dir=install_dir)
    return (
        f"{build} && {fetch} && "
        f"install -m 0644 {service_path} /etc/systemd/system/MTProxy.service && "
        "systemctl daemon-reload && systemctl enable --now MTProxy.service"
    )


def render_official_doctor_report(config: MTProxyConfig, diagnostics: MTProxyDiagnostics, generated_dir: Path) -> str:
    checks = [
        ("git", diagnostics.git_path is not None),
        ("curl", diagnostics.curl_path is not None),
        ("make", diagnostics.make_path is not None),
        ("gcc", diagnostics.gcc_path is not None),
        ("systemctl", diagnostics.systemctl_path is not None),
        (f"run user {config.run_user}", diagnostics.run_user_exists),
        (f"listen port {config.listen_port}", diagnostics.port_status == "free"),
        ("proxy-secret stub", (generated_dir / "data" / "proxy-secret").exists()),
        ("proxy-multi.conf stub", (generated_dir / "data" / "proxy-multi.conf").exists()),
    ]
    lines = ["Official MTProxy doctor:"]
    for name, ok in checks:
        lines.append(f"- [{'OK' if ok else 'NO'}] {name}")
    lines.append("")
    lines.append(f"Port check detail: {diagnostics.port_status}")
    suggested = suggest_free_ports()
    if suggested:
        lines.append("Suggested free ports: " + ", ".join(str(p) for p in suggested))
    lines.append("Note: occupied port is not fatal for planning, but blocks a clean MTProxy bind.")
    return "\n".join(lines)


def render_build_commands(install_dir: str = OFFICIAL_INSTALL_DIR) -> str:
    return (
        "apt update && apt install -y git curl build-essential libssl-dev zlib1g-dev\n"
        f"git clone {OFFICIAL_REPO} {install_dir} || (cd {install_dir} && git pull --ff-only)\n"
        f"cd {install_dir} && make"
    )


def render_bootstrap_script(config: MTProxyConfig, secret: str | None = None, install_dir: str = OFFICIAL_INSTALL_DIR) -> str:
    run_cmd = render_official_run_command(config, install_dir=install_dir, secret=secret)
    service_body = render_systemd_service(config, secret=secret, install_dir=install_dir)
    escaped_service = service_body.replace("'", "'\"'\"'")
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        f"INSTALL_DIR={install_dir!r}\n"
        "apt update\n"
        "apt install -y git curl build-essential libssl-dev zlib1g-dev\n"
        f"if [ ! -d \"$INSTALL_DIR/.git\" ]; then\n  git clone {OFFICIAL_REPO} \"$INSTALL_DIR\"\nelse\n  git -C \"$INSTALL_DIR\" pull --ff-only\nfi\n"
        "cd \"$INSTALL_DIR\"\n"
        "make\n"
        f"curl -fsSL {PROXY_SECRET_URL} -o \"$INSTALL_DIR/proxy-secret\"\n"
        f"curl -fsSL {PROXY_CONFIG_URL} -o \"$INSTALL_DIR/proxy-multi.conf\"\n"
        f"cat > /etc/systemd/system/MTProxy.service <<'EOF'\n{service_body}EOF\n"
        "systemctl daemon-reload\n"
        "systemctl enable --now MTProxy.service\n"
        f"echo 'Run command: {run_cmd}'\n"
    )


KEY_REFRESH_SERVICE_NAME = "mtproxy-key-refresh"


def refresh_official_keys(install_dir: str = OFFICIAL_INSTALL_DIR) -> tuple[bool, str]:
    """Download fresh proxy-secret and proxy-multi.conf from Telegram servers."""
    lines = []
    ok = True
    for url, filename in [
        (PROXY_SECRET_URL, "proxy-secret"),
        (PROXY_CONFIG_URL, "proxy-multi.conf"),
    ]:
        dest = Path(install_dir) / filename
        r = run(["curl", "-fsSL", url, "-o", str(dest)])
        if r.ok:
            lines.append(f"✓ {filename} обновлён")
        else:
            lines.append(f"✗ {filename}: {r.stderr or 'ошибка загрузки'}")
            ok = False
    return ok, "\n".join(lines)


def render_key_refresh_service(install_dir: str = OFFICIAL_INSTALL_DIR) -> str:
    """Render systemd oneshot service for key refresh."""
    return (
        "[Unit]\n"
        "Description=MTProxy key refresh (proxy-secret + proxy-multi.conf)\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart=/bin/bash -c 'curl -fsSL {PROXY_SECRET_URL} -o {install_dir}/proxy-secret"
        f" && curl -fsSL {PROXY_CONFIG_URL} -o {install_dir}/proxy-multi.conf"
        " && systemctl restart MTProxy'\n"
    )


def render_key_refresh_timer() -> str:
    """Render systemd monthly timer for key refresh."""
    return (
        "[Unit]\n"
        "Description=MTProxy key refresh — monthly timer\n"
        "\n"
        "[Timer]\n"
        "OnCalendar=monthly\n"
        "Persistent=true\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def save_generated_files(base_dir: Path, config: MTProxyConfig, public_ip: str | None = None) -> dict[str, Path]:
    generated_dir = ensure_dir(base_dir / "artifacts" / "generated" / "mtproxy")
    data_dir = ensure_dir(generated_dir / "data")
    secret_file = generated_dir / "secret.txt"
    existing_secret = secret_file.read_text(encoding="utf-8").strip() if secret_file.exists() else None
    secret = build_secret(config, existing_secret=existing_secret)
    tg_link = render_tg_link(config, public_ip=public_ip, secret=secret)
    compose_path = write_text(generated_dir / "docker-compose.yml", render_compose_yaml(config, secret=secret))
    secret_path = write_text(secret_file, secret + "\n")
    link_path = write_text(generated_dir / "tg-link.txt", tg_link + "\n")
    qr_path = write_text(generated_dir / "tg-link.qr.txt", render_qr_ascii(tg_link) + "\n")
    setup_notes_path = write_text(generated_dir / "official-setup-notes.txt", render_official_setup_notes(config) + "\n")
    fetch_path = write_text(generated_dir / "official-fetch.sh", render_fetch_commands() + "\n")
    build_path = write_text(generated_dir / "official-build.sh", render_build_commands() + "\n")
    bootstrap_path = write_text(generated_dir / "official-bootstrap.sh", render_bootstrap_script(config, secret=secret) + "\n")
    run_cmd_path = write_text(generated_dir / "official-run-command.sh", render_official_run_command(config, secret=secret) + "\n")
    service_path = write_text(generated_dir / "MTProxy.service", render_systemd_service(config, secret=secret))
    proxy_secret_path = write_text(data_dir / "proxy-secret", "# download from https://core.telegram.org/getProxySecret\n")
    proxy_multi_conf_path = write_text(data_dir / "proxy-multi.conf", "# download from https://core.telegram.org/getProxyConfig\n")
    return {
        "compose": compose_path,
        "secret": secret_path,
        "tg_link": link_path,
        "qr": qr_path,
        "official_notes": setup_notes_path,
        "official_fetch": fetch_path,
        "official_build": build_path,
        "official_bootstrap": bootstrap_path,
        "official_run": run_cmd_path,
        "systemd": service_path,
        "proxy_secret": proxy_secret_path,
        "proxy_multi_conf": proxy_multi_conf_path,
    }
