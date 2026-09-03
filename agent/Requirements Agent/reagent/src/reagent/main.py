#!/usr/bin/env python

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from runtime_bridge import RequirementSpecificationrun, run_cli


def main(argv: list[str] | None = None) -> dict[str, Any]:
    """
    保留旧的命令行入口。

    这里不再直接拼运行流程，只负责把命令行请求转交给新的函数桥梁。
    """

    return run_cli(argv)


if __name__ == "__main__":
    main()
        
    
