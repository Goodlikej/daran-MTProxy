"""Cascade / relay observed-state detector.

Detects iptables DNAT/REDIRECT rules and 3proxy service if present.

Per observed-state-model.md health rules:
  healthy:   persisted rules match observed rules and validation passes
  degraded:  rules exist but validation incomplete or partially broken
  broken:    state mismatch or forwarding not functioning
  stopped:   rule backend present but no active rules
  not_installed: no rule backend found
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from daran_proxy_stack.discovery.schema import (
    BaseModuleState,
    DiscoveryConfidence,
    ModuleHealth,
    ModuleManager,
    PortProtocol,
)
from daran_proxy_stack.lib.shell import run


# ---------------------------------------------------------------------------
# Rule model
# ---------------------------------------------------------------------------

@dataclass
class CascadeRule:
    id: str
    protocol: str          # "tcp" | "udp" | "both"
    listen_port: int
    target_host: str
    target_port: int
    status: str            # "active" | "inactive" | "unknown"
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "protocol": self.protocol,
            "listen_port": self.listen_port,
            "target_host": self.target_host,
            "target_port": self.target_port,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass
class CascadeDiagnosticsInfo:
    active_rule_count: int
    last_validation_at: str

    def to_dict(self) -> dict:
        return {
            "active_rule_count": self.active_rule_count,
            "last_validation_at": self.last_validation_at,
        }


@dataclass
class CascadeState(BaseModuleState):
    rule_backend: str = "none"   # "iptables" | "3proxy" | "none"
    rules: list[CascadeRule] = field(default_factory=list)
    diagnostics_info: CascadeDiagnosticsInfo | None = None

    def to_dict(self) -> dict:
        d = self._base_dict()
        d["rule_backend"] = self.rule_backend
        d["rules"] = [r.to_dict() for r in self.rules]
        d["diagnostics"] = self.diagnostics_info.to_dict() if self.diagnostics_info else None
        return d


# ---------------------------------------------------------------------------
# Persisted state helpers
# ---------------------------------------------------------------------------

_STATE_CANDIDATES = [
    Path("/opt/daran-proxy-stack/artifacts/cascade/state.json"),
    Path("/var/lib/daran-proxy-stack/generated/cascade/state.json"),
    Path("/etc/daran-proxy-stack/cascade/state.json"),
]

# Dev-mode: walk up from this file to find repo artifacts dir
_HERE = Path(__file__).resolve()
for _p in _HERE.parents:
    _c = _p / "artifacts" / "cascade" / "state.json"
    if _c.exists():
        _STATE_CANDIDATES.insert(0, _c)
        break


def _load_persisted_state() -> dict | None:
    for path in _STATE_CANDIDATES:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return None


# ---------------------------------------------------------------------------
# iptables rule discovery
# ---------------------------------------------------------------------------

def _parse_iptables_rules(iptables: str, table: str = "nat") -> list[dict]:
    """Parse DNAT rules from iptables -t nat -L PREROUTING -n -v --line-numbers."""
    result = run([iptables, "-t", table, "-L", "PREROUTING", "-n", "-v", "--line-numbers"])
    rules: list[dict] = []
    if not result.ok:
        return rules
    for line in result.stdout.splitlines():
        line = line.strip()
        # DNAT rules look like: "1  ... DNAT tcp  ...  dpt:443 to:10.0.0.2:8443"
        if "DNAT" not in line and "REDIRECT" not in line:
            continue
        try:
            protocol = "tcp" if " tcp " in line else "udp" if " udp " in line else "both"
            # dpt extraction
            dpt_part = ""
            to_part = ""
            for token in line.split():
                if token.startswith("dpt:"):
                    dpt_part = token.split(":")[1]
                if token.startswith("to:"):
                    to_part = token[3:]
            if not dpt_part:
                continue
            listen_port = int(dpt_part)
            target_host, target_port_str = "?", "0"
            if to_part and ":" in to_part:
                parts = to_part.rsplit(":", 1)
                target_host, target_port_str = parts[0], parts[1]
            rules.append({
                "protocol": protocol,
                "listen_port": listen_port,
                "target_host": target_host,
                "target_port": int(target_port_str) if target_port_str.isdigit() else 0,
                "source": "iptables",
            })
        except (ValueError, IndexError):
            continue
    return rules


# ---------------------------------------------------------------------------
# 3proxy process detection
# ---------------------------------------------------------------------------

def _detect_3proxy() -> tuple[bool, bool]:
    """Return (installed, running)."""
    binary = shutil.which("3proxy")
    if not binary:
        # Check common install paths
        for p in ["/usr/bin/3proxy", "/usr/local/bin/3proxy"]:
            if Path(p).exists():
                binary = p
                break
    if not binary:
        return False, False
    # Check if running
    pgrep = run(["pgrep", "-x", "3proxy"])
    running = pgrep.ok and bool(pgrep.stdout.strip())
    return True, running


# ---------------------------------------------------------------------------
# Public detector
# ---------------------------------------------------------------------------

def detect_cascade() -> CascadeState:
    """Detect cascade relay state. Never raises."""
    now = datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []
    errors: list[str] = []
    confidence = DiscoveryConfidence.full
    confidence_reasons: list[str] = []

    iptables = shutil.which("iptables")
    proxy3_installed, proxy3_running = _detect_3proxy()

    rule_backend = "none"
    backend_available = False

    if iptables:
        rule_backend = "iptables"
        backend_available = True
    if proxy3_installed:
        rule_backend = "3proxy" if not iptables else "hybrid"
        backend_available = True

    if not backend_available:
        return CascadeState(
            installed=False,
            enabled=False,
            running=False,
            health=ModuleHealth.not_installed,
            version=None,
            manager=ModuleManager.none,
            rule_backend="none",
            last_checked_at=now,
            confidence=DiscoveryConfidence.full,
        )

    # ── Load persisted rules from state.json ──────────────────────────────
    persisted = _load_persisted_state()
    persisted_rules: list[CascadeRule] = []
    if persisted:
        # state.json from cascade.apply() has a single relay entry
        try:
            p_relay_port = persisted.get("relay_port")
            p_target_host = persisted.get("upstream_socks_host", "?")
            p_target_port = persisted.get("upstream_socks_port", 0)
            if p_relay_port:
                persisted_rules.append(CascadeRule(
                    id="rule-persisted-0",
                    protocol="tcp",
                    listen_port=p_relay_port,
                    target_host=p_target_host,
                    target_port=p_target_port,
                    status="unknown",
                    notes="from state.json",
                ))
        except Exception as exc:
            warnings.append(f"state.json parse error: {exc}")

    # ── Observe iptables rules ─────────────────────────────────────────────
    observed_rules: list[CascadeRule] = []
    if iptables:
        try:
            raw_rules = _parse_iptables_rules(iptables)
            for i, r in enumerate(raw_rules):
                observed_rules.append(CascadeRule(
                    id=f"rule-iptables-{i:03d}",
                    protocol=r["protocol"],
                    listen_port=r["listen_port"],
                    target_host=r["target_host"],
                    target_port=r["target_port"],
                    status="active",
                    notes="observed from iptables",
                ))
        except Exception as exc:
            warnings.append(f"iptables parse error: {exc}")
            confidence = DiscoveryConfidence.partial
            confidence_reasons.append("iptables parsing failed")

    # ── Merge: prefer observed, fill with persisted where no overlap ──────
    all_listen_ports = {r.listen_port for r in observed_rules}
    merged_rules = list(observed_rules)
    for pr in persisted_rules:
        if pr.listen_port not in all_listen_ports:
            pr.status = "unknown"  # persisted but not confirmed in iptables
            merged_rules.append(pr)
            if iptables:
                warnings.append(
                    f"persisted rule on port {pr.listen_port} not seen in iptables"
                )

    # ── Determine manager ──────────────────────────────────────────────────
    manager = ModuleManager.none
    if proxy3_installed and iptables:
        manager = ModuleManager.hybrid
    elif proxy3_installed:
        manager = ModuleManager.process
    elif iptables:
        # iptables rules are managed directly (no daemon needed)
        manager = ModuleManager.hybrid  # iptables + shell scripts

    # ── Health ────────────────────────────────────────────────────────────
    active_count = sum(1 for r in merged_rules if r.status == "active")
    running = proxy3_running or active_count > 0

    if not merged_rules:
        health = ModuleHealth.stopped
    elif active_count == len(merged_rules):
        health = ModuleHealth.healthy
    elif active_count > 0:
        health = ModuleHealth.degraded
        warnings.append("some rules are not confirmed active")
    else:
        health = ModuleHealth.broken
        errors.append("rules exist in persisted state but none are active")

    diag_info = CascadeDiagnosticsInfo(
        active_rule_count=active_count,
        last_validation_at=now,
    )

    return CascadeState(
        installed=True,
        enabled=bool(persisted_rules or observed_rules),
        running=running,
        health=health,
        version=None,
        manager=manager,
        rule_backend=rule_backend,
        rules=merged_rules,
        diagnostics_info=diag_info,
        warnings=warnings,
        errors=errors,
        confidence=confidence,
        confidence_reasons=confidence_reasons,
        last_checked_at=now,
    )
