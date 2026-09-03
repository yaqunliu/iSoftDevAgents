from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUIREMENTS_FILE = REPO_ROOT / "agent" / "Requirements Agent" / "reagent" / "data" / "project_description.txt"
DEFAULT_DEBUG_RECORD = REPO_ROOT / "docs" / "gomoku-five-agent-debug-record.md"
DEFAULT_REQUIREMENTS_FULL_TIMEOUT_SECONDS = 600
DEFAULT_REQUIREMENTS_DRAFTS_TIMEOUT_SECONDS = 600


@dataclass
class RunLayout:
    run_id: str
    run_root: Path
    inputs_dir: Path
    requirements_dir: Path
    architecture_dir: Path
    coding_dir: Path
    ui_dir: Path
    test_dir: Path
    logs_dir: Path


@dataclass
class StageResult:
    name: str
    command: list[str]
    cwd: str
    env_keys: list[str]
    input_files: list[str]
    output_files: list[str]
    exit_code: int
    duration_seconds: float
    stdout_summary: str
    stderr_summary: str
    passed: bool
    bridge_sources: list[str]


@dataclass
class TestDatasetInputs:
    dataset_root: Path
    dataset_name: str
    srs_text: str
    architecture_text: str
    uml_class_text: str
    uml_sequence_text: str
    sut_root: Path
    language: str


def prepare_run_layout(base_dir: Path, run_id: str) -> RunLayout:
    run_root = base_dir / run_id
    layout = RunLayout(
        run_id=run_id,
        run_root=run_root,
        inputs_dir=run_root / "inputs",
        requirements_dir=run_root / "requirements",
        architecture_dir=run_root / "architecture",
        coding_dir=run_root / "coding",
        ui_dir=run_root / "ui",
        test_dir=run_root / "test",
        logs_dir=run_root / "logs",
    )
    for directory in (
        layout.run_root,
        layout.inputs_dir,
        layout.requirements_dir,
        layout.architecture_dir,
        layout.coding_dir,
        layout.ui_dir,
        layout.test_dir,
        layout.logs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return layout


def read_optional_text(path: Path, *, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8")


def coerce_subprocess_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def resolve_python_bin(preferred_path: Path) -> Path:
    if preferred_path.exists():
        return preferred_path
    return Path(sys.executable)


def summarize_text(text: str, *, limit: int = 800) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def list_relative_files(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def build_ui_api_methods(api_spec_path: Path) -> dict[str, Any]:
    if not api_spec_path.exists():
        return {}
    payload = yaml.safe_load(api_spec_path.read_text(encoding="utf-8")) or {}
    paths = payload.get("paths") or {}
    grouped: dict[str, dict[str, Any]] = {}
    for route, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        segments = [segment for segment in route.split("/") if segment and not segment.startswith("{")]
        service_key = (segments[1] if len(segments) > 1 and segments[0] == "api" else segments[0] if segments else "default")
        service_name = service_key.replace("-", "_")
        service = grouped.setdefault(service_name, {"methods": {}})
        for verb, details in methods.items():
            if not isinstance(details, dict):
                continue
            operation_id = details.get("operationId") or f"{verb}_{service_name}"
            service["methods"][operation_id] = {
                "http": {
                    "verb": str(verb).upper(),
                    "route": route,
                },
                "summary": details.get("summary") or "",
            }
    return grouped


def build_architecture_requirements_markdown(
    *,
    project_name: str,
    business_scope: str,
    functional_requirements: str,
    non_functional_requirements: str,
    use_case_text: str,
    dialog_map_text: str,
) -> str:
    sections = [
        f"# {project_name} Requirements Draft",
        "",
        "## Business Scope",
        business_scope or "(missing)",
        "",
        "## Functional Requirements",
        functional_requirements or "(missing)",
        "",
        "## Non-Functional Requirements",
        non_functional_requirements or "(missing)",
        "",
        "## Use Cases",
        use_case_text or "(missing)",
        "",
        "## Dialog Map",
        dialog_map_text or "(missing)",
        "",
    ]
    return "\n".join(sections)


def build_coding_project_manifest(project_prompt: str, selected_modules: list[dict[str, Any]]) -> dict[str, Any]:
    backend_manifest: dict[str, Any] = {
        "run.py": {
            "priority": 12,
            "description": "Bootstrap the generated FastAPI backend application.",
            "source_ref": ["project.summary", "artifacts.architecture"],
            "depends_on": ["app/__init__.py"],
        },
        "app": {
            "__init__.py": {
                "priority": 11,
                "description": "Create the FastAPI application and register routers.",
                "source_ref": ["project.summary", "artifacts.architecture"],
                "depends_on": ["app/api/__init__.py", "app/config.py"],
            },
            "config.py": {
                "priority": 1,
                "description": "Runtime configuration defaults.",
                "source_ref": ["project.summary"],
                "depends_on": [],
            },
            "api": {
                "__init__.py": {
                    "priority": 10,
                    "description": "Register generated routers.",
                    "source_ref": ["project.summary", "artifacts.api_spec"],
                    "depends_on": [],
                },
            },
            "services": {
                "__init__.py": {
                    "priority": 2,
                    "description": "Expose service implementations.",
                    "source_ref": ["project.summary"],
                    "depends_on": [],
                },
            },
            "repositories": {
                "__init__.py": {
                    "priority": 2,
                    "description": "Expose repository implementations.",
                    "source_ref": ["project.summary"],
                    "depends_on": [],
                },
            },
            "models": {
                "__init__.py": {
                    "priority": 2,
                    "description": "Aggregate model definitions.",
                    "source_ref": ["project.summary"],
                    "depends_on": [],
                },
            },
        },
    }
    for index, module in enumerate(selected_modules or [{"id": "gomoku", "labelEn": "Gomoku Game"}], start=1):
        raw_id = str(module.get("id") or module.get("labelEn") or f"module-{index}")
        label = str(module.get("labelEn") or module.get("label") or raw_id)
        stem = raw_id.replace("-", "_")
        backend_manifest["app"]["api"][f"{stem}_api.py"] = {
            "priority": 20 + index,
            "description": f"API endpoints for {label}.",
            "source_ref": [f"backend.modules.{stem}"],
            "depends_on": [f"app/services/{stem}_service.py"],
        }
        backend_manifest["app"]["services"][f"{stem}_service.py"] = {
            "priority": 15 + index,
            "description": f"Business logic for {label}.",
            "source_ref": [f"backend.modules.{stem}"],
            "depends_on": [f"app/repositories/{stem}_repository.py", f"app/models/{stem}.py"],
        }
        backend_manifest["app"]["repositories"][f"{stem}_repository.py"] = {
            "priority": 8 + index,
            "description": f"Repository helpers for {label}.",
            "source_ref": [f"backend.modules.{stem}"],
            "depends_on": [f"app/models/{stem}.py"],
        }
        backend_manifest["app"]["models"][f"{stem}.py"] = {
            "priority": 4 + index,
            "description": f"Models for {label}.",
            "source_ref": [f"backend.modules.{stem}"],
            "depends_on": [],
        }
    return {"project": {"summary": project_prompt}, "backend": backend_manifest}


def build_coding_semantic_model(project_prompt: str, selected_modules: list[dict[str, Any]], artifacts: dict[str, str]) -> dict[str, Any]:
    modules: dict[str, Any] = {}
    for index, module in enumerate(selected_modules or [{"id": "gomoku", "labelEn": "Gomoku Game"}], start=1):
        raw_id = str(module.get("id") or module.get("labelEn") or f"module-{index}")
        label = str(module.get("labelEn") or module.get("label") or raw_id)
        key = raw_id.replace("-", "_")
        modules[key] = {
            "name": label,
            "summary": f"{label} capability derived from {project_prompt}",
            "operations": [
                {"verb": "GET", "route": f"/api/{raw_id}", "summary": f"Fetch {label} state"},
                {"verb": "POST", "route": f"/api/{raw_id}", "summary": f"Update {label} state"},
            ],
            "routes": [f"/api/{raw_id}"],
        }
    return {
        "project": {
            "summary": project_prompt,
            "selected_modules": [module.get("labelEn") or module.get("label") or module.get("id") for module in selected_modules],
        },
        "artifacts": artifacts,
        "backend": {"modules": modules},
    }


def write_test_dataset(inputs: TestDatasetInputs) -> Path:
    dataset_dir = inputs.dataset_root / inputs.dataset_name
    dataset_dir.mkdir(parents=True, exist_ok=True)
    file_map = {
        "srs.md": inputs.srs_text,
        "architecture_design.md": inputs.architecture_text,
        "uml_class.md": inputs.uml_class_text,
        "uml_sequence.md": inputs.uml_sequence_text,
    }
    for name, content in file_map.items():
        (dataset_dir / name).write_text(content, encoding="utf-8")

    config_payload = {
        "srs": "srs.md",
        "uml_class": "uml_class.md",
        "uml_sequence": "uml_sequence.md",
        "architecture_design": "architecture_design.md",
        "sut_root": str(inputs.sut_root),
        "language": inputs.language,
        "conda_env": "",
    }
    (dataset_dir / "config.json").write_text(
        json.dumps(config_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return dataset_dir


def append_debug_record(record_path: Path, run_id: str, results: list[StageResult]) -> None:
    record_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"## Run {run_id}",
        "",
    ]
    for result in results:
        lines.extend(
            [
                f"### {result.name}",
                f"- Status: {'PASS' if result.passed else 'FAIL'}",
                f"- Command: `{' '.join(result.command)}`",
                f"- CWD: `{result.cwd}`",
                f"- Env Keys: {', '.join(result.env_keys) or '(none)'}",
                f"- Inputs: {', '.join(result.input_files) or '(none)'}",
                f"- Outputs: {', '.join(result.output_files) or '(none)'}",
                f"- Exit Code: `{result.exit_code}`",
                f"- Duration: `{result.duration_seconds:.2f}s`",
                f"- Stdout Summary: {result.stdout_summary or '(empty)'}",
                f"- Stderr Summary: {result.stderr_summary or '(empty)'}",
                f"- Bridge Sources: {', '.join(result.bridge_sources) or '(none)'}",
                "",
            ]
        )
    with record_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def write_summary(summary_path: Path, run_id: str, layout: RunLayout, results: list[StageResult]) -> None:
    payload = {
        "runId": run_id,
        "runRoot": str(layout.run_root),
        "results": [asdict(result) for result in results],
    }
    summary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_command(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
    input_files: list[Path],
    output_root: Path,
    bridge_sources: list[str],
    timeout_seconds: float | None = None,
) -> StageResult:
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - start
        stdout_text = coerce_subprocess_output(exc.stdout)
        stderr_text = coerce_subprocess_output(exc.stderr)
        log_path.write_text(
            "\n".join(
                [
                    f"COMMAND: {' '.join(command)}",
                    f"CWD: {cwd}",
                    f"TIMEOUT: {timeout_seconds}",
                    "",
                    "STDOUT",
                    stdout_text,
                    "",
                    "STDERR",
                    stderr_text,
                ]
            ),
            encoding="utf-8",
        )
        return StageResult(
            name=name,
            command=command,
            cwd=str(cwd),
            env_keys=sorted(key for key in env if key.startswith("OPENAI_") or key.startswith("ISOFTDEVAGENTS_") or key.startswith("CODEAGENT_") or key.startswith("TEST_AGENT_")),
            input_files=[str(path) for path in input_files],
            output_files=[str(output_root / path) for path in list_relative_files(output_root)],
            exit_code=124,
            duration_seconds=duration,
            stdout_summary=summarize_text(stdout_text),
            stderr_summary=summarize_text(stderr_text),
            passed=False,
            bridge_sources=bridge_sources,
        )
    duration = time.perf_counter() - start
    log_path.write_text(
        "\n".join(
            [
                f"COMMAND: {' '.join(command)}",
                f"CWD: {cwd}",
                "",
                "STDOUT",
                completed.stdout,
                "",
                "STDERR",
                completed.stderr,
            ]
        ),
        encoding="utf-8",
    )
    return StageResult(
        name=name,
        command=command,
        cwd=str(cwd),
        env_keys=sorted(key for key in env if key.startswith("OPENAI_") or key.startswith("ISOFTDEVAGENTS_") or key.startswith("CODEAGENT_") or key.startswith("TEST_AGENT_")),
        input_files=[str(path) for path in input_files],
        output_files=[str(output_root / path) for path in list_relative_files(output_root)],
        exit_code=completed.returncode,
        duration_seconds=duration,
        stdout_summary=summarize_text(completed.stdout),
        stderr_summary=summarize_text(completed.stderr),
        passed=completed.returncode == 0,
        bridge_sources=bridge_sources,
    )


def detect_architecture_output_dir(output_root: Path, project_name: str) -> Path:
    candidates = sorted(output_root.glob(f"*_{project_name}"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No Architecture Agent output directory found under {output_root}")
    return candidates[0]


def detect_generated_code_root(coding_root: Path) -> Path:
    for candidate in (coding_root / "generated", coding_root / "output", coding_root):
        if candidate.exists():
            return candidate
    return coding_root


def default_sequence_diagram() -> str:
    return "\n".join(
        [
            "# Gomoku Sequence",
            "",
            "1. User opens the game page.",
            "2. System renders a 15x15 board and marks black as the current player.",
            "3. User clicks an empty cell to place a stone.",
            "4. System updates board state, checks five-in-a-row, and either switches turns or announces a winner.",
            "5. User can restart the game to reset the board.",
        ]
    )


def copy_requirement_input(source_path: Path, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the five-agent Gomoku smoke workflow.")
    parser.add_argument("--requirements-file", type=Path, default=DEFAULT_REQUIREMENTS_FILE)
    parser.add_argument("--project-name", default="五子棋 Web 游戏")
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--base-dir", type=Path, default=REPO_ROOT / "var" / "gomoku-five-agent")
    parser.add_argument("--debug-record", type=Path, default=DEFAULT_DEBUG_RECORD)
    parser.add_argument(
        "--requirements-full-timeout",
        type=float,
        default=DEFAULT_REQUIREMENTS_FULL_TIMEOUT_SECONDS,
        help="Timeout in seconds for the Requirements Agent full stage.",
    )
    parser.add_argument(
        "--requirements-drafts-timeout",
        type=float,
        default=DEFAULT_REQUIREMENTS_DRAFTS_TIMEOUT_SECONDS,
        help="Timeout in seconds for the Requirements Agent drafts fallback stage.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    layout = prepare_run_layout(args.base_dir, args.run_id)
    input_copy = layout.inputs_dir / args.requirements_file.name
    copy_requirement_input(args.requirements_file, input_copy)

    env_base = os.environ.copy()
    env_base.setdefault("PYTHONUTF8", "1")
    env_base.setdefault("ISOFTDEVAGENTS_REAGENT_NONINTERACTIVE", "1")
    env_base.setdefault("ISOFTDEVAGENTS_REAGENT_ENABLE_WEB_TOOLS", "0")

    results: list[StageResult] = []

    reagent_python = resolve_python_bin(REPO_ROOT / "agent" / "Requirements Agent" / "reagent" / ".venv" / "bin" / "python")
    architecture_python = resolve_python_bin(REPO_ROOT / "agent" / "Architecture Agent" / ".venv" / "bin" / "python")
    coding_python = resolve_python_bin(REPO_ROOT / "agent" / "Coding Agent" / ".venv" / "bin" / "python")
    test_python = resolve_python_bin(REPO_ROOT / "agent" / "TestAgent" / ".venv" / "bin" / "python")

    requirements_env = env_base | {
        "REAGENT_STORE_PATH": str(layout.requirements_dir / "analysis"),
    }
    analysis = run_command(
        name="requirements-analysis",
        command=[
            str(reagent_python),
            "src/reagent/main.py",
            "--project_name",
            args.project_name,
            "--description_file",
            str(input_copy),
            "--mode",
            "analysis",
        ],
        cwd=REPO_ROOT / "agent" / "Requirements Agent" / "reagent",
        env=requirements_env,
        log_path=layout.logs_dir / "requirements-analysis.log",
        input_files=[input_copy],
        output_root=layout.requirements_dir / "analysis",
        bridge_sources=["feature_tree.md -> requirements/full"],
    )
    results.append(analysis)
    if not analysis.passed:
        append_debug_record(args.debug_record, args.run_id, results)
        write_summary(layout.run_root / "summary.json", args.run_id, layout, results)
        return 1

    requirements_env = env_base | {
        "REAGENT_STORE_PATH": str(layout.requirements_dir / "full"),
    }
    full = run_command(
        name="requirements-full",
        command=[
            str(reagent_python),
            "src/reagent/main.py",
            "--project_name",
            args.project_name,
            "--description_file",
            str(input_copy),
            "--mode",
            "full",
        ],
        cwd=REPO_ROOT / "agent" / "Requirements Agent" / "reagent",
        env=requirements_env,
        log_path=layout.logs_dir / "requirements-full.log",
        input_files=[input_copy, layout.requirements_dir / "analysis" / "feature_tree.md"],
        output_root=layout.requirements_dir / "full",
        bridge_sources=["SRS.md -> architecture", "use_case.md/dialog_map.md -> ui"],
        timeout_seconds=args.requirements_full_timeout,
    )
    results.append(full)
    requirements_output_dir = layout.requirements_dir / "full"
    if not full.passed:
        drafts = run_command(
            name="requirements-drafts",
            command=[
                str(reagent_python),
                "src/reagent/main.py",
                "--project_name",
                args.project_name,
                "--description_file",
                str(input_copy),
                "--mode",
                "drafts",
            ],
            cwd=REPO_ROOT / "agent" / "Requirements Agent" / "reagent",
            env=requirements_env | {"REAGENT_STORE_PATH": str(layout.requirements_dir / "drafts")},
            log_path=layout.logs_dir / "requirements-drafts.log",
            input_files=[input_copy, layout.requirements_dir / "analysis" / "feature_tree.md"],
            output_root=layout.requirements_dir / "drafts",
            bridge_sources=["draft outputs -> architecture/ui/coding"],
            timeout_seconds=args.requirements_drafts_timeout,
        )
        results.append(drafts)
        if not drafts.passed:
            append_debug_record(args.debug_record, args.run_id, results)
            write_summary(layout.run_root / "summary.json", args.run_id, layout, results)
            return 1
        requirements_output_dir = layout.requirements_dir / "drafts"

    srs_path = requirements_output_dir / "SRS.md"
    if not srs_path.exists():
        srs_path = layout.architecture_dir / "requirements_for_architecture.md"
        srs_path.write_text(
            build_architecture_requirements_markdown(
                project_name=args.project_name,
                business_scope=read_optional_text(requirements_output_dir / "business_scope.md"),
                functional_requirements=read_optional_text(requirements_output_dir / "functional_requirements.md"),
                non_functional_requirements=read_optional_text(requirements_output_dir / "non_functional_requirements.md"),
                use_case_text=read_optional_text(requirements_output_dir / "use_case.md"),
                dialog_map_text=read_optional_text(requirements_output_dir / "dialog_map.md"),
            ),
            encoding="utf-8",
        )
    architecture = run_command(
        name="architecture",
        command=[
            str(architecture_python),
            "src/arch_agent/main.py",
            str(srs_path),
            args.project_name,
        ],
        cwd=REPO_ROOT / "agent" / "Architecture Agent",
        env=env_base,
        log_path=layout.logs_dir / "architecture.log",
        input_files=[srs_path],
        output_root=REPO_ROOT / "agent" / "Architecture Agent" / "data" / "output",
        bridge_sources=["class_design_raw.md -> test dataset", "architecture draft -> coding"],
    )
    results.append(architecture)
    if not architecture.passed:
        append_debug_record(args.debug_record, args.run_id, results)
        write_summary(layout.run_root / "summary.json", args.run_id, layout, results)
        return 1

    architecture_output_dir = detect_architecture_output_dir(
        REPO_ROOT / "agent" / "Architecture Agent" / "data" / "output",
        args.project_name,
    )
    mirrored_architecture_dir = layout.architecture_dir / architecture_output_dir.name
    if mirrored_architecture_dir.exists():
        shutil.rmtree(mirrored_architecture_dir)
    shutil.copytree(architecture_output_dir, mirrored_architecture_dir)

    selected_modules = [{"id": "gomoku-game", "labelEn": "Gomoku Game"}]
    coding_manifest = build_coding_project_manifest(args.project_name, selected_modules)
    coding_semantic = build_coding_semantic_model(
        args.project_name,
        selected_modules,
        artifacts={
            "prd": read_optional_text(layout.requirements_dir / "full" / "functional_requirements.md"),
            "architecture": read_optional_text(mirrored_architecture_dir / "class_design_raw.md"),
            "api_spec": read_optional_text(layout.coding_dir / "api_spec.yaml"),
        },
    )
    manifest_path = layout.coding_dir / "project_manifest.json"
    semantic_path = layout.coding_dir / "semantic_model.json"
    manifest_path.write_text(json.dumps(coding_manifest["backend"], indent=2, ensure_ascii=False), encoding="utf-8")
    semantic_path.write_text(json.dumps(coding_semantic, indent=2, ensure_ascii=False), encoding="utf-8")

    openapi_payload = {
        "openapi": "3.0.0",
        "info": {"title": "Gomoku API", "version": "1.0.0"},
        "paths": {},
    }
    api_spec_path = layout.coding_dir / "api_spec.yaml"
    api_spec_path.write_text(yaml.safe_dump(openapi_payload, sort_keys=False, allow_unicode=True), encoding="utf-8")

    coding = run_command(
        name="coding",
        command=[
            str(coding_python),
            "main.py",
            "--mode",
            "full",
            "--srs",
            str(srs_path),
            "--architecture",
            str(mirrored_architecture_dir / "class_design_raw.md"),
            "--project-manifest",
            str(manifest_path),
            "--semantic-model",
            str(semantic_path),
            "--output-root",
            str(layout.coding_dir / "generated"),
        ],
        cwd=REPO_ROOT / "agent" / "Coding Agent" / "agent",
        env=env_base,
        log_path=layout.logs_dir / "coding.log",
        input_files=[srs_path, mirrored_architecture_dir / "class_design_raw.md", manifest_path, semantic_path],
        output_root=layout.coding_dir / "generated",
        bridge_sources=["generated code -> test dataset", "api spec/use case/dialog map -> ui"],
    )
    results.append(coding)
    if not coding.passed:
        append_debug_record(args.debug_record, args.run_id, results)
        write_summary(layout.run_root / "summary.json", args.run_id, layout, results)
        return 1

    ui_api_methods = build_ui_api_methods(api_spec_path)
    ui_api_path = layout.ui_dir / "api_methods_slim.json"
    ui_api_path.write_text(json.dumps(ui_api_methods, indent=2, ensure_ascii=False), encoding="utf-8")
    page_description_path = layout.ui_dir / "page_descriptions.json"
    dar_path = layout.ui_dir / "dar_model.json"
    ui_output_dir = layout.ui_dir / "app"

    use_case_path = requirements_output_dir / "use_case.md"
    dialog_map_path = requirements_output_dir / "dialog_map.md"

    page_description = run_command(
        name="ui-page-description",
        command=[
            sys.executable,
            "page_description.py",
            "--project-name",
            args.project_name,
            "--dialog-map-file",
            str(dialog_map_path),
            "--api-methods-file",
            str(ui_api_path),
            "--output-file",
            str(page_description_path),
        ],
        cwd=REPO_ROOT / "agent" / "UI Agent",
        env=env_base,
        log_path=layout.logs_dir / "ui-page-description.log",
        input_files=[dialog_map_path, ui_api_path],
        output_root=layout.ui_dir,
        bridge_sources=["page_descriptions.json -> dar/ui"],
    )
    results.append(page_description)
    if not page_description.passed:
        append_debug_record(args.debug_record, args.run_id, results)
        write_summary(layout.run_root / "summary.json", args.run_id, layout, results)
        return 1

    dar = run_command(
        name="ui-dar",
        command=[
            sys.executable,
            "dar_model.py",
            "--page-description-file",
            str(page_description_path),
            "--use-case-file",
            str(use_case_path),
            "--output-file",
            str(dar_path),
        ],
        cwd=REPO_ROOT / "agent" / "UI Agent",
        env=env_base,
        log_path=layout.logs_dir / "ui-dar.log",
        input_files=[page_description_path, use_case_path],
        output_root=layout.ui_dir,
        bridge_sources=["dar_model.json -> ui final"],
    )
    results.append(dar)
    if not dar.passed:
        append_debug_record(args.debug_record, args.run_id, results)
        write_summary(layout.run_root / "summary.json", args.run_id, layout, results)
        return 1

    ui = run_command(
        name="ui-design",
        command=[
            sys.executable,
            "ui_design.py",
            "--project-name",
            args.project_name,
            "--page-description-file",
            str(page_description_path),
            "--api-methods-file",
            str(ui_api_path),
            "--output-dir",
            str(ui_output_dir),
        ],
        cwd=REPO_ROOT / "agent" / "UI Agent",
        env=env_base,
        log_path=layout.logs_dir / "ui-design.log",
        input_files=[page_description_path, ui_api_path],
        output_root=ui_output_dir,
        bridge_sources=["ui app -> smoke artifact set"],
    )
    results.append(ui)
    if not ui.passed:
        append_debug_record(args.debug_record, args.run_id, results)
        write_summary(layout.run_root / "summary.json", args.run_id, layout, results)
        return 1

    test_dataset_dir = layout.test_dir / "dataset"
    generated_code_root = detect_generated_code_root(layout.coding_dir / "generated")
    write_test_dataset(
        TestDatasetInputs(
            dataset_root=test_dataset_dir,
            dataset_name="gomoku",
            srs_text=read_optional_text(srs_path, default="# SRS\n"),
            architecture_text=read_optional_text(mirrored_architecture_dir / "class_design_raw.md", default="# Architecture\n"),
            uml_class_text=read_optional_text(mirrored_architecture_dir / "class_design_raw.md", default="# UML Class\n"),
            uml_sequence_text=default_sequence_diagram(),
            sut_root=generated_code_root,
            language="python",
        )
    )

    test_stage = run_command(
        name="test-agent",
        command=[
            str(test_python),
            "main.py",
            "--dataset-root",
            str(test_dataset_dir),
            "--dataset-name",
            "gomoku",
            "--output-root",
            str(layout.test_dir / "output"),
            "--memory-root",
            str(layout.test_dir / "memory"),
        ],
        cwd=REPO_ROOT / "agent" / "TestAgent",
        env=env_base,
        log_path=layout.logs_dir / "test-agent.log",
        input_files=[
            srs_path,
            mirrored_architecture_dir / "class_design_raw.md",
            generated_code_root,
        ],
        output_root=layout.test_dir,
        bridge_sources=[],
    )
    results.append(test_stage)

    append_debug_record(args.debug_record, args.run_id, results)
    write_summary(layout.run_root / "summary.json", args.run_id, layout, results)
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
