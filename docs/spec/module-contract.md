# Module Contract

Every module (`warp`, `mtproxy`, future `relay`) **must** implement this interface. New modules that don't conform won't integrate with the CLI or agent pull loop.

## Required Functions

```python
# System probe — always safe to call, no side effects
def collect_diagnostics(config: ModuleConfig) -> DiagnosticsReport: ...

# Lifecycle — each returns ActionResult(ok, title, body)
def install(config: ModuleConfig) -> ActionResult: ...
def start(config: ModuleConfig) -> ActionResult: ...
def stop(config: ModuleConfig) -> ActionResult: ...
def uninstall(config: ModuleConfig) -> ActionResult: ...

# State read — reads state.json, returns status string
def get_status(config: ModuleConfig) -> str: ...  # one of the ModuleState.status values

# CLI display — returns a Rich renderable
def render_summary(config: ModuleConfig, diag: DiagnosticsReport) -> Panel: ...
```

## Optional Functions

Implement only when the module produces these outputs:

```python
# For modules integrating with Xray/3x-ui
def render_xray_outbound(config: ModuleConfig) -> dict: ...
def save_xray_artifact(config: ModuleConfig) -> None: ...

# For modules with shareable links
def render_share_link(config: ModuleConfig, public_ip: str) -> str: ...
def render_qr(config: ModuleConfig, public_ip: str) -> str: ...

# For modules with generated install scripts
def save_artifacts(config: ModuleConfig, public_ip: str | None) -> None: ...
```

## Invariants

- **Idempotent install/uninstall.** Calling `install` on an already-installed module must not error.
- **No side effects in diagnostics.** `collect_diagnostics` only reads; never writes or starts processes.
- **No interactive I/O in module functions.** All prompting happens at the CLI layer. Modules receive fully resolved config.
- **All writes go through `lib/files`** — ensures parent directories exist; no raw `open()` calls in modules.
- **All shell calls go through `lib/shell.run()`** — captures stdout/stderr, returns `CommandResult`.

## State Persistence Contract

After each lifecycle transition, the module must write `state.json`:

```python
from daran_proxy_stack.lib.files import write_text
import json, datetime

def _write_state(config: ModuleConfig, status: str, error: str | None = None) -> None:
    state = {
        "status": status,
        "last_checked": datetime.datetime.utcnow().isoformat(),
        "error": error,
    }
    write_text(Path(config.state_dir) / "state.json", json.dumps(state, indent=2))
```

## CLI Registration Contract

Each module's commands are grouped under a Typer sub-app and mounted at `cli/main.py`:

```python
# In cli/main.py
from daran_proxy_stack.modules.relay import relay_app  # future example
app.add_typer(relay_app, name="relay")
```

Each sub-app must expose at minimum: `status`, `install`, `start`, `stop`, `uninstall`.
