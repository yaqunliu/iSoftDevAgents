from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CODING_HELPER_PATH = REPO_ROOT / "agent" / "Coding Agent" / "agent" / "runtime_support.py"
UI_HELPER_PATH = REPO_ROOT / "agent" / "UI Agent" / "ui_runtime.py"
TEST_CONFIG_PATH = REPO_ROOT / "agent" / "TestAgent" / "config" / "config.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_coding_runtime_support_reads_json_config(tmp_path: Path):
    module = _load_module("coding_runtime_support", CODING_HELPER_PATH)
    config_path = tmp_path / "codeagent.json"
    config_path.write_text(
        json.dumps(
            {
                "srs": "/tmp/srs.md",
                "project": "/tmp/project.json",
                "memory": "/tmp/memory.json",
                "software": "/tmp/generated",
            }
        ),
        encoding="utf-8",
    )

    config = module.load_runtime_config(config_path)

    assert config["srs"] == "/tmp/srs.md"
    assert config["software"] == "/tmp/generated"


def test_ui_runtime_rejects_multiple_pages_for_gomoku():
    module = _load_module("ui_runtime", UI_HELPER_PATH)

    with pytest.raises(ValueError, match="exactly one page"):
        module.ensure_single_page_contract(
            {
                "pages": [
                    {"page_name": "Board", "artifacts": ["board"]},
                    {"page_name": "Settings", "artifacts": ["toggle"]},
                ]
            }
        )


def test_ui_runtime_requires_gomoku_artifacts():
    module = _load_module("ui_runtime", UI_HELPER_PATH)

    with pytest.raises(ValueError, match="15x15"):
        module.ensure_single_page_contract(
            {
                "pages": [
                    {
                        "page_name": "Gomoku",
                        "artifacts": [
                            "game title",
                            "current status area",
                            "restart button",
                        ],
                    }
                ]
            }
        )


def test_testagent_config_loads_explicit_file(tmp_path: Path):
    module = _load_module("testagent_config", TEST_CONFIG_PATH)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "dataset:",
                "  root_path: /tmp/datasets",
                "llm:",
                "  model: gpt-5",
            ]
        ),
        encoding="utf-8",
    )

    config = module.load_config(config_path, force_reload=True)

    assert config["dataset"]["root_path"] == "/tmp/datasets"
