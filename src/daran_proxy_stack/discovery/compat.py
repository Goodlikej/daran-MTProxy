"""Compatibility adapter: converts ObservedState → legacy ServiceInventory schema.

Allows /api/v1/inventory to source data from the new discovery backend
while preserving the existing UI contract:

    {
        "services": [
            {
                "name": str,
                "label": str,
                "detected": bool,
                "version": str | None,
                "runtime_status": "running" | "stopped" | "not_installed" | "unknown",
                "config_path": str | None,
                "endpoint": str | None,
                "meta": dict,
            },
            ...
        ],
        "timestamp": str,
        "count": int,
        "detected_count": int,
        "running_count": int,
    }

Health → runtime_status mapping:
    healthy   → running
    degraded  → running   (service is up, but impaired)
    broken    → unknown
    stopped   → stopped
    not_installed → not_installed
    unknown   → unknown
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Health → runtime_status mapping
# ---------------------------------------------------------------------------

_HEALTH_TO_STATUS: dict[str, str] = {
    "healthy":       "running",
    "degraded":      "running",
    "broken":        "unknown",
    "stopped":       "stopped",
    "not_installed": "not_installed",
    "unknown":       "unknown",
}

_MODULE_LABELS: dict[str, str] = {
    "warp":     "Cloudflare WARP",
    "mtproxy":  "MTProxy (Telegram)",
    "cascade":  "Cascade Relay",
}


def _module_to_service(name: str, state: Any) -> dict:
    """Convert a single BaseModuleState subclass instance to a ServiceInventory dict."""
    if state is None:
        return {
            "name": name,
            "label": _MODULE_LABELS.get(name, name.title()),
            "detected": False,
            "version": None,
            "runtime_status": "unknown",
            "config_path": None,
            "endpoint": None,
            "meta": {"error": "detector returned no data"},
        }

    d = state.to_dict()
    health = d.get("health", "unknown")
    runtime_status = _HEALTH_TO_STATUS.get(health, "unknown")
    detected = d.get("installed", False)

    # config_path: first entry from config_paths list
    config_path: str | None = None
    config_paths = d.get("config_paths", [])
    if config_paths:
        config_path = config_paths[0]

    # endpoint: first port entry as "bind:port"
    endpoint: str | None = None
    ports = d.get("ports", [])
    if ports:
        p = ports[0]
        endpoint = f"{p.get('bind', '0.0.0.0')}:{p['port']}"

    # meta: collect useful module-specific fields for the notes column
    meta: dict = {}
    warnings = d.get("warnings", [])
    errors = d.get("errors", [])
    if warnings:
        meta["warnings"] = warnings
    if errors:
        meta["error"] = "; ".join(errors)

    confidence = d.get("confidence", "unknown")
    if confidence != "full":
        meta["confidence"] = confidence
        reasons = d.get("confidence_reasons", [])
        if reasons:
            meta["confidence_reasons"] = reasons

    # Module-specific extras for the notes column
    if name == "warp":
        reg = d.get("registration")
        if reg:
            meta["registered"] = reg.get("registered")
        net = d.get("network")
        if net:
            if net.get("warp_ip"):
                meta["warp_ip"] = net["warp_ip"]
        backend = d.get("backend")
        if backend and backend != "unknown":
            meta["backend"] = backend

    elif name == "mtproxy":
        rt = d.get("runtime")
        if rt:
            meta["container"] = rt.get("container_name")
            meta["docker_status"] = rt.get("container_status")
        pub = d.get("public_endpoint")
        if pub:
            tg_link = pub.get("tg_link")
            if tg_link:
                meta["tg_link"] = tg_link

    elif name == "cascade":
        meta["rule_backend"] = d.get("rule_backend", "none")
        rules = d.get("rules", [])
        if rules:
            meta["rules_count"] = len(rules)

    return {
        "name": name,
        "label": _MODULE_LABELS.get(name, name.title()),
        "detected": detected,
        "version": d.get("version"),
        "runtime_status": runtime_status,
        "config_path": config_path,
        "endpoint": endpoint,
        "meta": meta,
    }


def observed_state_to_inventory_dict(observed_state: Any) -> dict:
    """Convert ObservedState to the legacy inventory dict schema.

    Preserves full UI compatibility with inventory.html.
    """
    from datetime import datetime, timezone

    services = []
    # Ordered by importance for UI display
    for module_name in ("warp", "mtproxy", "cascade"):
        module_state = getattr(observed_state, module_name, None)
        services.append(_module_to_service(module_name, module_state))

    detected_count = sum(1 for s in services if s["detected"])
    running_count = sum(1 for s in services if s["runtime_status"] == "running")

    return {
        "services": services,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "count": len(services),
        "detected_count": detected_count,
        "running_count": running_count,
        # Signal to consumers that this data came from the new backend
        "_backend": "discovery/v1",
    }


def inventory_dict_from_discovery() -> dict:
    """Run the new discovery backend and return a legacy-compatible inventory dict."""
    from daran_proxy_stack.discovery.runner import run_discovery
    observed = run_discovery()
    return observed_state_to_inventory_dict(observed)
