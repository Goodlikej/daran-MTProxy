"""First-run wizard for daran-proxy-stack.

Guides a non-technical user through the initial setup in one interactive flow:
  Step 1 — выбор режима  (MTProxy / Relay / MTProxy + Relay)
  Step 2 — MTProxy: порт, установка, tg-ссылка
  Step 3 — Relay: IP финского VPS, порты, протокол, применение
  Step 4 — Мониторинг: Telegram бот (опционально)
  Step 5 — Итоговая сводка

Returns a plain list of WizardStep results that menu.py displays.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WizardStep:
    """Result of a single wizard step."""
    name: str
    ok: bool
    summary: str


@dataclass
class WizardResult:
    """Accumulated result of the entire wizard run."""
    steps: list[WizardStep] = field(default_factory=list)
    cancelled: bool = False

    def add(self, step: WizardStep) -> None:
        self.steps.append(step)

    @property
    def ok(self) -> bool:
        return not self.cancelled and all(s.ok for s in self.steps)

    def summary_lines(self) -> list[str]:
        lines: list[str] = []
        for s in self.steps:
            icon = "✓" if s.ok else "⚠"
            lines.append(f"  {icon} {s.name}: {s.summary}")
        return lines


def is_fresh_install() -> bool:
    """Return True if no services appear to be installed (quick heuristic)."""
    import shutil
    # No MTProxy systemd unit
    if shutil.which("systemctl"):
        from daran_proxy_stack.lib.shell import run
        r = run(["systemctl", "is-active", "--quiet", "MTProxy"])
        if r.returncode == 0:
            return False
    # No relay-state.json
    from daran_proxy_stack.lib.backup import _find_generated_dir
    gen = _find_generated_dir()
    if gen and (gen / "cascade" / "relay-state.json").exists():
        return False
    return True


def run_wizard(
    input_fn,
    console,
    ask_confirm_fn,
    prompt_fn,
    show_result_fn,
) -> WizardResult:
    """Run the interactive first-run wizard.

    Args:
        input_fn:       raw input() replacement
        console:        Rich Console
        ask_confirm_fn: fn(input_fn) -> bool
        prompt_fn:      fn(label, input_fn, default) -> str
        show_result_fn: fn(ActionResult) -> None

    Returns:
        WizardResult with all completed steps.
    """
    from rich.panel import Panel

    result = WizardResult()

    console.print(Panel(
        "[bold cyan]Добро пожаловать в daran-proxy-stack![/bold cyan]\n\n"
        "Этот мастер поможет настроить прокси-стек за несколько минут.\n"
        "Вы можете прервать настройку в любой момент нажав [bold]Ctrl+C[/bold].\n\n"
        "Что вы хотите настроить?\n\n"
        "  [1] MTProxy  —  прокси для Telegram (один сервер)\n"
        "  [2] Relay    —  проброс трафика  RU VPS → FI VPS  (iptables)\n"
        "  [3] MTProxy + Relay  —  оба сразу\n"
        "  [0] Отмена",
        title="[bold]Мастер первого запуска[/bold]",
        border_style="cyan",
        expand=False,
    ))

    try:
        mode = input_fn().strip()
    except (EOFError, KeyboardInterrupt):
        result.cancelled = True
        return result

    if mode == "0":
        result.cancelled = True
        return result

    do_mtproxy = mode in ("1", "3")
    do_relay = mode in ("2", "3")

    if not do_mtproxy and not do_relay:
        console.print("[red]Неверный выбор.[/red]")
        result.cancelled = True
        return result

    # ── Step 2: MTProxy ──────────────────────────────────────────────────────
    if do_mtproxy:
        console.print("\n[bold cyan]━━ Шаг: Установка MTProxy ━━[/bold cyan]")
        from daran_proxy_stack.modules import mtproxy as mtp_mod
        from daran_proxy_stack.cli.actions import mtproxy as mtproxy_actions

        DEFAULT_PORT = 443
        port_status = mtp_mod.detect_port_status(DEFAULT_PORT)
        if port_status == "free":
            selected_port = DEFAULT_PORT
            console.print(f"  [green]✓ Порт 443 свободен[/green]")
        else:
            console.print(f"  [yellow]⚠ Порт 443 занят. Ищу свободный...[/yellow]")
            free = [p for p in [2053, 2083, 2087, 2096] if mtp_mod.is_port_free(p)]
            if free:
                selected_port = free[0]
                console.print(f"  Буду использовать порт [bold]{selected_port}[/bold]")
            else:
                port_str = prompt_fn("Введите порт вручную", input_fn, "8443")
                try:
                    selected_port = int(port_str)
                except ValueError:
                    result.add(WizardStep("MTProxy", False, "неверный порт — пропущено"))
                    selected_port = None  # type: ignore

        if selected_port:
            preview = mtproxy_actions.install(port=selected_port, confirmed=False)
            show_result_fn(preview)
            console.print("  Запустить установку MTProxy?")
            if ask_confirm_fn(input_fn):
                console.print(f"\n[cyan]Устанавливаю MTProxy на порту {selected_port}...[/cyan]")
                res = mtproxy_actions.install(port=selected_port, confirmed=True)
                show_result_fn(res)
                if res.ok:
                    result.add(WizardStep("MTProxy", True, f"установлен, порт {selected_port}"))
                else:
                    result.add(WizardStep("MTProxy", False, "ошибка установки"))
            else:
                result.add(WizardStep("MTProxy", False, "пропущено пользователем"))

    # ── Step 3: Relay ────────────────────────────────────────────────────────
    if do_relay:
        console.print("\n[bold cyan]━━ Шаг: Настройка Relay (RU → FI VPS) ━━[/bold cyan]")
        from daran_proxy_stack.cli.actions import cascade as cascade_actions

        console.print(Panel(
            "Укажите параметры финского VPS, куда пробрасывать трафик.\n"
            "Пример портов: 443 для HTTPS/MTProxy, 51820 для WireGuard.",
            border_style="blue",
            expand=False,
        ))

        target_host = prompt_fn("IP финского VPS", input_fn, "")
        if not target_host:
            result.add(WizardStep("Relay", False, "пропущено — не указан IP"))
        else:
            ports_str = prompt_fn("Порты (через запятую)", input_fn, "443")
            proto = prompt_fn("Протокол (tcp/udp/both)", input_fn, "tcp").lower().strip()

            try:
                ports = [int(p.strip()) for p in ports_str.split(",") if p.strip()]
            except ValueError:
                ports = [443]

            rules = [{"protocol": proto, "listen_port": p, "target_port": p} for p in ports]
            preview = cascade_actions.relay_setup(target_host, rules, confirmed=False)
            show_result_fn(preview)
            console.print("  Применить relay правила?")
            if ask_confirm_fn(input_fn):
                res = cascade_actions.relay_setup(target_host, rules, confirmed=True)
                show_result_fn(res)
                if res.ok:
                    result.add(WizardStep("Relay", True, f"{target_host}, порты: {ports_str}"))
                else:
                    result.add(WizardStep("Relay", False, "ошибка применения правил"))
            else:
                result.add(WizardStep("Relay", False, "пропущено пользователем"))

    # ── Step 4: Мониторинг (опционально) ─────────────────────────────────────
    console.print("\n[bold cyan]━━ Шаг: Telegram-уведомления (опционально) ━━[/bold cyan]")
    console.print("  Настроить уведомления о падении сервисов в Telegram? [y/N]: ", end="")
    try:
        ans = input_fn().strip().lower()
        setup_notify = ans in ("y", "yes", "да", "д")
    except (EOFError, KeyboardInterrupt):
        setup_notify = False

    if setup_notify:
        from daran_proxy_stack.cli.actions import monitor as monitor_actions
        console.print(
            "  Создайте бота через @BotFather → получите token\n"
            "  Узнайте chat_id через @userinfobot"
        )
        bot_token = prompt_fn("Bot token", input_fn, "")
        chat_id = prompt_fn("Chat ID", input_fn, "")
        if bot_token and chat_id:
            services = []
            if do_mtproxy:
                services.append("MTProxy")
            services = services or ["MTProxy"]
            res = monitor_actions.setup_monitoring(bot_token, chat_id, services, confirmed=True)
            show_result_fn(res)
            if res.ok:
                test = monitor_actions.test_notification(bot_token, chat_id)
                show_result_fn(test)
                result.add(WizardStep("Мониторинг", res.ok, "настроен, тест отправлен"))
            else:
                result.add(WizardStep("Мониторинг", False, "ошибка настройки"))
        else:
            result.add(WizardStep("Мониторинг", False, "пропущено — не указаны данные бота"))
    else:
        result.add(WizardStep("Мониторинг", True, "пропущено (по желанию)"))

    # ── Step 5: Резервная копия ───────────────────────────────────────────────
    console.print("\n[bold cyan]━━ Шаг: Резервная копия ━━[/bold cyan]")
    console.print("  Создать резервную копию конфигов и секретов? [Y/n]: ", end="")
    try:
        ans = input_fn().strip().lower()
        do_backup = ans not in ("n", "no", "нет", "н")
    except (EOFError, KeyboardInterrupt):
        do_backup = False

    if do_backup:
        from daran_proxy_stack.lib.backup import create_backup
        ok, msg, path = create_backup()
        if ok:
            result.add(WizardStep("Резервная копия", True, str(path)))
        else:
            result.add(WizardStep("Резервная копия", False, msg))

    return result
