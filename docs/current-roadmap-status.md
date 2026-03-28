# Current roadmap status

Дата: 2026-03-28 (updated release-prep pass)
Статус: release checkpoint

## Project position

Проект: `daran-proxy-stack` / `daran-MTProxy`

Целевое направление:
- terminal-first installer/control product for VPS
- optional panel as secondary function
- truthful observed state as the only source of truth

---

## What is done

### Foundation
- Python package scaffold with pyproject.toml and editable install
- `daran-net` CLI entry point (Typer)
- Config/model layer (Pydantic + PyYAML)
- Shell executor with result objects
- Bootstrap and run-panel scripts
- systemd unit template for panel
- Test baseline

### Discovery backend (implemented)
- Host-level discovery runner
- WARP detection module
- MTProxy detection module
- 3x-ui detection module
- Cascade detection module
- Compat adapter for API surface
- `daran-net discover` — non-interactive discovery command

### Terminal menu (implemented)
- Interactive menu: main view, module submenus
- Module status summary (WARP, MTProxy, 3x-ui, Cascade)
- Re-discover action

### MTProxy (implemented)
- Official source-build + systemd install flow
- proxy-secret + proxy-multi.conf fetch helpers
- systemd unit generation and apply
- tg:// link generation
- ASCII QR output
- Port suggestions and diagnostics
- Docker path retained as secondary compat

### WARP (implemented)
- Install/connect/disconnect
- Local SOCKS5 up/down
- Xray outbound JSON generation
- Uninstall

### 3x-ui (implemented)
- Status detection
- Install guide (mhsanaei/3x-ui)
- install-pro via mozaroc/x-ui-pro script
- Service restart

### Cascade (implemented)
- Status and diagnostics
- Rule list (iptables discovery)
- Managed rules (rules.json CRUD)
- Add/remove/reset rule
- Apply: generates 3proxy.cfg + cascade.service

### Web panel (implemented)
- Overview page with module status and inventory
- Servers page with inventory widget
- MTProxy, WARP, Cascade detail views
- Jobs view
- Inventory page
- REST API backend

---

## What is not done

### Product gaps
- First-run reconcile (auto-repair diverged state between observed and desired)
- Remote/multi-node panel mode (panel on one host, nodes on others)
- AmneziaWG detection and management
- Full iptables apply for cascade rules (currently generates 3proxy config only, does not apply iptables rules automatically)

### Infrastructure
- No automated deployment or packaging yet
- No CI/CD pipeline

---

## Delivery discipline from this point

Every future implementation block must leave repo-visible evidence of:
- completed scope
- verified current behavior
- known remaining gaps
- next recommended block

## Next recommended block

**Option A — first-run reconcile**
Goal: when discovery finds a module installed but misconfigured or stopped, offer a repair flow.

**Option B — iptables apply for cascade**
Goal: make cascade apply actually wire the iptables rules, not just generate config.

**Option C — AmneziaWG module**
Goal: detect and manage AmneziaWG alongside WARP/Xray outbound scenarios.

Pick based on which user scenario is most pressing.
