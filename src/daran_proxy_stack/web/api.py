from __future__ import annotations

import asyncio
import shutil
import socket
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from daran_proxy_stack.lib.config import load_config
from daran_proxy_stack.lib.shell import run
from daran_proxy_stack.modules import mtproxy as mt_mod
from daran_proxy_stack.modules import warp as warp_mod

router = APIRouter()

_START_TIME = time.time()


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
        return {
            "ok": True,
            "port": cfg.mtproxy.listen_port,
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
            "backend": d.recommended_backend,
            "socks_host": cfg.warp.socks_host,
            "socks_port": cfg.warp.socks_port,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _jobs_info() -> list[dict]:
    # Stub – no async job queue implemented yet.
    return [
        {
            "id": "mtproxy-fetch",
            "name": "MTProxy config fetch",
            "status": "idle",
            "last_run": None,
            "description": "Fetch proxy-secret and proxy-multi.conf from Telegram",
        },
        {
            "id": "warp-connect",
            "name": "WARP connection",
            "status": "idle",
            "last_run": None,
            "description": "Connect WARP and verify tunnel",
        },
        {
            "id": "cert-renew",
            "name": "Certificate renewal",
            "status": "planned",
            "last_run": None,
            "description": "Periodic cert renewal (not yet implemented)",
        },
    ]


# ── routes ─────────────────────────────────────────────────────────────────────

@router.get("/status")
async def status() -> JSONResponse:
    loop = asyncio.get_event_loop()
    mt, wp, srv = await asyncio.gather(
        loop.run_in_executor(None, _mtproxy_info),
        loop.run_in_executor(None, _warp_info),
        loop.run_in_executor(None, _server_info),
    )
    return JSONResponse({
        "panel_uptime_s": round(time.time() - _START_TIME),
        "server": srv,
        "mtproxy": mt,
        "warp": wp,
        "jobs": _jobs_info(),
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


@router.get("/jobs")
async def jobs() -> JSONResponse:
    return JSONResponse(_jobs_info())
