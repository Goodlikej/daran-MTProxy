# Rollout: Local-First to Multi-Node

## Phase 1 — Local MVP (current)

**Goal:** single VPS, CLI-driven, no networking between nodes.

Deliverables:
- [x] `daran-net warp {install,start,stop,status,xray-json}`
- [x] `daran-net mtproxy {official-install,status,tg-link,qr}`
- [x] `daran-net cascade {apply,status}`
- [ ] `state.json` writes after every lifecycle command
- [ ] First-run discovery: `discover()` per module, `POST /api/v1/discover` endpoint
      (spec: `docs/spec/discovery.md`)
- [ ] `GET /api/v1/inventory` — truthful stack inventory with version detection
      for mtproxy, warp, xray, xray-pro, amneziawg
- [ ] `DiagnosticsReport` extended with `version`, `runtime`, `config_path` fields
- [ ] Overview panel renders Stack Inventory table with Re-discover button

Done when: a single operator can deploy WARP + MTProxy on one VPS end-to-end
with no manual shell steps, and the panel shows truthful state on first load.

---

## Phase 2 — SSH Remote (no agent)

**Goal:** manage multiple nodes from one workstation via SSH, no daemon on remote nodes.

Approach: thin SSH wrapper in CLI that `ssh user@host daran-net <command>` and streams output locally.

```bash
daran-net remote --host vps-01 --ssh user@1.2.3.4 warp install
daran-net remote --host vps-01 --ssh user@1.2.3.4 warp start
daran-net remote status  # reads state.json from each node via scp/sftp
```

Deliverables:
- `RemoteNode` config in `config.yaml`:
  ```yaml
  nodes:
    - id: vps-01
      ssh: user@1.2.3.4
  ```
- `daran-net remote --host <id> <module> <command>` — forwards to SSH
- `daran-net fleet status` — aggregates status across all configured nodes

Done when: operator can manage 3–5 nodes without SSH-ing manually.

---

## Phase 3 — Agent Pull (multi-node at scale)

**Goal:** nodes self-reconcile from controller; operator edits desired-state files.

New components:
- **Controller**: static file server or minimal HTTP API serving per-node JSON.
- **Agent**: daemon on each node, runs pull loop, applies transitions, reports state.
- **`daran-net agent`** subcommand: start/stop/status/install-service.

Migration path from Phase 2:
1. Deploy controller (nginx serving `state/` directory, or `daran-net controller serve`).
2. On each node: `daran-net agent install-service --controller https://... --node-id vps-01`
3. Agent reads existing `state.json`; first pull is a no-op if state matches desired.
4. Remove SSH remote config; all changes go through controller desired-state files.

Deliverables:
- `lib/agent.py`: pull loop, reconcile logic, HTTP fetch
- `modules/agent_cli.py`: `agent` Typer sub-app
- Controller schema (JSON schema for desired-state document)
- Systemd unit template for agent service

Done when: adding a new node requires only: (a) write desired-state file, (b) run one bootstrap command on the node.

---

## Invariants Across All Phases

- `state.json` format never changes between phases — agent and CLI share it.
- Module functions (`install`, `start`, `stop`, `uninstall`) are identical in all phases — agent calls the same code as CLI.
- No phase requires rewriting existing modules; only new CLI surface area is added.
