from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO_ROOT / "agent" / "Requirements Agent" / "reagent" / "src" / "reagent" / "BusinessRequirements.py"


def test_context_diagram_run_passes_competitive_analysis_placeholder():
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert "'competitive_analysis': get_competitive_analysis()" in source
