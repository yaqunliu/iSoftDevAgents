import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parents[1]
ARCHITECTURE_AGENT_SRC_ROOT = REPO_ROOT / "agent" / "Architecture Agent" / "src"
ARCHITECTURE_AGENT_CREW_PATH = ARCHITECTURE_AGENT_SRC_ROOT / "arch_agent" / "crew.py"

if str(ARCHITECTURE_AGENT_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(ARCHITECTURE_AGENT_SRC_ROOT))


def _load_architecture_crew_module():
    module_name = "test_architecture_agent_crew_module"
    spec = importlib.util.spec_from_file_location(module_name, ARCHITECTURE_AGENT_CREW_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load architecture crew module: {ARCHITECTURE_AGENT_CREW_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ArchitectureAgentConfigTests(unittest.TestCase):
    def test_architecture_agent_passes_api_key_to_llm_wrapper(self) -> None:
        crew_module = _load_architecture_crew_module()
        captured_kwargs: dict[str, object] = {}

        class FakeLLMWithCache:
            def __init__(self, **kwargs) -> None:
                captured_kwargs.update(kwargs)

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "secret-key",
                "OPENAI_BASE_URL": "https://example.com/v1",
                "OPENAI_MODEL": "moonshot/kimi-k2.5",
            },
            clear=False,
        ):
            with patch.object(crew_module, "LLMWithCache", FakeLLMWithCache):
                crew_module.ArchDesign(timestamp="20260409_1200", project_name="demo-project")

        self.assertEqual(captured_kwargs["api_key"], "secret-key")
        self.assertEqual(captured_kwargs["base_url"], "https://example.com/v1")
        self.assertEqual(captured_kwargs["model"], "moonshot/kimi-k2.5")

