"""Monitoring actions: Telegram alerts + watchdog setup.

Provides:
  setup_monitoring  — configure bot token + chat_id, install watchdog systemd timer
  test_notification — send a test message to verify bot credentials
  monitoring_status — show current config + timer status
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from daran_proxy_stack.lib.notify import load_notify_config, save_notify_config, send_telegram
from daran_proxy_stack.lib.shell import run


@dataclass
class ActionResult:
    ok: bool
    title: str
    body: str
    tip: str = ""


_WATCHDOG_SERVICE_NAME = "daran-proxy-watchdog"
_WATCHDOG_SCRIPT_PATH = "/opt/daran-proxy-stack/watchdog.sh"


def _config_dir() -> Path:
    """Return config directory for notify settings."""
    candidates = [
        Path("/opt/daran-proxy-stack"),
        Path("/var/lib/daran-proxy-stack"),
    ]
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "artifacts").exists():
            candidates.insert(0, p / "artifacts" / "generated")
            break
    for p in candidates:
        if p.exists():
            return p
    return candidates[-1]


def _render_watchdog_script(bot_token: str, chat_id: str, services: list[str]) -> str:
    """Generate a bash watchdog script that alerts on service failure."""
    checks = "\n".join(
        f'  if ! systemctl is-active --quiet {svc}; then\n'
        f'    FAILED="$FAILED {svc}"\n'
        f'  fi'
        for svc in services
    )
    return (
        "#!/usr/bin/env bash\n"
        "# daran-proxy-stack watchdog — auto-generated, do not edit manually\n"
        "set -euo pipefail\n\n"
        "FAILED=''\n"
        f"{checks}\n\n"
        "if [ -n \"$FAILED\" ]; then\n"
        f'  HOST=$(hostname -f 2>/dev/null || hostname)\n'
        f'  MSG="⚠ daran-proxy [$HOST]: сервис(ы) не работают:$FAILED"\n'
        f'  curl -fsSL -X POST "https://api.telegram.org/bot{bot_token}/sendMessage" \\\n'
        f'    -F "chat_id={chat_id}" \\\n'
        f'    -F "text=$MSG"\n'
        "fi\n"
    )


def _render_watchdog_service(script_path: str = _WATCHDOG_SCRIPT_PATH) -> str:
    return (
        "[Unit]\n"
        "Description=daran-proxy-stack watchdog\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart=/bin/bash {script_path}\n"
    )


def _render_watchdog_timer() -> str:
    return (
        "[Unit]\n"
        "Description=daran-proxy-stack watchdog — every 5 minutes\n"
        "\n"
        "[Timer]\n"
        "OnBootSec=2min\n"
        "OnUnitActiveSec=5min\n"
        "Persistent=true\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def monitoring_status() -> ActionResult:
    """Show current notify config and watchdog timer status."""
    cfg = load_notify_config(_config_dir())
    lines: list[str] = []

    if cfg:
        token = cfg.get("bot_token", "")
        token_preview = f"{token[:8]}…{token[-4:]}" if len(token) > 12 else token
        lines.append(f"Bot token: {token_preview}")
        lines.append(f"Chat ID:   {cfg.get('chat_id', 'не задан')}")
    else:
        lines.append("Конфигурация не найдена.")
        lines.append("Настройте: выберите «Настроить мониторинг».")

    # Timer status
    systemctl = shutil.which("systemctl")
    if systemctl:
        r = run([systemctl, "is-active", f"{_WATCHDOG_SERVICE_NAME}.timer"])
        timer_status = r.stdout.strip() if r.stdout.strip() else ("active" if r.ok else "inactive")
        lines.append(f"\nТаймер watchdog: {timer_status}")
    else:
        lines.append("\nsystemctl не найден")

    return ActionResult(bool(cfg), "Мониторинг: статус", "\n".join(lines))


def test_notification(bot_token: str, chat_id: str) -> ActionResult:
    """Send a test Telegram message to verify bot credentials."""
    import socket
    try:
        host = socket.gethostname()
    except Exception:
        host = "сервер"

    ok, msg = send_telegram(bot_token, chat_id, f"✅ daran-proxy-stack: тест уведомлений с [{host}]")
    if ok:
        return ActionResult(True, "Мониторинг: тест отправлен", f"Бот ответил успешно.\n{msg}")
    return ActionResult(False, "Мониторинг: ошибка отправки", f"Не удалось отправить:\n{msg}")


def setup_monitoring(
    bot_token: str,
    chat_id: str,
    services: list[str] | None = None,
    confirmed: bool = False,
) -> ActionResult:
    """Configure Telegram alerts and install watchdog systemd timer.

    confirmed=False → preview only.
    confirmed=True  → save config, write script/units, enable timer.
    """
    if not bot_token or not chat_id:
        return ActionResult(
            False,
            "Мониторинг: ошибка",
            "Необходимо указать bot_token и chat_id.\n\n"
            "Создайте бота через @BotFather и получите chat_id через @userinfobot.",
        )

    monitored = services or ["MTProxy"]
    script = _render_watchdog_script(bot_token, chat_id, monitored)
    svc = _render_watchdog_service()
    timer = _render_watchdog_timer()

    if not confirmed:
        return ActionResult(
            True,
            "Мониторинг: план настройки",
            f"Будет выполнено:\n\n"
            f"  1. Сохранить bot_token + chat_id в {_config_dir() / 'notify-config.json'}\n"
            f"  2. Записать watchdog скрипт → {_WATCHDOG_SCRIPT_PATH}\n"
            f"  3. Создать systemd сервис + таймер (каждые 5 мин)\n"
            f"  4. systemctl enable --now {_WATCHDOG_SERVICE_NAME}.timer\n\n"
            f"Контролируемые сервисы: {', '.join(monitored)}\n\n"
            f"--- watchdog.sh ---\n{script}",
            tip="Нажмите [y] для установки.",
        )

    steps: list[str] = []

    # 1. Save config
    try:
        save_notify_config(_config_dir(), bot_token, chat_id)
        steps.append(f"  ✓ конфиг сохранён → {_config_dir() / 'notify-config.json'}")
    except Exception as exc:
        steps.append(f"  ✗ конфиг: {exc}")

    # 2. Write watchdog script
    script_dir = Path(_WATCHDOG_SCRIPT_PATH).parent
    r = run(["sudo", "mkdir", "-p", str(script_dir)])
    if r.ok:
        import subprocess
        p = subprocess.run(
            ["sudo", "tee", _WATCHDOG_SCRIPT_PATH],
            input=script,
            text=True,
            capture_output=True,
        )
        if p.returncode == 0:
            run(["sudo", "chmod", "+x", _WATCHDOG_SCRIPT_PATH])
            steps.append(f"  ✓ {_WATCHDOG_SCRIPT_PATH}")
        else:
            steps.append(f"  ✗ скрипт: {p.stderr}")
    else:
        steps.append(f"  ✗ mkdir: {r.stderr}")

    # 3. Write systemd units
    import subprocess
    for unit_name, content in [
        (f"{_WATCHDOG_SERVICE_NAME}.service", svc),
        (f"{_WATCHDOG_SERVICE_NAME}.timer", timer),
    ]:
        unit_path = f"/etc/systemd/system/{unit_name}"
        p = subprocess.run(
            ["sudo", "tee", unit_path],
            input=content,
            text=True,
            capture_output=True,
        )
        ok = p.returncode == 0
        steps.append(f"  {'✓' if ok else '✗'} {unit_path}")

    # 4. Enable timer
    for cmd in [
        ["sudo", "systemctl", "daemon-reload"],
        ["sudo", "systemctl", "enable", "--now", f"{_WATCHDOG_SERVICE_NAME}.timer"],
    ]:
        r3 = run(cmd)
        steps.append(f"  {'✓' if r3.ok else '✗'} {' '.join(cmd[1:])}")

    body = "\n".join(steps) + "\n\nПроверить: sudo systemctl list-timers | grep watchdog"
    return ActionResult(True, "Мониторинг: настроен", body)
