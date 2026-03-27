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
  name:       str          # warp | mtproxy | relay
  config:     ModuleConfig # typed Pydantic model
  state:      ModuleState  # persisted to state_dir/{module}/state.json
  artifacts:  list[Path]   # generated files in artifacts/generated/{module}/
```

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
