from __future__ import annotations

from pathlib import Path

import yaml

from daran_proxy_stack.lib.files import write_text
from daran_proxy_stack.lib.models import AppConfig


def find_local_config(start: Path | None = None) -> Path | None:
    """Locate a repo-local config.yaml by walking up from the codebase."""
    here = start or Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config.yaml"
        if candidate.exists():
            return candidate
    return None


def default_config_path() -> Path:
    """Return the preferred writable config path for local CLI/menu flows."""
    found = find_local_config()
    if found is not None:
        return found
    return Path(__file__).resolve().parents[3] / "config.yaml"


def load_config(path: Path | None = None) -> AppConfig:
    target = path or find_local_config()
    if target is None or not target.exists():
        return AppConfig()

    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(data)


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    target = path or default_config_path()
    data = config.model_dump(mode="python", exclude_none=True)
    content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    write_text(target, content)
    return target
