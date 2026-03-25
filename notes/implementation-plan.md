# Implementation plan

## Stage 1 — project skeleton
- package metadata
- base CLI entrypoint
- config models
- module placeholders

## Stage 2 — WARP MVP
- detect OS/dependencies
- decide WARP backend strategy
- install/configure local SOCKS endpoint
- print status and Xray outbound JSON

## Stage 3 — MTProxy MVP
- docker-based deployment
- fake TLS host + port + secret
- tg://proxy generation
- QR output

## Stage 4 — relay/cascade MVP
- deterministic rule backend
- TCP + UDP rules
- persistence and diagnostics

## Stage 5 — menu wrapper
- numbered guided flows over CLI commands
