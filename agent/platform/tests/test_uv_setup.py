from __future__ import annotations

from pathlib import Path
import tomllib


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parents[1]


def test_platform_has_uv_project_file() -> None:
    pyproject_path = BACKEND_ROOT / "pyproject.toml"
    requirements_path = BACKEND_ROOT / "requirements.txt"

    assert pyproject_path.exists()
    assert not requirements_path.exists()

    content = pyproject_path.read_text(encoding="utf-8")
    assert "[project]" in content
    assert 'name = "isoftdevagents-platform"' in content
    assert "dependencies = [" in content


def test_run_dev_uses_uv_run() -> None:
    run_dev_path = BACKEND_ROOT / "run_dev.sh"

    content = run_dev_path.read_text(encoding="utf-8")
    assert "uv run" in content
    assert "./.venv/bin/python" not in content


def test_readme_uses_uv_install_and_start_commands() -> None:
    backend_readme = (BACKEND_ROOT / "README.md").read_text(encoding="utf-8")
    repo_readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "uv sync" in backend_readme
    assert "uv run" in backend_readme
    assert "pip install -r requirements.txt" not in backend_readme

    assert "uv sync" in repo_readme
    assert "uv run" in repo_readme
    assert "pip install -r requirements.txt" not in repo_readme


def test_platform_dependencies_include_crewai_for_inprocess_agents() -> None:
    pyproject_path = BACKEND_ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    dependencies = data["project"]["dependencies"]

    assert any(str(item).startswith("crewai[tools]==") for item in dependencies)
    assert any(str(item).startswith("litellm==") for item in dependencies)


def test_platform_dependencies_include_prompt_toolkit_for_prompt_bridge() -> None:
    pyproject_path = BACKEND_ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    dependencies = data["project"]["dependencies"]

    assert any(str(item).startswith("prompt-toolkit==") for item in dependencies)


def test_reagent_dependencies_include_prompt_toolkit_for_interactive_feedback() -> None:
    reagent_root = REPO_ROOT / "agent" / "Requirements Agent" / "reagent"
    pyproject_data = tomllib.loads((reagent_root / "pyproject.toml").read_text(encoding="utf-8"))
    pyproject_dependencies = pyproject_data["project"]["dependencies"]
    requirements_lines = (reagent_root / "requirements.txt").read_text(encoding="utf-8").splitlines()

    assert any(str(item).startswith("prompt-toolkit==") for item in pyproject_dependencies)
    assert any(line.startswith("prompt-toolkit==") for line in requirements_lines)
