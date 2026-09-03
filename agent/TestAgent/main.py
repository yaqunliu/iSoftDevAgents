#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

CURRENT = Path(__file__).resolve()
ROOT_DIR = CURRENT.parents[2]
BASE_DIR = CURRENT.parent

load_dotenv(ROOT_DIR / ".env")

from agent import TestAgentApp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TestAgent against a dataset.")
    parser.add_argument("--dataset-name", default="hone")
    parser.add_argument("--dataset-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=BASE_DIR / "output")
    parser.add_argument("--memory-root", type=Path, default=BASE_DIR / "memory")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    os.makedirs(args.output_root, exist_ok=True)
    app = TestAgentApp(
        dataset_name=args.dataset_name,
        dataset_root=args.dataset_root,
        output_root=args.output_root,
        memory_root=args.memory_root,
    )
    app.run()
