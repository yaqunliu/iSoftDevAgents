from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from app import CodeAgentApp
from runtime_support import load_runtime_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Coding Agent with runtime-supplied inputs.")
    parser.add_argument("--mode", default="full", choices=["full"])
    parser.add_argument("--config-json", type=Path, default=None)
    parser.add_argument("--srs", type=Path, default=None)
    parser.add_argument("--architecture", type=Path, default=None)
    parser.add_argument("--project-manifest", type=Path, default=None)
    parser.add_argument("--semantic-model", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    return parser.parse_args()


def build_runtime_paths(args: argparse.Namespace) -> dict[str, str]:
    paths = load_runtime_config(args.config_json)
    overrides = {}
    if args.srs is not None:
        overrides["srs"] = str(args.srs)
    if args.project_manifest is not None:
        overrides["project"] = str(args.project_manifest)
    if args.semantic_model is not None:
        overrides["semantic_model"] = str(args.semantic_model)
        overrides["memory"] = str(args.semantic_model)
    if args.output_root is not None:
        overrides["software"] = str(args.output_root)
    if args.architecture is not None:
        overrides["av"] = str(args.architecture)
    paths.update(overrides)
    return paths


def main() -> None:
    args = parse_args()
    runtime_paths = build_runtime_paths(args)
    app = CodeAgentApp(paths=runtime_paths)
    app.run(mode=args.mode)


if __name__ == "__main__":
    main()
