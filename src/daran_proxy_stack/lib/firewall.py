"""Shared firewall and port-check utilities.

Used by MTProxy and Cascade actions to:
  - Open ports in ufw after service installation
  - Persist iptables rules after relay setup
  - Check if a port is listening locally
  - Get server public IP for post-install verification
"""
from __future__ import annotations

import shutil

from daran_proxy_stack.lib.shell import run


def check_ufw_active() -> bool:
    """Return True if ufw is installed and currently active."""
    ufw = shutil.which("ufw")
    if not ufw:
        return False
    r = run(["sudo", "ufw", "status"])
    return r.ok and "status: active" in (r.stdout or "").lower()


def apply_ufw_rule(port: int, protocol: str = "tcp") -> tuple[bool, str]:
    """Open port in ufw. protocol: "tcp" | "udp" | "both".

    Returns (ok, message). Returns (True, skip_msg) if ufw absent or inactive —
    this is not an error, just informational.
    """
    ufw = shutil.which("ufw")
    if not ufw:
        return True, f"ufw не установлен — порт {port} не добавлен в firewall"

    if not check_ufw_active():
        return True, f"ufw не активен — пропускаем (firewall выключен)"

    protos = ["tcp", "udp"] if protocol == "both" else [protocol]
    errors: list[str] = []
    for p in protos:
        r = run(["sudo", "ufw", "allow", f"{port}/{p}"])
        if not r.ok:
            errors.append(f"{port}/{p}: {(r.stderr or r.stdout or '').strip()}")

    if errors:
        return False, "ufw ошибка:\n" + "\n".join(f"  {e}" for e in errors)

    if protocol == "both":
        return True, f"✓ ufw: порт {port}/tcp и {port}/udp открыты"
    return True, f"✓ ufw: порт {port}/{protocol} открыт"


def check_port_listening(port: int) -> bool:
    """Return True if any process is listening on the given TCP port."""
    ss = shutil.which("ss")
    if not ss:
        return False
    r = run([ss, "-ltnp", f"( sport = :{port} )"])
    if not r.ok:
        return False
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    return len(lines) > 1  # first line is header


def get_public_ip() -> str | None:
    """Detect server public IP via curl. Returns None on failure."""
    for url in ["https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"]:
        r = run(["curl", "-s", "--max-time", "5", url])
        if r.ok and r.stdout.strip():
            ip = r.stdout.strip().split()[0]
            # Basic sanity check: four numeric octets
            parts = ip.split(".")
            if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                return ip
    return None


def persist_iptables() -> tuple[bool, str]:
    """Save iptables rules for persistence across reboots.

    Tries netfilter-persistent first, then iptables-save.
    Returns (ok, message).
    """
    if shutil.which("netfilter-persistent"):
        r = run(["sudo", "netfilter-persistent", "save"])
        if r.ok:
            return True, "✓ Правила сохранены (netfilter-persistent save)"
        return False, f"netfilter-persistent ошибка: {(r.stderr or '').strip()}"

    if shutil.which("iptables-save"):
        r = run(["sudo", "bash", "-c",
                 "mkdir -p /etc/iptables && iptables-save > /etc/iptables/rules.v4"])
        if r.ok:
            return True, "✓ Правила сохранены → /etc/iptables/rules.v4"
        return False, f"iptables-save ошибка: {(r.stderr or '').strip()}"

    return False, (
        "⚠ netfilter-persistent не найден.\n"
        "  Установите: sudo apt install iptables-persistent\n"
        "  Затем:      sudo netfilter-persistent save"
    )
