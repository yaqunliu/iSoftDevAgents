from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def agent_root() -> Path:
    return Path(__file__).resolve().parent


def _default_paths() -> dict[str, str]:
    root = agent_root()
    return {
        "memory": str(root / "output_latest" / "working_memory.json"),
        "software": str(root / "generated"),
        "semantic_model": str(root / "output_latest" / "working_memory.json"),
        "project": str(root / "output_latest" / "step5_6_test.md"),
        "srs": str(root / "output_latest" / "use_case_latest.md"),
        "add": str(root / "output_latest" / "add.json"),
        "av": str(root / "output_latest" / "av.md"),
        "domain": str(root / "output_latest" / "step1_test.md"),
        "data_model": str(root / "output_latest" / "step2_test.md"),
        "module": str(root / "output_latest" / "step5_test.md"),
        "frontend": str(root / "output_latest" / "step3_4_test.md"),
        "cot1_desc": str(root / "config" / "standard_prompt" / "c1_domain" / "descrption"),
        "cot1_out": str(root / "config" / "standard_prompt" / "c1_domain" / "expected_output"),
        "cot2_desc": str(root / "config" / "standard_prompt" / "c2_data_model" / "descrption"),
        "cot2_out": str(root / "config" / "standard_prompt" / "c2_data_model" / "expected_output"),
        "cot3_desc": str(root / "config" / "standard_prompt" / "c3_module" / "descrption"),
        "cot3_out": str(root / "config" / "standard_prompt" / "c3_module" / "expected_output"),
        "cot3_4_desc": str(root / "config" / "standard_prompt" / "c3_4_ui" / "description"),
        "cot3_4_out": str(root / "config" / "standard_prompt" / "c3_4_ui" / "expected_output"),
        "cot4_desc": str(root / "config" / "standard_prompt" / "c4_step" / "descrption"),
        "cot4_out": str(root / "config" / "standard_prompt" / "c4_step" / "expected_output"),
        "cot4_5_desc": str(root / "config" / "standard_prompt" / "c4-5_function" / "description"),
        "cot4_5_out": str(root / "config" / "standard_prompt" / "c4-5_function" / "expected_output"),
        "cotm_desc": str(root / "config" / "standard_prompt" / "c5-6_map" / "description"),
        "cotm_out": str(root / "config" / "standard_prompt" / "c5-6_map" / "expected_output"),
        "code_desc_general": str(root / "config" / "code_prompt" / "back_general"),
        "code_desc_entity": str(root / "config" / "task_prompt" / "code_generation" / "desc_entity"),
        "code_desc_model": str(root / "config" / "code_prompt" / "back_model"),
        "code_desc_repo": str(root / "config" / "code_prompt" / "back_repository"),
        "code_desc_service": str(root / "config" / "code_prompt" / "back_service"),
        "code_desc_route": str(root / "config" / "code_prompt" / "back_api"),
        "code_desc_front_utils": str(root / "config" / "code_prompt" / "front_utils"),
        "code_desc_front_api": str(root / "config" / "code_prompt" / "frontend_api_client"),
        "code_desc_front_component": str(root / "config" / "code_prompt" / "frontend_component"),
        "code_desc_frontend_pages": str(root / "config" / "code_prompt" / "frontend_pages"),
        "code_desc_frontend_routes": str(root / "config" / "code_prompt" / "frontend_routes"),
        "code_desc_frontend_app": str(root / "config" / "code_prompt" / "frontend_app"),
        "code_desc_frontend_entry": str(root / "config" / "code_prompt" / "frontend_entry"),
        "code_desc_frontend_general": str(root / "config" / "code_prompt" / "frontend_general"),
    }


def load_runtime_config(config_path: str | Path | None = None) -> dict[str, Any]:
    base = _default_paths()
    path_value = config_path or os.getenv("CODEAGENT_CONFIG_JSON")
    if not path_value:
        return base
    payload = json.loads(Path(path_value).read_text(encoding="utf-8"))
    merged = dict(base)
    merged.update({key: str(value) for key, value in payload.items()})
    return merged
