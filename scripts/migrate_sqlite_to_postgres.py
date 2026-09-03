#!/usr/bin/env python3
"""
SQLite → PostgreSQL 数据迁移脚本。

用法：
    python scripts/migrate_sqlite_to_postgres.py \
        --sqlite agent/platform/data/app.db \
        --pg "postgresql://isoftdev:isoftdev@localhost:5432/isoftdev"

设计注释：
    逐表读取 SQLite 数据，批量写入 PostgreSQL。
    类型转换：
      - TEXT 时间戳 → Python datetime → PostgreSQL TIMESTAMPTZ
      - INTEGER 0/1 → Python bool → PostgreSQL BOOLEAN
      - TEXT JSON → Python dict → PostgreSQL JSONB
      - BLOB → bytes → PostgreSQL BYTEA
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def _parse_json(value: str | None):
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _parse_bool(value) -> bool | None:
    if value is None:
        return None
    return bool(value)


# 表迁移顺序（考虑外键依赖）
TABLES = [
    "projects",
    "temp_users",
    "auth_tokens",
    "uploaded_files",
    "uploaded_file_contents",
    "messages",
    "tasks",
    "task_statistics",
    "step_records",
    "generation_tasks",
    "artifacts",
    "code_files",
    "agent_artifacts",
    "code_file_locks",
    "project_file_drafts",
    "project_modules",
    "project_versions",
]

# 每张表哪些列需要类型转换
# 格式: { "column_name": "converter" }
# converter: "ts" = timestamp, "json" = json, "bool" = boolean, "blob" = keep bytes
COLUMN_CONVERTERS: dict[str, dict[str, str]] = {
    "projects": {
        "created_at": "ts", "updated_at": "ts",
    },
    "temp_users": {
        "created_at": "ts", "updated_at": "ts",
    },
    "auth_tokens": {
        "created_at": "ts", "revoked_at": "ts",
    },
    "uploaded_files": {
        "is_temporary": "bool",
        "created_at": "ts", "analysis_updated_at": "ts",
    },
    "uploaded_file_contents": {
        "created_at": "ts",
        # content_blob 是 BLOB，asyncpg 直接接受 bytes
    },
    "messages": {
        "metadata": "json",
        "created_at": "ts",
    },
    "tasks": {
        "input_data": "json", "output_data": "json",
        "created_at": "ts", "started_at": "ts", "completed_at": "ts",
    },
    "task_statistics": {
        "created_at": "ts", "started_at": "ts", "completed_at": "ts",
    },
    "step_records": {
        "metadata": "json",
        "created_at": "ts",
    },
    "generation_tasks": {
        "created_at": "ts", "started_at": "ts", "completed_at": "ts",
    },
    "artifacts": {
        "metadata": "json",
        "created_at": "ts",
    },
    "code_files": {
        "created_at": "ts",
    },
    "agent_artifacts": {
        "is_primary_source": "bool",
        "mapped_artifact_types": "json",
        "created_at": "ts",
    },
    "code_file_locks": {
        "locked_at": "ts", "updated_at": "ts",
    },
    "project_file_drafts": {
        "created_at": "ts", "updated_at": "ts",
    },
    "project_modules": {
        "is_selected": "bool",
        "created_at": "ts",
    },
    "project_versions": {
        "changes": "json", "state_manifest": "json", "modules_snapshot": "json",
        "is_current": "bool",
        "created_at": "ts",
    },
}


def _convert_value(value, converter: str):
    if converter == "ts":
        return _parse_timestamp(value)
    if converter == "json":
        return _parse_json(value)
    if converter == "bool":
        return _parse_bool(value)
    return value


async def migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg_pool: asyncpg.Pool,
    table_name: str,
) -> int:
    sqlite_conn.row_factory = sqlite3.Row
    rows = sqlite_conn.execute(f"SELECT * FROM {table_name}").fetchall()
    if not rows:
        print(f"  {table_name}: 0 rows (empty)")
        return 0

    columns = rows[0].keys()
    converters = COLUMN_CONVERTERS.get(table_name, {})

    # 构建 INSERT 语句
    col_list = ", ".join(columns)
    param_list = ", ".join(f"${i+1}" for i in range(len(columns)))
    insert_sql = f"INSERT INTO {table_name} ({col_list}) VALUES ({param_list}) ON CONFLICT DO NOTHING"

    batch: list[tuple] = []
    for row in rows:
        values = []
        for col in columns:
            val = row[col]
            if col in converters:
                val = _convert_value(val, converters[col])
            values.append(val)
        batch.append(tuple(values))

    async with pg_pool.acquire() as conn:
        await conn.executemany(insert_sql, batch)

    print(f"  {table_name}: {len(batch)} rows migrated")
    return len(batch)


async def main(sqlite_path: str, pg_dsn: str) -> None:
    if not Path(sqlite_path).exists():
        print(f"Error: SQLite file not found: {sqlite_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Source: {sqlite_path}")
    print(f"Target: {pg_dsn}")
    print()

    sqlite_conn = sqlite3.connect(sqlite_path)
    pg_pool = await asyncpg.create_pool(pg_dsn, min_size=2, max_size=5)

    total = 0
    for table_name in TABLES:
        try:
            count = await migrate_table(sqlite_conn, pg_pool, table_name)
            total += count
        except Exception as exc:
            print(f"  {table_name}: FAILED - {exc}", file=sys.stderr)

    print(f"\nDone. Total rows migrated: {total}")
    sqlite_conn.close()
    await pg_pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate SQLite data to PostgreSQL")
    parser.add_argument("--sqlite", required=True, help="Path to SQLite database file")
    parser.add_argument("--pg", required=True, help="PostgreSQL DSN (e.g. postgresql://user:pass@host:5432/db)")
    args = parser.parse_args()
    asyncio.run(main(args.sqlite, args.pg))
