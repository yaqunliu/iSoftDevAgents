import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parents[1]
TEST_AGENT_ROOT = REPO_ROOT / "agent" / "TestAgent"

if str(TEST_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_AGENT_ROOT))

from tools.write_python_file import WriteCodeFileTool


class TestAgentWriteCodeFileToolTests(unittest.TestCase):
    def test_write_code_file_allows_writes_inside_configured_runtime_roots(self) -> None:
        tool = WriteCodeFileTool()

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            generated_root = runtime_root / "generated-code"
            generated_root.mkdir(parents=True, exist_ok=True)
            target_path = generated_root / "tests" / "test_demo.py"

            with patch.dict(
                os.environ,
                {
                    "ISOFTDEVAGENTS_TEST_AGENT_ALLOWED_WRITE_ROOTS": str(generated_root),
                },
                clear=False,
            ):
                result = tool._run(
                    path=str(target_path),
                    code="print('ok')",
                    overwrite=True,
                )

            self.assertIn("Successfully wrote code", result)
            self.assertEqual(target_path.read_text(encoding="utf-8"), "print('ok')\n")

    def test_write_code_file_rejects_writes_outside_configured_runtime_roots(self) -> None:
        tool = WriteCodeFileTool()

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            generated_root = runtime_root / "generated-code"
            generated_root.mkdir(parents=True, exist_ok=True)
            forbidden_path = runtime_root / "outside.py"

            with patch.dict(
                os.environ,
                {
                    "ISOFTDEVAGENTS_TEST_AGENT_ALLOWED_WRITE_ROOTS": str(generated_root),
                },
                clear=False,
            ):
                result = tool._run(
                    path=str(forbidden_path),
                    code="print('forbidden')",
                    overwrite=True,
                )

            self.assertIn("outside the allowed runtime roots", result)
            self.assertFalse(forbidden_path.exists())

    def test_write_code_file_rejects_empty_overwrite_and_keeps_existing_content(self) -> None:
        tool = WriteCodeFileTool()

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            generated_root = runtime_root / "generated-code"
            generated_root.mkdir(parents=True, exist_ok=True)
            target_path = generated_root / "__init__.py"
            target_path.write_text("existing = True\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "ISOFTDEVAGENTS_TEST_AGENT_ALLOWED_WRITE_ROOTS": str(generated_root),
                },
                clear=False,
            ):
                result = tool._run(
                    path=str(target_path),
                    code="",
                    overwrite=True,
                )

            self.assertIn("Refused to overwrite", result)
            self.assertEqual(target_path.read_text(encoding="utf-8"), "existing = True\n")
