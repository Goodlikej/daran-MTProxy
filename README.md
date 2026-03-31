# daran-proxy-stack

**Terminal-first VPS management toolkit** for MTProxy (Telegram), Cloudflare WARP, 3x-ui/Xray, relay/cascade, AmneziaWG, and multi-server scenarios.

The primary interface is a terminal menu over SSH. A web panel exists as a secondary, optional surface — protected by login/password.

---

## What this is

A modular Python system that replaces ad-hoc bash scripts for managing a VPS proxy stack. Core principle: truthful observed state first, then install/manage actions on top of it.

**Modules:**

| Module | What it does |
|---|---|
| **MTProxy** | Official Telegram MTProxy — systemd build, tg:// link + QR, secret key rotation timer |
| **AmneziaWG** | AmneziaWG VPN — install, server config, peer management, obfuscation parameters |
| **WARP** | Cloudflare WARP helper — install, connect, local SOCKS5 endpoint, Xray outbound JSON |
| **3x-ui (xui)** | 3x-ui (Xray-based web panel) detection and service management |
| **Cascade** | Port-forward relay rule manager — TCP/UDP rules, iptables DNAT, 3proxy config |
| **Monitoring** | Telegram watchdog — systemd timer every 5 min, alert on service failure |
| **Backup** | Archive config/state to tar.gz with manifest; restore with dry-run preview |
| **Multi-server** | Manage multiple VPS from one panel — TCP ping, SSH diagnostics, remote commands |
| **Discovery** | Truthful observed-state backend — detects what is actually installed and running |

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

Menu structure:

```
[1] MTProxy          — install, manage, key rotation
[2] WARP             — install, connect, SOCKS5
[3] 3x-ui            — install, service control
[4] Cascade          — relay rules, iptables DNAT
[5] AmneziaWG        — install, server config, peers
[6] Backup           — create / restore / inspect archives
[7] Monitoring       — Telegram watchdog setup
[8] Multi-server     — add/ping/diagnose remote VPS
[9] MTProxy key rotation — systemd timer for monthly refresh
[w] First-run wizard — guided setup for new server
```

### Non-interactive discovery

```bash
daran-net discover
```

---

## CLI entrypoints

All commands are under `daran-net`.

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
daran-net mtproxy key-refresh --yes       # download fresh proxy-secret + restart
daran-net mtproxy setup-key-rotation --yes # install monthly systemd timer
daran-net mtproxy uninstall --yes
```

### AmneziaWG

```bash
daran-net awg status
daran-net awg install --yes
daran-net awg generate-config --port 51820 --address 10.8.0.1/24 --yes
daran-net awg apply-config --yes
daran-net awg service-start --yes
daran-net awg service-stop --yes
daran-net awg service-restart --yes
daran-net awg list-peers
daran-net awg add-peer <name> --yes
daran-net awg remove-peer <name> --yes
daran-net awg show-client <name>   # print client config + QR
```

Generated client configs are saved to `~/.daran-proxy-stack/awg-generated/`.

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
daran-net xui install
daran-net xui install-pro --yes
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

### Backup

```bash
daran-net backup create --yes         # creates tar.gz archive
daran-net backup list                 # list available backups
daran-net backup inspect <path>       # show manifest + file list
daran-net backup restore <path> --yes # restore (dry-run first without --yes)
```

Archives are saved to `~/.daran-proxy-stack/backups/` by default.
Backed up: MTProxy secret/tg-link/service, cascade rules, relay state, AWG config, notify config.

### Monitoring

```bash
daran-net monitor setup --bot-token <TOKEN> --chat-id <ID> --yes
daran-net monitor test --bot-token <TOKEN> --chat-id <ID>
daran-net monitor status
```

Installs a systemd timer (`daran-watchdog.timer`) that fires every 5 minutes, checks each monitored service, and sends a Telegram alert on failure.

### Multi-server

```bash
daran-net servers list
daran-net servers ping-all
daran-net servers add --host 1.2.3.4 --label "VPS-DE" --user root --port 22
daran-net servers remove <server-id> --yes
daran-net servers status <server-id>    # SSH diagnostics
daran-net servers run <server-id> "systemctl status MTProxy" --yes
```

Server registry is stored in `~/.daran-proxy-stack/servers.json`.

---

## Web panel

Secondary surface — same observed state as terminal. Requires login on first access.

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

### Authentication

On first visit the panel redirects to `/setup` to create a username and password.
Subsequent logins via `/login`. Sessions are stored as httponly cookies (7-day expiry).

- Passwords hashed with PBKDF2-SHA256 (200 000 iterations, stdlib only)
- Session tokens: HS256 JWT (stdlib `hmac` + `hashlib`, no external deps)
- Credentials: `~/.daran-proxy-stack/auth-config.json` (chmod 600)
- HMAC secret: `~/.daran-proxy-stack/panel-secret.key` (chmod 600)

### Panel pages

| Path | Description |
|---|---|
| `/` | Overview — observed state of all modules |
| `/mtproxy` | MTProxy status, link, QR |
| `/warp` | WARP status |
| `/cascade` | Relay rules |
| `/amneziawg` | AmneziaWG status, peers, diagnostics |
| `/servers` | Multi-server — local + remote VPS overview |
| `/login` | Login form |
| `/setup` | First-run password setup |
| `/logout` | End session |

### Panel REST API

```
GET  /api/v1/status               — full observed state
GET  /api/v1/mtproxy              — MTProxy diagnostics
GET  /api/v1/amneziawg            — AWG diagnostics + peer list
GET  /api/v1/multiserver/servers  — list registered servers
POST /api/v1/multiserver/servers  — add server {host, port, user, label, description}
DEL  /api/v1/multiserver/servers/{id} — remove server
GET  /api/v1/multiserver/ping     — TCP ping all servers
GET  /api/v1/multiserver/servers/{id}/status — SSH diagnostics for one server
```

### systemd service (panel)

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
  cli/
    actions/       Action functions: mtproxy, warp, cascade, amneziawg,
                   backup, wizard, monitor, multiserver
    menu.py        Interactive terminal menu (Rich)
  discovery/       Observed-state backend + module detectors
  modules/         Business logic: mtproxy, warp, cascade, amneziawg
  lib/             Shared: config, models, executor, shell, paths,
                   firewall, notify, backup, multiserver
  web/
    app.py         FastAPI app + auth routes (login/logout/setup)
    api.py         REST API endpoints
    auth.py        AuthManager — JWT + PBKDF2 password hashing
    templates/     Jinja2 HTML templates (dark theme)

docs/              Architecture and product design specs
deploy/            systemd service templates
scripts/           bootstrap.sh, run-panel.sh
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
- No external crypto deps — JWT and password hashing use stdlib `hmac`/`hashlib`

---

## Current status

**Works:**
- Discovery backend (WARP, MTProxy, 3x-ui, Cascade, AmneziaWG)
- Interactive terminal menu — all modules
- MTProxy official-build + install/manage + monthly key rotation timer
- AmneziaWG — install (Ubuntu PPA), server config with obfuscation params (Jc/Jmin/Jmax/S1/S2/H1-H4), peer add/remove, client config + QR
- WARP install/connect/SOCKS management
- 3x-ui install guide and service control
- Cascade rule manager (rules.json → iptables DNAT + 3proxy config)
- Telegram monitoring watchdog (systemd timer, per-service alerts)
- Backup/restore with tar.gz archives and JSON manifest
- First-run wizard (mode selection → MTProxy / Relay / Both → monitoring → backup)
- Multi-server registry — TCP ping, SSH diagnostics, remote command execution
- Web panel — all views, protected by JWT login session
- Web panel REST API — status, MTProxy, AmneziaWG, multi-server CRUD

**Notes:**
- MTProxy: official Telegram source build is the preferred path. Docker image is marked outdated by upstream.
- Tested on Ubuntu 24.04 alongside 3x-ui occupying common ports (443/8443). Alternate ports like 2053 are fully supported.
- WARP: designed for use as an outbound transport for Xray/3x-ui.
- AmneziaWG key generation: tries `awg genkey` → `wg genkey` → pure-Python Curve25519 RFC 7748 fallback.
- Multi-server SSH uses `StrictHostKeyChecking=accept-new` and `BatchMode=yes` (key-based auth only).

---

## License

MIT
