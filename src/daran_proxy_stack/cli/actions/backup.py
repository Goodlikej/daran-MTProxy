"""Backup / restore actions for the terminal menu."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from daran_proxy_stack.lib import backup as backup_lib


@dataclass
class ActionResult:
    ok: bool
    title: str
    body: str
    tip: str = ""


def create_backup(confirmed: bool = False) -> ActionResult:
    """Create a timestamped tar.gz backup of all generated artifacts.

    confirmed=False → show what will be backed up (dry run).
    confirmed=True  → create archive.
    """
    if not confirmed:
        archives = backup_lib.list_available_backups()
        existing = (
            f"\nСуществующих резервных копий: {len(archives)}"
            + (f"\n  Последняя: {archives[0].name}" if archives else "")
        )
        return ActionResult(
            True,
            "Резервная копия: план",
            "Будет создан архив tar.gz со следующими файлами:\n\n"
            "  • mtproxy/secret.txt  (секрет прокси)\n"
            "  • mtproxy/tg-link.txt  (ссылка для клиентов)\n"
            "  • mtproxy/MTProxy.service  (systemd unit)\n"
            "  • mtproxy/data/proxy-secret + proxy-multi.conf\n"
            "  • cascade/relay-state.json  (конфиг relay)\n"
            "  • cascade/rules.json  (правила 3proxy)\n"
            "  • notify-config.json  (Telegram бот)\n"
            f"{existing}",
            tip="Нажмите [y] для создания архива.",
        )

    ok, msg, archive_path = backup_lib.create_backup()
    if ok:
        return ActionResult(True, "Резервная копия создана", msg)
    return ActionResult(False, "Ошибка резервного копирования", msg)


def list_backups() -> ActionResult:
    """Show all available backup archives."""
    archives = backup_lib.list_available_backups()
    if not archives:
        return ActionResult(
            False,
            "Резервные копии",
            "Резервных копий не найдено.\n\n"
            "Создайте первую копию выбрав «Создать резервную копию».",
        )

    lines = [f"Найдено архивов: {len(archives)}", ""]
    for i, p in enumerate(archives, 1):
        size_kb = p.stat().st_size // 1024
        from datetime import datetime
        mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        lines.append(f"  [{i}] {p.name}  ({size_kb} КБ, {mtime})")
    lines.append(f"\nДиректория: {archives[0].parent}")
    return ActionResult(True, "Резервные копии", "\n".join(lines))


def inspect_backup(archive_path: Path) -> ActionResult:
    """Show contents of a specific backup archive."""
    ok, msg = backup_lib.list_backup_contents(archive_path)
    return ActionResult(ok, "Содержимое архива", msg)


def restore_backup(archive_path: Path, confirmed: bool = False) -> ActionResult:
    """Restore from a backup archive.

    confirmed=False → preview only.
    confirmed=True  → extract and overwrite.
    """
    ok, msg = backup_lib.restore_backup(archive_path, confirmed=confirmed)
    if not confirmed:
        title = "Восстановление: план"
    elif ok:
        title = "Восстановление выполнено"
    else:
        title = "Ошибка восстановления"
    return ActionResult(ok, title, msg)
