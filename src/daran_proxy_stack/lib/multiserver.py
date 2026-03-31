"""Multi-server registry and SSH execution for daran-proxy-stack.

Allows managing multiple VPS nodes from a single interface.

State stored in artifacts/generated/servers.json:
  [{"id": "fi-01", "label": "Finland VPS", "host": "1.2.3.4",
    "port": 22, "user": "root", "description": "Exit node", "tags": ["exit"]}]

Usage:
    from daran_proxy_stack.lib.multiserver import ServerRegistry
    reg = ServerRegistry(config_dir)
    servers = reg.list_servers()
    ok, latency = reg.ping_server(servers[0])
    result = reg.ssh_run(servers[0], "systemctl status MTProxy")
"""
from __future__ import annotations

import json
import secrets
import socket
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from daran_proxy_stack.lib.shell import run

_SERVERS_FILE = "servers.json"


@dataclass
class ServerEntry:
    id: str
    label: str
    host: str
    port: int = 22
    user: str = "root"
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ServerEntry":
        return cls(
            id=d["id"],
            label=d.get("label", d["id"]),
            host=d["host"],
            port=int(d.get("port", 22)),
            user=d.get("user", "root"),
            description=d.get("description", ""),
            tags=d.get("tags", []),
        )


class ServerRegistry:
    """Persistent registry of remote server entries."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = Path(config_dir)

    def _path(self) -> Path:
        return self.config_dir / _SERVERS_FILE

    def list_servers(self) -> list[ServerEntry]:
        path = self._path()
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return [ServerEntry.from_dict(d) for d in raw]
        except Exception:
            return []

    def get_server(self, server_id: str) -> ServerEntry | None:
        for s in self.list_servers():
            if s.id == server_id:
                return s
        return None

    def add_server(self, entry: ServerEntry) -> None:
        servers = self.list_servers()
        # Replace if same id
        servers = [s for s in servers if s.id != entry.id]
        servers.append(entry)
        self._save(servers)

    def remove_server(self, server_id: str) -> bool:
        servers = self.list_servers()
        before = len(servers)
        servers = [s for s in servers if s.id != server_id]
        if len(servers) == before:
            return False
        self._save(servers)
        return True

    def _save(self, servers: list[ServerEntry]) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._path().write_text(
            json.dumps([s.to_dict() for s in servers], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Connectivity ──────────────────────────────────────────────────────────

    def ping_server(self, entry: ServerEntry, timeout: float = 3.0) -> tuple[bool, float | None]:
        """TCP-ping the server's SSH port. Returns (reachable, latency_ms)."""
        t0 = time.monotonic()
        try:
            with socket.create_connection((entry.host, entry.port), timeout=timeout):
                latency = (time.monotonic() - t0) * 1000
                return True, round(latency, 1)
        except (OSError, socket.timeout):
            return False, None

    def ping_all(self) -> list[dict]:
        """Ping all registered servers. Returns list of status dicts."""
        results = []
        for s in self.list_servers():
            ok, latency = self.ping_server(s)
            results.append({
                "id": s.id,
                "label": s.label,
                "host": s.host,
                "port": s.port,
                "reachable": ok,
                "latency_ms": latency,
            })
        return results

    # ── SSH execution ─────────────────────────────────────────────────────────

    def ssh_run(
        self,
        entry: ServerEntry,
        command: str,
        timeout: int = 30,
        identity_file: str | None = None,
    ) -> "CommandResult":
        """Run a command on a remote server via SSH.

        Requires SSH key auth (no password prompts in non-interactive mode).
        """
        from daran_proxy_stack.lib.shell import CommandResult
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"ConnectTimeout={timeout}",
            "-o", "BatchMode=yes",
            "-p", str(entry.port),
        ]
        if identity_file:
            cmd += ["-i", identity_file]
        cmd += [f"{entry.user}@{entry.host}", command]
        return run(cmd)

    def collect_remote_status(self, entry: ServerEntry) -> dict:
        """Run quick diagnostics on a remote server via SSH."""
        results: dict = {"host": entry.host, "user": entry.user}

        # Reachability
        reachable, latency = self.ping_server(entry)
        results["reachable"] = reachable
        results["latency_ms"] = latency

        if not reachable:
            results["error"] = "SSH port не доступен"
            return results

        # Uptime + OS
        r = self.ssh_run(entry, "uname -r && uptime -p && cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'")
        if r.ok:
            lines = r.stdout.splitlines()
            results["kernel"] = lines[0] if len(lines) > 0 else None
            results["uptime"] = lines[1] if len(lines) > 1 else None
            results["os"] = lines[2] if len(lines) > 2 else None

        # Service statuses
        services_r = self.ssh_run(
            entry,
            "for svc in MTProxy awg-quick@wg0 x-ui; do "
            "  status=$(systemctl is-active $svc 2>/dev/null || echo 'not-found'); "
            "  echo \"$svc:$status\"; "
            "done"
        )
        if services_r.ok:
            svc_map = {}
            for line in services_r.stdout.splitlines():
                if ":" in line:
                    name, status = line.split(":", 1)
                    svc_map[name.strip()] = status.strip()
            results["services"] = svc_map

        # Load avg
        load_r = self.ssh_run(entry, "cat /proc/loadavg | awk '{print $1,$2,$3}'")
        if load_r.ok:
            results["load_avg"] = load_r.stdout.strip()

        # Disk
        disk_r = self.ssh_run(entry, "df -h / | awk 'NR==2{print $3\"/\"$2\" (\"$5\")\"}'")
        if disk_r.ok:
            results["disk"] = disk_r.stdout.strip()

        return results


# ---------------------------------------------------------------------------
# Config dir helpers
# ---------------------------------------------------------------------------

def _default_config_dir() -> Path:
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "artifacts").exists():
            return p / "artifacts" / "generated"
    return Path("/opt/daran-proxy-stack/artifacts/generated")


def default_registry() -> ServerRegistry:
    return ServerRegistry(_default_config_dir())


def make_server_id(label: str) -> str:
    """Generate a slug-style ID from a label."""
    slug = "".join(c if c.isalnum() else "-" for c in label.lower()).strip("-")
    return slug or secrets.token_hex(4)
