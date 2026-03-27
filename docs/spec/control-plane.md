# Control Plane & Agent Pull Model

## Overview

The stack uses a **pull model**: agents on nodes periodically fetch desired state from a controller and reconcile locally. The controller never pushes; it only serves state.

```
Controller (desired state)
    │  serves: GET /state/{node_id}.json
    │
    ▼  (agent polls on interval, default 60s)
Agent on Node
    │
    ├─ read desired_state
    ├─ read local_state  (state.json files)
    ├─ diff
    └─ apply changes via module functions
         └─ write new state.json
         └─ POST /state/{node_id}/report  (optional)
```

---

## Desired State Format

The controller serves a single JSON document per node:

```json
{
  "node_id": "vps-01",
  "modules": {
    "warp": {
      "target_status": "running",
      "config": {
        "socks_host": "127.0.0.1",
        "socks_port": 40000,
        "backend": "warp-cli"
      }
    },
    "mtproxy": {
      "target_status": "absent"
    }
  }
}
```

`target_status` mirrors the domain model states: `absent | installed | running | stopped`.

---

## Agent Pull Loop

```python
def pull_loop(controller_url: str, node_id: str, interval: int = 60):
    while True:
        desired = fetch_desired_state(controller_url, node_id)
        for module_name, spec in desired["modules"].items():
            reconcile(module_name, spec)
        sleep(interval)

def reconcile(module_name: str, spec: dict):
    current = get_status(module_name)       # reads state.json
    target  = spec["target_status"]
    if current == target:
        return
    config = build_config(module_name, spec.get("config", {}))
    apply_transition(module_name, config, current, target)
```

Transition table (current → target → action):

| current    | target    | action              |
|------------|-----------|---------------------|
| absent     | installed | install()           |
| absent     | running   | install() → start() |
| installed  | running   | start()             |
| running    | stopped   | stop()              |
| running    | absent    | stop() → uninstall()|
| stopped    | running   | start()             |
| stopped    | absent    | uninstall()         |
| error      | *any*     | install() (retry)   |

---

## Controller Implementation (Phase 3)

Minimal controller: a static file server or tiny HTTP API that serves per-node JSON files.

```
controller/
  state/
    vps-01.json
    vps-02.json
```

No database required for MVP. Files can be version-controlled. Future: replace with HTTP API backed by SQLite.

---

## Agent CLI Entry Point

```bash
daran-net agent start --controller http://control.example.com --node-id vps-01 --interval 60
daran-net agent status
daran-net agent stop
```

Agent runs as a systemd service. Unit file generated via `daran-net agent install-service`.

---

## Local-First Operation (Phase 1 & 2)

No controller, no agent. The CLI is the control plane.

```bash
daran-net warp install
daran-net warp start
daran-net mtproxy official-install
```

State is still written to `state.json` so that Phase 3 migration is seamless: the agent's first reconcile will see existing state and skip redundant transitions.
