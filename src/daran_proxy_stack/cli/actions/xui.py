"""3x-ui actions for the terminal menu.

3x-ui is an Xray-based web panel installed via an official shell script.
It is NOT a daran-proxy-stack native module — it runs independently.

Detection strategy:
  1. Check systemctl unit  «x-ui»
  2. Check process «x-ui»
  3. Probe web UI at localhost:2053

Install path:
  Guides the user to run the official installer script in their terminal.
  We never pipe-to-bash automatically — that's the operator's call.

Status is always safe (read-only checks), install is guide-only.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from daran_proxy_stack.lib.shell import run


@dataclass
class ActionResult:
    ok: bool
    title: str
    body: str
    tip: str = ""


# Default web UI port for 3x-ui
_XUI_DEFAULT_PORT = 2053
_XUI_INSTALL_SCRIPT_URL = (
    "https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh"
)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def _detect_xui_systemd() -> tuple[bool, bool]:
    """(unit_exists, is_active)."""
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False, False
    r = run([systemctl, "status", "x-ui", "--no-pager"])
    if r.returncode == 4:  # unit not found
        return False, False
    unit_exists = r.returncode in (0, 3)  # 0=active, 3=inactive
    is_active = r.returncode == 0
    return unit_exists, is_active


def _detect_xui_process() -> bool:
    """True if x-ui process is running."""
    pgrep = shutil.which("pgrep")
    if not pgrep:
        r = run(["pidof", "x-ui"])
        return r.ok and bool(r.stdout.strip())
    r = run([pgrep, "-f", "x-ui"])
    return r.ok and bool(r.stdout.strip())


def _detect_xui_binary() -> str | None:
    """Return path to x-ui binary if found."""
    for p in [
        "/usr/local/x-ui/x-ui",
        "/usr/bin/x-ui",
        shutil.which("x-ui"),
    ]:
        if p and Path(p).exists():
            return p
    return None


def _probe_web_ui(port: int = _XUI_DEFAULT_PORT) -> bool:
    """True if something is listening on localhost:<port>."""
    r = run(
        ["bash", "-c", f"timeout 1 bash -c 'echo >/dev/tcp/127.0.0.1/{port}' 2>/dev/null && echo ok || echo fail"],
    )
    return r.ok and "ok" in (r.stdout or "")


# ---------------------------------------------------------------------------
# Public actions
# ---------------------------------------------------------------------------

def status() -> ActionResult:
    """Detect 3x-ui installation and runtime state."""
    unit_exists, is_active = _detect_xui_systemd()
    process_running = _detect_xui_process()
    binary = _detect_xui_binary()
    web_up = _probe_web_ui(_XUI_DEFAULT_PORT)

    installed = bool(binary or unit_exists)
    running = is_active or process_running

    lines: list[str] = [
        f"Бинарный файл:  {binary or 'не найден'}",
        f"systemd unit:   {'существует' if unit_exists else 'не найден'}",
        f"Служба active:  {'да' if is_active else 'нет'}",
        f"Процесс x-ui:   {'запущен' if process_running else 'не запущен'}",
        f"Web UI :{_XUI_DEFAULT_PORT}:    {'отвечает' if web_up else 'не отвечает'}",
        "",
        f"Итог:  {'установлен' if installed else 'не установлен'}  /  "
        f"{'работает' if running else 'остановлен'}",
    ]

    if installed and not running:
        lines.append("")
        lines.append("Для запуска:  sudo systemctl start x-ui")
    elif not installed:
        lines.append("")
        lines.append("3x-ui не обнаружен. Используйте «Установить» для инструкции.")
    elif web_up:
        lines.append("")
        lines.append(f"Web-панель доступна: http://localhost:{_XUI_DEFAULT_PORT}")
        lines.append("Логин по умолчанию: admin / admin  (смените после установки!)")

    ok = running
    return ActionResult(ok, "3x-ui: статус", "\n".join(lines))


def install_guide(confirmed: bool = False) -> ActionResult:
    """Show the official 3x-ui install path.

    If confirmed=False: show preview + the command to run.
    If confirmed=True:  show the install command and instructions clearly
                        (does NOT execute it — that's the operator's job).
    """
    # Pre-check: already installed?
    unit_exists, _ = _detect_xui_systemd()
    binary = _detect_xui_binary()
    if binary or unit_exists:
        return ActionResult(
            True,
            "3x-ui: установка",
            f"3x-ui уже установлен: {binary or 'systemd unit найден'}.\n\n"
            "Используйте «Статус» для проверки состояния.",
        )

    if not confirmed:
        return ActionResult(
            False,
            "3x-ui: установка",
            "Установка выполняется через официальный скрипт mhsanaei/3x-ui.\n\n"
            "Команда для запуска в вашем терминале:\n\n"
            f"  bash <(curl -Ls {_XUI_INSTALL_SCRIPT_URL})\n\n"
            "Скрипт выполнит:\n"
            "  • Загрузку последнего релиза с GitHub\n"
            "  • Установку в /usr/local/x-ui/\n"
            "  • Регистрацию systemd-службы x-ui\n"
            "  • Открытие веб-панели на порту 2053\n\n"
            "[yellow]⚠ Скрипт требует root. Перед запуском проверьте содержимое.[/yellow]",
            tip="Нажмите [y] чтобы скопировать команду в консоль.",
        )

    # confirmed=True — output the full command prominently so operator can copy-paste
    body = (
        "Команда установки 3x-ui (выполните в терминале от root):\n\n"
        "────────────────────────────────────────────────────\n"
        f"bash <(curl -Ls {_XUI_INSTALL_SCRIPT_URL})\n"
        "────────────────────────────────────────────────────\n\n"
        "После установки:\n"
        f"  1. Откройте  http://<server-ip>:{_XUI_DEFAULT_PORT}/\n"
        "  2. Войдите: admin / admin\n"
        "  3. Сразу смените пароль в настройках панели\n"
        "  4. Настройте входящие (inbounds) для VLESS/VMess/Trojan\n\n"
        "Управление службой:\n"
        "  sudo systemctl status x-ui\n"
        "  sudo systemctl restart x-ui\n"
        "  sudo x-ui  # интерактивный скрипт управления"
    )
    return ActionResult(
        True,
        "3x-ui: инструкция по установке",
        body,
        tip="Команда не выполнялась автоматически. Скопируйте и запустите вручную.",
    )


def service_restart() -> ActionResult:
    """Restart x-ui systemd service if available."""
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return ActionResult(
            False,
            "3x-ui: перезапуск",
            "systemctl не найден.\n\nВручную:\n  pkill x-ui && /usr/local/x-ui/x-ui",
        )

    unit_exists, _ = _detect_xui_systemd()
    if not unit_exists:
        return ActionResult(
            False,
            "3x-ui: перезапуск",
            "systemd unit x-ui не найден.\n"
            "Возможно, 3x-ui не установлен или установлен иначе.\n\n"
            "Проверьте: sudo systemctl status x-ui",
        )

    r = run(["sudo", "systemctl", "restart", "x-ui"])
    if r.ok:
        return ActionResult(True, "3x-ui: перезапуск", "systemctl restart x-ui: ok")
    return ActionResult(False, "3x-ui: перезапуск не удался", r.stderr or r.stdout or "unknown error")
