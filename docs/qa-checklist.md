# QA Checklist — daran-proxy-stack

Runnable smoke gate: `pytest` (see `tests/test_smoke.py`)
Manual verifications below require a live VPS.

---

## MTProxy

### Config & generation
- [ ] `daran-net mtproxy status` prints module summary without errors
- [ ] `daran-net mtproxy bootstrap` generates `artifacts/generated/mtproxy/` files:
  - `docker-compose.yml` — valid YAML; contains `-H <port>` and `-S <secret>`
  - `secret.txt` — 32-char hex; stable across re-runs (not regenerated if file exists)
  - `tg-link.txt` — starts with `tg://proxy?server=`
  - `tg-link.qr.txt` — non-empty QR ASCII art
  - `MTProxy.service` — contains `[Unit]`, `[Service]`, `[Install]`, `ExecStart=`
  - `official-bootstrap.sh` — `bash -n` passes (syntax check)

### Live (Docker path)
- [ ] `docker compose -f artifacts/generated/mtproxy/docker-compose.yml up -d` starts container
- [ ] `docker ps` shows `mtproxy` container as `Up`
- [ ] Stats port responds: `curl -s http://localhost:8888/stats` returns JSON
- [ ] `tg://proxy` link opens Telegram and connects successfully

### Live (official/systemd path)
- [ ] `official-bootstrap.sh` completes without errors on Debian/Ubuntu
- [ ] `systemctl status MTProxy.service` shows `active (running)`
- [ ] Proxy reachable from Telegram client using generated link

### Port conflicts
- [ ] `daran-net mtproxy suggest-ports` lists ports with no listener
- [ ] `daran-net mtproxy official-doctor` reports `[OK]` for all prerequisites when met

---

## WARP

### Config & generation
- [ ] `daran-net warp status` prints module summary; no crash when warp-cli absent
- [ ] `daran-net warp xray-json` outputs valid JSON with `protocol: socks`
- [ ] `daran-net warp plan` shows configured vs effective backend and SOCKS endpoint

### Auto backend detection
- [ ] With `backend: auto` + `warp-cli` installed → effective backend = `warp-cli`
- [ ] With `backend: auto` + only `cloudflared` installed → effective backend = `cloudflared`
- [ ] `backend: warp-cli` override is honoured regardless of environment

### OS detection guardrails (new)
- [ ] `daran-net warp install` on Debian/Ubuntu proceeds to apt install
- [ ] `daran-net warp install` on non-Debian/Ubuntu prints unsupported-OS message and exits non-zero
- [ ] Re-running `warp install` when warp-cli already installed returns ok without re-downloading

### Live (warp-cli)
- [ ] `warp-cli --accept-tos status` reports `Connected` after connect
- [ ] SOCKS proxy at configured `socks_host:socks_port` forwards traffic (curl via SOCKS)
- [ ] `socks_running` field in `warp status` reflects actual process state

### Live (cloudflared)
- [ ] SOCKS process starts; PID file written to `state_dir`
- [ ] Stop cleans up PID file; `socks_running` becomes `false`

---

## Cascade / Relay

> Module scaffold present; connectivity probing not yet implemented.
> All live tests are pre-planned acceptance criteria — marked accordingly.

### Implemented (testable offline)
- [x] `cascade:` section accepted in `config.yaml` and parsed into `CascadeConfig`
- [x] `CascadeConfig` defaults: `relay_host=127.0.0.1`, `relay_port=1080`, `enabled=false`
- [x] `collect_diagnostics(None)` returns stub with `config_present=false`
- [x] `collect_diagnostics(config)` with `enabled=false` skips port probes, sets `relay_reachable=false`
- [x] `render_summary(cfg)` returns Rich Panel without crashing

### Live / pre-planned (not yet implemented)
- [ ] `daran-net cascade status` CLI command exists and prints summary
- [ ] `enabled: true` causes connectivity probe of `relay_host:relay_port`
- [ ] Traffic route: client → MTProxy → WARP SOCKS → target
- [ ] Fallback node selected when primary is unreachable

---

## Web Panel API

> Panel routes live at `/api/v1/*`. HTML views require Jinja2 templates on disk.

### Implemented (testable with httpx)
- [x] `GET /api/v1/status` returns 200 with keys: `panel_uptime_s`, `server`, `mtproxy`, `warp`, `jobs`
- [x] `GET /api/v1/jobs` returns 200 with a JSON list; each item has `id`, `name`, `status`, `description`, `last_run`
- [x] `GET /api/v1/warp` returns 200 with `ok` key
- [x] `GET /api/v1/mtproxy` returns 200 with `ok` key
- [x] `GET /api/v1/servers` returns 200 with `hostname` key
- [x] `GET /` redirects to `/overview` (3xx)

### Live panel (VPS)
- [ ] `daran-net panel` starts uvicorn; panel reachable at configured host:port
- [ ] All 5 HTML views (overview, servers, mtproxy, warp, jobs) render without 500 errors
- [ ] `/api/v1/status` `warp.connected` reflects live warp-cli state
- [ ] `/api/v1/mtproxy` `container_status` reflects live docker container state

---

## Panel Sync

> Module not yet implemented.

- [ ] Panel API credentials stored securely (not in plain YAML)
- [ ] `daran-net panel sync` pushes generated `tg-link.txt` to configured panel endpoint
- [ ] Sync is idempotent; re-run does not duplicate entries
- [ ] Failed sync exits non-zero and prints actionable error

---

## Node Targeting

> Module not yet implemented.

- [ ] `--node <name>` flag accepted by `daran-net mtproxy` and `warp` subcommands
- [ ] Config supports `nodes:` list with per-node overrides (port, backend, etc.)
- [ ] `daran-net nodes list` shows configured nodes and their status
- [ ] Default node applies when `--node` is omitted

---

## General CLI

- [ ] `daran-net version` prints semver string
- [ ] `daran-net doctor` exits 0 when all required tools are present
- [ ] Unknown subcommand prints usage, exits non-zero
- [ ] `--config <path>` loads alternate config file for all subcommands
- [ ] `daran-net --help` and all subcommand `--help` flags render without errors
