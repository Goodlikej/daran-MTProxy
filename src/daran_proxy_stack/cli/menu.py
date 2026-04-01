"""Интерактивное терминальное меню для daran-proxy-stack.

Точка входа: ``daran-net menu``

Главное меню:
  Показывает статус всех модулей (MTProxy / Cascade / WARP / 3x-ui)
  с индикаторами — обнаружен / установлен / работает.

  [1] MTProxy        ● работает  (или ○ не установлен, и т.д.)
  [2] Cascade        ○ не обнаружен
  [3] WARP           ● работает
  [4] 3x-ui          ○ не установлен
  [r] Обновить статус
  [0] Выход

Подменю модуля:
  [1] Статус
  [2] Установить
  [3] Удалить
  [4..N] Дополнительные действия
  [0] Назад

Рендер-хелперы остаются тестируемыми (чистые функции, только данные → Rich).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Callable, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from daran_proxy_stack.discovery.runner import run_discovery
from daran_proxy_stack.discovery.schema import (
    DiscoveryConfidence,
    ModuleHealth,
    ObservedState,
)
from daran_proxy_stack.cli.actions import warp as warp_actions
from daran_proxy_stack.cli.actions import mtproxy as mtproxy_actions
from daran_proxy_stack.cli.actions import cascade as cascade_actions
from daran_proxy_stack.cli.actions import xui as xui_actions
from daran_proxy_stack.cli.actions import monitor as monitor_actions
from daran_proxy_stack.cli.actions import backup as backup_actions
from daran_proxy_stack.cli.actions import amneziawg as awg_actions
from daran_proxy_stack.cli.actions import multiserver as ms_actions

console = Console()

# ---------------------------------------------------------------------------
# Colour / style helpers
# ---------------------------------------------------------------------------

_HEALTH_STYLE: dict[str, str] = {
    ModuleHealth.healthy.value: "bold green",
    ModuleHealth.degraded.value: "yellow",
    ModuleHealth.broken.value: "bold red",
    ModuleHealth.stopped.value: "dim",
    ModuleHealth.not_installed.value: "dim",
    ModuleHealth.unknown.value: "dim white",
}

_CONFIDENCE_STYLE: dict[str, str] = {
    DiscoveryConfidence.full.value: "green",
    DiscoveryConfidence.partial.value: "yellow",
    DiscoveryConfidence.none.value: "red",
}

# Статус-иконки для краткого отображения
_STATUS_ICON = {
    ModuleHealth.healthy.value: ("●", "bold green"),
    ModuleHealth.degraded.value: ("◕", "yellow"),
    ModuleHealth.broken.value: ("✗", "bold red"),
    ModuleHealth.stopped.value: ("○", "dim"),
    ModuleHealth.not_installed.value: ("○", "dim"),
    ModuleHealth.unknown.value: ("?", "dim white"),
}

_HEALTH_RU = {
    ModuleHealth.healthy.value: "работает",
    ModuleHealth.degraded.value: "деградирует",
    ModuleHealth.broken.value: "сломан",
    ModuleHealth.stopped.value: "остановлен",
    ModuleHealth.not_installed.value: "не установлен",
    ModuleHealth.unknown.value: "неизвестно",
}


def _health_text(health_val: str) -> Text:
    style = _HEALTH_STYLE.get(health_val, "white")
    return Text(health_val, style=style)


def _confidence_text(conf_val: str) -> Text:
    style = _CONFIDENCE_STYLE.get(conf_val, "white")
    return Text(conf_val, style=style)


def _status_badge(health_val: str, version: str | None = None) -> Text:
    """Краткий статус-badge для главного меню: ● работает  v1.2.3."""
    icon, style = _STATUS_ICON.get(health_val, ("?", "dim white"))
    label = _HEALTH_RU.get(health_val, health_val)
    t = Text()
    t.append(icon + " ", style=style)
    t.append(label, style=style)
    if version:
        t.append(f"  {version}", style="dim")
    return t


# ---------------------------------------------------------------------------
# Render helpers (pure — take data, return renderable or string)
# ---------------------------------------------------------------------------

def render_host_summary(state: ObservedState) -> Panel:
    """Однострочная панель с информацией о хосте."""
    h = state.host
    ip = h.public_ip or "unknown"
    bbr = " BBR:on" if h.bbr_enabled else (" BBR:off" if h.bbr_enabled is False else "")
    text = f"[bold]{h.hostname}[/bold]  OS: {h.os} {h.version}  IP: {ip}{bbr}"
    return Panel(text, title="Host", border_style="cyan", expand=False)


def render_modules_table(state: ObservedState) -> Table:
    """Сводная таблица модулей."""
    table = Table(
        title="Обнаруженные модули",
        show_header=True,
        header_style="bold magenta",
        border_style="dim",
        expand=False,
    )
    table.add_column("Модуль", style="bold", min_width=10)
    table.add_column("Статус", min_width=14)
    table.add_column("Запущен", min_width=8)
    table.add_column("Менеджер", min_width=9)
    table.add_column("Версия", min_width=12)
    table.add_column("Уверенность", min_width=12)

    module_map = {
        "warp": state.warp,
        "mtproxy": state.mtproxy,
        "cascade": state.cascade,
        "xui": state.xui,
    }
    for name, mod in module_map.items():
        if mod is None:
            table.add_row(name, Text("нет данных", style="dim"), "-", "-", "-", "-")
            continue
        d = mod.to_dict()
        running_icon = "✓" if d.get("running") else "✗"
        running_style = "green" if d.get("running") else "dim"
        table.add_row(
            name,
            _health_text(d.get("health", "unknown")),
            Text(running_icon, style=running_style),
            d.get("manager", "-"),
            d.get("version") or "-",
            _confidence_text(d.get("confidence", "none")),
        )
    return table


def render_discovery_meta(state: ObservedState) -> Panel:
    """Панель с метаданными последнего discovery-запуска."""
    m = state.discovery
    ts = m.last_run_at
    status_style = "green" if m.status == "ok" else "yellow"
    lines = [f"Статус: [{status_style}]{m.status}[/{status_style}]  Запуск: {ts}"]
    if m.warnings:
        lines.append("[yellow]Предупреждения:[/yellow]")
        for w in m.warnings:
            lines.append(f"  • {w}")
    if m.partial_modules:
        lines.append(f"[yellow]Частичные:[/yellow] {', '.join(m.partial_modules)}")
    return Panel("\n".join(lines), title="Discovery", border_style="dim", expand=False)


def render_module_detail(name: str, mod_state) -> Panel:
    """Развёрнутые детали конкретного модуля."""
    if mod_state is None:
        return Panel(f"No data for {name}", title=name, border_style="red")
    d = mod_state.to_dict()
    lines: list[str] = []

    health_val = d.get("health", "unknown")
    health_style = _HEALTH_STYLE.get(health_val, "white")
    lines.append(f"Статус:    [{health_style}]{health_val}[/{health_style}]")
    lines.append(f"Установлен: {d.get('installed')}")
    lines.append(f"Запущен:   {d.get('running')}")
    lines.append(f"Включён:   {d.get('enabled')}")
    lines.append(f"Менеджер:  {d.get('manager', '-')}")
    lines.append(f"Версия:    {d.get('version') or '-'}")
    lines.append(f"Уверенность: {d.get('confidence', '-')}")

    ports = d.get("ports", [])
    if ports:
        lines.append("Порты:")
        for p in ports:
            lines.append(f"  {p['bind']}:{p['port']}/{p['protocol']}  [{p['purpose']}]")

    # Module-specific extras
    if name == "mtproxy":
        ep = d.get("public_endpoint")
        ca = d.get("client_artifacts")
        rt = d.get("runtime")
        if ep:
            lines.append(f"Эндпоинт:  {ep.get('ip')}:{ep.get('port')}")
        if ca:
            lines.append(f"Секрет:    {'есть' if ca.get('secret_present') else 'отсутствует'}")
            if ca.get("tg_link"):
                lines.append(f"tg-ссылка: {ca['tg_link']}")
        if rt:
            lines.append(f"Контейнер: {rt.get('container_name') or '-'}  запущен={rt.get('container_running')}")

    if name == "warp":
        reg = d.get("registration")
        net = d.get("network")
        if reg:
            lines.append(f"Зарегистрирован: {reg.get('registered')}  тип={reg.get('account_type') or '-'}")
        if net:
            lines.append(f"IP сервера: {net.get('server_ip') or '-'}")
            lines.append(f"IP выхода:  {net.get('warp_ip') or '-'}")
            lines.append(f"Выход изменён: {net.get('egress_changed')}")

    warnings = d.get("warnings", [])
    errors = d.get("errors", [])
    if warnings:
        lines.append("[yellow]Предупреждения:[/yellow]")
        for w in warnings:
            lines.append(f"  • {w}")
    if errors:
        lines.append("[red]Ошибки:[/red]")
        for e in errors:
            lines.append(f"  • {e}")

    return Panel("\n".join(lines), title=f"Модуль: {name}", border_style="dim", expand=False)


def render_full_discovery(state: ObservedState) -> None:
    """Вывод полной информации discovery в консоль."""
    console.print()
    console.print(render_host_summary(state))
    console.print(render_discovery_meta(state))
    console.print(render_modules_table(state))


# ---------------------------------------------------------------------------
# Status summary for main menu (inline badge per module)
# ---------------------------------------------------------------------------

def _module_status_badge(name: str | None, state: ObservedState | None) -> Text:
    """Краткий badge для строки главного меню."""
    if name is None:
        return Text("", style="dim")
    if state is None:
        return Text("○ нет данных", style="dim")

    mod = getattr(state, name, None)
    if mod is None:
        return Text("○ нет данных", style="dim")

    d = mod.to_dict()
    health_val = d.get("health", "unknown")
    version = d.get("version")
    return _status_badge(health_val, version)


# ---------------------------------------------------------------------------
# Menu actions
# ---------------------------------------------------------------------------

def cmd_rediscover() -> ObservedState:
    """Запустить discovery и вернуть новое состояние."""
    console.print("\n[bold cyan]Запускаю discovery…[/bold cyan]")
    state = run_discovery()
    render_full_discovery(state)
    return state


def cmd_view_modules(state: ObservedState | None) -> None:
    """Показать детали всех модулей. Если нет данных — предупредить."""
    if state is None:
        console.print("[yellow]Нет данных discovery. Сначала запустите «Обновить статус».[/yellow]")
        return
    console.print()
    for name in ("warp", "mtproxy", "cascade", "xui"):
        mod = getattr(state, name, None)
        console.print(render_module_detail(name, mod))


# Конкретные альтернативные порты для MTProxy (443 занят)
_MTPROXY_ALT_PORTS = [2053, 2083, 2087, 2096]


# ---------------------------------------------------------------------------
# Per-module submenus
# ---------------------------------------------------------------------------

def _print_submenu(title: str, items: list[tuple[str, str]], status_line: Text | None = None) -> None:
    """Отрисовать подменю модуля."""
    lines: list[str] = [""]
    if status_line:
        lines.append(f"  Статус: {status_line.plain}")
        lines.append("")
    for key, label in items:
        lines.append(f"  [{key}] {label}")
    lines.append("")
    console.print(Panel(
        "\n".join(lines),
        title=f"[bold]{title}[/bold]",
        border_style="blue",
        expand=False,
    ))


def _submenu_status(module_name: str, state: ObservedState | None) -> None:
    """Показать детальный статус модуля."""
    if state is None:
        console.print("[yellow]Нет данных. Запустите обновление статуса из главного меню.[/yellow]")
        return
    mod = getattr(state, module_name, None)
    console.print(render_module_detail(module_name, mod))


def _wip_action(action_name: str) -> None:
    """Заглушка для ещё не реализованного действия."""
    console.print(Panel(
        f"[yellow]Действие «{action_name}» будет реализовано в следующем проходе.[/yellow]\n"
        "Используйте CLI-команды напрямую: [bold]daran-net [модуль] --help[/bold]",
        title="В разработке",
        border_style="yellow",
        expand=False,
    ))


def _ask_confirm(input_fn: Callable[[], str]) -> bool:
    """Ask user for confirmation. Returns True if confirmed."""
    console.print(
        "  [bold yellow]Подтвердить?[/bold yellow]  [green][1] Да[/green]  [dim][0] Нет[/dim]"
    )
    try:
        answer = input_fn().strip().lower()
        return answer in ("1", "y", "yes", "да", "д")
    except (EOFError, KeyboardInterrupt):
        return False


def _show_action_result(result) -> None:
    """Display an ActionResult panel."""
    border = "green" if result.ok else "red"
    body = result.body
    if result.tip:
        body += f"\n\n[dim]{result.tip}[/dim]"
    console.print(Panel(body, title=result.title, border_style=border, expand=False))


def _run_mtproxy_install_flow(
    state: ObservedState | None,
    input_fn: Callable[[], str],
) -> ObservedState | None:
    """Интерактивный сценарий установки MTProxy.

    Сценарий:
      1. Проверяет порт 443.
      2. Если занят — предлагает 2053 / 2083 / 2087 / 2096 (свободные).
      3. Пользователь выбирает порт.
      4. Показывает план, запрашивает подтверждение.
      5. Запускает установку.
      6. После успеха обновляет discovery и возвращает новое состояние.
    """
    from daran_proxy_stack.modules import mtproxy as mtp_mod

    DEFAULT_PORT = 443

    console.print("\n[bold cyan]Проверяю доступность порта 443…[/bold cyan]")
    port_status = mtp_mod.detect_port_status(DEFAULT_PORT)
    selected_port: int | None = None

    if port_status == "free":
        selected_port = DEFAULT_PORT
    else:
        console.print(f"\n[yellow]Порт 443 занят ({port_status}).[/yellow]")
        console.print("[cyan]Проверяю альтернативные порты…[/cyan]")

        free_alts = [p for p in _MTPROXY_ALT_PORTS if mtp_mod.is_port_free(p)]

        if not free_alts:
            console.print(Panel(
                "[red]Порт 443 занят, и все предложенные альтернативы (2053, 2083, 2087, 2096) тоже заняты.\n"
                "Введите порт вручную или освободите 443.[/red]",
                title="MTProxy: выбор порта",
                border_style="red",
                expand=False,
            ))
            port_str = _prompt("Введите порт вручную (Enter = отмена)", input_fn, "")
            if not port_str:
                console.print("[dim]Отменено.[/dim]")
                return None
            try:
                selected_port = int(port_str)
            except ValueError:
                console.print("[red]Неверный порт.[/red]")
                return None
        else:
            lines = ["", "Порт 443 занят. Выберите альтернативный порт:", ""]
            for i, p in enumerate(free_alts, 1):
                lines.append(f"  [{i}] {p}")
            lines.append("  [c] Ввести порт вручную")
            lines.append("  [0] Отмена")
            lines.append("")
            console.print(Panel(
                "\n".join(lines),
                title="MTProxy: выбор порта",
                border_style="blue",
                expand=False,
            ))

            try:
                port_choice = input_fn()
            except (EOFError, KeyboardInterrupt):
                console.print("[dim]Отменено.[/dim]")
                return None

            if port_choice == "0":
                console.print("[dim]Отменено.[/dim]")
                return None
            elif port_choice.lower() == "c":
                port_str = _prompt("Введите порт", input_fn, "")
                if not port_str:
                    console.print("[dim]Отменено.[/dim]")
                    return None
                try:
                    selected_port = int(port_str)
                except ValueError:
                    console.print("[red]Неверный порт.[/red]")
                    return None
            else:
                try:
                    idx = int(port_choice) - 1
                    if 0 <= idx < len(free_alts):
                        selected_port = free_alts[idx]
                    else:
                        console.print("[red]Неверный выбор.[/red]")
                        return None
                except ValueError:
                    console.print("[red]Неверный выбор.[/red]")
                    return None

    if selected_port is None:
        console.print("[dim]Отменено.[/dim]")
        return None

    # Показать план и запросить подтверждение
    preview = mtproxy_actions.install(port=selected_port, confirmed=False)
    _show_action_result(preview)

    if not _ask_confirm(input_fn):
        console.print("[dim]Отменено.[/dim]")
        return None

    # Запустить установку
    console.print(f"\n[bold cyan]Устанавливаю MTProxy на порту {selected_port}…[/bold cyan]")
    result = mtproxy_actions.install(port=selected_port, confirmed=True)
    _show_action_result(result)

    if result.ok:
        console.print("\n[bold cyan]Обновляю статус системы…[/bold cyan]")
        return cmd_rediscover()

    return None


def _run_mtproxy_submenu(state: ObservedState | None, input_fn: Callable[[], str]) -> None:
    """Подменю MTProxy с реальными действиями."""
    items = [
        ("1", "Статус (discovery)"),
        ("2", "Диагностика системы"),
        ("3", "Установить  (official build + systemd)"),
        ("4", "Удалить"),
        ("5", "Перезапустить"),
        ("6", "Показать tg-ссылку"),
        ("7", "Обновить данные"),
        ("8", "Обновить ключи  (proxy-secret + proxy-multi.conf)"),
        ("9", "Авто-обновление ключей  (systemd timer, раз в месяц)"),
        ("0", "← Назад"),
    ]
    while True:
        badge = _module_status_badge("mtproxy", state)
        _print_submenu("MTProxy", items, status_line=badge)
        try:
            choice = input_fn()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "1":
            _submenu_status("mtproxy", state)

        elif choice == "2":
            result = mtproxy_actions.status()
            _show_action_result(result)

        elif choice == "3":
            new_state = _run_mtproxy_install_flow(state, input_fn)
            if new_state is not None:
                state = new_state

        elif choice == "4":
            # Show plan first
            preview = mtproxy_actions.uninstall(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = mtproxy_actions.uninstall(confirmed=True)
                _show_action_result(result)
                if result.ok:
                    state = cmd_rediscover()
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "5":
            result = mtproxy_actions.restart()
            _show_action_result(result)

        elif choice == "6":
            # First try from discovery state
            if state and state.mtproxy:
                d = state.mtproxy.to_dict()
                ca = d.get("client_artifacts")
                if ca and ca.get("tg_link"):
                    console.print(Panel(
                        f"[green]{ca['tg_link']}[/green]\n\n[dim](из discovery)[/dim]",
                        title="MTProxy tg-ссылка",
                        border_style="green",
                        expand=False,
                    ))
                else:
                    # Fallback to artifacts
                    result = mtproxy_actions.show_tg_link()
                    _show_action_result(result)
            else:
                result = mtproxy_actions.show_tg_link()
                _show_action_result(result)

        elif choice == "7":
            state = cmd_rediscover()

        elif choice == "8":
            preview = mtproxy_actions.key_refresh(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                console.print("\n[bold cyan]Обновляю ключи…[/bold cyan]")
                result = mtproxy_actions.key_refresh(confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "9":
            preview = mtproxy_actions.setup_key_rotation(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = mtproxy_actions.setup_key_rotation(confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "0":
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")


def _prompt(label: str, input_fn: Callable[[], str], default: str = "") -> str:
    """Print a prompt label and read one line. Returns default on empty input."""
    hint = f" [{default}]" if default else ""
    console.print(f"  [cyan]{label}{hint}:[/cyan] ", end="")
    try:
        val = input_fn().strip()
        return val if val else default
    except (EOFError, KeyboardInterrupt):
        return default


_RELAY_PRESETS: dict[str, tuple[str, str, int]] = {
    "1": ("AmneziaWG / WireGuard", "udp", 51820),
    "2": ("VLESS / XRay",          "tcp", 443),
    "3": ("TProxy / MTProto",      "tcp", 443),
}


def _show_cascade_instruction(input_fn: Callable[[], str], server_ip: str | None = None) -> None:
    """Display the 3-step cascade setup instruction and wait for Enter."""
    from daran_proxy_stack.lib.firewall import get_public_ip
    ip = server_ip or get_public_ip() or "IP_ЭТОГО_СЕРВЕРА"
    body = (
        "[bold cyan]ШАГ 1: Подготовка[/bold cyan]\n"
        "У вас должны быть данные от зарубежного сервера (VPN/Прокси и т.д.):\n"
        " - [bold]IP адрес[/bold] (зарубежный)\n"
        " - [bold]Порт[/bold] (на котором работает целевой сервис)\n\n"
        "[bold cyan]ШАГ 2: Настройка этого сервера[/bold cyan]\n"
        "1. Выберите нужный пункт (1-3 для стандартных или 4 для кастомных).\n"
        "2. Введите IP и Порты (входящий и исходящий).\n"
        "3. Скрипт создаст 'мост' через этот VPS.\n\n"
        "[bold cyan]ШАГ 3: Настройка Клиента (Важно!)[/bold cyan]\n"
        "1. Откройте приложение клиента.\n"
        "2. В настройках соединения найдите поле [bold]Endpoint / Адрес сервера[/bold].\n"
        f"3. Замените зарубежный IP на [bold green]{ip}[/bold green].\n"
        "4. Если вы использовали разные порты в правиле №4, укажите Входящий порт.\n\n"
        "Готово! Теперь трафик идёт: Клиент -> Этот Сервер -> Зарубеж."
    )
    console.print(Panel(body, title="ИНСТРУКЦИЯ: КАК НАСТРОИТЬ КАСКАД",
                        border_style="red", expand=False))
    console.print("\n[dim]Нажмите Enter, чтобы вернуться в меню...[/dim]")
    try:
        input_fn()
    except (EOFError, KeyboardInterrupt):
        pass


def _run_cascade_add_rule(input_fn: Callable[[], str]) -> None:
    """Interactive flow: collect rule params, preview, confirm, write."""
    console.print(Panel(
        "Введите параметры нового правила.\n"
        "  Протокол: tcp / udp / both\n"
        "  Порт прослушивания: 1–65535\n"
        "  Целевой хост и порт\n"
        "  Заметка (необязательно)",
        title="Cascade: добавить правило",
        border_style="blue",
        expand=False,
    ))

    protocol = _prompt("Протокол (tcp/udp/both)", input_fn, "tcp")
    listen_port_str = _prompt("Порт прослушивания", input_fn, "1080")
    target_host = _prompt("Целевой хост", input_fn, "127.0.0.1")
    target_port_str = _prompt("Целевой порт", input_fn, "40000")
    notes = _prompt("Заметка (Enter — пропустить)", input_fn, "")

    try:
        listen_port = int(listen_port_str)
        target_port = int(target_port_str)
    except ValueError:
        console.print("[red]Ошибка: порт должен быть числом.[/red]")
        return

    preview = cascade_actions.add_rule(
        protocol=protocol,
        listen_port=listen_port,
        target_host=target_host,
        target_port=target_port,
        notes=notes,
        confirmed=False,
    )
    _show_action_result(preview)

    if preview.ok is False and "Неверный" not in preview.body and "не указан" not in preview.body:
        # It's a preview (not a validation error) — ask confirm
        if _ask_confirm(input_fn):
            result = cascade_actions.add_rule(
                protocol=protocol,
                listen_port=listen_port,
                target_host=target_host,
                target_port=target_port,
                notes=notes,
                confirmed=True,
            )
            _show_action_result(result)
        else:
            console.print("[dim]Отменено.[/dim]")


def _run_cascade_remove_rule(input_fn: Callable[[], str]) -> None:
    """Interactive flow: show list, ask for ID, preview, confirm, remove."""
    # First show current list
    list_result = cascade_actions.list_managed_rules()
    _show_action_result(list_result)

    if "нет" in list_result.body.lower() or "нет." in list_result.body.lower():
        return

    rule_id = _prompt("ID правила для удаления", input_fn, "")
    if not rule_id:
        console.print("[dim]Отменено.[/dim]")
        return

    preview = cascade_actions.remove_rule(rule_id, confirmed=False)
    _show_action_result(preview)

    if preview.ok is False and "не найдено" not in preview.body:
        if _ask_confirm(input_fn):
            result = cascade_actions.remove_rule(rule_id, confirmed=True)
            _show_action_result(result)
        else:
            console.print("[dim]Отменено.[/dim]")


def _run_cascade_relay_flow(input_fn: Callable[[], str]) -> None:
    """Интерактивный сценарий настройки iptables relay с выбором пресета."""
    lines = ["", "Выберите тип трафика:", ""]
    for k, (name, proto, port) in _RELAY_PRESETS.items():
        lines.append(f"  [{k}] {name}  ({proto.upper()}, порт {port})")
    lines += ["  [4] Кастомное правило  (любой протокол/порт)", "  [0] Назад", ""]
    console.print(Panel("\n".join(lines), title="Cascade: relay (iptables DNAT)",
                        border_style="blue", expand=False))

    try:
        choice = input_fn()
    except (EOFError, KeyboardInterrupt):
        return

    if choice == "0":
        return

    if choice in _RELAY_PRESETS:
        label, proto, default_port = _RELAY_PRESETS[choice]
        target_host = _prompt("IP зарубежного сервера", input_fn, "")
        if not target_host:
            console.print("[dim]Отменено.[/dim]")
            return
        port_str = _prompt(f"Порт на целевом сервере (Enter = {default_port})",
                           input_fn, str(default_port))
        try:
            port = int(port_str)
        except ValueError:
            console.print("[red]Неверный порт.[/red]")
            return
        rules = [{"protocol": proto, "listen_port": port, "target_port": port}]

    elif choice == "4":
        target_host = _prompt("IP целевого сервера", input_fn, "")
        if not target_host:
            console.print("[dim]Отменено.[/dim]")
            return
        console.print("  [dim]Примеры: 443  /  443,8443  /  443,51820[/dim]")
        ports_str = _prompt("Порты для проброса (через запятую)", input_fn, "443")
        try:
            ports = [int(p.strip()) for p in ports_str.split(",") if p.strip()]
            if not ports:
                raise ValueError
        except ValueError:
            console.print("[red]Неверный формат портов.[/red]")
            return
        proto = _prompt("Протокол (tcp / udp / both)", input_fn, "tcp").lower().strip()
        if proto not in ("tcp", "udp", "both"):
            console.print(f"[red]Неверный протокол: {proto!r}[/red]")
            return
        rules = [{"protocol": proto, "listen_port": p, "target_port": p} for p in ports]

    else:
        console.print("[red]Неверный выбор.[/red]")
        return

    preview = cascade_actions.relay_setup(target_host, rules, confirmed=False)
    _show_action_result(preview)

    if not _ask_confirm(input_fn):
        console.print("[dim]Отменено.[/dim]")
        return

    console.print(f"\n[bold cyan]Применяю relay правила → {target_host}…[/bold cyan]")
    result = cascade_actions.relay_setup(target_host, rules, confirmed=True)
    _show_action_result(result)

    if result.ok:
        _show_cascade_instruction(input_fn)


def _run_cascade_submenu(state: ObservedState | None, input_fn: Callable[[], str]) -> None:
    """Подменю Cascade с реальными действиями."""
    items = [
        ("1", "Статус (discovery + TCP-пробы)"),
        ("2", "Список правил (iptables / persisted)"),
        ("3", "Показать конфигурацию (сгенерированные файлы)"),
        ("4", "Применить конфиг  (записать 3proxy.cfg + .service + state.json)"),
        ("5", "Установить 3proxy  (инструкция)"),
        ("6", "Управление правилами: список (rules.json)"),
        ("7", "Управление правилами: добавить правило"),
        ("8", "Управление правилами: удалить правило"),
        ("9", "Управление правилами: сбросить все  ⚠"),
        ("a", "Relay → FI VPS: настроить  (iptables DNAT)"),
        ("b", "Relay → FI VPS: статус"),
        ("c", "Relay → FI VPS: удалить правила  ⚠"),
        ("i", "Инструкция (как настроить каскад)"),
        ("u", "Обновить данные"),
        ("0", "← Назад"),
    ]
    while True:
        badge = _module_status_badge("cascade", state)
        _print_submenu("Cascade", items, status_line=badge)
        try:
            choice = input_fn()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "1":
            result = cascade_actions.status()
            _show_action_result(result)

        elif choice == "2":
            result = cascade_actions.list_rules()
            _show_action_result(result)

        elif choice == "3":
            result = cascade_actions.show_config()
            _show_action_result(result)

        elif choice == "4":
            preview = cascade_actions.apply_config(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = cascade_actions.apply_config(confirmed=True)
                _show_action_result(result)
                if result.ok:
                    state = cmd_rediscover()
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "5":
            result = cascade_actions.install_3proxy_guide()
            _show_action_result(result)

        elif choice == "6":
            result = cascade_actions.list_managed_rules()
            _show_action_result(result)

        elif choice == "7":
            _run_cascade_add_rule(input_fn)

        elif choice == "8":
            _run_cascade_remove_rule(input_fn)

        elif choice == "9":
            preview = cascade_actions.reset_rules(confirmed=False)
            _show_action_result(preview)
            if not preview.ok:
                # There are rules to reset — ask confirm
                if _ask_confirm(input_fn):
                    result = cascade_actions.reset_rules(confirmed=True)
                    _show_action_result(result)
                else:
                    console.print("[dim]Отменено.[/dim]")

        elif choice in ("a", "A"):
            _run_cascade_relay_flow(input_fn)

        elif choice in ("b", "B"):
            result = cascade_actions.relay_status()
            _show_action_result(result)

        elif choice in ("c", "C"):
            preview = cascade_actions.relay_flush(confirmed=False)
            _show_action_result(preview)
            if not preview.ok and "не найден" not in preview.body:
                if _ask_confirm(input_fn):
                    result = cascade_actions.relay_flush(confirmed=True)
                    _show_action_result(result)
                else:
                    console.print("[dim]Отменено.[/dim]")

        elif choice in ("i", "I"):
            _show_cascade_instruction(input_fn)

        elif choice in ("u", "U"):
            state = cmd_rediscover()

        elif choice == "0":
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")


def _run_warp_submenu(state: ObservedState | None, input_fn: Callable[[], str]) -> None:
    """Подменю WARP с реальными действиями."""
    items = [
        ("1", "Статус (discovery)"),
        ("2", "Диагностика системы"),
        ("3", "Установить warp-cli"),
        ("4", "Удалить warp-cli"),
        ("5", "Подключить WARP"),
        ("6", "Отключить WARP"),
        ("7", "SOCKS прокси: включить"),
        ("8", "SOCKS прокси: выключить"),
        ("9", "Показать Xray outbound JSON"),
        ("s", "Настройки SOCKS5 / JSON / Инструкция для 3X-UI"),
        ("u", "Обновить данные"),
        ("0", "← Назад"),
    ]
    while True:
        badge = _module_status_badge("warp", state)
        _print_submenu("WARP", items, status_line=badge)
        try:
            choice = input_fn()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "1":
            _submenu_status("warp", state)

        elif choice == "2":
            result = warp_actions.status()
            _show_action_result(result)

        elif choice == "3":
            # Show plan, ask confirm
            preview = warp_actions.install(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = warp_actions.install(confirmed=True)
                _show_action_result(result)
                if result.ok:
                    state = cmd_rediscover()
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "4":
            preview = warp_actions.uninstall(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = warp_actions.uninstall(confirmed=True)
                _show_action_result(result)
                if result.ok:
                    state = cmd_rediscover()
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "5":
            preview = warp_actions.connect(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = warp_actions.connect(confirmed=True)
                _show_action_result(result)
                if result.ok:
                    state = cmd_rediscover()
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "6":
            preview = warp_actions.disconnect(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = warp_actions.disconnect(confirmed=True)
                _show_action_result(result)
                if result.ok:
                    state = cmd_rediscover()
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "7":
            preview = warp_actions.socks_up(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = warp_actions.socks_up(confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "8":
            preview = warp_actions.socks_down(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = warp_actions.socks_down(confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "9":
            result = warp_actions.xray_info()
            _show_action_result(result)

        elif choice in ("s", "S"):
            _run_warp_socks_settings(input_fn)

        elif choice in ("u", "U"):
            state = cmd_rediscover()

        elif choice == "0":
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")


def _run_warp_socks_settings(input_fn: Callable[[], str]) -> None:
    """SOCKS5 settings submenu: show endpoint/WARP IP, JSON, 3X-UI guide, port change."""
    from daran_proxy_stack.modules import warp as warp_mod_local

    while True:
        cfg = warp_actions.default_config()
        warp_ip = "—"
        try:
            diag = warp_mod_local.collect_diagnostics(cfg)
            warp_ip = diag.server_ip or "—"
        except Exception:
            pass

        items = [
            ("1", "Показать JSON Outbound и Routing"),
            ("2", "Пошаговая инструкция для 3X-UI"),
            (f"3", f"Изменить порт SOCKS5  (сейчас: {cfg.socks_port})"),
            ("0", "← Назад"),
        ]
        header = Text(
            f"SOCKS5-прокси: {cfg.socks_host}:{cfg.socks_port}\n"
            f"WARP IP:       {warp_ip}"
        )
        _print_submenu("WARP: настройки SOCKS5", items, status_line=header)

        try:
            choice = input_fn()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "1":
            _show_action_result(warp_actions.xray_routing_info())
        elif choice == "2":
            _show_action_result(warp_actions.xui_integration_guide())
        elif choice == "3":
            port_str = _prompt(
                f"Новый порт SOCKS5 (сейчас {cfg.socks_port})",
                input_fn,
                str(cfg.socks_port),
            )
            try:
                port = int(port_str)
            except ValueError:
                console.print("[red]Неверный порт.[/red]")
                continue
            preview = warp_actions.set_socks_port(port, confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                _show_action_result(warp_actions.set_socks_port(port, confirmed=True))
            else:
                console.print("[dim]Отменено.[/dim]")
        elif choice == "0":
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")


def _run_monitoring_setup_flow(input_fn: Callable[[], str]) -> None:
    """Interactive flow: collect bot token + chat_id, configure monitoring."""
    console.print(Panel(
        "Telegram-уведомления через вашего бота.\n\n"
        "Как получить данные:\n"
        "  1. Создайте бота → @BotFather → /newbot\n"
        "  2. Скопируйте токен (вида 123456:AAF...)\n"
        "  3. Напишите боту любое сообщение\n"
        "  4. Узнайте chat_id → @userinfobot или /getUpdates",
        title="Мониторинг: настройка",
        border_style="blue",
        expand=False,
    ))

    bot_token = _prompt("Bot token", input_fn, "")
    if not bot_token:
        console.print("[dim]Отменено.[/dim]")
        return

    chat_id = _prompt("Chat ID", input_fn, "")
    if not chat_id:
        console.print("[dim]Отменено.[/dim]")
        return

    services_str = _prompt("Контролируемые сервисы (через запятую)", input_fn, "MTProxy")
    services = [s.strip() for s in services_str.split(",") if s.strip()]

    preview = monitor_actions.setup_monitoring(bot_token, chat_id, services, confirmed=False)
    _show_action_result(preview)

    if not _ask_confirm(input_fn):
        console.print("[dim]Отменено.[/dim]")
        return

    console.print("\n[bold cyan]Настраиваю мониторинг…[/bold cyan]")
    result = monitor_actions.setup_monitoring(bot_token, chat_id, services, confirmed=True)
    _show_action_result(result)

    if result.ok:
        console.print("\n[cyan]Отправляю тестовое уведомление…[/cyan]")
        test_result = monitor_actions.test_notification(bot_token, chat_id)
        _show_action_result(test_result)


def _run_monitoring_submenu(input_fn: Callable[[], str]) -> None:
    """Подменю Мониторинг: Telegram-уведомления + watchdog."""
    items = [
        ("1", "Статус  (конфиг + таймер)"),
        ("2", "Настроить мониторинг  (bot token + chat_id)"),
        ("3", "Отправить тестовое уведомление"),
        ("0", "← Назад"),
    ]
    while True:
        _print_submenu("Мониторинг", items)
        try:
            choice = input_fn()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "1":
            result = monitor_actions.monitoring_status()
            _show_action_result(result)

        elif choice == "2":
            _run_monitoring_setup_flow(input_fn)

        elif choice == "3":
            from daran_proxy_stack.lib.notify import load_notify_config
            cfg = load_notify_config(monitor_actions._config_dir())
            if not cfg:
                console.print(Panel(
                    "[yellow]Конфигурация не найдена.\nСначала выполните «Настроить мониторинг» (пункт 2).[/yellow]",
                    title="Мониторинг",
                    border_style="yellow",
                    expand=False,
                ))
            else:
                result = monitor_actions.test_notification(
                    cfg["bot_token"], cfg["chat_id"]
                )
                _show_action_result(result)

        elif choice == "0":
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")


def _run_awg_submenu(state: ObservedState | None, input_fn: Callable[[], str]) -> None:
    """Подменю AmneziaWG — обфусцированный WireGuard."""
    items = [
        ("1", "Статус"),
        ("2", "Установить  (apt PPA, Ubuntu)"),
        ("3", "Сгенерировать серверный конфиг  (ключи + wg0.conf)"),
        ("4", "Применить конфиг  → /etc/amneziawg/"),
        ("5", "Запустить сервис  (awg-quick@wg0)"),
        ("6", "Остановить сервис"),
        ("7", "Перезапустить сервис"),
        ("8", "Список пиров"),
        ("9", "Добавить пира"),
        ("d", "Удалить пира"),
        ("c", "Показать клиентский конфиг"),
        ("u", "Обновить данные"),
        ("0", "← Назад"),
    ]
    while True:
        _print_submenu("AmneziaWG", items)
        try:
            choice = input_fn()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "1":
            result = awg_actions.status()
            _show_action_result(result)

        elif choice == "2":
            preview = awg_actions.install(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                console.print("\n[bold cyan]Устанавливаю AmneziaWG…[/bold cyan]")
                result = awg_actions.install(confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "3":
            port_str = _prompt("Порт (UDP)", input_fn, "51820")
            addr_str = _prompt("Адрес сервера (CIDR)", input_fn, "10.8.0.1/24")
            try:
                port = int(port_str)
            except ValueError:
                port = 51820
            preview = awg_actions.generate_server_config(port=port, address=addr_str, confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = awg_actions.generate_server_config(port=port, address=addr_str, confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "4":
            preview = awg_actions.apply_config(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = awg_actions.apply_config(confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "5":
            preview = awg_actions.service_start(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = awg_actions.service_start(confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "6":
            preview = awg_actions.service_stop(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = awg_actions.service_stop(confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "7":
            preview = awg_actions.service_restart(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = awg_actions.service_restart(confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "8":
            result = awg_actions.list_peers()
            _show_action_result(result)

        elif choice == "9":
            peer_name = _prompt("Имя пира (клиента)", input_fn, "")
            if not peer_name:
                console.print("[dim]Отменено.[/dim]")
            else:
                preview = awg_actions.add_peer(peer_name, confirmed=False)
                _show_action_result(preview)
                if _ask_confirm(input_fn):
                    result = awg_actions.add_peer(peer_name, confirmed=True)
                    _show_action_result(result)
                else:
                    console.print("[dim]Отменено.[/dim]")

        elif choice in ("d", "D"):
            list_result = awg_actions.list_peers()
            _show_action_result(list_result)
            peer_name = _prompt("Имя пира для удаления", input_fn, "")
            if not peer_name:
                console.print("[dim]Отменено.[/dim]")
            else:
                preview = awg_actions.remove_peer(peer_name, confirmed=False)
                _show_action_result(preview)
                if preview.ok and _ask_confirm(input_fn):
                    result = awg_actions.remove_peer(peer_name, confirmed=True)
                    _show_action_result(result)
                else:
                    console.print("[dim]Отменено.[/dim]")

        elif choice in ("c", "C"):
            list_result = awg_actions.list_peers()
            _show_action_result(list_result)
            peer_name = _prompt("Имя пира", input_fn, "")
            if peer_name:
                result = awg_actions.show_client_config(peer_name)
                _show_action_result(result)

        elif choice in ("u", "U"):
            state = cmd_rediscover()

        elif choice == "0":
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")


def _run_backup_submenu(input_fn: Callable[[], str]) -> None:
    """Подменю резервного копирования."""
    items = [
        ("1", "Список резервных копий"),
        ("2", "Создать резервную копию"),
        ("3", "Просмотреть содержимое архива"),
        ("4", "Восстановить из архива"),
        ("0", "← Назад"),
    ]
    while True:
        _print_submenu("Резервное копирование", items)
        try:
            choice = input_fn()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "1":
            result = backup_actions.list_backups()
            _show_action_result(result)

        elif choice == "2":
            preview = backup_actions.create_backup(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                console.print("\n[cyan]Создаю архив…[/cyan]")
                result = backup_actions.create_backup(confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "3":
            from daran_proxy_stack.lib.backup import list_available_backups
            archives = list_available_backups()
            if not archives:
                console.print("[yellow]Резервных копий не найдено.[/yellow]")
            else:
                list_result = backup_actions.list_backups()
                _show_action_result(list_result)
                idx_str = _prompt("Номер архива для просмотра", input_fn, "1")
                try:
                    idx = int(idx_str) - 1
                    if 0 <= idx < len(archives):
                        result = backup_actions.inspect_backup(archives[idx])
                        _show_action_result(result)
                    else:
                        console.print("[red]Неверный номер.[/red]")
                except ValueError:
                    console.print("[red]Введите число.[/red]")

        elif choice == "4":
            from daran_proxy_stack.lib.backup import list_available_backups
            archives = list_available_backups()
            if not archives:
                console.print("[yellow]Резервных копий не найдено. Сначала создайте архив.[/yellow]")
            else:
                list_result = backup_actions.list_backups()
                _show_action_result(list_result)
                idx_str = _prompt("Номер архива для восстановления", input_fn, "1")
                try:
                    idx = int(idx_str) - 1
                    if 0 <= idx < len(archives):
                        archive = archives[idx]
                        preview = backup_actions.restore_backup(archive, confirmed=False)
                        _show_action_result(preview)
                        if _ask_confirm(input_fn):
                            result = backup_actions.restore_backup(archive, confirmed=True)
                            _show_action_result(result)
                        else:
                            console.print("[dim]Отменено.[/dim]")
                    else:
                        console.print("[red]Неверный номер.[/red]")
                except ValueError:
                    console.print("[red]Введите число.[/red]")

        elif choice == "0":
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")


def _run_multiserver_submenu(input_fn: Callable[[], str]) -> None:
    """Подменю мульти-сервер — управление несколькими VPS."""
    items = [
        ("1", "Список серверов"),
        ("2", "Пинг всех серверов  (TCP на SSH-порт)"),
        ("3", "Статус сервера  (SSH диагностика)"),
        ("4", "Добавить сервер"),
        ("5", "Удалить сервер"),
        ("6", "Выполнить команду на сервере  (SSH)"),
        ("0", "← Назад"),
    ]
    while True:
        _print_submenu("Мульти-сервер", items)
        try:
            choice = input_fn()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "1":
            result = ms_actions.list_servers()
            _show_action_result(result)

        elif choice == "2":
            console.print("\n[cyan]Пингую серверы…[/cyan]")
            result = ms_actions.ping_all()
            _show_action_result(result)

        elif choice == "3":
            list_res = ms_actions.list_servers()
            _show_action_result(list_res)
            server_id = _prompt("ID сервера", input_fn, "")
            if server_id:
                console.print("\n[cyan]Подключаюсь через SSH…[/cyan]")
                result = ms_actions.server_status(server_id)
                _show_action_result(result)

        elif choice == "4":
            console.print(Panel(
                "Добавление сервера в реестр.\n"
                "Требуется настроенный SSH-ключ для беспарольного доступа.",
                title="Добавить сервер",
                border_style="blue",
                expand=False,
            ))
            label = _prompt("Название (например: Finland VPS)", input_fn, "")
            if not label:
                console.print("[dim]Отменено.[/dim]")
                continue
            host = _prompt("IP / хост", input_fn, "")
            if not host:
                console.print("[dim]Отменено.[/dim]")
                continue
            port_str = _prompt("SSH порт", input_fn, "22")
            user = _prompt("SSH пользователь", input_fn, "root")
            desc = _prompt("Описание (Enter — пропустить)", input_fn, "")
            tags_str = _prompt("Теги через запятую (Enter — пропустить)", input_fn, "")
            tags = [t.strip() for t in tags_str.split(",") if t.strip()]
            try:
                port = int(port_str)
            except ValueError:
                port = 22
            preview = ms_actions.add_server(label, host, port, user, desc, tags, confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = ms_actions.add_server(label, host, port, user, desc, tags, confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "5":
            list_res = ms_actions.list_servers()
            _show_action_result(list_res)
            server_id = _prompt("ID сервера для удаления", input_fn, "")
            if server_id:
                preview = ms_actions.remove_server(server_id, confirmed=False)
                _show_action_result(preview)
                if preview.ok and _ask_confirm(input_fn):
                    result = ms_actions.remove_server(server_id, confirmed=True)
                    _show_action_result(result)
                else:
                    console.print("[dim]Отменено.[/dim]")

        elif choice == "6":
            list_res = ms_actions.list_servers()
            _show_action_result(list_res)
            server_id = _prompt("ID сервера", input_fn, "")
            if not server_id:
                console.print("[dim]Отменено.[/dim]")
                continue
            command = _prompt("Команда", input_fn, "")
            if not command:
                console.print("[dim]Отменено.[/dim]")
                continue
            preview = ms_actions.run_command(server_id, command, confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                result = ms_actions.run_command(server_id, command, confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "0":
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")


def _run_wizard(input_fn: Callable[[], str]) -> None:
    """Запустить мастер первого запуска."""
    from daran_proxy_stack.cli.actions.wizard import run_wizard
    from rich.panel import Panel

    result = run_wizard(
        input_fn=input_fn,
        console=console,
        ask_confirm_fn=_ask_confirm,
        prompt_fn=_prompt,
        show_result_fn=_show_action_result,
    )

    if result.cancelled:
        console.print("[dim]Мастер отменён.[/dim]")
        return

    # Final summary
    summary_lines = result.summary_lines()
    status = "[bold green]Настройка завершена успешно[/bold green]" if result.ok \
        else "[bold yellow]Настройка завершена с предупреждениями[/bold yellow]"
    console.print(Panel(
        status + "\n\n" + "\n".join(summary_lines),
        title="[bold]Мастер первого запуска — итог[/bold]",
        border_style="green" if result.ok else "yellow",
        expand=False,
    ))


def _run_3xui_submenu(state: ObservedState | None, input_fn: Callable[[], str]) -> None:
    """Подменю 3x-ui.

    Установка использует upstream mozaroc/x-ui-pro как временный backend.
    Attribution: vendor/xui-pro/NOTICE.md
    """
    items = [
        ("1", "Статус  (обнаружение: systemd + process + web-probe)"),
        ("2", "Установить  [upstream: mozaroc/x-ui-pro — nginx+REALITY+WS]"),
        ("3", "Перезапустить  (systemctl restart x-ui)"),
        ("0", "← Назад"),
    ]
    while True:
        badge = _module_status_badge("xui", state)
        _print_submenu("3x-ui", items, status_line=badge)
        try:
            choice = input_fn()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "1":
            result = xui_actions.status()
            _show_action_result(result)

        elif choice == "2":
            # Upstream-backed installer: mozaroc/x-ui-pro (temporary external backend)
            preview = xui_actions.install_xui_pro_upstream(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(input_fn):
                console.print("\n[bold cyan]Запускаю установщик x-ui-pro… (вывод в реальном времени)[/bold cyan]\n")
                result = xui_actions.install_xui_pro_upstream(confirmed=True, console=console)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "3":
            result = xui_actions.service_restart()
            _show_action_result(result)

        elif choice == "0":
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

def _print_main_menu(state: ObservedState | None) -> None:
    """Отрисовать главное меню со статусами модулей."""
    lines: list[str] = [""]

    # Module rows with inline status
    modules_info = [
        ("1", "MTProxy", "mtproxy"),
        ("2", "Cascade", "cascade"),
        ("3", "WARP", "warp"),
        ("4", "3x-ui", "xui"),
        ("5", "AmneziaWG", None),
        ("6", "Мониторинг", None),
        ("7", "Резервные копии", None),
        ("8", "Мульти-сервер", None),
    ]

    for key, label, attr in modules_info:
        badge = _module_status_badge(attr, state)
        badge_str = badge.plain
        # Pad label to align badges
        label_padded = f"{label:<12}"
        lines.append(f"  [{key}] {label_padded}  {badge_str}")

    lines.append("")

    if state is None:
        lines.append("  [dim]Данные не загружены. Выберите [r] для обновления.[/dim]")
    else:
        ts = state.discovery.last_run_at
        status = state.discovery.status
        status_style = "green" if status == "ok" else "yellow"
        lines.append(f"  [dim]Discovery: [{status_style}]{status}[/{status_style}]  {ts}[/dim]")

    lines.append("")
    lines.append("  [w] Мастер первого запуска")
    lines.append("  [r] Обновить статус")
    lines.append("  [0] Выход")
    lines.append("")

    console.print(Panel(
        "\n".join(lines),
        title="[bold]daran-proxy-stack[/bold]  главное меню",
        border_style="cyan",
        expand=False,
    ))


# ---------------------------------------------------------------------------
# Main menu loop
# ---------------------------------------------------------------------------

def run_menu(
    input_fn: Callable[[], str] | None = None,
    once: bool = False,
) -> None:
    """Запустить интерактивное меню.

    Args:
        input_fn: Переопределение ввода (для тестов). По умолчанию: input().
        once:     Если True — выйти после первой итерации (для тестов).
    """
    _input = input_fn or (lambda: input("  выбор > ").strip())
    last_state: ObservedState | None = None

    # Автоматический discovery при старте
    if input_fn is None:
        console.print("\n[bold cyan]Запускаю обнаружение системы…[/bold cyan]")
        try:
            last_state = run_discovery()
        except Exception as exc:
            console.print(f"[yellow]Discovery не удался: {exc}[/yellow]")

    while True:
        _print_main_menu(last_state)
        try:
            choice = _input()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Выход.[/dim]")
            break

        if choice == "1":
            _run_mtproxy_submenu(last_state, _input)
        elif choice == "2":
            _run_cascade_submenu(last_state, _input)
        elif choice == "3":
            _run_warp_submenu(last_state, _input)
        elif choice == "4":
            _run_3xui_submenu(last_state, _input)
        elif choice == "5":
            _run_awg_submenu(last_state, _input)
        elif choice == "6":
            _run_monitoring_submenu(_input)
        elif choice == "7":
            _run_backup_submenu(_input)
        elif choice == "8":
            _run_multiserver_submenu(_input)
        elif choice in ("w", "W", "в", "В"):
            _run_wizard(_input)
        elif choice in ("r", "R", "р", "Р"):  # латиница + кириллица
            last_state = cmd_rediscover()
        elif choice == "0":
            console.print("[dim]До свидания.[/dim]")
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")

        if once:
            break
