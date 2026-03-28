# Terminal-first product shape

Дата: 2026-03-28
Статус: draft

## Product direction

Главный продукт — не web panel как primary surface.
Главный продукт — terminal-first installer/control system для VPS.

Panel существует как дополнительная функция поверх того же source of truth.
Она может быть:
- поднята на том же VPS
- поднята отдельно и подключена к node позже
- не использоваться вообще

## Core principle

Сначала:
- truthful discovery
- install/repair/manage flows
- menu-driven terminal UX

Потом:
- optional web panel

Нельзя делать panel отдельной правдой. Она должна читать тот же observed state, что и terminal control menu.

## Primary user journeys

### Journey A — same VPS

Пользователь заходит на VPS по SSH и запускает bootstrap.
Дальше:
1. bootstrap проверяет окружение
2. ставит зависимости продукта
3. запускает terminal menu
4. пользователь выбирает установку модулей
5. система валидирует installed state
6. опционально предлагает поднять panel на этом же VPS

### Journey B — node only

Пользователь ставит только стек и terminal control layer на VPS.
Panel не поднимается.

### Journey C — remote panel later

На node ставится только стек + observed state + actions.
Panel потом может жить отдельно и подключаться к node как внешний control surface.

## Product layers

### Layer 1 — module logic
- install actions
- remove actions
- restart actions
- diagnostics
- config rendering
- generated user artifacts

### Layer 2 — truthful observed state
- installed / not installed
- enabled / disabled
- running / stopped / degraded
- version
- ports
- config paths
- public endpoints
- health summary
- generated client artifacts

### Layer 3 — terminal UX
- numbered menus
- guided prompts
- quick install flows
- advanced install flows
- repair / recovery flows
- generated copy-paste output

### Layer 4 — panel
- installed stack overview
- diagnostics summary
- actions over same backend
- local mode or remote mode later

## Source of truth

Единый source of truth обязателен.

Terminal menu и panel должны использовать:
- один observed state backend
- одни action handlers
- одну inventory/discovery модель

Запрещено:
- derived defaults вместо discovery
- UI-only state
- отдельная panel-логика, которая не совпадает с terminal behavior

## Modules in scope

### MVP modules
1. WARP
2. MTProxy
3. Cascade / Relay

### Planned next modules
4. Xray
5. Xray Pro
6. AmneziaWG 1.0
7. AmneziaWG 2.0

## Why this order

### WARP first
- проще как MVP
- меньше moving parts
- быстро валидируется
- сразу полезен для Xray / 3x-ui сценариев

### MTProxy second
- ясный install/result flow
- link + QR — понятный user-facing output
- легко показать ценность

### Cascade third
- сложнее
- требует rule model и diagnostics
- важен, но его нельзя делать без нормальной state model

## Terminal menu tree

```text
Daran Proxy Stack

1. Install components
2. Manage installed stack
3. Re-discover current system
4. Diagnostics and repair
5. Panel options
6. Backup / export config
7. Update toolkit
0. Exit
```

### 1. Install components

```text
Install components

1. MTProxy
2. WARP
3. Xray
4. Xray Pro
5. AmneziaWG 1.0
6. AmneziaWG 2.0
7. Cascade / Relay
8. Recommended preset
0. Back
```

### 2. Manage installed stack

```text
Manage installed stack

1. MTProxy
2. WARP
3. Xray
4. Xray Pro
5. AmneziaWG
6. Cascade / Relay
7. Show all statuses
0. Back
```

### 3. Re-discover current system

```text
Re-discover current system

1. Full discovery
2. MTProxy only
3. WARP only
4. Xray only
5. Cascade only
0. Back
```

### 4. Diagnostics and repair

```text
Diagnostics and repair

1. Validate ports and listeners
2. Validate outbound IP / routing
3. Rebuild generated configs
4. Restart selected service
5. Repair broken installation
6. Show logs
0. Back
```

### 5. Panel options

```text
Panel options

1. Install panel on this VPS
2. Configure local panel access
3. Connect node to external panel
4. Disable panel
5. Show panel status
0. Back
```

### 6. Backup / export config

```text
Backup / export config

1. Export install summary
2. Export generated links / client data
3. Backup configs
4. Backup observed state
0. Back
```

### 7. Update toolkit

```text
Update toolkit

1. Update control toolkit
2. Re-run dependency bootstrap
3. Show current version
0. Back
```

## Module-specific UX

## WARP

### Install flow
```text
Install WARP

1. Install WARP with local SOCKS5
2. Re-register WARP identity
3. Change local SOCKS5 port
4. Show Xray / 3x-ui outbound config
0. Back
```

### Expected output
- server IP
- WARP IP
- local SOCKS5 endpoint
- backend info
- outbound JSON for Xray / 3x-ui
- routing hints

## MTProxy

### Install flow
```text
Install MTProxy

1. Quick install
2. Advanced install
0. Back
```

### Quick install asks
- fake TLS host
- port
- auto-install prerequisites if needed

### Expected output
- public IP
- port
- secret
- fake TLS host
- tg://proxy link
- QR
- service/container status

## Cascade / Relay

### Flow
```text
Cascade / Relay

1. Add forwarding rule
2. List rules
3. Remove rule
4. Reset all rules
5. Validate relay connectivity
0. Back
```

### Requirements
- TCP and UDP support
- deterministic persistence
- clear diagnostics
- no hidden iptables magic without visible state

## Recommended preset menu

```text
Recommended preset

1. Telegram proxy stack
2. WARP outbound for Xray
3. Relay chain
4. Minimal install only
0. Back
```

## Required architectural rule

Every install flow must be:
- idempotent where possible
- discoverable after completion
- repairable without full reinstall
- able to produce user-facing artifacts again on demand

## Implementation phases

## Phase 0 — product lock
Status: next

Goal:
- зафиксировать terminal-first product shape
- явно понизить panel до optional function
- закрепить menu tree и module order

Artifacts:
- `docs/terminal-first-product-shape.md`
- updated planning docs / README references

Done means:
- больше нет двусмысленности, что primary UX = terminal

## Phase 1 — observed state model
Status: next

Goal:
- ввести единый truthful observed state backend

Need to define:
- module status model
- install/runtime/health fields
- generated artifacts fields
- discovery output contract

Done means:
- terminal/menu/panel смотрят в один state backend

## Phase 2 — discovery and first-run reconcile
Status: next

Goal:
- после установки система сама понимает, что реально стоит и как оно живёт

Includes:
- MTProxy detection
- WARP detection
- Xray detection
- Cascade rule detection where possible
- re-discover action
- first-run reconcile

Done means:
- система не врёт derived defaults вместо observed truth

## Phase 3 — WARP MVP
Status: next

Goal:
- сделать полноценный install/manage flow для WARP

Includes:
- install
- detect
- start/stop/restart
- local SOCKS5 management
- WARP IP discovery
- Xray outbound JSON generation

Done means:
- пользователь может поставить и использовать WARP через terminal menu

## Phase 4 — MTProxy MVP
Status: next

Goal:
- сделать install/manage flow для MTProxy

Includes:
- docker-based deployment
- detect existing install
- secret/link generation
- QR output
- restart/reconfigure

Done means:
- пользователь получает working MTProxy and client artifacts from terminal flow

## Phase 5 — Cascade MVP
Status: next

Goal:
- собрать rule-driven relay manager

Includes:
- add/list/remove/reset rules
- TCP + UDP support
- persistence
- diagnostics

Done means:
- cascade/relay управляется из terminal flow, а не набором разрозненных shell hacks

## Phase 6 — terminal menu wrapper
Status: next

Goal:
- собрать единый interactive terminal menu над module actions

Includes:
- main menu
- install menu
- manage menu
- diagnostics menu
- panel menu
- backup/export menu

Done means:
- продукт usable from SSH without panel

## Phase 7 — panel as optional function
Status: later

Goal:
- дать browser control surface without splitting source of truth

Includes:
- Installed Stack view
- statuses
- diagnostics
- action triggers
- local panel mode first
- remote panel mode later

Done means:
- panel useful, but not required for product operation

## Phase 8 — multi-node control
Status: later

Goal:
- вынести panel/control surface за пределы single node

Includes:
- remote panel -> node connectivity
- inventory aggregation
- multi-node actions
- access model

Done means:
- one panel can manage multiple nodes without inventing a second product

## Git and delivery discipline

For every meaningful block:
1. work from a dedicated branch
2. keep scope narrow
3. verify locally
4. commit checkpoint
5. update docs/status with:
   - what was done
   - what remains
   - current next block

Accepted working states must be committed before the next block starts.

## GitHub reporting discipline

Every pushed block should make the current state obvious.

Minimum required in commit/PR notes or repo-visible docs:
- completed scope
- current verified behavior
- known gaps
- next recommended block

The goal is to prevent "what exactly was done and what is left" ambiguity.
