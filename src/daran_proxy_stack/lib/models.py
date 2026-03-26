from pydantic import BaseModel, Field


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


class AppConfig(BaseModel):
    paths: AppPaths = Field(default_factory=AppPaths)
    warp: WarpConfig = Field(default_factory=WarpConfig)
    mtproxy: MTProxyConfig = Field(default_factory=MTProxyConfig)
