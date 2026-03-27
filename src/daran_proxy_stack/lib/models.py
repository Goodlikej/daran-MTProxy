from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared state enums
# ---------------------------------------------------------------------------

class NodeStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    error = "error"
    unknown = "unknown"


class ServiceStatus(str, Enum):
    running = "running"
    stopped = "stopped"
    error = "error"
    unknown = "unknown"


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


# ---------------------------------------------------------------------------
# Shared core models
# ---------------------------------------------------------------------------

class NodeInfo(BaseModel):
    id: str
    name: str
    host: str
    role: str  # e.g. "relay", "exit", "mtproxy"
    status: NodeStatus = NodeStatus.unknown
    meta: dict = Field(default_factory=dict)


class ServiceInfo(BaseModel):
    id: str
    name: str
    module: str  # "warp" | "mtproxy" | "cascade"
    status: ServiceStatus = ServiceStatus.unknown
    endpoint: str | None = None
    meta: dict = Field(default_factory=dict)


class TaskInfo(BaseModel):
    id: str
    name: str
    status: TaskStatus = TaskStatus.pending
    started_at: datetime | None = None
    finished_at: datetime | None = None
    output: str | None = None


class ArtifactInfo(BaseModel):
    id: str
    name: str
    path: str
    artifact_type: str  # "config" | "key" | "link" | "log"
    created_at: datetime | None = None


class StackState(BaseModel):
    nodes: list[NodeInfo] = Field(default_factory=list)
    services: list[ServiceInfo] = Field(default_factory=list)
    tasks: list[TaskInfo] = Field(default_factory=list)
    artifacts: list[ArtifactInfo] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# App-level config models
# ---------------------------------------------------------------------------

class AppPaths(BaseModel):
    config_dir: str = "/etc/daran-proxy-stack"
    state_dir: str = "/var/lib/daran-proxy-stack"
    log_dir: str = "/var/log/daran-proxy-stack"


class WarpConfig(BaseModel):
    socks_host: str = "127.0.0.1"
    socks_port: int = Field(default=40000, ge=1, le=65535)
    mode: str = "proxy"
    backend: str = "auto"
    state_dir: str = "/var/lib/daran-proxy-stack/warp"
    log_dir: str = "/var/log/daran-proxy-stack"


class MTProxyConfig(BaseModel):
    listen_host: str = "0.0.0.0"
    listen_port: int = Field(default=443, ge=1, le=65535)
    stats_port: int = Field(default=8888, ge=1, le=65535)
    public_host: str | None = None
    secret: str | None = None
    ad_tag: str | None = None
    run_user: str = "nobody"
    workers: int = Field(default=1, ge=1)
    container_name: str = "mtproxy"
    image: str = "telegrammessenger/proxy:latest"
    use_host_network: bool = True


class CascadeConfig(BaseModel):
    relay_host: str = "127.0.0.1"
    relay_port: int = Field(default=1080, ge=1, le=65535)
    upstream_socks_host: str = "127.0.0.1"
    upstream_socks_port: int = Field(default=40000, ge=1, le=65535)
    mode: str = "forward"  # "forward" | "chain"
    enabled: bool = False


class AppConfig(BaseModel):
    paths: AppPaths = Field(default_factory=AppPaths)
    warp: WarpConfig = Field(default_factory=WarpConfig)
    mtproxy: MTProxyConfig = Field(default_factory=MTProxyConfig)
    cascade: CascadeConfig = Field(default_factory=CascadeConfig)
