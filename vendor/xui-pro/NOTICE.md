# Third-Party Upstream: x-ui-pro

## Attribution

| Field       | Value                                             |
|-------------|---------------------------------------------------|
| Name        | x-ui-pro                                          |
| Author      | mozaroc (GitHub: @mozaroc)                        |
| Repository  | https://github.com/mozaroc/x-ui-pro               |
| Install URL | https://github.com/mozaroc/x-ui-pro/raw/master/x-ui-pro.sh |
| License     | Not explicitly stated in repository               |

## Usage in daran-proxy-stack

This project uses the **upstream install script** from `mozaroc/x-ui-pro` as a
**temporary external installer backend** for the 3x-ui panel component.

The install script is fetched directly from the upstream GitHub repository at
runtime — it is **not vendored, copied, or embedded** in this codebase. The
user sees the source URL and must explicitly confirm before anything is
executed in their shell.

## Why upstream

Installing 3x-ui with nginx reverse proxy (REALITY + WebSocket/gRPC support)
requires a complex setup covered by the upstream script. Until daran-proxy-stack
builds its own installer, we delegate to mozaroc/x-ui-pro as an acknowledged
external dependency.

## Temporary status

This integration is **explicitly temporary**. When daran-proxy-stack ships its
own 3x-ui installer, this upstream path will be replaced and this notice
will be updated.

## What we do NOT do

- We do NOT copy, redistribute, or claim authorship of the upstream script
- We do NOT modify the upstream script
- We fetch it fresh from GitHub at install time so the user gets the latest version
- We display the exact source URL to the operator before any action

---

*Added: 2026-03-28. See: src/daran_proxy_stack/cli/actions/xui.py*
