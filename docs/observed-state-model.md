# Observed state model

Дата: 2026-03-28
Статус: draft

## Purpose

Этот документ фиксирует единую truthful state model для terminal menu, automation layer и optional panel.

Главная цель:
- система должна показывать не guessed defaults,
- а реально обнаруженное состояние машины и модулей.

## Core rule

Observed state = source of truth.

Нельзя:
- собирать UI из дефолтов, если discovery не подтвердил реальное состояние
- смешивать config intent и observed runtime state
- держать отдельную panel-only правду

## State layers

Нужно жёстко разделять три слоя:

### 1. Desired state
Что пользователь хочет получить.

Примеры:
- установить MTProxy на 443
- использовать fake TLS host `cloudflare.com`
- держать WARP SOCKS5 на 40000
- включить panel локально

### 2. Configured state
Что реально записано в конфиги/файлы/systemd/docker compose/env.

Примеры:
- systemd unit enabled
- config file written
- docker container declared
- stored secret exists

### 3. Observed state
Что discovery реально увидел на машине сейчас.

Примеры:
- процесс жив или нет
- порт слушается или нет
- контейнер запущен или нет
- WARP IP реально изменился или нет
- tg link реально можно сгенерировать из найденных данных или нет

Terminal menu и panel должны показывать прежде всего observed state.

## Top-level snapshot

Рекомендуемая top-level структура:

```json
{
  "schema_version": "1.0",
  "host": {
    "os": "ubuntu",
    "version": "24.04",
    "public_ip": "1.2.3.4",
    "hostname": "node-01"
  },
  "discovery": {
    "last_run_at": "2026-03-28T10:00:00Z",
    "status": "ok",
    "warnings": []
  },
  "modules": {
    "mtproxy": {},
    "warp": {},
    "xray": {},
    "xray_pro": {},
    "amneziawg": {},
    "cascade": {},
    "panel": {}
  }
}
```

## Shared module state contract

Каждый модуль должен использовать единый общий каркас:

```json
{
  "installed": true,
  "enabled": true,
  "running": true,
  "health": "healthy",
  "version": "1.2.3",
  "manager": "systemd",
  "config_paths": [],
  "data_paths": [],
  "ports": [],
  "warnings": [],
  "errors": [],
  "last_checked_at": "2026-03-28T10:00:00Z"
}
```

## Fixed dictionaries

### health
Allowed:
- `unknown`
- `healthy`
- `degraded`
- `broken`
- `stopped`
- `not_installed`

### manager
Allowed:
- `systemd`
- `docker`
- `process`
- `hybrid`
- `none`

### port protocol
Allowed:
- `tcp`
- `udp`
- `both`

## Host-level state

Host snapshot should include:
- OS family/version
- public IP
- local IPs if needed
- virtualization hint if detectable
- default interface if relevant
- kernel/network tuning summary if relevant to module health

Example:

```json
{
  "os": "ubuntu",
  "version": "24.04",
  "public_ip": "1.2.3.4",
  "hostname": "proxy-node-1",
  "bbr_enabled": true
}
```

## Discovery metadata

Discovery block should tell whether the snapshot is trustworthy.

Example:

```json
{
  "last_run_at": "2026-03-28T10:00:00Z",
  "status": "ok",
  "warnings": [],
  "partial_modules": ["cascade"],
  "notes": []
}
```

If detection for a module is partial, UI must show that explicitly.

## MTProxy state model

MTProxy must include both service state and client artifacts.

```json
{
  "installed": true,
  "enabled": true,
  "running": true,
  "health": "healthy",
  "manager": "docker",
  "version": null,
  "config_paths": [],
  "data_paths": [],
  "ports": [
    {
      "bind": "0.0.0.0",
      "port": 443,
      "protocol": "tcp",
      "purpose": "telegram-mtproxy"
    }
  ],
  "public_endpoint": {
    "ip": "1.2.3.4",
    "port": 443
  },
  "secret": "<secret-or-redacted>",
  "secret_present": true,
  "fake_tls_host": "cloudflare.com",
  "client_artifacts": {
    "tg_link": "tg://proxy?...",
    "qr_path": "/opt/.../mtproxy-qr.png"
  },
  "runtime": {
    "container_name": "mtproxy",
    "container_running": true
  },
  "warnings": [],
  "errors": [],
  "last_checked_at": "2026-03-28T10:00:00Z"
}
```

### MTProxy discovery requirements
- detect whether Docker container exists
- detect whether container is running
- detect listening port
- detect secret presence
- detect fake TLS host if configured
- regenerate tg link from discovered state, not defaults
- detect whether QR can be re-rendered

### MTProxy health rules
- `not_installed`: no install found
- `healthy`: container running + port listening + secret present
- `degraded`: install exists but one artifact missing (e.g. QR missing, link not renderable)
- `broken`: config exists but container dead or required data missing
- `stopped`: installed but intentionally not running

## WARP state model

WARP must reflect transport truth, not just installed package truth.

```json
{
  "installed": true,
  "enabled": true,
  "running": true,
  "health": "healthy",
  "manager": "systemd",
  "backend": "warp-socks",
  "config_paths": [],
  "data_paths": [],
  "ports": [
    {
      "bind": "127.0.0.1",
      "port": 40000,
      "protocol": "tcp",
      "purpose": "local-socks5"
    }
  ],
  "registration": {
    "registered": true,
    "account_type": "free"
  },
  "network": {
    "server_ip": "1.2.3.4",
    "warp_ip": "8.8.8.8",
    "egress_changed": true
  },
  "xray_artifacts": {
    "socks_outbound_json": "{...}",
    "routing_examples": []
  },
  "warnings": [],
  "errors": [],
  "last_checked_at": "2026-03-28T10:00:00Z"
}
```

### WARP discovery requirements
- detect installed binaries/packages
- detect registration state
- detect local SOCKS5 process/service
- detect local SOCKS5 bind/port
- detect current public server IP
- detect current WARP egress IP
- confirm whether traffic actually exits through WARP
- regenerate Xray outbound JSON from discovered settings

### WARP health rules
- `healthy`: local SOCKS alive + registration ok + WARP egress confirmed
- `degraded`: WARP installed but SOCKS not listening, or egress verification uncertain
- `broken`: registration missing/corrupt or runtime repeatedly failing
- `stopped`: intentionally disabled

## Xray / Xray Pro state model

Xray family should expose runtime and integration surface.

```json
{
  "installed": true,
  "enabled": true,
  "running": true,
  "health": "healthy",
  "manager": "systemd",
  "version": "x.y.z",
  "config_paths": ["/usr/local/etc/xray/config.json"],
  "ports": [
    {
      "bind": "0.0.0.0",
      "port": 443,
      "protocol": "tcp",
      "purpose": "vless-inbound"
    }
  ],
  "integration": {
    "warp_outbound_present": true,
    "panel_managed": false
  },
  "warnings": [],
  "errors": [],
  "last_checked_at": "2026-03-28T10:00:00Z"
}
```

### Xray discovery requirements
- detect package/binary/service
- detect active config path
- detect listening inbounds
- detect outbound integration references
- detect if managed via 3x-ui or direct config

## AmneziaWG state model

```json
{
  "installed": true,
  "enabled": true,
  "running": true,
  "health": "healthy",
  "manager": "systemd",
  "version": null,
  "ports": [
    {
      "bind": "0.0.0.0",
      "port": 51820,
      "protocol": "udp",
      "purpose": "awg"
    }
  ],
  "config_paths": [],
  "peers": {
    "count": 3
  },
  "warnings": [],
  "errors": [],
  "last_checked_at": "2026-03-28T10:00:00Z"
}
```

## Cascade / Relay state model

Cascade is not just installed/not installed. It must expose rule truth.

```json
{
  "installed": true,
  "enabled": true,
  "running": true,
  "health": "healthy",
  "manager": "hybrid",
  "rule_backend": "iptables",
  "rules": [
    {
      "id": "rule-001",
      "protocol": "tcp",
      "listen_port": 443,
      "target_host": "10.0.0.2",
      "target_port": 8443,
      "status": "active",
      "notes": "telegram relay"
    }
  ],
  "diagnostics": {
    "active_rule_count": 1,
    "last_validation_at": "2026-03-28T10:00:00Z"
  },
  "warnings": [],
  "errors": [],
  "last_checked_at": "2026-03-28T10:00:00Z"
}
```

### Cascade discovery requirements
- detect whether rule backend exists
- detect rules actually applied
- map rules to persisted state if any
- validate target reachability where possible
- expose per-rule diagnostics

### Cascade health rules
- `healthy`: persisted rules match observed rules and validation passes
- `degraded`: rules exist but validation incomplete or partially broken
- `broken`: state mismatch or forwarding not functioning

## Panel state model

Panel is still just another module.

```json
{
  "installed": true,
  "enabled": true,
  "running": true,
  "health": "healthy",
  "manager": "systemd",
  "mode": "local",
  "listen": {
    "host": "0.0.0.0",
    "port": 8080
  },
  "access": {
    "local_url": "http://127.0.0.1:8080",
    "public_url": null
  },
  "warnings": [],
  "errors": [],
  "last_checked_at": "2026-03-28T10:00:00Z"
}
```

### panel mode
Allowed:
- `local`
- `remote-controller`
- `disabled`

## Generated user artifacts

Observed state must explicitly expose user-facing generated artifacts.

Examples:
- MTProxy `tg_link`
- MTProxy QR path
- WARP outbound JSON
- example routing snippets
- exported configs

If artifact cannot be generated from observed state, that must be shown as warning instead of silently fabricating output.

## Discovery confidence rules

Every module discovery should be classified:
- `full`
- `partial`
- `none`

Example:

```json
{
  "confidence": "partial",
  "reasons": [
    "service found but config path not resolved"
  ]
}
```

No module should silently pretend to be fully known when only partial evidence exists.

## UI / terminal rendering rules

### Terminal menu must show
- installed/not installed
- running/stopped/degraded
- key ports
- key user artifacts available/not available
- warnings if state is partial

### Panel must show
- the same statuses
- same health result
- same artifacts availability
- same warnings

No separate panel-specific interpretation layer.

## Re-discover contract

Re-discover must:
1. run detectors
2. rebuild observed state snapshot
3. mark partial confidence when needed
4. never overwrite desired/configured state blindly
5. update timestamps

## First-run reconcile contract

After installation, system must perform reconcile:
1. run discovery
2. compare intended install result with observed reality
3. mark mismatch if any
4. offer repair flow if needed

Installation is not complete until reconcile succeeds or explicitly reports mismatch.

## Required implementation phases tied to this model

### Phase 1
- define snapshot schema
- define shared module contract
- define health dictionaries

### Phase 2
- implement MTProxy/WARP/Cascade detectors
- implement confidence levels
- implement re-discover

### Phase 3
- wire terminal menu to observed state

### Phase 4
- wire panel to same observed state

## Git discipline for this area

Every discovery/state change must be committed as a narrow block with repo-visible status.

Minimum expected reporting in repo-visible form:
- what module state is now truthful
- what is still partial
- what discovery gaps remain
- what next block should be implemented
