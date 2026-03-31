"""Multi-server TUI actions for the terminal menu."""
from __future__ import annotations

from dataclasses import dataclass

from daran_proxy_stack.lib.multiserver import (
    ServerEntry,
    ServerRegistry,
    _default_config_dir,
    default_registry,
    make_server_id,
)


@dataclass
class ActionResult:
    ok: bool
    title: str
    body: str
    tip: str = ""


def _reg() -> ServerRegistry:
    return default_registry()


# ---------------------------------------------------------------------------
# Read-only
# ---------------------------------------------------------------------------

def list_servers() -> ActionResult:
    servers = _reg().list_servers()
    if not servers:
        return ActionResult(
            False,
            "Мульти-сервер: список",
            "Серверов не добавлено.\n\n"
            "Добавьте сервер через «Добавить сервер» в меню.",
        )
    lines = [f"Зарегистрированных серверов: {len(servers)}", ""]
    for i, s in enumerate(servers, 1):
        lines.append(f"  [{i}] {s.label}  ({s.user}@{s.host}:{s.port})")
        if s.description:
            lines.append(f"       {s.description}")
        if s.tags:
            lines.append(f"       теги: {', '.join(s.tags)}")
    lines.append(f"\nКонфиг: {_default_config_dir() / 'servers.json'}")
    return ActionResult(True, "Мульти-сервер: список серверов", "\n".join(lines))


def ping_all() -> ActionResult:
    reg = _reg()
    servers = reg.list_servers()
    if not servers:
        return ActionResult(False, "Мульти-сервер: пинг", "Серверов не добавлено.")
    results = reg.ping_all()
    lines = ["TCP-пинг на SSH-порты:", ""]
    for r in results:
        icon = "✓" if r["reachable"] else "✗"
        lat = f"{r['latency_ms']} мс" if r["latency_ms"] is not None else "недоступен"
        lines.append(f"  {icon} {r['label']}  {r['host']}:{r['port']}  — {lat}")
    return ActionResult(True, "Мульти-сервер: пинг", "\n".join(lines))


def server_status(server_id: str) -> ActionResult:
    """Collect diagnostics from a remote server via SSH."""
    reg = _reg()
    entry = reg.get_server(server_id)
    if not entry:
        return ActionResult(False, "Мульти-сервер: статус", f"Сервер «{server_id}» не найден.")

    info = reg.collect_remote_status(entry)
    lines = [
        f"Сервер: {entry.label}  ({entry.user}@{entry.host}:{entry.port})",
        "",
        f"  Доступен:   {'да' if info.get('reachable') else 'нет'}",
    ]
    if info.get("latency_ms") is not None:
        lines.append(f"  Задержка:   {info['latency_ms']} мс")
    if info.get("os"):
        lines.append(f"  ОС:         {info['os']}")
    if info.get("kernel"):
        lines.append(f"  Ядро:       {info['kernel']}")
    if info.get("uptime"):
        lines.append(f"  Uptime:     {info['uptime']}")
    if info.get("load_avg"):
        lines.append(f"  Load avg:   {info['load_avg']}")
    if info.get("disk"):
        lines.append(f"  Диск (/):   {info['disk']}")
    if info.get("services"):
        lines.append("")
        lines.append("  Сервисы:")
        for svc, status in info["services"].items():
            icon = "●" if status == "active" else "○"
            lines.append(f"    {icon} {svc}: {status}")
    if info.get("error"):
        lines.append(f"\n  ⚠ {info['error']}")
    return ActionResult(
        info.get("reachable", False),
        f"Мульти-сервер: {entry.label}",
        "\n".join(lines),
    )


# ---------------------------------------------------------------------------
# Mutating actions
# ---------------------------------------------------------------------------

def add_server(
    label: str,
    host: str,
    port: int = 22,
    user: str = "root",
    description: str = "",
    tags: list[str] | None = None,
    confirmed: bool = False,
) -> ActionResult:
    """Add a server to the registry."""
    if not label or not host:
        return ActionResult(False, "Мульти-сервер: ошибка", "label и host обязательны.")

    server_id = make_server_id(label)
    entry = ServerEntry(
        id=server_id,
        label=label,
        host=host,
        port=port,
        user=user,
        description=description,
        tags=tags or [],
    )

    if not confirmed:
        return ActionResult(
            True,
            "Мульти-сервер: добавить сервер",
            f"Будет добавлен:\n\n"
            f"  ID:    {server_id}\n"
            f"  Имя:   {label}\n"
            f"  Хост:  {user}@{host}:{port}\n"
            f"  Описание: {description or '—'}\n"
            f"  Теги:  {', '.join(tags or []) or '—'}",
            tip="Нажмите [y] для добавления.",
        )

    _reg().add_server(entry)
    return ActionResult(True, "Мульти-сервер: сервер добавлен", f"✓ {label} ({host}) добавлен.\nID: {server_id}")


def remove_server(server_id: str, confirmed: bool = False) -> ActionResult:
    """Remove a server from the registry."""
    reg = _reg()
    entry = reg.get_server(server_id)
    if not entry:
        return ActionResult(False, "Мульти-сервер: удаление", f"Сервер «{server_id}» не найден.")

    if not confirmed:
        return ActionResult(
            True,
            "Мульти-сервер: удалить сервер",
            f"Будет удалён: {entry.label} ({entry.host})\n"
            "Запись удаляется только из реестра — сам VPS не затрагивается.",
            tip="Нажмите [y] для удаления.",
        )

    ok = reg.remove_server(server_id)
    if ok:
        return ActionResult(True, "Мульти-сервер: сервер удалён", f"✓ {entry.label} удалён из реестра.")
    return ActionResult(False, "Мульти-сервер: ошибка", "Не удалось удалить запись.")


def run_command(server_id: str, command: str, confirmed: bool = False) -> ActionResult:
    """Run an arbitrary command on a remote server via SSH."""
    reg = _reg()
    entry = reg.get_server(server_id)
    if not entry:
        return ActionResult(False, "Мульти-сервер: выполнить команду", f"Сервер «{server_id}» не найден.")

    if not confirmed:
        return ActionResult(
            True,
            "Мульти-сервер: выполнить команду",
            f"На сервере {entry.label} ({entry.host}) будет выполнено:\n\n  {command}",
            tip="Нажмите [y] для выполнения.",
        )

    result = reg.ssh_run(entry, command)
    if result.ok:
        return ActionResult(True, f"Мульти-сервер: {entry.label}", result.stdout or "(нет вывода)")
    return ActionResult(
        False,
        f"Мульти-сервер: ошибка на {entry.label}",
        result.stderr or result.stdout or "SSH ошибка",
    )
