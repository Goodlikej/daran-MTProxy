# First-Run Discovery & Truthful State

## Problem

`state.json` is written only on lifecycle transitions. After a reboot, manual
intervention, or fresh install of a pre-existing service, the persisted state
no longer matches reality. The panel must never display stale state as truth.

---

## Definitions

**Persisted state** — contents of `{state_dir}/{module}/state.json`. Records
what the stack *last* did. May be absent or stale.

**Live state** — result of probing the system right now: binary presence,
process running, version string. Always fresh, never cached across requests.

**Truthful state** — the reconciled view: live state wins for the `running`
field; persisted state supplies `installed_at` and `error` history.

---

## First-Run Discovery

First run = state.json does not exist for a module **and** the panel/CLI is
starting up. In this case the module must not assume `absent` — it must probe.

### Discovery Algorithm (`discover(config) -> ModuleState`)

```
1. Run collect_diagnostics(config)  — no side effects
2. Determine presence:
     present = any of: binary exists, systemd unit active, process found
3. If present:
     Determine running:
       running = process/unit is in active/running state
     status = "running" if running else "installed"
4. If not present:
     status = "absent"
5. Write state.json with detected status + "discovered_at" timestamp
6. Return ModuleState
```

Call `discover()` in these conditions only:
- `state.json` is missing
- CLI flag `--rediscover` is passed
- `POST /api/v1/discover` is called

Do **not** auto-discover on every request — it is a probe, not a poll.

---

## InventoryReport

New entity. Returned by `GET /api/v1/inventory`. One entry per known module
name (even if absent). Never persisted — collected at call time.

```python
@dataclass
class ModuleInventory:
    name:         str           # canonical module id (see Module Registry below)
    present:      bool          # binary or systemd unit found
    running:      bool          # process/unit actively running
    version:      str | None    # parsed version string, None if not detectable
    runtime:      str | None    # e.g. "systemd", "docker", "process", None
    binary_path:  str | None    # absolute path from shutil.which, None if absent
    config_path:  str | None    # detected config file path, None if absent

@dataclass
class InventoryReport:
    collected_at: str           # ISO-8601 UTC
    node_id:      str           # hostname
    modules:      list[ModuleInventory]
```

The panel `/overview` page renders this table. Each row links to the module's
detail page. Missing modules show "not installed" — not an error state.

---

## Module Registry

Canonical names and detection targets:

| name           | binary(ies)                    | systemd unit           | version cmd                         | version regex                     |
|----------------|-------------------------------|------------------------|-------------------------------------|-----------------------------------|
| `mtproxy`      | `/opt/MTProxy/mtproto-proxy`  | `MTProxy.service`      | `./mtproto-proxy --version`         | `MTProto proxy version (\S+)`     |
| `warp`         | `warp-cli`, `cloudflared`     | `warp-svc.service`     | `warp-cli --version`                | `(\d+\.\d+\.\d+[\.\d]*)`         |
| `xray`         | `xray`                        | `xray.service`         | `xray --version`                    | `Xray (\S+) \(`                   |
| `xray-pro`     | `xray` (build tag `pro`)      | `xray-pro.service`     | `xray --version`                    | `Xray-Pro (\S+) \(`               |
| `amneziawg`    | `awg`, `awg-quick`            | `awg-quick@*.service`  | `awg --version`                     | `wireguard-tools v(\S+)`          |

**AmneziaWG version distinction** (1.0 vs 2.0):
- 1.0: `awg` binary present, version string contains `amn1` or version < 2.0.0
- 2.0: version string contains `amn2` or version >= 2.0.0; kernel module
  `amnezia_wg` loaded (`lsmod | grep amnezia_wg`)

Both share the same `amneziawg` module name. The `version` field is the
source of truth — implementers must not infer generation from binary path alone.

**Xray vs Xray Pro distinction**:
- Run `xray --version`; if output contains `Xray-Pro`, module name is `xray-pro`
- If it contains `Xray` without `Pro`, module name is `xray`
- If both unit files exist, report both entries with distinct `name` values

---

## Version Detection Rules

### General Rules

1. Run the version command with a 3-second timeout.
2. Check both `stdout` and `stderr` — some binaries write version to stderr.
3. Apply the regex from the Module Registry; take group 1 as `version`.
4. On any failure (missing binary, timeout, no regex match): set `version = None`.
5. Never raise an exception — detection is best-effort.

### MTProxy Special Case

Official build does not support `--version`. Instead:
- Check for git metadata: `git -C /opt/MTProxy rev-parse --short HEAD`
- Store as `version = "git:<hash>"` (e.g. `"git:a3b2c1d"`)
- If no git dir: set `version = None`

### WARP Special Case

Two binaries may coexist. Prefer `warp-cli` version; record `cloudflared`
version separately in `binary_path` comment field (not a separate inventory
entry — WARP is one logical module regardless of backend).

---

## collect_diagnostics() Extension

Extend the return type of `collect_diagnostics()` in each module to include:

```python
@dataclass
class DiagnosticsReport:
    # ... existing fields ...
    version:      str | None   # NEW — parsed version string
    runtime:      str | None   # NEW — "systemd" | "docker" | "process" | None
    config_path:  str | None   # NEW — detected config file path
```

No module is required to compute all three fields — use `None` for
fields that are not applicable or not detectable.

---

## API Exposure

### New Endpoints

```
GET  /api/v1/inventory
     Returns: InventoryReport (JSON)
     Behavior: calls collect_diagnostics() for all known modules; no state writes

POST /api/v1/discover
     Returns: InventoryReport (JSON)
     Behavior: runs discovery algorithm for all modules; writes state.json
               where state is missing or --force param is passed
     Query param: ?force=true — re-discover all, overwrite existing state.json
```

### Modified Endpoint

```
GET  /api/v1/status
     MUST include: top-level "inventory" key with InventoryReport
     (currently returns mtproxy/warp dicts inline; keep those for compatibility)
```

### Response Shape for GET /api/v1/inventory

```json
{
  "collected_at": "2026-03-27T12:00:00Z",
  "node_id": "vps-01",
  "modules": [
    {
      "name": "mtproxy",
      "present": true,
      "running": true,
      "version": "git:a3b2c1d",
      "runtime": "systemd",
      "binary_path": "/opt/MTProxy/mtproto-proxy",
      "config_path": null
    },
    {
      "name": "warp",
      "present": true,
      "running": false,
      "version": "2024.3.444.0",
      "runtime": "systemd",
      "binary_path": "/usr/bin/warp-cli",
      "config_path": null
    },
    {
      "name": "xray",
      "present": false,
      "running": false,
      "version": null,
      "runtime": null,
      "binary_path": null,
      "config_path": null
    },
    {
      "name": "xray-pro",
      "present": false,
      "running": false,
      "version": null,
      "runtime": null,
      "binary_path": null,
      "config_path": null
    },
    {
      "name": "amneziawg",
      "present": false,
      "running": false,
      "version": null,
      "runtime": null,
      "binary_path": null,
      "config_path": null
    }
  ]
}
```

---

## Panel /overview Changes

The overview page must render a **Stack Inventory** table above the existing
module cards. Columns: Name | Present | Running | Version | Runtime.

Rows for absent modules are shown with muted styling — not errors.
A "Re-discover" button triggers `POST /api/v1/discover` and reloads the page.

---

## Invariants

- `collect_diagnostics()` never writes state. `discover()` does write state.
- Inventory is always collected fresh — never served from cache.
- A module absent from `config.yaml` still appears in InventoryReport if its
  binary is found on PATH. Config is for operation; inventory is for truth.
- Version strings are raw parsed strings — no normalization, no semver
  comparison at this layer.
