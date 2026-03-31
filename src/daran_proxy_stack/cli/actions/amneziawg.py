"""AmneziaWG actions for the terminal menu.

All destructive / system-modifying actions require confirmed=True.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from daran_proxy_stack.lib.models import AmneziaWGConfig
from daran_proxy_stack.lib.shell import run
from daran_proxy_stack.modules import amneziawg as awg_mod


@dataclass
class ActionResult:
    ok: bool
    title: str
    body: str
    tip: str = ""


def _default_config() -> AmneziaWGConfig:
    return AmneziaWGConfig()


def _generated_dir() -> Path:
    return awg_mod._default_generated_dir()


# ---------------------------------------------------------------------------
# Read-only
# ---------------------------------------------------------------------------

def status() -> ActionResult:
    cfg = _default_config()
    try:
        diag = awg_mod.collect_diagnostics(cfg, _generated_dir())
    except Exception as exc:
        return ActionResult(False, "AmneziaWG: статус", f"Ошибка диагностики: {exc}")

    lines = [
        f"awg:              {diag.awg_path or 'не найден — нужна установка'}",
        f"awg-quick:        {diag.awg_quick_path or 'не найден'}",
        f"Установлен:       {'да' if diag.is_installed else 'нет'}",
        f"Сервис ({awg_mod.AWG_SERVICE}): {diag.service_status}",
        f"Интерфейс up:     {'да' if diag.interface_up else 'нет'}",
        f"Server IP:        {diag.server_ip or 'не определён'}",
        f"Конфиг создан:    {'да' if diag.config_exists else 'нет'}",
        f"Пиров настроено:  {diag.peers_count}",
    ]
    ok = diag.is_installed
    return ActionResult(ok, "AmneziaWG: статус", "\n".join(lines))


def list_peers() -> ActionResult:
    """Show configured peers from awg-state.json."""
    state = awg_mod.load_state(_generated_dir())
    peers = state.get("peers", [])
    if not peers:
        return ActionResult(
            False,
            "AmneziaWG: список пиров",
            "Пиров нет. Добавьте пир через меню → «Добавить пира».",
        )
    lines = [f"Пиров: {len(peers)}", ""]
    for i, p in enumerate(peers, 1):
        lines.append(f"  [{i}] {p['name']}")
        lines.append(f"       IP:  {p['address']}")
        lines.append(f"       Pub: {p['public_key'][:20]}…")
    return ActionResult(True, "AmneziaWG: список пиров", "\n".join(lines))


def show_client_config(peer_name: str) -> ActionResult:
    """Show saved client config for a peer."""
    gen = _generated_dir()
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in peer_name)
    conf_path = gen / "peers" / f"{safe_name}.conf"
    if not conf_path.exists():
        return ActionResult(
            False, "AmneziaWG: клиентский конфиг",
            f"Файл конфига для пира «{peer_name}» не найден.\n"
            f"Ожидался: {conf_path}",
        )
    content = conf_path.read_text(encoding="utf-8")
    return ActionResult(True, f"AmneziaWG: конфиг пира «{peer_name}»", content)


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

def install(confirmed: bool = False) -> ActionResult:
    """Install AmneziaWG via apt PPA (Ubuntu) or show manual steps (Debian).

    confirmed=False → show plan.
    confirmed=True  → run install script.
    """
    script = awg_mod.render_install_script()

    if not confirmed:
        return ActionResult(
            True,
            "AmneziaWG: план установки",
            "Будет выполнено:\n\n"
            "  1. apt install software-properties-common\n"
            "  2. add-apt-repository ppa:amnezia/amneziawg\n"
            "  3. apt install amneziawg amneziawg-tools\n"
            "  4. sysctl net.ipv4.ip_forward=1\n\n"
            f"Репозиторий: {awg_mod.AWG_RELEASES_URL}\n\n"
            "⚠ Требуется Ubuntu. На Debian — ручная установка .deb.",
            tip="Нажмите [y] для запуска.",
        )

    # Save and execute install script
    gen = _generated_dir()
    gen.mkdir(parents=True, exist_ok=True)
    script_path = gen / "install-awg.sh"
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)

    r = run(["bash", str(script_path)])
    if r.ok:
        return ActionResult(True, "AmneziaWG: установлен", r.stdout[-2000:] or "Установка завершена.")
    return ActionResult(False, "AmneziaWG: ошибка установки", (r.stderr or r.stdout)[-2000:])


# ---------------------------------------------------------------------------
# Config generation
# ---------------------------------------------------------------------------

def generate_server_config(
    port: int | None = None,
    address: str | None = None,
    confirmed: bool = False,
) -> ActionResult:
    """Generate server private/public keys and wg0.conf.

    confirmed=False → show what will be created.
    confirmed=True  → generate keys and write files.
    """
    cfg = _default_config()
    if port is not None:
        cfg = cfg.model_copy(update={"listen_port": port})
    if address is not None:
        cfg = cfg.model_copy(update={"server_address": address})

    if not confirmed:
        return ActionResult(
            True,
            "AmneziaWG: план генерации конфига",
            f"Будет создано:\n\n"
            f"  Интерфейс:   {cfg.interface}\n"
            f"  Порт:        {cfg.listen_port}/udp\n"
            f"  Адрес:       {cfg.server_address}\n"
            f"  Подсеть:     {cfg.client_subnet}.0/24\n\n"
            f"Параметры обфускации (AWG):\n"
            f"  Jc={cfg.jc}  Jmin={cfg.jmin}  Jmax={cfg.jmax}\n"
            f"  S1={cfg.s1}  S2={cfg.s2}\n"
            f"  H1={cfg.h1}  H2={cfg.h2}  H3={cfg.h3}  H4={cfg.h4}\n\n"
            f"Файлы → artifacts/generated/amneziawg/",
            tip="Нажмите [y] для генерации.",
        )

    # Generate keys
    try:
        priv, pub = awg_mod.generate_keypair()
    except Exception as exc:
        return ActionResult(False, "AmneziaWG: ошибка", f"Ошибка генерации ключей:\n{exc}")

    server_ip = awg_mod._detect_public_ip()

    # Find base dir
    base_dir = Path(__file__).resolve()
    for p in base_dir.parents:
        if (p / "artifacts").exists():
            base_dir = p
            break

    try:
        paths = awg_mod.save_generated_files(base_dir, cfg, priv, pub, server_ip=server_ip)
    except Exception as exc:
        return ActionResult(False, "AmneziaWG: ошибка сохранения", str(exc))

    return ActionResult(
        True,
        "AmneziaWG: конфиг сгенерирован",
        f"Ключи сгенерированы и сохранены:\n\n"
        f"  Приватный ключ: {paths['private_key']}\n"
        f"  Публичный ключ: {paths['public_key']}\n"
        f"  Конфиг сервера: {paths['server_conf']}\n"
        f"  Публичный IP:   {server_ip or 'не определён'}\n\n"
        f"Следующий шаг: «Применить конфиг» → скопирует в /etc/amneziawg/",
    )


def apply_config(confirmed: bool = False) -> ActionResult:
    """Copy generated wg0.conf to /etc/amneziawg/ and set permissions."""
    cfg = _default_config()
    gen = _generated_dir()
    src = gen / "wg0.conf"

    if not src.exists():
        return ActionResult(
            False, "AmneziaWG: применение конфига",
            "Конфиг не найден. Сначала выполните «Сгенерировать конфиг».",
        )

    if not confirmed:
        return ActionResult(
            True,
            "AmneziaWG: план применения",
            f"Будет скопировано:\n"
            f"  {src}\n"
            f"  → /etc/amneziawg/{cfg.interface}.conf\n\n"
            f"Права: 600 (только root)",
            tip="Нажмите [y] для применения.",
        )

    ok, msg = awg_mod.apply_config_to_system(gen, cfg)
    title = "AmneziaWG: конфиг применён" if ok else "AmneziaWG: ошибка применения"
    return ActionResult(ok, title, msg)


# ---------------------------------------------------------------------------
# Service management
# ---------------------------------------------------------------------------

def _systemctl_action(action: str, service: str = awg_mod.AWG_SERVICE) -> ActionResult:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return ActionResult(False, f"AmneziaWG: {action}", "systemctl не найден.")
    r = run(["sudo", systemctl, action, service])
    ok = r.ok
    body = r.stdout or r.stderr or f"systemctl {action} {service}: {'ok' if ok else 'error'}"
    title = f"AmneziaWG: сервис {action}"
    return ActionResult(ok, title, body)


def service_start(confirmed: bool = False) -> ActionResult:
    if not confirmed:
        return ActionResult(True, "AmneziaWG: запуск", f"Запустит: systemctl start {awg_mod.AWG_SERVICE}", tip="[y] для запуска.")
    return _systemctl_action("start")


def service_stop(confirmed: bool = False) -> ActionResult:
    if not confirmed:
        return ActionResult(True, "AmneziaWG: остановка", f"Остановит: systemctl stop {awg_mod.AWG_SERVICE}", tip="[y] для остановки.")
    return _systemctl_action("stop")


def service_restart(confirmed: bool = False) -> ActionResult:
    if not confirmed:
        return ActionResult(True, "AmneziaWG: перезапуск", f"Перезапустит: systemctl restart {awg_mod.AWG_SERVICE}", tip="[y] для перезапуска.")
    return _systemctl_action("restart")


def service_enable(confirmed: bool = False) -> ActionResult:
    if not confirmed:
        return ActionResult(True, "AmneziaWG: автозапуск", f"systemctl enable --now {awg_mod.AWG_SERVICE}", tip="[y] для включения.")
    return _systemctl_action("enable --now".split()[0])


# ---------------------------------------------------------------------------
# Peer management
# ---------------------------------------------------------------------------

def add_peer(peer_name: str, confirmed: bool = False) -> ActionResult:
    """Add a new peer. confirmed=False → preview IP assignment."""
    cfg = _default_config()
    gen = _generated_dir()
    state = awg_mod.load_state(gen)
    peers = state.get("peers", [])

    if not state.get("server_public_key"):
        return ActionResult(
            False, "AmneziaWG: добавить пира",
            "Сервер не настроен. Сначала сгенерируйте серверный конфиг.",
        )

    # Calculate next IP for preview
    existing = {p["address"] for p in peers}
    next_ip = None
    for i in range(2, 254):
        candidate = f"{cfg.client_subnet}.{i}"
        if candidate not in existing:
            next_ip = candidate
            break

    if not confirmed:
        return ActionResult(
            True,
            "AmneziaWG: новый пир",
            f"Будет создан пир:\n\n"
            f"  Имя:    {peer_name}\n"
            f"  IP:     {next_ip or 'нет свободных адресов'}\n\n"
            "Будут сгенерированы ключи пира.\n"
            "Клиентский конфиг сохранится в artifacts/generated/amneziawg/peers/",
            tip="Нажмите [y] для добавления.",
        )

    ok, msg, conf_path = awg_mod.add_peer(gen, cfg, peer_name)
    if ok and conf_path:
        # Reload service if running
        diag = awg_mod.collect_diagnostics(cfg, gen)
        reload_msg = ""
        if diag.service_status == "active":
            r_sync = run(["sudo", "awg", "syncconf", cfg.interface,
                          f"/etc/amneziawg/{cfg.interface}.conf"])
            reload_msg = "\n  ✓ awg syncconf применён" if r_sync.ok else "\n  ⚠ перезапустите сервис вручную"
        return ActionResult(
            True,
            f"AmneziaWG: пир «{peer_name}» добавлен",
            f"{msg}\n  Конфиг: {conf_path}{reload_msg}\n\n"
            "Для просмотра клиентского конфига: «Показать конфиг пира»",
        )
    return ActionResult(False, "AmneziaWG: ошибка добавления пира", msg)


def remove_peer(peer_name: str, confirmed: bool = False) -> ActionResult:
    """Remove a peer by name."""
    cfg = _default_config()
    gen = _generated_dir()

    if not confirmed:
        state = awg_mod.load_state(gen)
        names = [p["name"] for p in state.get("peers", [])]
        if peer_name not in names:
            return ActionResult(False, "AmneziaWG: удаление пира", f"Пир «{peer_name}» не найден.\nСписок: {', '.join(names) or 'пусто'}")
        return ActionResult(
            True, "AmneziaWG: удаление пира",
            f"Будет удалён пир «{peer_name}».\n"
            "Клиентский конфиг будет стёрт. Серверный конфиг будет пересоздан.",
            tip="Нажмите [y] для удаления.",
        )

    ok, msg = awg_mod.remove_peer(gen, cfg, peer_name)
    return ActionResult(ok, "AmneziaWG: пир удалён" if ok else "AmneziaWG: ошибка", msg)
