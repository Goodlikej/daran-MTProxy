"""Observed-state schema — core dataclasses aligned with docs/observed-state-model.md.

All values here represent what discovery *actually found*, not configured intent.

Three-layer separation (from spec):
    Desired state   — what user wants  (not stored here)
    Configured state — what is in configs/files (not stored here)
    Observed state  — what this module detects  ← this file
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Fixed dictionaries
# ---------------------------------------------------------------------------

class ModuleHealth(str, Enum):
    unknown = "unknown"
    healthy = "healthy"
    degraded = "degraded"
    broken = "broken"
    stopped = "stopped"
    not_installed = "not_installed"


class ModuleManager(str, Enum):
    systemd = "systemd"
    docker = "docker"
    process = "process"
    hybrid = "hybrid"
    none = "none"


class PortProtocol(str, Enum):
    tcp = "tcp"
    udp = "udp"
    both = "both"


class DiscoveryConfidence(str, Enum):
    full = "full"
    partial = "partial"
    none = "none"


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------

@dataclass
class PortEntry:
    bind: str
    port: int
    protocol: PortProtocol
    purpose: str

    def to_dict(self) -> dict:
        return {
            "bind": self.bind,
            "port": self.port,
            "protocol": self.protocol.value,
            "purpose": self.purpose,
        }


# ---------------------------------------------------------------------------
# Shared module state base
# ---------------------------------------------------------------------------

@dataclass
class BaseModuleState:
    """Common fields for every module, per observed-state-model.md spec."""
    installed: bool
    enabled: bool
    running: bool
    health: ModuleHealth
    version: str | None
    manager: ModuleManager
    config_paths: list[str] = field(default_factory=list)
    data_paths: list[str] = field(default_factory=list)
    ports: list[PortEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    confidence: DiscoveryConfidence = DiscoveryConfidence.full
    confidence_reasons: list[str] = field(default_factory=list)
    last_checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def _base_dict(self) -> dict:
        return {
            "installed": self.installed,
            "enabled": self.enabled,
            "running": self.running,
            "health": self.health.value,
            "version": self.version,
            "manager": self.manager.value,
            "config_paths": self.config_paths,
            "data_paths": self.data_paths,
            "ports": [p.to_dict() for p in self.ports],
            "warnings": self.warnings,
            "errors": self.errors,
            "confidence": self.confidence.value,
            "confidence_reasons": self.confidence_reasons,
            "last_checked_at": self.last_checked_at,
        }

    def to_dict(self) -> dict:  # override in subclasses
        return self._base_dict()


# ---------------------------------------------------------------------------
# Host state
# ---------------------------------------------------------------------------

@dataclass
class HostState:
    os: str
    version: str
    public_ip: str | None
    hostname: str
    bbr_enabled: bool | None = None

    def to_dict(self) -> dict:
        return {
            "os": self.os,
            "version": self.version,
            "public_ip": self.public_ip,
            "hostname": self.hostname,
            "bbr_enabled": self.bbr_enabled,
        }


# ---------------------------------------------------------------------------
# Discovery metadata
# ---------------------------------------------------------------------------

@dataclass
class DiscoveryMeta:
    last_run_at: str
    status: str  # "ok" | "partial" | "failed"
    warnings: list[str] = field(default_factory=list)
    partial_modules: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "last_run_at": self.last_run_at,
            "status": self.status,
            "warnings": self.warnings,
            "partial_modules": self.partial_modules,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Top-level observed state snapshot
# ---------------------------------------------------------------------------

@dataclass
class ObservedState:
    """Full observed-state snapshot. schema_version tracks breaking changes."""
    schema_version: str
    host: HostState
    discovery: DiscoveryMeta
    # Module slots — None means detector did not run / fatal error
    warp: Any | None = None      # WarpState
    mtproxy: Any | None = None   # MTProxyState
    cascade: Any | None = None   # CascadeState
    xui: Any | None = None       # XuiState  (3x-ui web panel)

    def to_dict(self) -> dict:
        modules: dict = {}
        for key in ("warp", "mtproxy", "cascade", "xui"):
            val = getattr(self, key)
            modules[key] = val.to_dict() if val is not None else None
        return {
            "schema_version": self.schema_version,
            "host": self.host.to_dict(),
            "discovery": self.discovery.to_dict(),
            "modules": modules,
        }
