"""Real WARP actions for the terminal menu.

Each function returns an ActionResult that the menu can display.
All operations are safe-by-default: destructive ones require
a bool `confirmed` parameter.
"""
from __future__ import annotations

from dataclasses import dataclass

from daran_proxy_stack.lib.models import WarpConfig
from daran_proxy_stack.modules import warp as warp_mod


@dataclass
class ActionResult:
    ok: bool
    title: str
    body: str
    tip: str = ""


def default_config() -> WarpConfig:
    return WarpConfig()


# ---------------------------------------------------------------------------
# Read-only actions
# ---------------------------------------------------------------------------

def status() -> ActionResult:
    """Collect and return WARP diagnostics as text."""
    cfg = default_config()
    try:
        diag = warp_mod.collect_diagnostics(cfg)
    except Exception as exc:
        return ActionResult(False, "WARP: статус", f"Ошибка при сборе диагностики: {exc}")

    lines = [
        f"OS:                {diag.os_release}",
        f"warp-cli:          {diag.warp_cli_path or 'не найден'}",
        f"cloudflared:       {diag.cloudflared_path or 'не найден'}",
        f"systemctl:         {diag.systemctl_path or 'не найден'}",
        f"Server IP:         {diag.server_ip or 'unknown'}",
        f"WARP статус:       {diag.warp_status}",
        f"Подключён:         {'да' if diag.connected else 'нет'}",
        f"SOCKS запущен:     {'да' if diag.socks_running else 'нет'}",
        f"Рек. backend:      {diag.recommended_backend}",
        f"SOCKS endpoint:    {cfg.socks_host}:{cfg.socks_port}",
    ]
    return ActionResult(True, "WARP: статус", "\n".join(lines))


def xray_info() -> ActionResult:
    """Return Xray SOCKS outbound JSON snippet."""
    cfg = default_config()
    try:
        diag = warp_mod.collect_diagnostics(cfg)
        json_str = warp_mod.render_xray_outbound(cfg)
    except Exception as exc:
        return ActionResult(False, "WARP: Xray outbound", f"Ошибка: {exc}")

    socks_ok = diag.socks_running
    note = (
        "✓ SOCKS endpoint активен" if socks_ok
        else "⚠ SOCKS endpoint сейчас не слушает — запустите SOCKS прокси"
    )
    body = f"{note}\n\nJSON для xray/v2ray outbound:\n\n{json_str}"
    tip = "Сохранить: daran-net warp xray-json --save"
    return ActionResult(socks_ok, "WARP: Xray outbound JSON", body, tip=tip)


# ---------------------------------------------------------------------------
# Mutating actions (require explicit confirmation)
# ---------------------------------------------------------------------------

def install(confirmed: bool = False) -> ActionResult:
    """Install warp-cli. Requires confirmed=True."""
    if not confirmed:
        return ActionResult(
            False,
            "WARP: установка",
            "Требуется подтверждение.\n\n"
            "Будут выполнены:\n"
            "  • Добавление Cloudflare APT-репозитория\n"
            "  • apt-get install cloudflare-warp\n\n"
            "Поддерживаемые ОС: Debian/Ubuntu.",
            tip="Нажмите [y] для подтверждения.",
        )
    result = warp_mod.install_warp_cli()
    return ActionResult(result.ok, f"WARP: {result.title}", result.body)


def connect(confirmed: bool = False) -> ActionResult:
    """Connect WARP (registration new + connect). Requires confirmed=True."""
    if not confirmed:
        return ActionResult(
            False,
            "WARP: подключение",
            "Выполнит:\n"
            "  warp-cli registration new  (если ещё не зарегистрирован)\n"
            "  warp-cli connect",
            tip="Нажмите [y] для подтверждения.",
        )
    cfg = default_config()
    result = warp_mod.connect_warp(cfg)
    return ActionResult(result.ok, f"WARP: {result.title}", result.body)


def disconnect(confirmed: bool = False) -> ActionResult:
    """Disconnect WARP. Requires confirmed=True."""
    if not confirmed:
        return ActionResult(
            False,
            "WARP: отключение",
            "Выполнит:\n  warp-cli disconnect",
            tip="Нажмите [y] для подтверждения.",
        )
    result = warp_mod.disconnect_warp(default_config())
    return ActionResult(result.ok, f"WARP: {result.title}", result.body)


def socks_up(confirmed: bool = False) -> ActionResult:
    """Start local SOCKS5 proxy. Requires confirmed=True."""
    if not confirmed:
        return ActionResult(
            False,
            "WARP SOCKS: включить",
            "Запустит cloudflared SOCKS5 прокси локально.",
            tip="Нажмите [y] для подтверждения.",
        )
    cfg = default_config()
    result = warp_mod.start_local_socks(cfg)
    return ActionResult(result.ok, f"WARP: {result.title}", result.body)


def socks_down(confirmed: bool = False) -> ActionResult:
    """Stop local SOCKS5 proxy. Requires confirmed=True."""
    if not confirmed:
        return ActionResult(
            False,
            "WARP SOCKS: выключить",
            "Остановит cloudflared SOCKS5 процесс.",
            tip="Нажмите [y] для подтверждения.",
        )
    cfg = default_config()
    result = warp_mod.stop_local_socks(cfg)
    return ActionResult(result.ok, f"WARP: {result.title}", result.body)


def uninstall(confirmed: bool = False) -> ActionResult:
    """Uninstall warp-cli. Requires confirmed=True."""
    if not confirmed:
        return ActionResult(
            False,
            "WARP: удаление",
            "Выполнит:\n"
            "  warp-cli disconnect  (если подключён)\n"
            "  apt-get remove -y cloudflare-warp\n\n"
            "[yellow]Это удалит warp-cli и регистрацию WARP.[/yellow]",
            tip="Нажмите [y] для подтверждения.",
        )
    from daran_proxy_stack.lib.shell import run
    import shutil

    steps: list[str] = []

    warp_cli = shutil.which("warp-cli")
    if not warp_cli:
        return ActionResult(True, "WARP: удаление", "warp-cli не найден — уже удалён.")

    # Disconnect first (best effort)
    r = run([warp_cli, "--accept-tos", "disconnect"])
    steps.append(f"disconnect: {'ok' if r.ok else r.stderr or 'failed'}")

    # apt remove
    r = run(["sudo", "apt-get", "remove", "-y", "cloudflare-warp"])
    if r.ok:
        steps.append("apt remove cloudflare-warp: ok")
    else:
        steps.append(f"apt remove failed: {r.stderr or r.stdout}")
        return ActionResult(False, "WARP: удаление не удалось", "\n".join(steps))

    return ActionResult(True, "WARP: удалён", "\n".join(steps))
