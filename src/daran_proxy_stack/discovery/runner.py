"""Discovery runner — assembles ObservedState from all module detectors.

Usage:
    from daran_proxy_stack.discovery import run_discovery, discovery_dict

    state = run_discovery()         # ObservedState dataclass
    data  = discovery_dict()        # JSON-serialisable dict
    data  = discovery_dict(state)   # reuse existing state
"""
from __future__ import annotations

from datetime import datetime, timezone

from daran_proxy_stack.discovery.host import discover_host
from daran_proxy_stack.discovery.modules.cascade import detect_cascade
from daran_proxy_stack.discovery.modules.mtproxy import detect_mtproxy
from daran_proxy_stack.discovery.modules.warp import detect_warp
from daran_proxy_stack.discovery.modules.xui import detect_xui
from daran_proxy_stack.discovery.schema import (
    DiscoveryConfidence,
    DiscoveryMeta,
    ObservedState,
)

SCHEMA_VERSION = "1.0"


def run_discovery() -> ObservedState:
    """Run all detectors, assemble and return ObservedState.

    Never raises. Each detector is called in try/except; failures produce
    partial confidence entries, not missing slots.
    """
    now = datetime.now(timezone.utc).isoformat()
    global_warnings: list[str] = []
    partial_modules: list[str] = []

    # ── Host ──────────────────────────────────────────────────────────────
    try:
        host = discover_host()
    except Exception as exc:
        from daran_proxy_stack.discovery.schema import HostState
        host = HostState(os="unknown", version="", public_ip=None, hostname="unknown")
        global_warnings.append(f"host discovery failed: {exc}")

    # ── WARP ──────────────────────────────────────────────────────────────
    try:
        warp_state = detect_warp()
        if warp_state.confidence == DiscoveryConfidence.partial:
            partial_modules.append("warp")
    except Exception as exc:
        from daran_proxy_stack.discovery.modules.warp import WarpState
        from daran_proxy_stack.discovery.schema import ModuleHealth, ModuleManager
        warp_state = WarpState(
            installed=False, enabled=False, running=False,
            health=ModuleHealth.unknown, version=None, manager=ModuleManager.none,
            errors=[f"detector crashed: {exc}"],
            confidence=DiscoveryConfidence.none,
            last_checked_at=now,
        )
        partial_modules.append("warp")
        global_warnings.append(f"warp detector exception: {exc}")

    # ── MTProxy ───────────────────────────────────────────────────────────
    try:
        mtproxy_state = detect_mtproxy()
        if mtproxy_state.confidence == DiscoveryConfidence.partial:
            partial_modules.append("mtproxy")
    except Exception as exc:
        from daran_proxy_stack.discovery.modules.mtproxy import MTProxyState
        from daran_proxy_stack.discovery.schema import ModuleHealth, ModuleManager
        mtproxy_state = MTProxyState(
            installed=False, enabled=False, running=False,
            health=ModuleHealth.unknown, version=None, manager=ModuleManager.none,
            errors=[f"detector crashed: {exc}"],
            confidence=DiscoveryConfidence.none,
            last_checked_at=now,
        )
        partial_modules.append("mtproxy")
        global_warnings.append(f"mtproxy detector exception: {exc}")

    # ── Cascade ───────────────────────────────────────────────────────────
    try:
        cascade_state = detect_cascade()
        if cascade_state.confidence == DiscoveryConfidence.partial:
            partial_modules.append("cascade")
    except Exception as exc:
        from daran_proxy_stack.discovery.modules.cascade import CascadeState
        from daran_proxy_stack.discovery.schema import ModuleHealth, ModuleManager
        cascade_state = CascadeState(
            installed=False, enabled=False, running=False,
            health=ModuleHealth.unknown, version=None, manager=ModuleManager.none,
            errors=[f"detector crashed: {exc}"],
            confidence=DiscoveryConfidence.none,
            last_checked_at=now,
        )
        partial_modules.append("cascade")
        global_warnings.append(f"cascade detector exception: {exc}")

    # ── 3x-ui ─────────────────────────────────────────────────────────────
    try:
        xui_state = detect_xui()
        if xui_state.confidence == DiscoveryConfidence.partial:
            partial_modules.append("xui")
    except Exception as exc:
        from daran_proxy_stack.discovery.modules.xui import XuiState
        from daran_proxy_stack.discovery.schema import ModuleHealth, ModuleManager
        xui_state = XuiState(
            installed=False, enabled=False, running=False,
            health=ModuleHealth.unknown, version=None, manager=ModuleManager.none,
            errors=[f"detector crashed: {exc}"],
            confidence=DiscoveryConfidence.none,
            last_checked_at=now,
        )
        partial_modules.append("xui")
        global_warnings.append(f"xui detector exception: {exc}")

    # ── Discovery meta ────────────────────────────────────────────────────
    meta_status = "ok" if not partial_modules else "partial"
    meta = DiscoveryMeta(
        last_run_at=now,
        status=meta_status,
        warnings=global_warnings,
        partial_modules=partial_modules,
    )

    return ObservedState(
        schema_version=SCHEMA_VERSION,
        host=host,
        discovery=meta,
        warp=warp_state,
        mtproxy=mtproxy_state,
        cascade=cascade_state,
        xui=xui_state,
    )


def discovery_dict(state: ObservedState | None = None) -> dict:
    """Return JSON-serialisable observed-state dict."""
    if state is None:
        state = run_discovery()
    return state.to_dict()
