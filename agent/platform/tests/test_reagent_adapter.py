import tempfile
import unittest
from pathlib import Path
import sys
import importlib
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents import reagent_adapter


class _FakeTask:
    def __init__(self, output_file: str) -> None:
        self.output_file = output_file


class _FakeCrew:
    def __init__(self, tasks) -> None:
        self.tasks = tasks

    def kickoff(self, inputs=None):
        class _Result:
            raw = "# Survey\n\nGenerated content.\n"

        return _Result()

    def calculate_usage_metrics(self):
        class _Usage:
            prompt_tokens = 12
            completion_tokens = 8
            total_tokens = 20

        return _Usage()


class _FakeCrewWithoutUsage(_FakeCrew):
    def kickoff(self, inputs=None):
        class _Usage:
            prompt_tokens = 21
            completion_tokens = 9
            total_tokens = 30

        class _Result:
            raw = "# Survey\n\nGenerated content.\n"
            token_usage = _Usage()

        return _Result()

    def calculate_usage_metrics(self):
        class _Usage:
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0

        return _Usage()


class _FakeCrewWithCamelCaseUsage(_FakeCrew):
    def calculate_usage_metrics(self):
        class _Usage:
            inputTokens = 34
            outputTokens = 13
            totalTokens = 47

        return _Usage()


class _FakeCrewWithNestedResultUsage(_FakeCrew):
    def kickoff(self, inputs=None):
        class _Usage:
            input_tokens = 55
            output_tokens = 21
            total_tokens = 76

        class _Result:
            raw = "# Survey\n\nGenerated content.\n"
            usage = _Usage()

        return _Result()

    def calculate_usage_metrics(self):
        class _Usage:
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0

        return _Usage()


class _FakeCrewFactory:
    def __init__(self, output_file: str) -> None:
        self.tasks = []
        self._crew = _FakeCrew([_FakeTask(output_file)])

    def crew(self):
        return self._crew


class _FakeCrewWithCamelCaseUsageFactory:
    def __init__(self, output_file: str) -> None:
        self.tasks = []
        self._crew = _FakeCrewWithCamelCaseUsage([_FakeTask(output_file)])

    def crew(self):
        return self._crew


class _FakeCrewWithoutUsageFactory:
    def __init__(self, output_file: str) -> None:
        self.tasks = []
        self._crew = _FakeCrewWithoutUsage([_FakeTask(output_file)])

    def crew(self):
        return self._crew


class _FakeCrewWithNestedResultUsageFactory:
    def __init__(self, output_file: str) -> None:
        self.tasks = []
        self._crew = _FakeCrewWithNestedResultUsage([_FakeTask(output_file)])

    def crew(self):
        return self._crew


class ReagentAdapterTests(unittest.TestCase):
    def test_direct_reagent_run_with_retry_persists_output_file_from_crew_object(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        reagent_root = repo_root / "agent" / "Requirements Agent" / "reagent"

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "survey.md"

            for module_name in list(sys.modules):
                if module_name == "util" or module_name.startswith("util."):
                    sys.modules.pop(module_name, None)

            original_sys_path = list(sys.path)
            sys.path.insert(0, str(reagent_root))
            try:
                with patch.dict("os.environ", {"REAGENT_STORE_PATH": temp_dir}, clear=False):
                    util_module = importlib.import_module("util")
                    util_module.run_with_retry(
                        lambda: _FakeCrewFactory(str(output_path)),
                        inputs={},
                        name="SurveyCrew",
                    )
            finally:
                sys.path[:] = original_sys_path
                for module_name in list(sys.modules):
                    if module_name == "util" or module_name.startswith("util."):
                        sys.modules.pop(module_name, None)

            self.assertTrue(output_path.exists())
            self.assertIn("Generated content.", output_path.read_text(encoding="utf-8"))

    def test_patched_run_with_retry_persists_output_file_from_crew_object(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "survey.md"
            reagent_adapter._patched_run_with_retry(
                lambda: _FakeCrewFactory(str(output_path)),
                inputs={},
                name="SurveyCrew",
            )

            self.assertTrue(output_path.exists())
            self.assertIn("Generated content.", output_path.read_text(encoding="utf-8"))

    def test_patched_run_with_retry_restores_absolute_store_path_when_crewai_strips_leading_slash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "survey.md"
            stripped_output_path = str(output_path).lstrip("/")

            with patch.dict("os.environ", {"REAGENT_STORE_PATH": temp_dir}, clear=False):
                reagent_adapter._patched_run_with_retry(
                    lambda: _FakeCrewFactory(stripped_output_path),
                    inputs={},
                    name="SurveyCrew",
                )

            self.assertTrue(output_path.exists())
            self.assertIn("Generated content.", output_path.read_text(encoding="utf-8"))

    def test_patched_run_with_retry_reports_usage_to_callback(self) -> None:
        captured_usage = []

        reagent_adapter._patched_run_with_retry(
            lambda: _FakeCrewFactory("survey.md"),
            inputs={},
            name="SurveyCrew",
            usage_callback=captured_usage.append,
        )

        self.assertEqual(
            captured_usage,
            [
                {
                    "inputTokens": 12,
                    "outputTokens": 8,
                    "totalTokens": 20,
                }
            ],
        )

    def test_patched_run_with_retry_falls_back_to_result_token_usage_when_crew_summary_is_empty(self) -> None:
        captured_usage = []

        reagent_adapter._patched_run_with_retry(
            lambda: _FakeCrewWithoutUsageFactory("survey.md"),
            inputs={},
            name="SurveyCrew",
            usage_callback=captured_usage.append,
        )

        self.assertEqual(
            captured_usage,
            [
                {
                    "inputTokens": 21,
                    "outputTokens": 9,
                    "totalTokens": 30,
                }
            ],
        )

    def test_patched_run_with_retry_supports_camel_case_usage_summary(self) -> None:
        captured_usage = []

        reagent_adapter._patched_run_with_retry(
            lambda: _FakeCrewWithCamelCaseUsageFactory("survey.md"),
            inputs={},
            name="SurveyCrew",
            usage_callback=captured_usage.append,
        )

        self.assertEqual(
            captured_usage,
            [
                {
                    "inputTokens": 34,
                    "outputTokens": 13,
                    "totalTokens": 47,
                }
            ],
        )

    def test_patched_run_with_retry_falls_back_to_result_usage_field(self) -> None:
        captured_usage = []

        reagent_adapter._patched_run_with_retry(
            lambda: _FakeCrewWithNestedResultUsageFactory("survey.md"),
            inputs={},
            name="SurveyCrew",
            usage_callback=captured_usage.append,
        )

        self.assertEqual(
            captured_usage,
            [
                {
                    "inputTokens": 55,
                    "outputTokens": 21,
                    "totalTokens": 76,
                }
            ],
        )
