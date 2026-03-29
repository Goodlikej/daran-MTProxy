"""Real MTProxy actions for the terminal menu.

Wraps existing MTProxy module helpers and provides preview/confirm flows
aligned with the rest of the terminal menu actions.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from daran_proxy_stack.discovery.modules.mtproxy import detect_mtproxy
from daran_proxy_stack.discovery.schema import ModuleHealth
from daran_proxy_stack.lib.config import default_config_path, load_config, save_config
from daran_proxy_stack.lib.models import AppConfig, MTProxyConfig
from daran_proxy_stack.lib.shell import run
from daran_proxy_stack.modules import mtproxy as mtp_mod

FALLBACK_PORTS = [2053, 2083, 2087, 2096]


@dataclass
class ActionResult:
    ok: bool
    title: str
    body: str
    tip: str = ""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def default_config(config_path: Path | None = None) -> MTProxyConfig:
    return load_config(config_path).mtproxy


def _resolve_mtproxy_config(
    app_cfg: AppConfig,
    *,
    port: int | None = None,
    stats_port: int | None = None,
) -> AppConfig:
    mtproxy_data = app_cfg.mtproxy.model_dump()
    if port is not None:
        mtproxy_data["listen_port"] = port
    if stats_port is not None:
        mtproxy_data["stats_port"] = stats_port
    return AppConfig(
        paths=app_cfg.paths,
        warp=app_cfg.warp,
        cascade=app_cfg.cascade,
        mtproxy=MTProxyConfig(**mtproxy_data),
    )


def _validate_port(port: int) -> str | None:
    if port < 1 or port > 65535:
        return "Port must be in range 1..65535."
    return None


def _available_fallback_ports() -> list[int]:
    return [candidate for candidate in FALLBACK_PORTS if mtp_mod.is_port_free(candidate)]


def _save_selected_port(port: int, config_path: Path | None = None) -> Path:
    target = config_path or default_config_path()
    app_cfg = load_config(target)
    updated_cfg = _resolve_mtproxy_config(app_cfg, port=port)
    return save_config(updated_cfg, target)


def _find_generated_dir() -> Path | None:
    """Locate the generated artifacts directory."""
    candidates = [
        Path("/opt/daran-proxy-stack/artifacts/generated/mtproxy"),
        Path("/var/lib/daran-proxy-stack/generated/mtproxy"),
    ]
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
# Read-only
# ---------------------------------------------------------------------------

def status(config_path: Path | None = None) -> ActionResult:
    """Collect MTProxy diagnostics."""
    cfg = default_config(config_path)
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
                    "tg://proxy ссылка для клиентов:\n\n"
                    f"  {tg_link}\n\n"
                    f"Секрет: {secret}\n"
                    f"Файл:   {link_file}"
                )
                return ActionResult(True, "MTProxy: tg-ссылка", body)
        except OSError:
            pass

    cfg = default_config()
    if secret_file.exists():
        try:
            secret = secret_file.read_text(encoding="utf-8").strip()
            server_ip = mtp_mod.detect_server_ip()
            if server_ip and secret:
                tg_link = mtp_mod.render_tg_link(cfg, public_ip=server_ip, secret=secret)
                body = (
                    "tg://proxy ссылка (вычислена):\n\n"
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


# ---------------------------------------------------------------------------
# Service control (systemctl or docker)
# ---------------------------------------------------------------------------

def _detect_manager() -> tuple[str, str | None]:
    """Return (manager_type, unit_or_container)."""
    systemctl = shutil.which("systemctl")
    if systemctl:
        r = run([systemctl, "is-active", "--quiet", "MTProxy"])
        if r.returncode in (0, 3):
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


# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------

def install(
    *,
    confirmed: bool = False,
    port: int | None = None,
    stats_port: int | None = None,
    config_path: Path | None = None,
) -> ActionResult:
    """Preview or execute the official MTProxy install flow."""
    base_cfg = load_config(config_path)
    target_port = port if port is not None else base_cfg.mtproxy.listen_port
    target_stats_port = stats_port if stats_port is not None else base_cfg.mtproxy.stats_port

    port_error = _validate_port(target_port)
    if port_error:
        return ActionResult(False, "MTProxy: установка", port_error)

    state = detect_mtproxy()
    if state.installed and state.running and state.health in (ModuleHealth.healthy, ModuleHealth.degraded):
        observed_port = None
        if state.public_endpoint is not None:
            observed_port = state.public_endpoint.port
        port_note = f" на порту {observed_port}" if observed_port else ""
        return ActionResult(True, "MTProxy: установка", f"MTProxy уже установлен и работает{port_note}.")

    resolved_cfg = _resolve_mtproxy_config(base_cfg, port=target_port, stats_port=target_stats_port)
    diagnostics = mtp_mod.collect_diagnostics(resolved_cfg.mtproxy)
    project_root = _project_root()
    paths = mtp_mod.save_generated_files(project_root, resolved_cfg.mtproxy, public_ip=resolved_cfg.mtproxy.public_host)
    generated_dir = paths["compose"].parent
    doctor_report = mtp_mod.render_official_doctor_report(resolved_cfg.mtproxy, diagnostics, generated_dir)
    command = mtp_mod.render_install_command_sequence(resolved_cfg.mtproxy, str(paths["systemd"]))

    port_busy = diagnostics.port_status != "free"
    if port_busy and target_port == 443:
        available = _available_fallback_ports()
        choices = ", ".join(str(p) for p in available) if available else "нет свободных кандидатов"
        body = (
            "Порт 443 уже занят.\n"
            f"Доступные альтернативные порты: {choices}\n\n"
            f"--- Doctor report ---\n{doctor_report}"
        )
        return ActionResult(
            False,
            "MTProxy: конфликт порта",
            body,
            tip="Выберите один из предложенных fallback-портов и повторите установку.",
        )

    if port_busy:
        return ActionResult(
            False,
            "MTProxy: установка",
            f"Порт {target_port} уже занят.\n\n--- Doctor report ---\n{doctor_report}",
        )

    if not confirmed:
        body = (
            "Будет выполнена официальная установка MTProxy.\n\n"
            f"Listen port: {target_port}\n"
            f"Stats port:  {target_stats_port}\n"
            f"Config path: {config_path or default_config_path()}\n\n"
            f"--- Doctor report ---\n{doctor_report}\n\n"
            f"Команда:\n{command}"
        )
        return ActionResult(
            False,
            "MTProxy: установка",
            body,
            tip="Нажмите [y] для подтверждения установки.",
        )

    save_path = _save_selected_port(target_port, config_path=config_path)
    result = run(["bash", "-lc", command])
    if result.ok:
        body = (
            "Official MTProxy install sequence completed.\n\n"
            f"Listen port saved to: {save_path}\n"
            f"stdout:\n{result.stdout or '(empty)'}"
        )
        return ActionResult(True, "MTProxy: установка завершена", body)

    return ActionResult(
        False,
        "MTProxy: установка не удалась",
        f"Listen port saved to: {save_path}\n\nstderr:\n{result.stderr or '(empty)'}",
    )


def install_guide(
    *,
    port: int | None = None,
    stats_port: int | None = None,
    config_path: Path | None = None,
) -> ActionResult:
    """Backward-compatible alias for the install preview."""
    return install(
        confirmed=False,
        port=port,
        stats_port=stats_port,
        config_path=config_path,
    )


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
