from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "run_gomoku_five_agent_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("gomoku_five_agent_smoke", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_prepare_run_layout_creates_expected_directories(tmp_path: Path):
    module = _load_module()

    layout = module.prepare_run_layout(tmp_path, "run-001")

    assert layout.run_root == tmp_path / "run-001"
    assert layout.inputs_dir.is_dir()
    assert layout.requirements_dir.is_dir()
    assert layout.architecture_dir.is_dir()
    assert layout.coding_dir.is_dir()
    assert layout.ui_dir.is_dir()
    assert layout.test_dir.is_dir()
    assert layout.logs_dir.is_dir()


def test_build_ui_api_methods_returns_empty_contract_for_blank_openapi(tmp_path: Path):
    module = _load_module()
    spec_path = tmp_path / "api_spec.yaml"
    spec_path.write_text("openapi: 3.0.0\npaths: {}\n", encoding="utf-8")

    api_methods = module.build_ui_api_methods(spec_path)

    assert api_methods == {}


def test_write_test_dataset_materializes_bridge_files(tmp_path: Path):
    module = _load_module()
    dataset_root = tmp_path / "dataset"
    coding_root = tmp_path / "generated-code"
    coding_root.mkdir()

    inputs = module.TestDatasetInputs(
        dataset_root=dataset_root,
        dataset_name="gomoku",
        srs_text="# SRS\n",
        architecture_text="# Architecture\n",
        uml_class_text="# UML Class\n",
        uml_sequence_text="# UML Sequence\n",
        sut_root=coding_root,
        language="typescript",
    )

    dataset_dir = module.write_test_dataset(inputs)

    config_payload = json.loads((dataset_dir / "config.json").read_text(encoding="utf-8"))

    assert dataset_dir == dataset_root / "gomoku"
    assert (dataset_dir / "srs.md").read_text(encoding="utf-8") == "# SRS\n"
    assert (dataset_dir / "architecture_design.md").read_text(encoding="utf-8") == "# Architecture\n"
    assert config_payload["sut_root"] == str(coding_root)
    assert config_payload["language"] == "typescript"


def test_build_architecture_requirements_markdown_uses_available_drafts():
    module = _load_module()

    markdown = module.build_architecture_requirements_markdown(
        project_name="五子棋 Web 游戏",
        business_scope="scope",
        functional_requirements="functional",
        non_functional_requirements="non-functional",
        use_case_text="use-cases",
        dialog_map_text="dialog-map",
    )

    assert "# 五子棋 Web 游戏 Requirements Draft" in markdown
    assert "functional" in markdown
    assert "dialog-map" in markdown


def test_append_debug_record_writes_stage_metadata(tmp_path: Path):
    module = _load_module()
    record_path = tmp_path / "debug-record.md"
    result = module.StageResult(
        name="coding",
        command=["python", "main.py"],
        cwd="/tmp/work",
        env_keys=["OPENAI_API_KEY", "OPENAI_BASE_URL"],
        input_files=["/tmp/in.json"],
        output_files=["/tmp/out.py"],
        exit_code=0,
        duration_seconds=1.23,
        stdout_summary="generated files",
        stderr_summary="",
        passed=True,
        bridge_sources=["/tmp/out.py -> next/input.py"],
    )

    module.append_debug_record(record_path, "run-001", [result])

    content = record_path.read_text(encoding="utf-8")
    assert "run-001" in content
    assert "coding" in content
    assert "python main.py" in content
    assert "generated files" in content


def test_resolve_python_bin_falls_back_to_current_interpreter(tmp_path: Path):
    module = _load_module()

    resolved = module.resolve_python_bin(tmp_path / "missing-python")

    assert resolved == Path(sys.executable)


def test_run_command_supports_timeout_reporting(tmp_path: Path):
    module = _load_module()
    result = module.run_command(
        name="timeout-test",
        command=[sys.executable, "-c", "import time; time.sleep(1)"],
        cwd=tmp_path,
        env={},
        log_path=tmp_path / "timeout.log",
        input_files=[],
        output_root=tmp_path,
        bridge_sources=[],
        timeout_seconds=0.01,
    )

    assert result.exit_code == 124
    assert result.passed is False


def test_coerce_subprocess_output_decodes_bytes():
    module = _load_module()

    assert module.coerce_subprocess_output(b"hello") == "hello"
    assert module.coerce_subprocess_output("world") == "world"


def test_build_parser_uses_longer_default_requirements_full_timeout():
    module = _load_module()

    parser = module.build_parser()
    args = parser.parse_args([])

    assert args.requirements_full_timeout == 600
    assert args.requirements_drafts_timeout == 600


def test_build_parser_allows_overriding_requirements_full_timeout():
    module = _load_module()

    parser = module.build_parser()
    args = parser.parse_args(
        [
            "--requirements-full-timeout",
            "1800",
            "--requirements-drafts-timeout",
            "900",
        ]
    )

    assert args.requirements_full_timeout == 1800
    assert args.requirements_drafts_timeout == 900


@pytest.mark.parametrize(
    ("artifact_name", "expected"),
    [
        ("class_design_raw.md", "# Class Design\n"),
        ("component_design.json", "{\n  \"components\": []\n}\n"),
    ],
)
def test_read_optional_text_defaults_when_missing(tmp_path: Path, artifact_name: str, expected: str):
    module = _load_module()
    artifact_path = tmp_path / artifact_name

    assert module.read_optional_text(artifact_path, default=expected) == expected
