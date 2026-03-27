from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI

from daran_proxy_stack.lib.config import load_config
from daran_proxy_stack.lib.models import (
    ArtifactInfo,
    NodeInfo,
    ServiceInfo,
    ServiceStatus,
    StackState,
    TaskInfo,
)

app = FastAPI(title="daran-proxy-stack API", version="0.1.0")


def _build_state() -> StackState:
    config = load_config()
    services: list[ServiceInfo] = []

    # --- WARP ---
    try:
        from daran_proxy_stack.modules import warp as warp_mod

        diag = warp_mod.collect_diagnostics(config.warp)
        if diag.socks_running:
            warp_status = ServiceStatus.running
        elif diag.connected:
            warp_status = ServiceStatus.stopped
        else:
            warp_status = ServiceStatus.unknown
        services.append(
            ServiceInfo(
                id="warp",
                name="WARP SOCKS Proxy",
                module="warp",
                status=warp_status,
                endpoint=(
                    f"socks5://{config.warp.socks_host}:{config.warp.socks_port}"
                    if diag.socks_running
                    else None
                ),
                meta={
                    "connected": diag.connected,
                    "backend": diag.recommended_backend,
                    "os": diag.os_release,
                },
            )
        )
    except Exception as exc:  # noqa: BLE001
        services.append(
            ServiceInfo(
                id="warp",
                name="WARP SOCKS Proxy",
                module="warp",
                status=ServiceStatus.error,
                meta={"error": str(exc)},
            )
        )

    # --- MTProxy ---
    try:
        from daran_proxy_stack.modules import mtproxy as mt_mod

        mt_diag = mt_mod.collect_diagnostics(config.mtproxy)
        container_up = "up" in mt_diag.container_status.lower()
        mt_status = ServiceStatus.running if container_up else ServiceStatus.stopped
        server_host = config.mtproxy.public_host or mt_diag.server_ip or "unknown"
        services.append(
            ServiceInfo(
                id="mtproxy",
                name="MTProxy",
                module="mtproxy",
                status=mt_status,
                endpoint=(
                    f"tg://proxy?server={server_host}&port={config.mtproxy.listen_port}"
                    if container_up
                    else None
                ),
                meta={
                    "port": config.mtproxy.listen_port,
                    "container_status": mt_diag.container_status,
                },
            )
        )
    except Exception as exc:  # noqa: BLE001
        services.append(
            ServiceInfo(
                id="mtproxy",
                name="MTProxy",
                module="mtproxy",
                status=ServiceStatus.error,
                meta={"error": str(exc)},
            )
        )

    # --- Cascade ---
    try:
        from daran_proxy_stack.modules import cascade as cascade_mod

        c_diag = cascade_mod.collect_diagnostics(config.cascade)
        services.append(
            ServiceInfo(
                id="cascade",
                name="Cascade Relay",
                module="cascade",
                status=ServiceStatus.unknown,
                meta={
                    "note": c_diag.note,
                    "relay_reachable": c_diag.relay_reachable,
                    "upstream_reachable": c_diag.upstream_reachable,
                },
            )
        )
    except Exception as exc:  # noqa: BLE001
        services.append(
            ServiceInfo(
                id="cascade",
                name="Cascade Relay",
                module="cascade",
                status=ServiceStatus.error,
                meta={"error": str(exc)},
            )
        )

    return StackState(services=services)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/overview")
def overview() -> dict:
    state = _build_state()
    return {
        "node_count": len(state.nodes),
        "service_count": len(state.services),
        "task_count": len(state.tasks),
        "artifact_count": len(state.artifacts),
        "services": [
            {"id": s.id, "name": s.name, "status": s.status, "endpoint": s.endpoint}
            for s in state.services
        ],
    }


@app.get("/nodes")
def nodes() -> list[NodeInfo]:
    state = _build_state()
    return state.nodes


@app.get("/tasks")
def tasks() -> list[TaskInfo]:
    state = _build_state()
    return state.tasks


@app.get("/services")
def services() -> list[ServiceInfo]:
    state = _build_state()
    return state.services


@app.get("/artifacts")
def artifacts() -> list[ArtifactInfo]:
    state = _build_state()
    return state.artifacts
