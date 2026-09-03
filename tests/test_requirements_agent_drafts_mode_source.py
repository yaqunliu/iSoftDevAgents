from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO_ROOT / "agent" / "Requirements Agent" / "reagent" / "src" / "reagent" / "main.py"


def test_requirements_agent_main_declares_drafts_mode():
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert 'choices=["full", "analysis", "drafts"]' in source
    assert '"dialog_map.md"' in source or "DialogMaprun(" in source
