"""Telegram notification helpers for daran-proxy-stack.

Usage:
    from daran_proxy_stack.lib.notify import send_telegram, load_notify_config, save_notify_config

    ok, msg = send_telegram(token, chat_id, "MTProxy is running ✓")
"""
from __future__ import annotations

import json
from pathlib import Path

from daran_proxy_stack.lib.shell import run

_CONFIG_FILE = "notify-config.json"
_TELEGRAM_API = "https://api.telegram.org"


def send_telegram(bot_token: str, chat_id: str, message: str) -> tuple[bool, str]:
    """Send a message via Telegram Bot API using curl.

    Returns:
        (True, success_msg) on success, (False, error_msg) on failure.
    """
    url = f"{_TELEGRAM_API}/bot{bot_token}/sendMessage"
    r = run([
        "curl", "-fsSL", "-X", "POST", url,
        "-F", f"chat_id={chat_id}",
        "-F", f"text={message}",
        "-F", "parse_mode=HTML",
    ])
    if r.ok:
        return True, "Сообщение отправлено"
    return False, r.stderr or r.stdout or "ошибка отправки"


def load_notify_config(config_dir: Path) -> dict | None:
    """Load notify config from config_dir/notify-config.json.

    Returns dict with keys 'bot_token' and 'chat_id', or None if not found.
    """
    cfg_path = config_dir / _CONFIG_FILE
    if not cfg_path.exists():
        return None
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_notify_config(config_dir: Path, bot_token: str, chat_id: str) -> None:
    """Save notify config to config_dir/notify-config.json."""
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = config_dir / _CONFIG_FILE
    cfg_path.write_text(
        json.dumps({"bot_token": bot_token, "chat_id": chat_id}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
