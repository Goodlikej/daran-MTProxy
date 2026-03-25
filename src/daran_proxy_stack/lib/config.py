from pathlib import Path

import yaml

from daran_proxy_stack.lib.models import AppConfig


def load_config(path: Path | None = None) -> AppConfig:
    if path is None or not path.exists():
        return AppConfig()

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(data)
