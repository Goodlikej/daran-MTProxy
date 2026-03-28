"""Discovery backend package.

Provides the truthful observed-state backend for all stack modules.

Public surface:
    ObservedState      — top-level snapshot dataclass
    run_discovery()    — run all module detectors, return ObservedState
    discovery_dict()   — JSON-serialisable dict of the full snapshot
"""
from daran_proxy_stack.discovery.schema import (
    DiscoveryMeta,
    HostState,
    ModuleHealth,
    ModuleManager,
    ObservedState,
    PortEntry,
    PortProtocol,
)
from daran_proxy_stack.discovery.host import discover_host
from daran_proxy_stack.discovery.modules.warp import detect_warp, WarpState
from daran_proxy_stack.discovery.modules.mtproxy import detect_mtproxy, MTProxyState
from daran_proxy_stack.discovery.modules.cascade import detect_cascade, CascadeState
from daran_proxy_stack.discovery.runner import run_discovery, discovery_dict

__all__ = [
    # schema
    "ObservedState",
    "HostState",
    "DiscoveryMeta",
    "ModuleHealth",
    "ModuleManager",
    "PortProtocol",
    "PortEntry",
    # module states
    "WarpState",
    "MTProxyState",
    "CascadeState",
    # functions
    "discover_host",
    "detect_warp",
    "detect_mtproxy",
    "detect_cascade",
    "run_discovery",
    "discovery_dict",
]
