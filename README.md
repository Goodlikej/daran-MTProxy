# daran-proxy-stack

Modular VPS network toolkit for:
- MTProxy for Telegram
- WARP outbound helpers for Xray / 3x-ui / Amnezia
- relay / cascade management for TCP/UDP scenarios

## Status
This repository is currently an active work-in-progress.

### What already works
- Python CLI foundation via `daran-net`
- MTProxy official-first flow
- environment diagnostics
- free-port suggestions
- systemd unit generation
- tg://proxy link generation
- ASCII QR generation
- official build / fetch / bootstrap / install helpers
- tested on a real Ubuntu 24.04 VPS alongside x-ui / nginx

### Current focus
- finish MTProxy polish
- improve state/config persistence
- make install/status/link/qr/remove/recreate flows cleaner
- continue with WARP and relay modules later

## Why this project exists
The goal is to build a maintainable alternative to huge interactive bash scripts that mix:
- installation
- business logic
- menus
- generated configs
- removal logic
- diagnostics

Instead, this project uses:
- a Python core
- a CLI layer
- optional future TUI / web layer

## Stack
- Python 3.12+
- Typer
- Rich
- Pydantic
- PyYAML
- qrcode

## Install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Or on systems without `venv`:
```bash
python3 -m pip install -e .
```

## CLI examples
### General
```bash
daran-net version
daran-net doctor
```

### MTProxy
```bash
daran-net mtproxy status
daran-net mtproxy suggest-ports
daran-net mtproxy official-doctor --port 2053
daran-net mtproxy bootstrap --port 2053 --stats-port 8889
daran-net mtproxy official-install --port 2053 --stats-port 8889 --yes
daran-net mtproxy tg-link --public-ip 89.125.72.158
```

### WARP
```bash
daran-net warp status
daran-net warp xray-json
daran-net warp plan
```

## Project layout
```text
artifacts/     generated helpers and examples
docs/          architecture and technical specs
notes/         working understanding and plans
transcripts/   source notes from videos / research
src/           Python source code
```

## Notes
- Official Telegram MTProxy source is preferred over Docker-first flow.
- Docker support remains as a secondary compatibility path.
- MTProxy was tested on a real VPS where x-ui already occupied common ports like 443/8443.
- Using an alternate port such as 2053 is supported and useful when coexisting with x-ui.

## License
MIT
