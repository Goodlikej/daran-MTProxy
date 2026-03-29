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

def _module_status_badge(name: str, state: ObservedState | None) -> Text:
    """Краткий badge для строки главного меню."""
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


def _read_line(prompt: str = "  выбор > ") -> str:
    """Read one line from stdin with a plain prompt.

    Keep prompts ASCII/plain to avoid locale/TTY decoding issues in mixed SSH
    environments. Higher-level UI text can stay in Russian.
    """
    return input(prompt)



def _ask_confirm(input_fn: Callable[[], str] | None = None) -> bool:
    """Ask user for y/n confirmation. Returns True if confirmed."""
    try:
        if input_fn is None:
            answer = _read_line("  confirm [y/N] > ").strip().lower()
        else:
            console.print("  [bold yellow]Подтвердить? [y/N][/bold yellow]")
            answer = input_fn().strip().lower()
        return answer in ("y", "yes", "да", "д")
    except (EOFError, KeyboardInterrupt):
        return False


def _show_action_result(result) -> None:
    """Display an ActionResult panel."""
    border = "green" if result.ok else "red"
    body = result.body
    if result.tip:
        body += f"\n\n[dim]{result.tip}[/dim]"
    console.print(Panel(body, title=result.title, border_style=border, expand=False))


def _resolve_confirm_input(input_fn: Callable[[], str]) -> Callable[[], str] | None:
    """Use plain stdin prompt only for the real built-in menu reader; keep injected readers for tests."""
    if getattr(input_fn, "__module__", "") == __name__ and getattr(input_fn, "__name__", "") == "<lambda>":
        return None
    return input_fn



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
            result = mtproxy_actions.install_guide()
            _show_action_result(result)

        elif choice == "4":
            # Show plan first
            preview = mtproxy_actions.uninstall(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(_resolve_confirm_input(input_fn)):
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
        if _ask_confirm(_resolve_confirm_input(input_fn)):
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
        if _ask_confirm(_resolve_confirm_input(input_fn)):
            result = cascade_actions.remove_rule(rule_id, confirmed=True)
            _show_action_result(result)
        else:
            console.print("[dim]Отменено.[/dim]")


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
            if _ask_confirm(_resolve_confirm_input(input_fn)):
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
                if _ask_confirm(_resolve_confirm_input(input_fn)):
                    result = cascade_actions.reset_rules(confirmed=True)
                    _show_action_result(result)
                else:
                    console.print("[dim]Отменено.[/dim]")

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
            if _ask_confirm(_resolve_confirm_input(input_fn)):
                result = warp_actions.install(confirmed=True)
                _show_action_result(result)
                if result.ok:
                    state = cmd_rediscover()
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "4":
            preview = warp_actions.uninstall(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(_resolve_confirm_input(input_fn)):
                result = warp_actions.uninstall(confirmed=True)
                _show_action_result(result)
                if result.ok:
                    state = cmd_rediscover()
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "5":
            preview = warp_actions.connect(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(_resolve_confirm_input(input_fn)):
                result = warp_actions.connect(confirmed=True)
                _show_action_result(result)
                if result.ok:
                    state = cmd_rediscover()
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "6":
            preview = warp_actions.disconnect(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(_resolve_confirm_input(input_fn)):
                result = warp_actions.disconnect(confirmed=True)
                _show_action_result(result)
                if result.ok:
                    state = cmd_rediscover()
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "7":
            preview = warp_actions.socks_up(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(_resolve_confirm_input(input_fn)):
                result = warp_actions.socks_up(confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "8":
            preview = warp_actions.socks_down(confirmed=False)
            _show_action_result(preview)
            if _ask_confirm(_resolve_confirm_input(input_fn)):
                result = warp_actions.socks_down(confirmed=True)
                _show_action_result(result)
            else:
                console.print("[dim]Отменено.[/dim]")

        elif choice == "9":
            result = warp_actions.xray_info()
            _show_action_result(result)

        elif choice in ("u", "U"):
            state = cmd_rediscover()

        elif choice == "0":
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")


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
            if _ask_confirm(_resolve_confirm_input(input_fn)):
                result = xui_actions.install_xui_pro_upstream(confirmed=True)
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
        input_fn: Переопределение ввода (для тестов). По умолчанию: stdin line reader.
        once:     Если True — выйти после первой итерации (для тестов).
    """
    _input = input_fn or (lambda: _read_line("  choice > ").strip())
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
        elif choice in ("r", "R", "р", "Р"):  # латиница + кириллица
            last_state = cmd_rediscover()
        elif choice == "0":
            console.print("[dim]До свидания.[/dim]")
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")

        if once:
            break
