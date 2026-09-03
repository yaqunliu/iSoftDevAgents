from __future__ import annotations

import os
from pathlib import Path


def _normalize_env_value(value: str) -> str:
    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        return normalized[1:-1]
    return normalized


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def database_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql://isoftdev:isoftdev@localhost:5432/isoftdev")


def delete_local_files_after_persist_enabled() -> bool:
    """
    接口注释：
    判断当前是否启用了“成功后删除本地文件残留”模式。

    教学注释：
    这个开关只影响“已经安全进入数据库”的成功路径。
    失败排查需要的调试包不在这里一刀切删除。
    """

    return env_flag("ISOFTDEVAGENTS_DELETE_LOCAL_FILES_AFTER_PERSIST", default=False)


def load_local_env_files(root: Path | None = None) -> None:
    base_root = root or Path(__file__).resolve().parents[1]
    merged: dict[str, str] = {}
    for file_name in (".env", ".env.local"):
        file_path = base_root / file_name
        if not file_path.exists():
            continue
        for raw_line in file_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            merged[key.strip()] = _normalize_env_value(value)
    for key, value in merged.items():
        os.environ.setdefault(key, value)
