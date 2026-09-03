from __future__ import annotations

from pathlib import Path

import yaml


config = None


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config.yaml"


def load_config(filename: str | Path | None = None, *, force_reload: bool = False):
    global config
    if config is None or force_reload:
        path = Path(filename) if filename is not None else default_config_path()
        with path.open("r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
    return config


load_config()
