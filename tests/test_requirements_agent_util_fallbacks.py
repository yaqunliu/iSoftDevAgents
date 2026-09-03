from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "agent" / "Requirements Agent" / "reagent" / "util" / "util.py"


def _load_module_with_store_path(store_path: Path):
    module_name = "reagent_util_fallback_test"
    previous = os.environ.get("REAGENT_STORE_PATH")
    os.environ["REAGENT_STORE_PATH"] = str(store_path)
    try:
        spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None
        assert spec.loader is not None
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            os.environ.pop("REAGENT_STORE_PATH", None)
        else:
            os.environ["REAGENT_STORE_PATH"] = previous


def test_get_competitive_analysis_falls_back_to_survey(tmp_path: Path):
    survey_path = tmp_path / "survey.md"
    survey_path.write_text("# Survey\ncontent\n", encoding="utf-8")
    module = _load_module_with_store_path(tmp_path)

    result = module.get_competitive_analysis()

    assert result == "# Survey\ncontent\n"
