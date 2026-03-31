"""Real MTProxy actions for the terminal menu.

Wraps existing modules/mtproxy.py logic and systemctl/docker calls.
All destructive operations require confirmed=True.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from daran_proxy_stack.lib.models import MTProxyConfig
from daran_proxy_stack.lib.shell import run
from daran_proxy_stack.modules import mtproxy as mtp_mod


@dataclass
class ActionResult:
    ok: bool
    title: str
    body: str
    tip: str = ""


def default_config() -> MTProxyConfig:
    return MTProxyConfig()


# ---------------------------------------------------------------------------
# Read-only
# ---------------------------------------------------------------------------

def status() -> ActionResult:
    """Collect MTProxy diagnostics."""
    cfg = default_config()
    try:
        diag = mtp_mod.collect_diagnostics(cfg)
    except Exception as exc:
        return ActionResult(False, "MTProxy: статус", f"Ошибка диагностики: {exc}")

    lines = [
        f"Server IP:         {diag.server_ip or 'unknown'}",
        f"Docker:            {diag.docker_path or 'не найден'}",
        f"docker-compose:    {diag.docker_compose_path or 'не найден'}",
        f"git:               {diag.git_path or 'не найден'}",
        f"curl:              {diag.curl_path or 'не найден'}",
        f"make:              {diag.make_path or 'не найден'}",
        f"gcc:               {diag.gcc_path or 'не найден'}",
        f"systemctl:         {diag.systemctl_path or 'не найден'}",
        f"ufw:               {diag.ufw_path or 'не найден'}",
        f"Run user exists:   {'да' if diag.run_user_exists else 'нет'}",
        f"Compose generated: {'да' if diag.compose_exists else 'нет'}",
        f"Container status:  {diag.container_status}",
        f"Port {cfg.listen_port}:         {diag.port_status}",
    ]
    return ActionResult(True, "MTProxy: диагностика", "\n".join(lines))


def show_tg_link() -> ActionResult:
    """Show tg:// link if available from generated artifacts."""
    # Check generated artifacts
    generated_dir = _find_generated_dir()
    if not generated_dir:
        return ActionResult(
            False,
            "MTProxy: tg-ссылка",
            "Артефакты не найдены.\n\n"
            "Сначала запустите генерацию:\n"
            "  daran-net mtproxy generate\n"
            "  daran-net mtproxy official-install",
        )

    secret_file = generated_dir / "secret.txt"
    link_file = generated_dir / "tg-link.txt"

    if link_file.exists():
        try:
            tg_link = link_file.read_text(encoding="utf-8").strip()
            if tg_link:
                secret = secret_file.read_text(encoding="utf-8").strip() if secret_file.exists() else "n/a"
                body = (
                    f"tg://proxy ссылка для клиентов:\n\n"
                    f"  {tg_link}\n\n"
                    f"Секрет: {secret}\n"
                    f"Файл:   {link_file}"
                )
                return ActionResult(True, "MTProxy: tg-ссылка", body)
        except OSError:
            pass

    # Try to build from secret + server IP
    cfg = default_config()
    if secret_file.exists():
        try:
            secret = secret_file.read_text(encoding="utf-8").strip()
            server_ip = mtp_mod.detect_server_ip()
            if server_ip and secret:
                tg_link = mtp_mod.render_tg_link(cfg, public_ip=server_ip, secret=secret)
                body = (
                    f"tg://proxy ссылка (вычислена):\n\n"
                    f"  {tg_link}\n\n"
                    f"Секрет: {secret}\n"
                    f"IP:     {server_ip}\n"
                    f"Порт:   {cfg.listen_port}"
                )
                return ActionResult(True, "MTProxy: tg-ссылка", body)
        except Exception as exc:
            return ActionResult(False, "MTProxy: tg-ссылка", f"Ошибка: {exc}")

    return ActionResult(
        False,
        "MTProxy: tg-ссылка",
        "Секрет не найден. Запустите установку или генерацию артефактов.\n"
        "  daran-net mtproxy generate",
    )


def _find_generated_dir() -> Path | None:
    """Locate the generated artifacts directory."""
    candidates = [
        Path("/opt/daran-proxy-stack/artifacts/generated/mtproxy"),
        Path("/var/lib/daran-proxy-stack/generated/mtproxy"),
    ]
    # Dev-mode: relative to project root
    here = Path(__file__).resolve()
    for p in here.parents:
        candidate = p / "artifacts" / "generated" / "mtproxy"
        if candidate.exists():
            candidates.insert(0, candidate)
            break
    for p in candidates:
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Service control (systemctl or docker)
# ---------------------------------------------------------------------------

def _detect_manager() -> tuple[str, str | None]:
    """Return (manager_type, unit_or_container).

    manager_type: 'systemd' | 'docker' | 'none'
    """
    systemctl = shutil.which("systemctl")
    if systemctl:
        r = run([systemctl, "is-active", "--quiet", "MTProxy"])
        if r.returncode in (0, 3):  # 3 = inactive (but unit exists)
            # check if unit file exists
            r2 = run([systemctl, "cat", "MTProxy"])
            if r2.ok or r.returncode == 0:
                return "systemd", "MTProxy"

    docker = shutil.which("docker")
    if docker:
        r = run([docker, "ps", "-a", "--filter", "name=mtproxy", "--format", "{{.Names}}"])
        if r.ok and "mtproxy" in r.stdout:
            return "docker", "mtproxy"

    return "none", None


def restart() -> ActionResult:
    """Restart MTProxy service (systemd or docker)."""
    manager, unit = _detect_manager()

    if manager == "systemd":
        r = run(["sudo", "systemctl", "restart", unit])
        if r.ok:
            return ActionResult(True, "MTProxy: перезапуск", f"systemctl restart {unit}: ok")
        return ActionResult(False, "MTProxy: перезапуск не удался", r.stderr or r.stdout)

    if manager == "docker":
        r = run(["docker", "restart", unit])
        if r.ok:
            return ActionResult(True, "MTProxy: перезапуск", f"docker restart {unit}: ok")
        return ActionResult(False, "MTProxy: перезапуск не удался", r.stderr or r.stdout)

    return ActionResult(
        False,
        "MTProxy: перезапуск",
        "Не удалось определить менеджер сервиса.\n\n"
        "Вручную:\n"
        "  sudo systemctl restart MTProxy\n"
        "  # или\n"
        "  docker restart mtproxy",
    )


def install_guide() -> ActionResult:
    """Return installation guide and commands (read-only, no execution)."""
    cfg = default_config()
    try:
        diag = mtp_mod.collect_diagnostics(cfg)
        generated_base = Path(__file__).resolve()
        for p in generated_base.parents:
            if (p / "artifacts").exists():
                generated_base = p
                break
        doctor_report = mtp_mod.render_official_doctor_report(
            cfg,
            diag,
            generated_base / "artifacts" / "generated" / "mtproxy",
        )
    except Exception as exc:
        doctor_report = f"(doctor check failed: {exc})"

    body = (
        "Официальная установка MTProxy:\n\n"
        "  daran-net mtproxy official-install\n\n"
        "Или пошагово:\n"
        "  daran-net mtproxy official-build --yes\n"
        "  daran-net mtproxy official-fetch --yes\n"
        "  daran-net mtproxy systemd-apply --yes\n\n"
        f"--- Doctor report ---\n{doctor_report}"
    )
    return ActionResult(True, "MTProxy: установка", body, tip="Запустите команды в отдельном терминале.")


def install(port: int | None = None, confirmed: bool = False) -> ActionResult:
    """Install MTProxy via official build + systemd.

    confirmed=False → preview plan only (no system changes).
    confirmed=True  → execute bootstrap script.
    """
    cfg = default_config()
    if port is not None:
        cfg = cfg.model_copy(update={"listen_port": port})

    port_status = mtp_mod.detect_port_status(cfg.listen_port)
    port_free = port_status == "free"

    if not confirmed:
        lines = [
            "Официальная установка MTProxy (сборка из исходников + systemd):",
            "",
            f"  Порт прослушивания: {cfg.listen_port}",
            f"  Порт статистики:    {cfg.stats_port}",
            f"  Пользователь:       {cfg.run_user}",
            "",
            "Шаги:",
            "  1. apt install git curl build-essential libssl-dev zlib1g-dev",
            f"  2. git clone {mtp_mod.OFFICIAL_REPO} {mtp_mod.OFFICIAL_INSTALL_DIR}",
            "  3. make  (компиляция ~2–5 мин)",
            "  4. Загрузка proxy-secret + proxy-multi.conf",
            "  5. Установка MTProxy.service в /etc/systemd/system/",
            "  6. systemctl enable --now MTProxy.service",
        ]
        if not port_free:
            lines.append("")
            lines.append(f"[yellow]⚠ Порт {cfg.listen_port} занят ({port_status})[/yellow]")
        return ActionResult(
            True,
            "MTProxy: план установки",
            "\n".join(lines),
            tip="Нажмите [y] для запуска установки.",
        )

    # === Execute installation ===
    # Locate project root (directory containing artifacts/) or fall back to cwd
    generated_base = Path.cwd()
    for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if (p / "artifacts").exists():
            generated_base = p
            break

    # Save generated files (creates bootstrap script + secrets + service)
    try:
        server_ip = mtp_mod.detect_server_ip()
        paths = mtp_mod.save_generated_files(generated_base, cfg, public_ip=server_ip)
        bootstrap_path = paths.get("official_bootstrap")
    except Exception as exc:
        return ActionResult(False, "MTProxy: установка", f"Ошибка генерации файлов:\n{exc}")

    if not bootstrap_path or not Path(bootstrap_path).exists():
        return ActionResult(False, "MTProxy: установка", "Не удалось создать скрипт установки.")

    # Run bootstrap script
    r = run(["bash", str(bootstrap_path)])
    if r.ok:
        out = r.stdout[-2000:] if len(r.stdout) > 2000 else r.stdout

        # Post-install: open firewall + verify port + get public IP
        from daran_proxy_stack.lib import firewall
        ufw_ok, ufw_msg = firewall.apply_ufw_rule(cfg.listen_port, "tcp")
        port_up = firewall.check_port_listening(cfg.listen_port)
        public_ip = firewall.get_public_ip() or "не определён"

        checklist = [
            "",
            "─── Пост-установочная проверка ───",
            f"  {'✓' if port_up else '⚠'} Сервис слушает порт {cfg.listen_port}:"
            f" {'да' if port_up else 'нет — проверьте: systemctl status MTProxy'}",
            f"  {'✓' if ufw_ok else '⚠'} Firewall: {ufw_msg}",
            f"  🌐 Публичный IP сервера: {public_ip}",
            "",
            "  Следующий шаг: выберите [6] в меню MTProxy → получить tg-ссылку",
        ]
        return ActionResult(
            True,
            "MTProxy: установка завершена",
            f"Установка выполнена успешно.\n\n{out}" + "\n".join(checklist),
        )
    err = (r.stderr or r.stdout or "неизвестная ошибка")[-3000:]
    return ActionResult(False, "MTProxy: ошибка установки", f"Ошибка:\n{err}")


def uninstall(confirmed: bool = False) -> ActionResult:
    """Remove MTProxy (systemd + binary, or docker container)."""
    if not confirmed:
        return ActionResult(
            False,
            "MTProxy: удаление",
            "Будет выполнено:\n"
            "  sudo systemctl stop MTProxy\n"
            "  sudo systemctl disable MTProxy\n"
            "  sudo rm /etc/systemd/system/MTProxy.service\n"
            "  sudo systemctl daemon-reload\n"
            "# или docker rm mtproxy\n\n"
            "[yellow]Артефакты в artifacts/generated/mtproxy НЕ удаляются.[/yellow]",
            tip="Нажмите [y] для подтверждения.",
        )

    manager, unit = _detect_manager()
    steps: list[str] = []

    if manager == "systemd":
        for cmd in [
            ["sudo", "systemctl", "stop", "MTProxy"],
            ["sudo", "systemctl", "disable", "MTProxy"],
            ["sudo", "rm", "-f", "/etc/systemd/system/MTProxy.service"],
            ["sudo", "systemctl", "daemon-reload"],
        ]:
            r = run(cmd)
            steps.append(f"{' '.join(cmd[1:])}: {'ok' if r.ok else r.stderr or 'failed'}")

        return ActionResult(True, "MTProxy: удалён (systemd)", "\n".join(steps))

    if manager == "docker":
        r = run(["docker", "rm", "-f", unit])
        if r.ok:
            return ActionResult(True, "MTProxy: удалён (docker)", f"docker rm -f {unit}: ok")
        return ActionResult(False, "MTProxy: удаление не удалось", r.stderr or r.stdout)

    return ActionResult(
        False,
        "MTProxy: удаление",
        "Сервис не обнаружен (ни systemd, ни docker).\n"
        "Возможно, MTProxy уже удалён.",
    )
