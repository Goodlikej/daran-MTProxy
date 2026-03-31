from __future__ import annotations

import asyncio
import shutil
import socket
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daran_proxy_stack.lib.config import load_config
from daran_proxy_stack.lib.executor import executor
from daran_proxy_stack.lib.multiserver import ServerEntry, ServerRegistry, _default_config_dir, make_server_id
from daran_proxy_stack.lib.shell import run
from daran_proxy_stack.modules import cascade as cascade_mod
from daran_proxy_stack.modules import discovery as discovery_mod
from daran_proxy_stack.modules import mtproxy as mt_mod
from daran_proxy_stack.modules import warp as warp_mod
from daran_proxy_stack import discovery as new_discovery

router = APIRouter()

_START_TIME = time.time()

# Project root: api.py → web → daran_proxy_stack → src → project_root
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_ARTIFACTS = _PROJECT_ROOT / "artifacts" / "generated"
_MTPROXY_GENERATED = _ARTIFACTS / "mtproxy"


def _cfg():
    return load_config(None)


# ── helpers ────────────────────────────────────────────────────────────────────

def _server_info() -> dict:
    cfg = _cfg()
    ip = warp_mod.detect_server_ip()
    os_rel = warp_mod.detect_os_release()

    hostname = "unknown"
    try:
        hostname = socket.gethostname()
    except Exception:
        pass

    uptime_s: float | None = None
    try:
        uptime_s = float(Path("/proc/uptime").read_text().split()[0])
    except Exception:
        pass

    mem: dict = {}
    try:
        raw = {k: v for k, v in (
            line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines() if ":" in line
        )}
        total_kb = int(raw.get("MemTotal", "0 kB").split()[0])
        avail_kb = int(raw.get("MemAvailable", "0 kB").split()[0])
        mem = {
            "total_mb": total_kb // 1024,
            "available_mb": avail_kb // 1024,
            "used_mb": (total_kb - avail_kb) // 1024,
            "used_pct": round((total_kb - avail_kb) / total_kb * 100, 1) if total_kb else 0,
        }
    except Exception:
        pass

    load_avg: list[float] = []
    try:
        load_avg = [round(float(x), 2) for x in Path("/proc/loadavg").read_text().split()[:3]]
    except Exception:
        pass

    disk: dict = {}
    try:
        res = run(["df", "-BM", "--output=size,used,avail,pcent", "/"])
        if res.ok:
            lines = res.stdout.strip().splitlines()
            if len(lines) >= 2:
                parts = lines[1].split()
                disk = {
                    "total": parts[0],
                    "used": parts[1],
                    "avail": parts[2],
                    "used_pct": parts[3],
                }
    except Exception:
        pass

    return {
        "hostname": hostname,
        "ip": ip,
        "os": os_rel,
        "uptime_s": uptime_s,
        "mem": mem,
        "load_avg": load_avg,
        "disk": disk,
    }


def _mtproxy_info() -> dict:
    cfg = _cfg()
    try:
        d = mt_mod.collect_diagnostics(cfg.mtproxy)
        secret_file = Path(__file__).resolve().parents[4] / "artifacts" / "generated" / "mtproxy" / "secret.txt"
        secret = secret_file.read_text().strip() if secret_file.exists() else None
        tg_link_file = secret_file.parent / "tg-link.txt"
        tg_link = tg_link_file.read_text().strip() if tg_link_file.exists() else None

        # Prefer observed port from running container over raw config default.
        observed_port: int | None = None
        container_running = d.container_status and d.container_status.lower().startswith("up")
        if container_running and d.docker_path:
            _port_result = run([d.docker_path, "ps",
                "--filter", f"name={cfg.mtproxy.container_name}",
                "--format", "{{.Ports}}"])
            if _port_result.ok and _port_result.stdout.strip():
                _ep = discovery_mod._parse_docker_ports(_port_result.stdout.strip().splitlines()[0])
                if _ep and ":" in _ep:
                    try:
                        observed_port = int(_ep.rsplit(":", 1)[1])
                    except ValueError:
                        pass

        effective_port = observed_port if observed_port is not None else cfg.mtproxy.listen_port

        return {
            "ok": True,
            "port": effective_port,
            "port_source": "observed" if observed_port is not None else "config",
            "stats_port": cfg.mtproxy.stats_port,
            "docker": d.docker_path is not None,
            "docker_compose": d.docker_compose_path is not None,
            "systemctl": d.systemctl_path is not None,
            "git": d.git_path is not None,
            "gcc": d.gcc_path is not None,
            "make": d.make_path is not None,
            "server_ip": d.server_ip,
            "container_status": d.container_status,
            "port_status": d.port_status,
            "compose_exists": d.compose_exists,
            "run_user_exists": d.run_user_exists,
            "secret": secret,
            "tg_link": tg_link,
            "image": cfg.mtproxy.image,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _warp_info() -> dict:
    cfg = _cfg()
    try:
        d = warp_mod.collect_diagnostics(cfg.warp)

        # Observed backend: if backend=auto, trust detected tool presence over config label.
        observed_backend = d.recommended_backend  # already resolved from detection

        # SOCKS endpoint is only valid when the SOCKS proxy process is actually running.
        socks_endpoint = (
            f"{cfg.warp.socks_host}:{cfg.warp.socks_port}"
            if d.socks_running
            else None
        )

        # Version from warp-cli --version if available.
        warp_version: str | None = None
        if d.warp_cli_path:
            _ver = run([d.warp_cli_path, "--version"])
            if _ver.ok and _ver.stdout.strip():
                warp_version = _ver.stdout.strip().splitlines()[0]

        return {
            "ok": True,
            "warp_cli": d.warp_cli_path is not None,
            "cloudflared": d.cloudflared_path is not None,
            "systemctl": d.systemctl_path is not None,
            "os": d.os_release,
            "server_ip": d.server_ip,
            "warp_status": d.warp_status,
            "connected": d.connected,
            "socks_running": d.socks_running,
            "backend": observed_backend,
            "backend_source": "detected" if cfg.warp.backend == "auto" else "config",
            "socks_host": cfg.warp.socks_host,
            "socks_port": cfg.warp.socks_port,
            "socks_endpoint": socks_endpoint,
            "version": warp_version,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


_KNOWN_ACTIONS = [
    {"id": "mtproxy/generate", "name": "MTProxy generate artifacts", "module": "mtproxy"},
    {"id": "warp/connect",     "name": "WARP connect",               "module": "warp"},
    {"id": "warp/disconnect",  "name": "WARP disconnect",            "module": "warp"},
    {"id": "warp/socks-up",    "name": "WARP SOCKS start",           "module": "warp"},
    {"id": "warp/socks-down",  "name": "WARP SOCKS stop",            "module": "warp"},
    {"id": "cascade/apply",    "name": "Cascade apply config",       "module": "cascade"},
    {"id": "cascade/status",   "name": "Cascade status probe",       "module": "cascade"},
]


def _action_dispatch(module: str, action: str):
    """Return a zero-arg callable for the given module/action, or raise HTTPException."""
    cfg = _cfg()

    def _warp_result(fn) -> str:
        r = fn(cfg.warp)
        return f"{r.title}\n{r.body}"

    table: dict[str, dict[str, callable]] = {
        "mtproxy": {
            "generate": lambda: "\n".join(
                f"{k}: {v}" for k, v in mt_mod.save_generated_files(_PROJECT_ROOT, cfg.mtproxy).items()
            ),
        },
        "warp": {
            "connect":    lambda: _warp_result(warp_mod.connect_warp),
            "disconnect": lambda: _warp_result(warp_mod.disconnect_warp),
            "socks-up":   lambda: _warp_result(warp_mod.start_local_socks),
            "socks-down": lambda: _warp_result(warp_mod.stop_local_socks),
        },
        "cascade": {
            "apply":  lambda: cascade_mod.apply(cfg.cascade, _ARTIFACTS),
            "status": lambda: "\n".join(f"{k}: {v}" for k, v in cascade_mod.status_dict(cfg.cascade).items()),
        },
    }

    mod = table.get(module)
    if mod is None:
        raise HTTPException(status_code=404, detail=f"unknown module: {module!r}")
    fn = mod.get(action)
    if fn is None:
        raise HTTPException(status_code=404, detail=f"unknown action {action!r} for module {module!r}")
    return fn


def _inventory_info() -> dict:
    """Collect discovery/inventory for all known stack components.

    Sources data from the new discovery backend via the compat adapter.
    Falls back to the legacy modules/discovery path if the new backend fails.
    """
    try:
        from daran_proxy_stack.discovery.compat import inventory_dict_from_discovery
        return inventory_dict_from_discovery()
    except Exception as exc_new:
        # Graceful fallback: legacy path keeps the endpoint alive if new backend breaks
        try:
            result = discovery_mod.inventory_dict()
            result.setdefault("meta", {})["_backend"] = "legacy/fallback"
            result["meta"]["_fallback_reason"] = str(exc_new)
            return result
        except Exception as exc_old:
            return {"ok": False, "error": str(exc_old), "services": []}


# ── routes ─────────────────────────────────────────────────────────────────────

@router.get("/status")
async def status() -> JSONResponse:
    loop = asyncio.get_event_loop()
    mt, wp, srv, inv = await asyncio.gather(
        loop.run_in_executor(None, _mtproxy_info),
        loop.run_in_executor(None, _warp_info),
        loop.run_in_executor(None, _server_info),
        loop.run_in_executor(None, _inventory_info),
    )
    return JSONResponse({
        "panel_uptime_s": round(time.time() - _START_TIME),
        "server": srv,
        "mtproxy": mt,
        "warp": wp,
        "inventory": inv,
        "tasks": [t.model_dump(mode="json") for t in executor.list_all()],
    })


@router.get("/servers")
async def servers() -> JSONResponse:
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _server_info)
    return JSONResponse(info)


@router.get("/mtproxy")
async def mtproxy() -> JSONResponse:
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _mtproxy_info)
    return JSONResponse(info)


@router.get("/warp")
async def warp() -> JSONResponse:
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _warp_info)
    return JSONResponse(info)


@router.get("/inventory")
async def inventory() -> JSONResponse:
    """Return discovery inventory for all detected stack components."""
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _inventory_info)
    return JSONResponse(info)


@router.get("/discovery")
async def discovery_state() -> JSONResponse:
    """Return full observed-state snapshot from the new discovery backend.

    Uses daran_proxy_stack.discovery (schema v1.0) — richer than /inventory.
    """
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, new_discovery.discovery_dict)
    return JSONResponse(data)


@router.get("/jobs")
async def jobs() -> JSONResponse:
    """Return live task list; fall back to known-action stubs when empty."""
    tasks = executor.list_all()
    if not tasks:
        return JSONResponse([
            {"id": a["id"], "name": a["name"], "status": "idle", "last_run": None}
            for a in _KNOWN_ACTIONS
        ])
    return JSONResponse([
        {
            "id": t.id,
            "name": t.name,
            "status": t.status.value,
            "last_run": t.finished_at.isoformat() if t.finished_at else None,
            "output": t.output,
        }
        for t in tasks
    ])


# ── cascade ─────────────────────────────────────────────────────────────────────

def _cascade_info() -> dict:
    cfg = _cfg()
    try:
        d = cascade_mod.collect_diagnostics(cfg.cascade)
        return {
            "ok": True,
            "note": d.note,
            "config_present": d.config_present,
            "enabled": cfg.cascade.enabled,
            "relay": f"{cfg.cascade.relay_host}:{cfg.cascade.relay_port}",
            "upstream": f"{cfg.cascade.upstream_socks_host}:{cfg.cascade.upstream_socks_port}",
            "relay_reachable": d.relay_reachable,
            "upstream_reachable": d.upstream_reachable,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/cascade")
async def cascade() -> JSONResponse:
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _cascade_info)
    return JSONResponse(info)


@router.post("/cascade/refresh")
async def cascade_refresh() -> JSONResponse:
    # PLACEHOLDER: cascade has no runtime actions yet; returns fresh diagnostics.
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _cascade_info)
    return JSONResponse({"ok": info.get("ok", False), "action": "refresh", "data": info})


# ── warp actions ─────────────────────────────────────────────────────────────────

def _warp_action(fn) -> dict:
    cfg = _cfg()
    try:
        result = fn(cfg.warp)
        return {"ok": result.ok, "title": result.title, "body": result.body}
    except Exception as exc:
        return {"ok": False, "title": "error", "body": str(exc)}


@router.post("/warp/connect")
async def warp_connect() -> JSONResponse:
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, lambda: _warp_action(warp_mod.connect_warp))
    return JSONResponse(res)


@router.post("/warp/disconnect")
async def warp_disconnect() -> JSONResponse:
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, lambda: _warp_action(warp_mod.disconnect_warp))
    return JSONResponse(res)


@router.post("/warp/socks/start")
async def warp_socks_start() -> JSONResponse:
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, lambda: _warp_action(warp_mod.start_local_socks))
    return JSONResponse(res)


@router.post("/warp/socks/stop")
async def warp_socks_stop() -> JSONResponse:
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, lambda: _warp_action(warp_mod.stop_local_socks))
    return JSONResponse(res)


# ── mtproxy actions ──────────────────────────────────────────────────────────────

@router.post("/mtproxy/generate")
async def mtproxy_generate() -> JSONResponse:
    """Generate compose file, secret, and TG link artifacts on disk."""
    def _generate() -> dict:
        cfg = _cfg()
        try:
            paths = mt_mod.save_generated_files(_PROJECT_ROOT, cfg.mtproxy)
            return {"ok": True, "files": {k: str(v) for k, v in paths.items()}}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, _generate)
    return JSONResponse(res)


@router.post("/mtproxy/up")
async def mtproxy_up() -> JSONResponse:
    """Run docker compose up -d on the generated compose file."""
    def _up() -> dict:
        compose_file = _MTPROXY_GENERATED / "docker-compose.yml"
        if not compose_file.exists():
            return {"ok": False, "error": "compose file not generated — call /mtproxy/generate first"}
        docker = shutil.which("docker")
        if not docker:
            return {"ok": False, "error": "docker not found"}
        result = run([docker, "compose", "-f", str(compose_file), "up", "-d"])
        return {"ok": result.ok, "stdout": result.stdout, "stderr": result.stderr}
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, _up)
    return JSONResponse(res)


@router.post("/mtproxy/down")
async def mtproxy_down() -> JSONResponse:
    """Run docker compose down on the generated compose file."""
    def _down() -> dict:
        compose_file = _MTPROXY_GENERATED / "docker-compose.yml"
        if not compose_file.exists():
            return {"ok": False, "error": "compose file not generated"}
        docker = shutil.which("docker")
        if not docker:
            return {"ok": False, "error": "docker not found"}
        result = run([docker, "compose", "-f", str(compose_file), "down"])
        return {"ok": result.ok, "stdout": result.stdout, "stderr": result.stderr}
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, _down)
    return JSONResponse(res)


# ── task / action routes ──────────────────────────────────────────────────────────

@router.get("/tasks")
async def list_tasks() -> JSONResponse:
    return JSONResponse([t.model_dump(mode="json") for t in executor.list_all()])


@router.get("/tasks/{run_id}")
async def get_task(run_id: str) -> JSONResponse:
    task = executor.get(run_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task run {run_id!r} not found")
    return JSONResponse(task.model_dump(mode="json"))


@router.post("/actions/{module}/{action}")
async def trigger_action(module: str, action: str) -> JSONResponse:
    """Dispatch module/action as a tracked background task; return TaskInfo immediately."""
    fn = _action_dispatch(module, action)
    task_name = f"{module}/{action}"
    loop = asyncio.get_event_loop()
    task = await loop.run_in_executor(None, lambda: executor.submit(task_name, fn))
    return JSONResponse(task.model_dump(mode="json"), status_code=202)


# ── multiserver ───────────────────────────────────────────────────────────────────

def _ms_registry() -> ServerRegistry:
    return ServerRegistry(_default_config_dir())


class _AddServerRequest(BaseModel):
    label: str
    host: str
    port: int = 22
    user: str = "root"
    description: str = ""
    tags: list[str] = []


@router.get("/multiserver/servers")
async def multiserver_list() -> JSONResponse:
    reg = _ms_registry()
    return JSONResponse({"servers": [s.to_dict() for s in reg.list_servers()]})


@router.post("/multiserver/servers")
async def multiserver_add(req: _AddServerRequest) -> JSONResponse:
    if not req.label or not req.host:
        raise HTTPException(status_code=400, detail="label and host required")
    reg = _ms_registry()
    entry = ServerEntry(
        id=make_server_id(req.label),
        label=req.label,
        host=req.host,
        port=req.port,
        user=req.user,
        description=req.description,
        tags=req.tags,
    )
    reg.add_server(entry)
    return JSONResponse({"ok": True, "id": entry.id})


@router.delete("/multiserver/servers/{server_id}")
async def multiserver_remove(server_id: str) -> JSONResponse:
    reg = _ms_registry()
    ok = reg.remove_server(server_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"server {server_id!r} not found")
    return JSONResponse({"ok": True})


@router.get("/multiserver/ping")
async def multiserver_ping() -> JSONResponse:
    """TCP-ping all registered servers (parallel)."""
    reg = _ms_registry()
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, reg.ping_all)
    # Merge with full server info for the UI
    server_map = {s.id: s for s in reg.list_servers()}
    enriched = []
    for r in results:
        s = server_map.get(r["id"])
        enriched.append({
            **r,
            "user": s.user if s else "?",
            "description": s.description if s else "",
            "tags": s.tags if s else [],
        })
    return JSONResponse({"servers": enriched})


@router.get("/multiserver/servers/{server_id}/status")
async def multiserver_server_status(server_id: str) -> JSONResponse:
    """Collect diagnostics from a remote server via SSH."""
    reg = _ms_registry()
    entry = reg.get_server(server_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"server {server_id!r} not found")
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, lambda: reg.collect_remote_status(entry))
    return JSONResponse({"label": entry.label, **info})


# ── amneziawg ─────────────────────────────────────────────────────────────────────

@router.get("/amneziawg")
async def amneziawg_status() -> JSONResponse:
    """Return AmneziaWG diagnostics + peer list."""
    def _collect() -> dict:
        try:
            from daran_proxy_stack.lib.models import AmneziaWGConfig
            from daran_proxy_stack.modules.amneziawg import (
                _default_generated_dir, collect_diagnostics, load_state,
            )
            cfg = AmneziaWGConfig()
            gen = _default_generated_dir()
            d = collect_diagnostics(cfg, gen)
            state = load_state(gen)
            return {
                "awg_path": d.awg_path,
                "awg_quick_path": d.awg_quick_path,
                "is_installed": d.is_installed,
                "service_status": d.service_status,
                "interface_up": d.interface_up,
                "interface": cfg.interface,
                "listen_port": cfg.listen_port,
                "server_ip": d.server_ip,
                "config_exists": d.config_exists,
                "peers_count": d.peers_count,
                "peers": state.get("peers", []),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _collect)
    return JSONResponse(info)
