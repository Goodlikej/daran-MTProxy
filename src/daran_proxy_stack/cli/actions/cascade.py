"""Real Cascade actions for the terminal menu.

Actions are safe-by-default:
  - Read-only: status(), list_rules()
  - Write-only to disk: apply_config() — generates artifacts but does NOT
    start any process (confirmed flow for write ops)
  - Guide-only: install_3proxy_guide() — never executes apt directly

Destructive service operations are not implemented here yet (no daemon
management layer exists for cascade).
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from daran_proxy_stack.lib.models import CascadeConfig
from daran_proxy_stack.lib.shell import run
from daran_proxy_stack.modules import cascade as cascade_mod


@dataclass
class ActionResult:
    ok: bool
    title: str
    body: str
    tip: str = ""


def default_config() -> CascadeConfig:
    return CascadeConfig()


# ---------------------------------------------------------------------------
# Read-only
# ---------------------------------------------------------------------------

def status() -> ActionResult:
    """Collect cascade diagnostics (TCP probes + discovery snapshot)."""
    # Discovery-level detection
    try:
        from daran_proxy_stack.discovery.modules.cascade import detect_cascade
        disc_state = detect_cascade()
        disc_data = disc_state.to_dict()
    except Exception as exc:
        disc_data = {"error": str(exc)}

    cfg = default_config()
    try:
        diag = cascade_mod.collect_diagnostics(cfg)
        sdict = cascade_mod.status_dict(cfg)
    except Exception as exc:
        return ActionResult(False, "Cascade: статус", f"Ошибка диагностики: {exc}")

    lines = [
        f"Rule backend:       {disc_data.get('rule_backend', '?')}",
        f"Установлен:         {disc_data.get('installed', '?')}",
        f"Запущен:            {disc_data.get('running', '?')}",
        f"Health:             {disc_data.get('health', '?')}",
        f"Уверенность:        {disc_data.get('confidence', '?')}",
        "",
        f"Config enabled:     {sdict.get('enabled', '?')}",
        f"Relay endpoint:     {sdict.get('relay', '?')}",
        f"Upstream SOCKS:     {sdict.get('upstream_socks', '?')}",
        f"Relay reachable:    {sdict.get('relay_reachable', '?')}",
        f"Upstream reachable: {sdict.get('upstream_reachable', '?')}",
        f"Note:               {sdict.get('note', '?')}",
    ]

    # Rules
    rules = disc_data.get("rules", [])
    if rules:
        lines.append("")
        lines.append(f"Правила ({len(rules)}):")
        for r in rules:
            lines.append(
                f"  [{r['id']}] "
                f"{r['protocol']} :{r['listen_port']} → {r['target_host']}:{r['target_port']}"
                f"  ({r['status']})  {r.get('notes', '')}"
            )
    else:
        lines.append("")
        lines.append("Активных правил не обнаружено.")

    warnings = disc_data.get("warnings", [])
    errors = disc_data.get("errors", [])
    if warnings:
        lines.append("")
        lines.append("Предупреждения:")
        for w in warnings:
            lines.append(f"  • {w}")
    if errors:
        lines.append("")
        lines.append("Ошибки:")
        for e in errors:
            lines.append(f"  • {e}")

    ok = disc_data.get("health", "unknown") not in ("broken", "unknown")
    return ActionResult(ok, "Cascade: статус", "\n".join(lines))


def list_rules() -> ActionResult:
    """Return current observed cascade rules (iptables + persisted state)."""
    try:
        from daran_proxy_stack.discovery.modules.cascade import detect_cascade
        state = detect_cascade()
        d = state.to_dict()
    except Exception as exc:
        return ActionResult(False, "Cascade: список правил", f"Ошибка обнаружения: {exc}")

    rules = d.get("rules", [])
    backend = d.get("rule_backend", "none")

    if not rules:
        return ActionResult(
            True,
            "Cascade: список правил",
            f"Rule backend: {backend}\n\n"
            "Правила не обнаружены.\n\n"
            "Cascade ещё не сконфигурирован или все правила неактивны.\n"
            "Используйте «Применить конфиг» для генерации конфигурации.",
        )

    lines = [f"Rule backend: {backend}", f"Всего правил: {len(rules)}", ""]
    for r in rules:
        status_icon = "✓" if r["status"] == "active" else "?"
        lines.append(
            f"  {status_icon} [{r['id']}] "
            f"{r['protocol'].upper()} "
            f":{r['listen_port']} → {r['target_host']}:{r['target_port']}"
        )
        if r.get("notes"):
            lines.append(f"      ({r['notes']})")

    tip = (
        "Правила из iptables — наблюдаемые, не управляемые через этот стек.\n"
        "Используйте «Применить конфиг» для генерации управляемых правил."
    )
    return ActionResult(True, "Cascade: список правил", "\n".join(lines), tip=tip)


# ---------------------------------------------------------------------------
# Config apply (write to disk, no process management)
# ---------------------------------------------------------------------------

def apply_config(confirmed: bool = False) -> ActionResult:
    """Generate cascade config artifacts (3proxy.cfg + cascade.service + state.json).

    Does NOT start any service — only writes files to the artifacts directory.
    """
    cfg = default_config()

    # Locate artifacts dir
    artifacts_dir = _find_artifacts_dir()

    if not confirmed:
        rules = cascade_mod.load_rules(artifacts_dir)
        proxy_cfg = cascade_mod.render_3proxy_config(cfg, rules=rules)
        out_dir = artifacts_dir / "cascade"

        rules_summary: str
        if rules:
            rules_lines = []
            for r in rules:
                rules_lines.append(
                    f"    [{r['id']}] "
                    f"{r['protocol'].upper()} :{r['listen_port']} → "
                    f"{r['target_host']}:{r['target_port']}"
                )
            rules_summary = f"Управляемых правил: {len(rules)}\n" + "\n".join(rules_lines)
        else:
            rules_summary = "Управляемых правил: 0 (добавьте через «Добавить правило»)"

        return ActionResult(
            False,
            "Cascade: генерация конфигурации",
            f"Будет создано в {out_dir}:\n\n"
            "  • 3proxy.cfg    — конфиг 3proxy (SOCKS5 → upstream + managed rules)\n"
            "  • cascade.service — systemd unit\n"
            "  • state.json    — снимок конфигурации\n\n"
            f"Relay:         {cfg.relay_host}:{cfg.relay_port}\n"
            f"Upstream SOCKS: {cfg.upstream_socks_host}:{cfg.upstream_socks_port}\n\n"
            f"{rules_summary}\n\n"
            "Предпросмотр 3proxy.cfg:\n"
            "─────────────────────────\n"
            f"{proxy_cfg}",
            tip="Нажмите [y] для подтверждения.",
        )

    try:
        summary = cascade_mod.apply(cfg, artifacts_dir)
    except Exception as exc:
        return ActionResult(False, "Cascade: генерация не удалась", str(exc))

    return ActionResult(
        True,
        "Cascade: конфигурация сгенерирована",
        summary + "\n\n"
        "Для запуска службы:\n"
        "  sudo cp artifacts/cascade/cascade.service /etc/systemd/system/\n"
        "  sudo systemctl daemon-reload && sudo systemctl enable --now cascade",
        tip="Не забудьте также установить 3proxy если ещё не установлен.",
    )


def list_managed_rules() -> ActionResult:
    """List rules from managed rules.json (written by add_rule/reset_rules)."""
    artifacts_dir = _find_artifacts_dir()
    rules = cascade_mod.load_rules(artifacts_dir)
    rules_path = artifacts_dir / "cascade" / "rules.json"

    if not rules:
        return ActionResult(
            True,
            "Cascade: управляемые правила",
            f"Файл правил: {rules_path}\n\n"
            "Управляемых правил нет.\n\n"
            "Используйте «Добавить правило» для создания нового правила.",
        )

    lines = [f"Файл правил: {rules_path}", f"Всего правил: {len(rules)}", ""]
    for r in rules:
        lines.append(
            f"  [{r['id']}] "
            f"{r['protocol'].upper()} :{r['listen_port']} → {r['target_host']}:{r['target_port']}"
            f"  [{r.get('status', '?')}]"
        )
        if r.get("notes"):
            lines.append(f"      {r['notes']}")

    return ActionResult(True, "Cascade: управляемые правила", "\n".join(lines))


def add_rule(
    protocol: str,
    listen_port: int,
    target_host: str,
    target_port: int,
    notes: str = "",
    confirmed: bool = False,
) -> ActionResult:
    """Add a managed rule to rules.json.

    When confirmed=False, returns a preview. When confirmed=True, writes the rule.
    """
    # Validate inputs
    if protocol not in ("tcp", "udp", "both"):
        return ActionResult(
            False, "Cascade: добавить правило",
            f"Неверный протокол: {protocol!r}. Допустимые: tcp, udp, both."
        )
    if not (1 <= listen_port <= 65535):
        return ActionResult(
            False, "Cascade: добавить правило",
            f"Неверный порт прослушивания: {listen_port}. Допустимый диапазон: 1–65535."
        )
    if not (1 <= target_port <= 65535):
        return ActionResult(
            False, "Cascade: добавить правило",
            f"Неверный целевой порт: {target_port}. Допустимый диапазон: 1–65535."
        )
    if not target_host:
        return ActionResult(
            False, "Cascade: добавить правило",
            "Целевой хост не указан."
        )

    artifacts_dir = _find_artifacts_dir()

    if not confirmed:
        return ActionResult(
            False,
            "Cascade: добавить правило",
            f"Будет добавлено в {artifacts_dir / 'cascade' / 'rules.json'}:\n\n"
            f"  Протокол:  {protocol.upper()}\n"
            f"  Порт:      :{listen_port}\n"
            f"  Цель:      {target_host}:{target_port}\n"
            f"  Заметка:   {notes or '—'}\n\n"
            "Правило сохраняется только в rules.json.\n"
            "Для применения в iptables потребуется ручная конфигурация системы.",
            tip="Нажмите [y] для подтверждения.",
        )

    try:
        rule = cascade_mod.add_rule(
            artifacts_dir,
            protocol=protocol,
            listen_port=listen_port,
            target_host=target_host,
            target_port=target_port,
            notes=notes,
        )
    except Exception as exc:
        return ActionResult(False, "Cascade: добавить правило", f"Ошибка записи: {exc}")

    return ActionResult(
        True,
        "Cascade: правило добавлено",
        f"ID:       {rule['id']}\n"
        f"Протокол: {rule['protocol'].upper()}\n"
        f"Порт:     :{rule['listen_port']}\n"
        f"Цель:     {rule['target_host']}:{rule['target_port']}\n"
        f"Заметка:  {rule.get('notes') or '—'}",
    )


def remove_rule(rule_id: str, confirmed: bool = False) -> ActionResult:
    """Remove a managed rule by id from rules.json.

    When confirmed=False, returns a preview. When confirmed=True, removes the rule.
    """
    artifacts_dir = _find_artifacts_dir()
    rules = cascade_mod.load_rules(artifacts_dir)

    target = next((r for r in rules if r.get("id") == rule_id), None)
    if target is None:
        return ActionResult(
            False,
            "Cascade: удалить правило",
            f"Правило с ID {rule_id!r} не найдено в rules.json.\n\n"
            "Используйте «Список правил» для просмотра актуальных ID.",
        )

    if not confirmed:
        return ActionResult(
            False,
            "Cascade: удалить правило",
            f"Будет удалено:\n\n"
            f"  ID:       {target['id']}\n"
            f"  Протокол: {target['protocol'].upper()}\n"
            f"  Порт:     :{target['listen_port']}\n"
            f"  Цель:     {target['target_host']}:{target['target_port']}\n",
            tip="Нажмите [y] для подтверждения.",
        )

    try:
        removed = cascade_mod.remove_rule(artifacts_dir, rule_id)
    except Exception as exc:
        return ActionResult(False, "Cascade: удалить правило", f"Ошибка записи: {exc}")

    if removed:
        return ActionResult(
            True,
            "Cascade: правило удалено",
            f"Правило {rule_id!r} удалено из rules.json.",
        )
    return ActionResult(
        False,
        "Cascade: удалить правило",
        f"Правило {rule_id!r} не найдено (возможно уже удалено).",
    )


def reset_rules(confirmed: bool = False) -> ActionResult:
    """Clear all managed rules from rules.json.

    When confirmed=False, returns a preview with current count.
    When confirmed=True, removes all rules (destructive).
    """
    artifacts_dir = _find_artifacts_dir()
    rules = cascade_mod.load_rules(artifacts_dir)

    if not confirmed:
        if not rules:
            return ActionResult(
                True,
                "Cascade: сброс правил",
                "Управляемых правил нет — сбрасывать нечего.",
            )
        return ActionResult(
            False,
            "Cascade: сброс правил",
            f"⚠ Будут удалены ВСЕ {len(rules)} управляемых правила из rules.json.\n\n"
            "Это действие необратимо для файла rules.json.\n"
            "(Системные правила iptables не затрагиваются.)",
            tip="Нажмите [y] для подтверждения.",
        )

    try:
        count = cascade_mod.reset_rules(artifacts_dir)
    except Exception as exc:
        return ActionResult(False, "Cascade: сброс правил", f"Ошибка записи: {exc}")

    return ActionResult(
        True,
        "Cascade: правила сброшены",
        f"Удалено правил: {count}. Файл rules.json очищен.",
    )


def show_config() -> ActionResult:
    """Show contents of generated config files if they exist."""
    artifacts_dir = _find_artifacts_dir()
    out_dir = artifacts_dir / "cascade"

    cfg_file = out_dir / "3proxy.cfg"
    svc_file = out_dir / "cascade.service"
    state_file = out_dir / "state.json"

    if not any(f.exists() for f in [cfg_file, svc_file, state_file]):
        return ActionResult(
            False,
            "Cascade: конфигурация",
            f"Файлы конфигурации не найдены в {out_dir}.\n\n"
            "Используйте «Применить конфиг» для генерации.",
        )

    lines: list[str] = [f"Директория: {out_dir}", ""]
    for f in [cfg_file, svc_file, state_file]:
        if f.exists():
            lines.append(f"── {f.name} ──")
            lines.append(f.read_text(encoding="utf-8").strip())
            lines.append("")

    return ActionResult(True, "Cascade: конфигурация", "\n".join(lines))


# ---------------------------------------------------------------------------
# 3proxy install guide (read-only)
# ---------------------------------------------------------------------------

def install_3proxy_guide() -> ActionResult:
    """Show instructions for installing 3proxy (never executes apt directly)."""
    proxy3 = shutil.which("3proxy")
    installed = proxy3 is not None

    if installed:
        # Check version
        r = run([proxy3, "--version"])
        version_line = r.stdout.strip().splitlines()[0] if r.ok and r.stdout.strip() else "версия неизвестна"
        return ActionResult(
            True,
            "3proxy: установка",
            f"3proxy уже установлен: {proxy3}\n{version_line}\n\n"
            "Можно переходить к «Применить конфиг».",
        )

    body = (
        "3proxy не найден в PATH.\n\n"
        "Установка (Debian/Ubuntu):\n\n"
        "  sudo apt-get update\n"
        "  sudo apt-get install -y 3proxy\n\n"
        "Или из исходников:\n\n"
        "  git clone https://github.com/z3apa3a/3proxy\n"
        "  cd 3proxy && make -f Makefile.Linux\n"
        "  sudo make -f Makefile.Linux install\n\n"
        "После установки используйте «Применить конфиг» для генерации конфигурации,\n"
        "затем запустите службу вручную или через systemd."
    )
    return ActionResult(False, "3proxy: установка", body, tip="Выполните команды в отдельном терминале.")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_artifacts_dir() -> Path:
    """Locate the artifacts base directory (project root / /opt / /var/lib)."""
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "artifacts").exists():
            return p
    # Fallback: try standard paths
    for path in [
        Path("/opt/daran-proxy-stack"),
        Path("/var/lib/daran-proxy-stack"),
    ]:
        if path.exists():
            return path
    # Use project root heuristic (3 levels up from actions/)
    return here.parent.parent.parent.parent.parent
