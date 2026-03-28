# daran-proxy-stack

**Terminal-first VPS management toolkit** for MTProxy (Telegram), Cloudflare WARP, 3x-ui/Xray, and relay/cascade scenarios.

The primary interface is a terminal menu over SSH. A web panel exists as a secondary, optional surface.

---

## What this is

A modular Python system that replaces ad-hoc bash scripts for managing a VPS proxy stack. Core principle: truthful observed state first, then install/manage actions on top of it.

**Modules:**

| Module | What it does |
|---|---|
| **MTProxy** | Official Telegram MTProxy installer/manager — systemd-based, source build, tg:// link + QR generation |
| **WARP** | Cloudflare WARP helper — install, connect, local SOCKS5 endpoint, Xray outbound JSON |
| **3x-ui (xui)** | 3x-ui (Xray-based web panel) detection and service management |
| **Cascade** | Port-forward relay rule manager — TCP/UDP rules, iptables discovery, 3proxy config generation |
| **Discovery** | Truthful observed-state backend — detects what is actually installed and running on the host |

---

## Quick start

```bash
git clone <repo-url> daran-proxy-stack
cd daran-proxy-stack
bash scripts/bootstrap.sh
```

Bootstrap creates `.venv/`, installs the package in editable mode, and verifies the environment.

### Interactive terminal menu

```bash
source .venv/bin/activate
daran-net menu
```

### Non-interactive discovery

```bash
daran-net discover
```

---

## CLI entrypoints

All commands are under `daran-net`. Entry point is registered by `pyproject.toml`.

### Global

```bash
daran-net version
daran-net doctor
daran-net discover        # run discovery, print observed state
daran-net menu            # interactive terminal menu
daran-net panel           # start web panel (default: http://127.0.0.1:7331)
```

### MTProxy

```bash
daran-net mtproxy status
daran-net mtproxy suggest-ports
daran-net mtproxy official-doctor --port 2053
daran-net mtproxy bootstrap --port 2053 --stats-port 8889
daran-net mtproxy official-install --port 2053 --stats-port 8889 --yes
daran-net mtproxy tg-link --public-ip <YOUR_IP>
daran-net mtproxy qr
daran-net mtproxy uninstall --yes
```

### WARP

```bash
daran-net warp status
daran-net warp install
daran-net warp connect
daran-net warp socks-up
daran-net warp socks-down
daran-net warp xray-json
daran-net warp uninstall --yes
```

### 3x-ui

```bash
daran-net xui status
daran-net xui install           # prints install guide
daran-net xui install-pro --yes # upstream mozaroc/x-ui-pro script
daran-net xui restart
```

### Cascade

```bash
daran-net cascade status
daran-net cascade list-rules
daran-net cascade managed-rules
daran-net cascade add-rule tcp 443 1.2.3.4 443 --yes
daran-net cascade remove-rule <rule-id> --yes
daran-net cascade reset-rules --yes
daran-net cascade apply --yes
```

---

## Web panel

Secondary surface — same observed state as terminal.

```bash
# via run script (handles venv activation)
bash scripts/run-panel.sh

# with options
DARAN_PANEL_HOST=0.0.0.0 DARAN_PANEL_PORT=8080 bash scripts/run-panel.sh

# dev mode
DARAN_RELOAD=1 bash scripts/run-panel.sh

# via CLI
daran-net panel --host 127.0.0.1 --port 7331
```

Default: `http://127.0.0.1:7331`

## systemd service (panel)

```bash
REPO=/opt/daran-proxy-stack
USER=ubuntu
sed "s|%REPO_DIR%|$REPO|g; s|%RUN_USER%|$USER|g; s|%RUN_GROUP%|$USER|g" \
  deploy/daran-proxy-panel.service \
  | sudo tee /etc/systemd/system/daran-proxy-panel.service
sudo systemctl daemon-reload
sudo systemctl enable --now daran-proxy-panel
```

---

## Project layout

```text
src/daran_proxy_stack/
  cli/           CLI entrypoints (Typer) + interactive terminal menu
  discovery/     Truthful observed-state backend and module detectors
  modules/       Business logic: MTProxy, WARP, Cascade
  lib/           Shared: config, models, executor, shell, paths
  web/           Optional FastAPI panel + Jinja2 templates
  api/           REST API used by the panel

docs/            Architecture and product design specs
deploy/          systemd service template
scripts/         bootstrap.sh, run-panel.sh
config.example.yaml
tests/
```

---

## Stack

- Python 3.12+
- Typer + Rich (CLI/TUI)
- Pydantic (config models)
- PyYAML
- FastAPI + Uvicorn + Jinja2 (web panel)
- qrcode

---

## Current status and known limitations

**Works:**
- Discovery backend (WARP, MTProxy, 3x-ui, Cascade)
- Terminal menu with module status view
- MTProxy official-build + systemd install/manage flow
- WARP install/connect/socks management
- 3x-ui install guide and service control
- Cascade rule manager (rules.json → 3proxy config)
- Web panel (overview, inventory, MTProxy, WARP, Cascade views)

**Not yet done / partial:**
- First-run reconcile (auto-repair diverged state)
- Remote/multi-node panel mode
- AmneziaWG detection and management
- Full iptables apply for cascade rules (currently config-gen only)

**Notes:**
- MTProxy: official Telegram source build is the preferred path. Docker image is marked outdated by upstream.
- Tested on Ubuntu 24.04 alongside 3x-ui occupying common ports (e.g. 443/8443). Alternate ports like 2053 are fully supported.
- WARP: designed for use as an outbound transport for Xray/3x-ui, not as a standalone VPN client.

---

## License

MIT
