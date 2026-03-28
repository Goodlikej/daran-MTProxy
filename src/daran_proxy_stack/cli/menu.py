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
    for name in ("warp", "mtproxy", "cascade"):
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


def _run_mtproxy_submenu(state: ObservedState | None, input_fn: Callable[[], str]) -> None:
    """Подменю MTProxy."""
    items = [
        ("1", "Статус"),
        ("2", "Установить  (official build + systemd)"),
        ("3", "Удалить"),
        ("4", "Перезапустить"),
        ("5", "Показать tg-ссылку"),
        ("6", "Обновить данные"),
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
            console.print(Panel(
                "[cyan]Официальная установка MTProxy:[/cyan]\n\n"
                "  daran-net mtproxy official-install\n\n"
                "Или пошагово:\n"
                "  daran-net mtproxy official-build --yes\n"
                "  daran-net mtproxy official-fetch --yes\n"
                "  daran-net mtproxy systemd-apply --yes\n\n"
                "[dim]Запустите нужную команду в отдельном терминале.[/dim]",
                title="Установка MTProxy",
                border_style="cyan",
                expand=False,
            ))
        elif choice == "3":
            console.print(Panel(
                "[red]Удаление MTProxy:[/red]\n\n"
                "  sudo systemctl stop MTProxy\n"
                "  sudo systemctl disable MTProxy\n"
                "  sudo rm /etc/systemd/system/MTProxy.service\n"
                "  sudo systemctl daemon-reload\n\n"
                "[dim]Или для Docker-варианта:[/dim]\n"
                "  daran-net mtproxy remove",
                title="Удаление MTProxy",
                border_style="red",
                expand=False,
            ))
        elif choice == "4":
            console.print(Panel(
                "[yellow]Перезапуск MTProxy:[/yellow]\n\n"
                "  sudo systemctl restart MTProxy\n\n"
                "[dim]Или для Docker-варианта:[/dim]\n"
                "  daran-net mtproxy restart",
                title="Перезапуск MTProxy",
                border_style="yellow",
                expand=False,
            ))
        elif choice == "5":
            if state and state.mtproxy:
                d = state.mtproxy.to_dict()
                ca = d.get("client_artifacts")
                if ca and ca.get("tg_link"):
                    console.print(Panel(
                        f"[green]{ca['tg_link']}[/green]",
                        title="MTProxy tg-ссылка",
                        border_style="green",
                        expand=False,
                    ))
                else:
                    console.print(Panel(
                        "tg-ссылка недоступна. Запустите:\n  daran-net mtproxy tg-link",
                        title="MTProxy tg-ссылка",
                        border_style="yellow",
                        expand=False,
                    ))
            else:
                console.print("[yellow]MTProxy не обнаружен или нет данных.[/yellow]")
        elif choice == "6":
            state = cmd_rediscover()
        elif choice == "0":
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")


def _run_cascade_submenu(state: ObservedState | None, input_fn: Callable[[], str]) -> None:
    """Подменю Cascade."""
    items = [
        ("1", "Статус"),
        ("2", "Установить"),
        ("3", "Удалить"),
        ("4", "Показать конфигурацию"),
        ("5", "Обновить данные"),
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
            _submenu_status("cascade", state)
        elif choice == "2":
            _wip_action("Установить Cascade")
        elif choice == "3":
            _wip_action("Удалить Cascade")
        elif choice == "4":
            _wip_action("Показать конфигурацию Cascade")
        elif choice == "5":
            state = cmd_rediscover()
        elif choice == "0":
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")


def _run_warp_submenu(state: ObservedState | None, input_fn: Callable[[], str]) -> None:
    """Подменю WARP."""
    items = [
        ("1", "Статус"),
        ("2", "Установить  (warp-cli)"),
        ("3", "Удалить"),
        ("4", "Подключить"),
        ("5", "Отключить"),
        ("6", "SOCKS прокси: включить"),
        ("7", "SOCKS прокси: выключить"),
        ("8", "Показать Xray outbound JSON"),
        ("9", "Обновить данные"),
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
            console.print(Panel(
                "[cyan]Установка WARP:[/cyan]\n\n"
                "  daran-net warp install\n\n"
                "[dim]Запустите команду в отдельном терминале.[/dim]",
                title="Установка WARP",
                border_style="cyan",
                expand=False,
            ))
        elif choice == "3":
            _wip_action("Удалить WARP")
        elif choice == "4":
            console.print(Panel(
                "  daran-net warp connect",
                title="Подключить WARP",
                border_style="green",
                expand=False,
            ))
        elif choice == "5":
            console.print(Panel(
                "  daran-net warp disconnect",
                title="Отключить WARP",
                border_style="yellow",
                expand=False,
            ))
        elif choice == "6":
            console.print(Panel(
                "  daran-net warp socks-up",
                title="WARP SOCKS: включить",
                border_style="green",
                expand=False,
            ))
        elif choice == "7":
            console.print(Panel(
                "  daran-net warp socks-down",
                title="WARP SOCKS: выключить",
                border_style="yellow",
                expand=False,
            ))
        elif choice == "8":
            console.print(Panel(
                "  daran-net warp xray-json\n  daran-net warp xray-json --save",
                title="Xray outbound JSON",
                border_style="cyan",
                expand=False,
            ))
        elif choice == "9":
            state = cmd_rediscover()
        elif choice == "0":
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")


def _run_3xui_submenu(state: ObservedState | None, input_fn: Callable[[], str]) -> None:
    """Подменю 3x-ui (каркас — установка через отдельный скрипт)."""
    items = [
        ("1", "Статус"),
        ("2", "Установить  [установка через отдельный скрипт]"),
        ("3", "Удалить     [не реализовано]"),
        ("0", "← Назад"),
    ]
    while True:
        _print_submenu(
            "3x-ui",
            items,
            status_line=Text("○ обнаружение через отдельный скрипт", style="dim"),
        )
        try:
            choice = input_fn()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "1":
            console.print(Panel(
                "[yellow]⚠ Обнаружение 3x-ui пока не интегрировано в discovery.[/yellow]\n\n"
                "Проверить вручную:\n"
                "  systemctl status x-ui 2>/dev/null\n"
                "  ps aux | grep x-ui\n"
                "  curl -s http://localhost:2053/ 2>/dev/null | head -5",
                title="Статус 3x-ui",
                border_style="yellow",
                expand=False,
            ))
        elif choice == "2":
            console.print(Panel(
                "[cyan]Установка 3x-ui (официальный скрипт):[/cyan]\n\n"
                "  bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)\n\n"
                "[yellow]⚠ Установка выполняется вручную через официальный скрипт.[/yellow]\n"
                "[dim]После установки раздел будет обновлён автоматически при следующем discovery.[/dim]",
                title="Установка 3x-ui",
                border_style="cyan",
                expand=False,
            ))
        elif choice == "3":
            _wip_action("Удалить 3x-ui")
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
        ("4", "3x-ui", None),  # no discovery slot yet
    ]

    for key, label, attr in modules_info:
        if attr is not None:
            badge = _module_status_badge(attr, state)
            badge_str = badge.plain
        else:
            # 3x-ui: no discovery data yet
            badge_str = "○ не обнаружен"
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
        elif choice in ("r", "R", "р", "Р"):  # латиница + кириллица
            last_state = cmd_rediscover()
        elif choice == "0":
            console.print("[dim]До свидания.[/dim]")
            break
        else:
            console.print(f"[red]Неизвестный выбор: {choice!r}[/red]")

        if once:
            break
