# Domain Model

## Core Entities

### Node
Represents a single VPS/server where the stack runs.

```
Node
  id:       str          # hostname or UUID
  ip:       str          # primary public IP
  role:     NodeRole     # standalone | agent | controller
  modules:  list[Module]
```

`standalone` — default for Phase 1/2. No controller dependency.
`agent` — Phase 3: polls controller for desired state.
`controller` — Phase 3: serves desired state to agents.

---

### Module
A functional unit that manages one network service on a Node.

```
Module
  name:       str          # warp | mtproxy | cascade | xray | xray-pro | amneziawg
  config:     ModuleConfig # typed Pydantic model
  state:      ModuleState  # persisted to state_dir/{module}/state.json
  artifacts:  list[Path]   # generated files in artifacts/generated/{module}/
```

Implemented modules: `warp`, `mtproxy`, `cascade`.
Registered but not yet implemented: `xray`, `xray-pro`, `amneziawg`.
All five must appear in InventoryReport regardless of implementation status —
see `docs/spec/discovery.md`.

---

### ModuleConfig
Pydantic model, loaded from `/etc/daran-proxy-stack/config.yaml` and validated at startup. Each module has its own typed subclass (`WarpConfig`, `MTProxyConfig`, future `RelayConfig`).

Invariant: config is **read-only** during a command run. Mutations require a new config write + reload.

---

### ModuleState
Persisted JSON at `{state_dir}/{module}/state.json`. Tracks what is actually installed/running on the node.

```json
{
  "status": "running",         // absent | installed | configured | running | stopped | error
  "installed_at": "ISO-8601",
  "last_checked": "ISO-8601",
  "error": null | "message"
}
```

---

### Artifact
A generated file (bash script, systemd unit, xray JSON, tg-link, QR). Written once to `artifacts/generated/{module}/`. Safe to regenerate; idempotent.

---

### DiagnosticsReport
Read-only snapshot of system state (binary paths, port availability, process status). Never persisted — collected fresh each command run.

Required additional fields (added to all module diagnostics structs):
```
version:      str | None   # parsed version string; None if not detectable
runtime:      str | None   # "systemd" | "docker" | "process" | None
config_path:  str | None   # detected config file path; None if not applicable
```

---

### ModuleInventory
Lightweight cross-module view for the stack inventory table. Derived from
`DiagnosticsReport` — never persisted. See `docs/spec/discovery.md` for the
full field list and discovery algorithm.

---

### InventoryReport
Collection of `ModuleInventory` for all known modules (present and absent).
Returned by `GET /api/v1/inventory`. Always collected live.

---

### ActionResult
Standard return type for all module operations.

```python
@dataclass
class ActionResult:
    ok:    bool
    title: str
    body:  str
```

---

## Module State Machine

```
ABSENT
  → (install)     → INSTALLED
INSTALLED
  → (configure)   → CONFIGURED
  → (uninstall)   → ABSENT
CONFIGURED
  → (start)       → RUNNING
  → (uninstall)   → ABSENT
RUNNING
  → (stop)        → STOPPED
  → (error)       → ERROR
STOPPED
  → (start)       → RUNNING
  → (uninstall)   → ABSENT
ERROR
  → (install/fix) → INSTALLED
  → (uninstall)   → ABSENT
```

Transitions are driven by CLI commands or the agent pull loop. Each transition writes the new status to `state.json`.
