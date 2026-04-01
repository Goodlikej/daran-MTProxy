"""Real WARP actions for the terminal menu.

Each function returns an ActionResult that the menu can display.
All operations are safe-by-default: destructive ones require
a bool `confirmed` parameter.
"""
from __future__ import annotations

import json as _json
from dataclasses import dataclass
from pathlib import Path

from daran_proxy_stack.lib.models import WarpConfig
from daran_proxy_stack.modules import warp as warp_mod

_WARP_PORT_FILE = Path.home() / ".daran-proxy-stack" / "warp-port.json"


@dataclass
class ActionResult:
    ok: bool
    title: str
    body: str
    tip: str = ""


def default_config() -> WarpConfig:
    cfg = WarpConfig()
    if _WARP_PORT_FILE.exists():
        try:
            data = _json.loads(_WARP_PORT_FILE.read_text(encoding="utf-8"))
            cfg = cfg.model_copy(update={"socks_port": data.get("socks_port", cfg.socks_port)})
        except Exception:
            pass
    return cfg


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
            "  warp-cli registration new   (если ещё не зарегистрирован)\n"
            "  warp-cli set-mode proxy     ← не меняет таблицу маршрутизации\n"
            "  warp-cli connect",
            tip="Режим proxy: SSH-сессия не прерывается. WARP доступен через SOCKS5 127.0.0.1:40000.",
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


# ---------------------------------------------------------------------------
# SOCKS5 settings actions
# ---------------------------------------------------------------------------

def xray_routing_info() -> ActionResult:
    """Return Xray outbound JSON + routing rule example for 3X-UI."""
    cfg = default_config()
    outbound = warp_mod.render_xray_outbound(cfg)
    routing = _json.dumps(
        {
            "type": "field",
            "outboundTag": "warp-out",
            "domain": ["geosite:openai", "geosite:netflix", "geosite:disney"],
        },
        ensure_ascii=False,
        indent=2,
    )
    body = (
        "── Outbound (вставить в раздел outbounds) ──\n\n"
        f"{outbound}\n\n"
        "── Routing rule (вставить в routing.rules) ──\n\n"
        f"{routing}"
    )
    return ActionResult(True, "WARP: JSON для 3X-UI", body)


def xui_integration_guide() -> ActionResult:
    """Return step-by-step guide for connecting 3X-UI to WARP via SOCKS5."""
    cfg = default_config()
    socks = f"{cfg.socks_host}:{cfg.socks_port}"
    body = (
        f"SOCKS5-прокси: {socks}\n\n"
        "ШАГ 1: Убедитесь что WARP подключён и SOCKS запущен\n"
        "  Меню WARP → [5] Подключить → [7] SOCKS прокси включить\n\n"
        "ШАГ 2: Откройте панель 3X-UI\n"
        "  Settings → Xray Settings → вкладка Outbound\n"
        "  Добавить новый outbound:\n"
        "    Protocol: Socks\n"
        f"    Address: {cfg.socks_host}   Port: {cfg.socks_port}\n"
        "    Tag: warp-out\n\n"
        "ШАГ 3: Settings → Xray Settings → вкладка Routing\n"
        '  Добавить rule: outboundTag "warp-out"\n'
        '  domain: ["geosite:openai","geosite:netflix","geosite:disney"]\n\n'
        "ШАГ 4: Save → перезапустить Xray\n\n"
        f"Схема: Клиент → 3X-UI → SOCKS5 ({socks}) → Cloudflare WARP → Интернет"
    )
    return ActionResult(True, "WARP: инструкция для 3X-UI", body)


def set_socks_port(port: int, confirmed: bool = False) -> ActionResult:
    """Change SOCKS5 port, persisted to ~/.daran-proxy-stack/warp-port.json."""
    if not 1 <= port <= 65535:
        return ActionResult(False, "WARP: порт SOCKS5", "Порт вне диапазона 1–65535")
    cur = default_config().socks_port
    if not confirmed:
        return ActionResult(
            False,
            "WARP: изменить порт SOCKS5",
            f"Сменить порт SOCKS5 с {cur} на {port}.\n"
            "Текущий SOCKS прокси потребует перезапуска.",
        )
    _WARP_PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _WARP_PORT_FILE.write_text(_json.dumps({"socks_port": port}), encoding="utf-8")
    return ActionResult(True, "WARP: порт SOCKS5", f"Порт сохранён: {port}\nПерезапустите SOCKS прокси.")
