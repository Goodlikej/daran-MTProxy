"""AmneziaWG management module.

AmneziaWG is an obfuscated fork of WireGuard that hides traffic from DPI
by adding configurable junk packets before each handshake.

Handles:
  - Installation via apt (PPA) or manual deb download
  - Server config generation (keys + wg0.conf)
  - Client (peer) config generation
  - Service management via systemd awg-quick@wg0
  - Peer add/list/remove
  - State persistence in artifacts/generated/amneziawg/
"""
from __future__ import annotations

import base64
import json
import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from daran_proxy_stack.lib.files import ensure_dir, write_text
from daran_proxy_stack.lib.models import AmneziaWGConfig
from daran_proxy_stack.lib.shell import run

AWG_INSTALL_DIR = "/etc/amneziawg"
AWG_INTERFACE = "wg0"
AWG_SERVICE = "awg-quick@wg0"
AWG_STATE_FILE = "awg-state.json"

# AmneziaWG GitHub release page (for manual install reference)
AWG_RELEASES_URL = "https://github.com/amnezia-vpn/amneziawg-linux-kernel-module/releases"
AWG_TOOLS_URL = "https://github.com/amnezia-vpn/amneziawg-tools"


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

@dataclass
class AmneziaWGDiagnostics:
    awg_path: str | None
    awg_quick_path: str | None
    systemctl_path: str | None
    iptables_path: str | None
    is_installed: bool
    service_status: str      # "active" | "inactive" | "not-found" | "unknown"
    interface_up: bool
    server_ip: str | None
    config_exists: bool
    peers_count: int


def detect_awg() -> str | None:
    return shutil.which("awg")


def detect_awg_quick() -> str | None:
    return shutil.which("awg-quick")


def is_installed() -> bool:
    return detect_awg() is not None and detect_awg_quick() is not None


def _service_status() -> str:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return "unknown"
    r = run([systemctl, "is-active", AWG_SERVICE])
    status = r.stdout.strip()
    return status if status else ("active" if r.ok else "inactive")


def _interface_up(interface: str = AWG_INTERFACE) -> bool:
    ip_bin = shutil.which("ip")
    if not ip_bin:
        return False
    r = run([ip_bin, "link", "show", interface])
    return r.ok and "UP" in (r.stdout or "")


def _count_peers(generated_dir: Path) -> int:
    peers_dir = generated_dir / "peers"
    if not peers_dir.exists():
        return 0
    return len(list(peers_dir.glob("*.conf")))


def collect_diagnostics(config: AmneziaWGConfig, generated_dir: Path | None = None) -> AmneziaWGDiagnostics:
    if generated_dir is None:
        generated_dir = _default_generated_dir()
    config_path = Path(AWG_INSTALL_DIR) / f"{config.interface}.conf"
    return AmneziaWGDiagnostics(
        awg_path=detect_awg(),
        awg_quick_path=detect_awg_quick(),
        systemctl_path=shutil.which("systemctl"),
        iptables_path=shutil.which("iptables"),
        is_installed=is_installed(),
        service_status=_service_status(),
        interface_up=_interface_up(config.interface),
        server_ip=_detect_public_ip(),
        config_exists=config_path.exists(),
        peers_count=_count_peers(generated_dir),
    )


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

def generate_keypair() -> tuple[str, str]:
    """Generate (private_key, public_key) using awg, wg, or pure Python fallback.

    Returns base64-encoded Curve25519 keys compatible with WireGuard/AmneziaWG.
    """
    # Try awg first
    for tool in ("awg", "wg"):
        bin_path = shutil.which(tool)
        if bin_path is None:
            continue
        r_priv = run([bin_path, "genkey"])
        if r_priv.ok and r_priv.stdout:
            private_key = r_priv.stdout.strip()
            # Derive public key
            import subprocess
            p = subprocess.run(
                [bin_path, "pubkey"],
                input=private_key,
                text=True,
                capture_output=True,
            )
            if p.returncode == 0 and p.stdout.strip():
                return private_key, p.stdout.strip()

    # Pure-Python Curve25519 fallback (no external deps)
    return _python_curve25519_keypair()


def _python_curve25519_keypair() -> tuple[str, str]:
    """Generate Curve25519 keypair in pure Python.

    Implements the RFC 7748 scalar multiplication on Curve25519.
    Returns (private_key_b64, public_key_b64) in WireGuard base64 format.
    """
    raw_private = bytearray(secrets.token_bytes(32))
    # Clamp as per RFC 7748
    raw_private[0] &= 248
    raw_private[31] &= 127
    raw_private[31] |= 64

    public_bytes = _curve25519_mul(bytes(raw_private), _BASE_POINT)
    priv_b64 = base64.b64encode(bytes(raw_private)).decode()
    pub_b64 = base64.b64encode(public_bytes).decode()
    return priv_b64, pub_b64


# Curve25519 constants
_P = 2**255 - 19
_BASE_POINT = (9).to_bytes(32, "little")


def _curve25519_mul(scalar: bytes, point: bytes) -> bytes:
    """Curve25519 scalar multiplication (RFC 7748 §5)."""
    u = int.from_bytes(point, "little") % _P
    k = int.from_bytes(scalar, "little")

    x1, x2, z2, x3, z3 = u, 1, 0, u, 1
    swap = 0
    for t in range(254, -1, -1):
        kt = (k >> t) & 1
        if kt ^ swap:
            x2, x3 = x3, x2
            z2, z3 = z3, z2
        swap = kt
        A = (x2 + z2) % _P
        AA = A * A % _P
        B = (x2 - z2) % _P
        BB = B * B % _P
        E = (AA - BB) % _P
        C = (x3 + z3) % _P
        D = (x3 - z3) % _P
        DA = D * A % _P
        CB = C * B % _P
        x3 = pow(DA + CB, 2, _P)
        z3 = u * pow(DA - CB, 2, _P) % _P
        x2 = AA * BB % _P
        z2 = E * (AA + 121665 * E) % _P
    if swap:
        x2, x3 = x3, x2
        z2, z3 = z3, z2
    result = x2 * pow(z2, _P - 2, _P) % _P
    return result.to_bytes(32, "little")


# ---------------------------------------------------------------------------
# Config rendering
# ---------------------------------------------------------------------------

def _detect_public_ip() -> str | None:
    for url in ["https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"]:
        r = run(["curl", "-s", "--max-time", "5", url])
        if r.ok and r.stdout.strip():
            ip = r.stdout.strip().split()[0]
            parts = ip.split(".")
            if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                return ip
    return None


def _detect_default_interface() -> str:
    """Detect the main network interface for iptables PostUp/PostDown."""
    r = run(["bash", "-c", "ip route show default | awk '/default/ {print $5; exit}'"])
    iface = r.stdout.strip()
    return iface if iface else "eth0"


def render_server_config(
    config: AmneziaWGConfig,
    private_key: str,
    peers: list[dict] | None = None,
) -> str:
    """Render wg0.conf server config for AmneziaWG."""
    iface = _detect_default_interface()
    lines = [
        "[Interface]",
        f"Address = {config.server_address}",
        f"ListenPort = {config.listen_port}",
        f"PrivateKey = {private_key}",
        f"Jc = {config.jc}",
        f"Jmin = {config.jmin}",
        f"Jmax = {config.jmax}",
        f"S1 = {config.s1}",
        f"S2 = {config.s2}",
        f"H1 = {config.h1}",
        f"H2 = {config.h2}",
        f"H3 = {config.h3}",
        f"H4 = {config.h4}",
        f"PostUp = iptables -A FORWARD -i %i -j ACCEPT; "
        f"iptables -A FORWARD -o %i -j ACCEPT; "
        f"iptables -t nat -A POSTROUTING -o {iface} -j MASQUERADE",
        f"PostDown = iptables -D FORWARD -i %i -j ACCEPT; "
        f"iptables -D FORWARD -o %i -j ACCEPT; "
        f"iptables -t nat -D POSTROUTING -o {iface} -j MASQUERADE",
        "",
    ]
    for peer in (peers or []):
        lines += [
            f"# Peer: {peer.get('name', 'unknown')}",
            "[Peer]",
            f"PublicKey = {peer['public_key']}",
            f"AllowedIPs = {peer['allowed_ips']}",
            "",
        ]
    return "\n".join(lines)


def render_client_config(
    config: AmneziaWGConfig,
    server_public_key: str,
    server_ip: str,
    client_private_key: str,
    client_address: str,
) -> str:
    """Render client config for a peer."""
    lines = [
        "[Interface]",
        f"Address = {client_address}/32",
        f"PrivateKey = {client_private_key}",
        f"DNS = {config.dns}",
        f"Jc = {config.jc}",
        f"Jmin = {config.jmin}",
        f"Jmax = {config.jmax}",
        f"S1 = {config.s1}",
        f"S2 = {config.s2}",
        f"H1 = {config.h1}",
        f"H2 = {config.h2}",
        f"H3 = {config.h3}",
        f"H4 = {config.h4}",
        "",
        "[Peer]",
        f"PublicKey = {server_public_key}",
        f"Endpoint = {server_ip}:{config.listen_port}",
        "AllowedIPs = 0.0.0.0/0",
        f"PersistentKeepalive = {config.persistent_keepalive}",
    ]
    return "\n".join(lines)


def render_install_script() -> str:
    """Render a bash install script for AmneziaWG on Debian/Ubuntu."""
    return (
        "#!/usr/bin/env bash\n"
        "# AmneziaWG installation script — Debian/Ubuntu\n"
        "set -euo pipefail\n\n"
        "# Install kernel module and userspace tools\n"
        "apt update\n"
        "apt install -y software-properties-common\n\n"
        "# Ubuntu PPA\n"
        "if command -v add-apt-repository &>/dev/null; then\n"
        "  add-apt-repository -y ppa:amnezia/amneziawg\n"
        "  apt update\n"
        "  apt install -y amneziawg amneziawg-tools\n"
        "else\n"
        "  # Debian: download deb from GitHub releases\n"
        f"  echo 'Visit {AWG_RELEASES_URL} and download the .deb for your kernel.'\n"
        "  echo 'Then: dpkg -i amneziawg-*.deb'\n"
        "  exit 1\n"
        "fi\n\n"
        "# Enable IP forwarding\n"
        "sysctl -w net.ipv4.ip_forward=1\n"
        "grep -qxF 'net.ipv4.ip_forward=1' /etc/sysctl.conf "
        "|| echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf\n\n"
        "echo '✓ AmneziaWG установлен'\n"
        "awg --version 2>/dev/null || echo 'awg binary not in PATH'\n"
    )


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def _default_generated_dir() -> Path:
    here = Path(__file__).resolve()
    for p in here.parents:
        candidate = p / "artifacts" / "generated" / "amneziawg"
        if candidate.parent.parent.exists():
            return candidate
    return Path("/opt/daran-proxy-stack/artifacts/generated/amneziawg")


def load_state(generated_dir: Path) -> dict:
    """Load AWG state from awg-state.json."""
    state_file = generated_dir / AWG_STATE_FILE
    if not state_file.exists():
        return {"peers": [], "server_public_key": None, "server_ip": None}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {"peers": [], "server_public_key": None, "server_ip": None}


def save_state(generated_dir: Path, state: dict) -> None:
    ensure_dir(generated_dir)
    (generated_dir / AWG_STATE_FILE).write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def save_generated_files(
    base_dir: Path,
    config: AmneziaWGConfig,
    private_key: str,
    public_key: str,
    peers: list[dict] | None = None,
    server_ip: str | None = None,
) -> dict[str, Path]:
    """Write server config, keys, and state to artifacts directory."""
    gen = ensure_dir(base_dir / "artifacts" / "generated" / "amneziawg")
    peers_dir = ensure_dir(gen / "peers")

    server_conf = render_server_config(config, private_key, peers)
    paths: dict[str, Path] = {
        "server_conf": write_text(gen / "wg0.conf", server_conf),
        "private_key": write_text(gen / "server-private.key", private_key + "\n"),
        "public_key": write_text(gen / "server-public.key", public_key + "\n"),
        "install_script": write_text(gen / "install-awg.sh", render_install_script()),
    }

    # State
    state = load_state(gen)
    state["server_public_key"] = public_key
    state["server_ip"] = server_ip
    state["listen_port"] = config.listen_port
    state["server_address"] = config.server_address
    if "peers" not in state:
        state["peers"] = []
    save_state(gen, state)

    return paths


def add_peer(
    generated_dir: Path,
    config: AmneziaWGConfig,
    peer_name: str,
) -> tuple[bool, str, Path | None]:
    """Generate a new peer keypair, update server config, and save client config.

    Returns (ok, message, client_conf_path).
    """
    state = load_state(generated_dir)
    server_public_key = state.get("server_public_key")
    server_ip = state.get("server_ip")

    if not server_public_key:
        return False, "Сервер не настроен. Сначала сгенерируйте серверный конфиг.", None
    if not server_ip:
        server_ip = _detect_public_ip() or "YOUR_SERVER_IP"

    # Assign next available IP
    existing_ips = {p["address"] for p in state.get("peers", [])}
    subnet_base = config.client_subnet  # e.g. "10.8.0"
    client_ip: str | None = None
    for last_octet in range(2, 254):
        candidate = f"{subnet_base}.{last_octet}"
        if candidate not in existing_ips:
            client_ip = candidate
            break
    if client_ip is None:
        return False, "Все адреса в подсети заняты (максимум 252 пира).", None

    # Generate peer keypair
    try:
        peer_priv, peer_pub = generate_keypair()
    except Exception as exc:
        return False, f"Ошибка генерации ключей: {exc}", None

    # Save client config
    peers_dir = ensure_dir(generated_dir / "peers")
    client_conf_content = render_client_config(
        config,
        server_public_key=server_public_key,
        server_ip=server_ip,
        client_private_key=peer_priv,
        client_address=client_ip,
    )
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in peer_name)
    client_conf_path = write_text(peers_dir / f"{safe_name}.conf", client_conf_content)

    # Update state
    peer_entry = {
        "name": peer_name,
        "public_key": peer_pub,
        "address": client_ip,
        "allowed_ips": f"{client_ip}/32",
    }
    state.setdefault("peers", []).append(peer_entry)
    save_state(generated_dir, state)

    # Rewrite server config with updated peers
    priv_key_file = generated_dir / "server-private.key"
    if priv_key_file.exists():
        priv_key = priv_key_file.read_text(encoding="utf-8").strip()
        server_conf = render_server_config(config, priv_key, state["peers"])
        write_text(generated_dir / "wg0.conf", server_conf)

    return True, f"Пир «{peer_name}» добавлен → {client_ip}", client_conf_path


def remove_peer(generated_dir: Path, config: AmneziaWGConfig, peer_name: str) -> tuple[bool, str]:
    """Remove a peer by name from state and regenerate server config."""
    state = load_state(generated_dir)
    peers = state.get("peers", [])
    before = len(peers)
    state["peers"] = [p for p in peers if p["name"] != peer_name]
    if len(state["peers"]) == before:
        return False, f"Пир «{peer_name}» не найден."

    save_state(generated_dir, state)

    # Remove client conf file
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in peer_name)
    conf_file = generated_dir / "peers" / f"{safe_name}.conf"
    if conf_file.exists():
        conf_file.unlink()

    # Rewrite server config
    priv_key_file = generated_dir / "server-private.key"
    if priv_key_file.exists():
        priv_key = priv_key_file.read_text(encoding="utf-8").strip()
        server_conf = render_server_config(config, priv_key, state["peers"])
        write_text(generated_dir / "wg0.conf", server_conf)

    return True, f"Пир «{peer_name}» удалён."


def apply_config_to_system(generated_dir: Path, config: AmneziaWGConfig) -> tuple[bool, str]:
    """Copy wg0.conf to /etc/amneziawg/ and reload interface."""
    src = generated_dir / "wg0.conf"
    if not src.exists():
        return False, "wg0.conf не найден. Сначала сгенерируйте конфиг."

    steps: list[str] = []
    # Create dir
    r = run(["sudo", "mkdir", "-p", AWG_INSTALL_DIR])
    steps.append(f"  mkdir -p {AWG_INSTALL_DIR}: {'ok' if r.ok else r.stderr}")

    # Copy config with restricted permissions
    import subprocess
    p = subprocess.run(
        ["sudo", "tee", f"{AWG_INSTALL_DIR}/{config.interface}.conf"],
        input=src.read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
    )
    steps.append(f"  tee {AWG_INSTALL_DIR}/{config.interface}.conf: {'ok' if p.returncode == 0 else p.stderr}")
    r2 = run(["sudo", "chmod", "600", f"{AWG_INSTALL_DIR}/{config.interface}.conf"])
    steps.append(f"  chmod 600: {'ok' if r2.ok else r2.stderr}")

    ok = r.ok and p.returncode == 0
    return ok, "\n".join(steps)
