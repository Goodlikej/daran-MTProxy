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

### Live (warp-cli)
- [ ] `warp-cli --accept-tos status` reports `Connected` after connect
- [ ] SOCKS proxy at configured `socks_host:socks_port` forwards traffic (curl via SOCKS)
- [ ] `socks_running` field in `warp status` reflects actual process state

### Live (cloudflared)
- [ ] SOCKS process starts; PID file written to `state_dir`
- [ ] Stop cleans up PID file; `socks_running` becomes `false`

---

## Cascade / Relay

> Module not yet implemented. Checklist items are pre-planned acceptance criteria.

- [ ] Cascade config accepted in `config.yaml` under a `cascade:` key
- [ ] Node list parsed; each entry has `host`, `port`, `protocol`
- [ ] `daran-net cascade status` lists all configured relay nodes
- [ ] Traffic route: client → MTProxy → WARP SOCKS → target
- [ ] Fallback node selected when primary is unreachable

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
