"""Backup and restore utilities for daran-proxy-stack.

Creates timestamped tar.gz archives of all generated artifacts:
  - MTProxy: secret.txt, tg-link.txt, MTProxy.service, data/
  - Cascade: relay-state.json, rules.json, 3proxy configs
  - Monitoring: notify-config.json

Usage:
    from daran_proxy_stack.lib.backup import create_backup, restore_backup, list_backup_contents
"""
from __future__ import annotations

import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path

# Files/dirs to always exclude from backup (generated binaries, secrets of secrets)
_EXCLUDE_PATTERNS = {"__pycache__", "*.pyc", "objs", ".git"}

# Relative paths inside an artifacts/generated/ tree worth backing up
_BACKUP_GLOBS = [
    "mtproxy/secret.txt",
    "mtproxy/tg-link.txt",
    "mtproxy/tg-link.qr.txt",
    "mtproxy/MTProxy.service",
    "mtproxy/official-bootstrap.sh",
    "mtproxy/official-run-command.sh",
    "mtproxy/data/proxy-secret",
    "mtproxy/data/proxy-multi.conf",
    "cascade/relay-state.json",
    "cascade/rules.json",
    "cascade/3proxy.cfg",
    "cascade/cascade.service",
    "notify-config.json",
]

_MANIFEST_NAME = "backup-manifest.json"


def _find_generated_dir() -> Path | None:
    """Locate artifacts/generated/ directory by walking up from this file."""
    here = Path(__file__).resolve()
    for p in here.parents:
        candidate = p / "artifacts" / "generated"
        if candidate.exists():
            return candidate
    # Production paths
    for prod in [
        Path("/opt/daran-proxy-stack/artifacts/generated"),
        Path("/var/lib/daran-proxy-stack/generated"),
    ]:
        if prod.exists():
            return prod
    return None


def _collect_files(generated_dir: Path) -> list[Path]:
    """Collect all existing backup-worthy files from generated_dir."""
    found: list[Path] = []
    for rel in _BACKUP_GLOBS:
        p = generated_dir / rel
        if p.exists():
            found.append(p)
    return found


def create_backup(output_dir: Path | None = None) -> tuple[bool, str, Path | None]:
    """Create a timestamped tar.gz backup archive.

    Args:
        output_dir: Where to write the archive. Defaults to artifacts/backups/.

    Returns:
        (ok, message, archive_path_or_None)
    """
    generated_dir = _find_generated_dir()
    if generated_dir is None:
        return False, "Директория артефактов не найдена. Сначала установите хотя бы один сервис.", None

    files = _collect_files(generated_dir)
    if not files:
        return False, "Нет файлов для резервного копирования. Сначала выполните установку/генерацию.", None

    # Output directory
    if output_dir is None:
        output_dir = generated_dir.parent / "backups"
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_name = f"daran-proxy-backup-{ts}.tar.gz"
    archive_path = output_dir / archive_name

    # Build manifest
    manifest = {
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "generated_dir": str(generated_dir),
        "files": [str(f.relative_to(generated_dir)) for f in files],
        "version": 1,
    }

    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            # Add manifest first
            import io
            manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode()
            info = tarfile.TarInfo(name=_MANIFEST_NAME)
            info.size = len(manifest_bytes)
            tar.addfile(info, io.BytesIO(manifest_bytes))

            # Add each file preserving relative path inside generated_dir
            for f in files:
                arcname = str(f.relative_to(generated_dir))
                tar.add(f, arcname=arcname)

        size_kb = archive_path.stat().st_size // 1024
        lines = [
            f"Архив создан: {archive_path}",
            f"Размер: {size_kb} КБ",
            f"Файлов: {len(files)}",
            "",
        ] + [f"  • {str(f.relative_to(generated_dir))}" for f in files]
        return True, "\n".join(lines), archive_path

    except Exception as exc:
        return False, f"Ошибка создания архива: {exc}", None


def list_backup_contents(archive_path: Path) -> tuple[bool, str]:
    """List files inside a backup archive."""
    if not archive_path.exists():
        return False, f"Файл не найден: {archive_path}"
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            names = tar.getnames()
            # Read manifest if present
            manifest_info = None
            if _MANIFEST_NAME in names:
                f = tar.extractfile(_MANIFEST_NAME)
                if f:
                    manifest_info = json.loads(f.read().decode())

            lines: list[str] = [f"Архив: {archive_path.name}", ""]
            if manifest_info:
                lines.append(f"Создан: {manifest_info.get('created_at', '?')}")
                lines.append("")
            lines.append("Содержимое:")
            for n in names:
                if n != _MANIFEST_NAME:
                    lines.append(f"  • {n}")
        return True, "\n".join(lines)
    except Exception as exc:
        return False, f"Ошибка чтения архива: {exc}"


def list_available_backups(backup_dir: Path | None = None) -> list[Path]:
    """Return list of backup archives sorted by modification time (newest first)."""
    if backup_dir is None:
        gen = _find_generated_dir()
        backup_dir = gen.parent / "backups" if gen else Path("/tmp")
    if not backup_dir.exists():
        return []
    archives = sorted(
        backup_dir.glob("daran-proxy-backup-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return archives


def restore_backup(archive_path: Path, confirmed: bool = False) -> tuple[bool, str]:
    """Restore a backup archive into the generated directory.

    confirmed=False → dry run (list what would be restored).
    confirmed=True  → extract files, overwriting existing ones.
    """
    if not archive_path.exists():
        return False, f"Архив не найден: {archive_path}"

    generated_dir = _find_generated_dir()
    if generated_dir is None:
        # Try to infer from archive location (../generated relative to backups/)
        generated_dir = archive_path.parent.parent / "generated"
        generated_dir.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            names = [n for n in tar.getnames() if n != _MANIFEST_NAME]

            if not confirmed:
                lines = [
                    f"Будет восстановлено из: {archive_path.name}",
                    f"В директорию: {generated_dir}",
                    f"Файлов: {len(names)}",
                    "",
                ] + [f"  • {n}" for n in names]
                lines.append("\n[yellow]⚠ Существующие файлы будут перезаписаны.[/yellow]")
                return True, "\n".join(lines)

            # Execute restore
            for member in tar.getmembers():
                if member.name == _MANIFEST_NAME:
                    continue
                dest = generated_dir / member.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                f = tar.extractfile(member)
                if f is not None:
                    dest.write_bytes(f.read())

        lines = [
            f"✓ Восстановлено {len(names)} файлов",
            f"  из: {archive_path.name}",
            f"  в:  {generated_dir}",
        ]
        return True, "\n".join(lines)

    except Exception as exc:
        return False, f"Ошибка восстановления: {exc}"
