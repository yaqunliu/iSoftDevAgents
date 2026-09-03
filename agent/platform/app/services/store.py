from __future__ import annotations

import json
import math
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import asyncpg

from app.config import delete_local_files_after_persist_enabled
from app.schemas import (
    Artifact,
    AgentArtifactRecord,
    ArtifactType,
    AuthTokenRecord,
    CodeFile,
    CodeFileLock,
    GenerationTask,
    ListProjectsResponse,
    Message,
    ProjectFileDraft,
    ProjectModule,
    ProjectSummary,
    ProjectVersion,
    StepRecord,
    TaskState,
    TaskStatistics,
    TempUser,
    UploadedFile,
    new_id,
    utc_now,
)


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _timestamp(value=None) -> str:
    current = value or utc_now()
    return current.isoformat().replace("+00:00", "Z")


def _dt(value=None) -> datetime:
    """返回 datetime 对象，用于 asyncpg 的 TIMESTAMPTZ 参数。"""
    current = value or utc_now()
    if isinstance(current, datetime):
        if current.tzinfo is None:
            return current.replace(tzinfo=timezone.utc)
        return current
    # 如果是字符串，解析回 datetime
    text = str(current).replace("Z", "+00:00")
    return datetime.fromisoformat(text)


class AsyncPostgresStore:
    CODE_FILE_LOCK_TIMEOUT = timedelta(minutes=5)

    def __init__(self, uploads_dir: str | None = None) -> None:
        root = Path(__file__).resolve().parents[2]
        self.uploads_dir = Path(uploads_dir or root / "data" / "uploads")
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self._pool: asyncpg.Pool | None = None

    async def initialize(self, dsn: str) -> None:
        self._pool = await asyncpg.create_pool(dsn, min_size=10, max_size=50)
        await self._create_schema()

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    async def _execute(self, sql: str, *args) -> str:
        async with self._pool.acquire() as conn:
            return await conn.execute(sql, *args)

    async def _query_one(self, sql: str, *args) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(sql, *args)

    async def _query_all(self, sql: str, *args) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(sql, *args)

    async def _query_val(self, sql: str, *args):
        async with self._pool.acquire() as conn:
            return await conn.fetchval(sql, *args)

    async def _create_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    thumbnail_path TEXT,
                    current_version INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    user_id TEXT
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS uploaded_files (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    project_id TEXT,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    content_preview TEXT,
                    analysis_summary TEXT,
                    analysis_status TEXT,
                    analysis_error TEXT,
                    analysis_updated_at TIMESTAMPTZ,
                    thumbnail_path TEXT,
                    is_temporary BOOLEAN NOT NULL DEFAULT true,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS uploaded_file_contents (
                    upload_id TEXT PRIMARY KEY,
                    content_blob BYTEA NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    FOREIGN KEY(upload_id) REFERENCES uploaded_files(id) ON DELETE CASCADE
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS temp_users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    name TEXT NOT NULL,
                    avatar_url TEXT,
                    real_user_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL,
                    revoked_at TIMESTAMPTZ
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB,
                    parent_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS code_files (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_artifacts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    task_id TEXT,
                    agent TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    content TEXT,
                    is_primary_source BOOLEAN NOT NULL DEFAULT false,
                    mapped_artifact_types JSONB NOT NULL DEFAULT '[]',
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS code_file_locks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    locked_by TEXT NOT NULL,
                    locked_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_file_drafts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    content TEXT NOT NULL,
                    base_version INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    updated_by TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_modules (
                    row_id SERIAL PRIMARY KEY,
                    id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    name_en TEXT NOT NULL,
                    is_selected BOOLEAN NOT NULL DEFAULT true,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    task_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_versions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    version_kind TEXT NOT NULL DEFAULT 'generation',
                    source_version INTEGER,
                    restored_from_version INTEGER,
                    created_by_type TEXT NOT NULL DEFAULT 'system',
                    created_by TEXT,
                    description TEXT NOT NULL,
                    changes JSONB NOT NULL DEFAULT '[]',
                    state_manifest JSONB NOT NULL DEFAULT '{}',
                    modules_snapshot JSONB NOT NULL DEFAULT '[]',
                    is_current BOOLEAN NOT NULL DEFAULT true,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_statistics (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    task_id TEXT NOT NULL UNIQUE,
                    started_at TIMESTAMPTZ NOT NULL,
                    completed_at TIMESTAMPTZ,
                    total_duration REAL NOT NULL DEFAULT 0,
                    steps_count INTEGER NOT NULL DEFAULT 0,
                    items_read INTEGER NOT NULL DEFAULT 0,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_amount REAL NOT NULL DEFAULT 0,
                    model_used TEXT NOT NULL DEFAULT 'gpt-5.4',
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS step_records (
                    id TEXT PRIMARY KEY,
                    task_statistics_id TEXT NOT NULL,
                    step_name TEXT NOT NULL,
                    step_type TEXT NOT NULL,
                    duration REAL NOT NULL DEFAULT 0,
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    cost REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    metadata JSONB,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_data JSONB NOT NULL,
                    output_data JSONB,
                    error_message TEXT,
                    parent_task_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ
                )
                """
            )

            # Indexes
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_updated_at ON projects(updated_at DESC)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_project_created ON messages(project_id, created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_temp_users_email ON temp_users(email)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_created ON auth_tokens(user_id, created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_project_type_created ON artifacts(project_id, type, created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_code_files_project_version_path ON code_files(project_id, version, file_path)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_artifacts_project_version_agent ON agent_artifacts(project_id, version, agent, created_at)")
            await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_code_file_locks_project_path ON code_file_locks(project_id, file_path)")
            await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_project_file_drafts_project_path ON project_file_drafts(project_id, file_path)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_project_file_drafts_project_updated ON project_file_drafts(project_id, updated_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_modules_project_created ON project_modules(project_id, created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_generation_tasks_project_created ON generation_tasks(project_id, created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_versions_project_created ON project_versions(project_id, created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_steps_stats_created ON step_records(task_statistics_id, created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project_created ON tasks(project_id, created_at)")
            await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_artifacts_project_version_type ON artifacts(project_id, version, type)")
            await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_artifacts_project_version_agent_file ON agent_artifacts(project_id, version, agent, file_name)")

    def _row_to_project(self, row: asyncpg.Record) -> ProjectSummary:
        return ProjectSummary.model_validate(
            {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "status": row["status"],
                "thumbnail": row["thumbnail_path"],
                "currentVersion": row["current_version"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
                "userId": row["user_id"],
            }
        )

    def _row_to_upload(self, row: asyncpg.Record) -> UploadedFile:
        return UploadedFile.model_validate(
            {
                "id": row["id"],
                "userId": row["user_id"],
                "projectId": row["project_id"],
                "fileName": row["file_name"],
                "filePath": row["file_path"],
                "fileType": row["file_type"],
                "fileSize": row["file_size"],
                "contentPreview": row["content_preview"],
                "thumbnailUrl": row["thumbnail_path"],
                "isTemporary": bool(row["is_temporary"]),
                "createdAt": row["created_at"],
            }
        )

    def _row_to_message(self, row: asyncpg.Record) -> Message:
        return Message.model_validate(
            {
                "id": row["id"],
                "projectId": row["project_id"],
                "role": row["role"],
                "type": row["type"],
                "content": row["content"],
                "metadata": _json_loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
                "parentId": row["parent_id"],
                "createdAt": row["created_at"],
            }
        )

    def _upload_disk_path(self, file_path: str) -> Path:
        # 设计注释：
        # 对外 `filePath` 继续保持 `/uploads/...` 这种虚拟路径，
        # 真正落盘位置统一收口到 store 自己的 uploads 目录里，避免把磁盘绝对路径暴露给前端。
        normalized_name = Path(str(file_path or "").lstrip("/")).name
        return self.uploads_dir / normalized_name

    def _delete_project_local_file(self, file_path: str | None) -> None:
        """
        接口注释：
        删除项目关联的本地文件，比如上传原件、缩略图或者项目缩略图。

        教学注释：
        这里做成"尽力删除"而不是"强制存在"。
        因为项目删除的核心目标是把项目状态清干净，
        某个本地文件如果早就没了，不应该导致整个删除接口失败。
        """

        normalized_path = str(file_path or "").strip()
        if not normalized_path:
            return

        candidate_path: Path
        if normalized_path.startswith("/uploads/"):
            candidate_path = self._upload_disk_path(normalized_path)
        else:
            candidate_path = Path(normalized_path)
            if not candidate_path.is_absolute():
                candidate_path = self.uploads_dir.parent / normalized_path.lstrip("/")

        try:
            candidate_path.unlink(missing_ok=True)
        except IsADirectoryError:
            return

    def _row_to_temp_user(self, row: asyncpg.Record) -> TempUser:
        return TempUser.model_validate(
            {
                "id": row["id"],
                "email": row["email"],
                "passwordHash": row["password_hash"],
                "name": row["name"],
                "avatarUrl": row["avatar_url"],
                "realUserId": row["real_user_id"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
        )

    def _row_to_auth_token(self, row: asyncpg.Record) -> AuthTokenRecord:
        return AuthTokenRecord.model_validate(
            {
                "id": row["id"],
                "userId": row["user_id"],
                "tokenHash": row["token_hash"],
                "createdAt": row["created_at"],
                "revokedAt": row["revoked_at"],
            }
        )

    def _row_to_code_file(self, row: asyncpg.Record) -> CodeFile:
        return CodeFile.model_validate(
            {
                "id": row["id"],
                "projectId": row["project_id"],
                "version": row["version"],
                "filePath": row["file_path"],
                "content": row["content"],
                "createdAt": row["created_at"],
            }
        )

    def _row_to_agent_artifact(self, row: asyncpg.Record) -> AgentArtifactRecord:
        return AgentArtifactRecord.model_validate(
            {
                "id": row["id"],
                "projectId": row["project_id"],
                "version": row["version"],
                "taskId": row["task_id"],
                "agent": row["agent"],
                "fileName": row["file_name"],
                "fileType": row["file_type"],
                "contentType": row["content_type"],
                "content": row["content"],
                "isPrimarySource": bool(row["is_primary_source"]),
                "mappedArtifactTypes": _json_loads(row["mapped_artifact_types"]) if isinstance(row["mapped_artifact_types"], str) else (row["mapped_artifact_types"] or []),
                "createdAt": row["created_at"],
            }
        )

    def _row_to_project_file_draft(self, row: asyncpg.Record) -> ProjectFileDraft:
        return ProjectFileDraft.model_validate(
            {
                "id": row["id"],
                "projectId": row["project_id"],
                "filePath": row["file_path"],
                "content": row["content"],
                "baseVersion": row["base_version"],
                "stage": row["stage"],
                "sourceType": row["source_type"],
                "updatedBy": row["updated_by"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
        )

    def _row_to_task(self, row: asyncpg.Record) -> TaskState:
        output_data = _json_loads(row["output_data"]) if isinstance(row["output_data"], str) else row["output_data"]
        input_data = _json_loads(row["input_data"]) if isinstance(row["input_data"], str) else row["input_data"]
        return TaskState.model_validate(
            {
                "id": row["id"],
                "projectId": row["project_id"],
                "taskType": row["task_type"],
                "status": row["status"],
                "inputData": input_data or {},
                "outputData": output_data,
                "errorType": output_data.get("errorType") if isinstance(output_data, dict) else None,
                "errorMessage": row["error_message"],
                "parentTaskId": row["parent_task_id"],
                "createdAt": row["created_at"],
                "startedAt": row["started_at"],
                "completedAt": row["completed_at"],
            }
        )

    def _row_to_code_file_lock(self, row: asyncpg.Record) -> CodeFileLock:
        return CodeFileLock.model_validate(
            {
                "id": row["id"],
                "projectId": row["project_id"],
                "filePath": row["file_path"],
                "version": row["version"],
                "lockedBy": row["locked_by"],
                "lockedAt": row["locked_at"],
                "updatedAt": row["updated_at"],
            }
        )

    def _parse_timestamp(self, value: str | datetime | None) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc)
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(timezone.utc)

    def _is_lock_expired(self, lock: CodeFileLock, *, now: datetime | None = None) -> bool:
        reference = now or utc_now()
        touched_at = lock.updatedAt if isinstance(lock.updatedAt, datetime) else self._parse_timestamp(lock.updatedAt)
        if touched_at is None:
            return True
        return reference - touched_at > self.CODE_FILE_LOCK_TIMEOUT

    def _row_to_generation_task(self, row: asyncpg.Record) -> GenerationTask:
        return GenerationTask.model_validate(
            {
                "id": row["id"],
                "projectId": row["project_id"],
                "taskName": row["task_name"],
                "status": row["status"],
                "progress": row["progress"],
                "errorMessage": row["error_message"],
                "startedAt": row["started_at"],
                "completedAt": row["completed_at"],
                "createdAt": row["created_at"],
            }
        )

    def _row_to_statistics(self, row: asyncpg.Record) -> TaskStatistics:
        return TaskStatistics.model_validate(
            {
                "id": row["id"],
                "projectId": row["project_id"],
                "taskId": row["task_id"],
                "startedAt": row["started_at"],
                "completedAt": row["completed_at"],
                "totalDuration": row["total_duration"],
                "stepsCount": row["steps_count"],
                "itemsRead": row["items_read"],
                "inputTokens": row["input_tokens"],
                "outputTokens": row["output_tokens"],
                "totalTokens": row["total_tokens"],
                "costAmount": row["cost_amount"],
                "modelUsed": row["model_used"],
                "createdAt": row["created_at"],
            }
        )

    def _row_to_step(self, row: asyncpg.Record) -> StepRecord:
        return StepRecord.model_validate(
            {
                "id": row["id"],
                "taskStatisticsId": row["task_statistics_id"],
                "stepName": row["step_name"],
                "stepType": row["step_type"],
                "duration": row["duration"],
                "tokensUsed": row["tokens_used"],
                "cost": row["cost"],
                "status": row["status"],
                "metadata": _json_loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
                "createdAt": row["created_at"],
            }
        )

    def _row_to_module(self, row: asyncpg.Record) -> ProjectModule:
        return ProjectModule.model_validate(
            {
                "id": row["id"],
                "projectId": row["project_id"],
                "name": row["name"],
                "nameEn": row["name_en"],
                "isSelected": bool(row["is_selected"]),
                "createdAt": row["created_at"],
            }
        )

    def _row_to_artifact(self, row: asyncpg.Record) -> Artifact:
        return Artifact.model_validate(
            {
                "id": row["id"],
                "projectId": row["project_id"],
                "version": row["version"],
                "type": row["type"],
                "title": row["title"],
                "content": row["content"],
                "metadata": _json_loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
                "createdAt": row["created_at"],
            }
        )

    def _row_to_version(self, row: asyncpg.Record) -> ProjectVersion:
        return ProjectVersion.model_validate(
            {
                "id": row["id"],
                "projectId": row["project_id"],
                "version": row["version"],
                "versionKind": row["version_kind"],
                "sourceVersion": row["source_version"],
                "restoredFromVersion": row["restored_from_version"],
                "createdByType": row["created_by_type"],
                "createdBy": row["created_by"],
                "description": row["description"],
                "changes": _json_loads(row["changes"]) if isinstance(row["changes"], str) else (row["changes"] or []),
                "stateManifest": _json_loads(row["state_manifest"]) if isinstance(row["state_manifest"], str) else (row["state_manifest"] or {}),
                "modulesSnapshot": _json_loads(row["modules_snapshot"]) if isinstance(row["modules_snapshot"], str) else (row["modules_snapshot"] or []),
                "isCurrent": bool(row["is_current"]),
                "createdAt": row["created_at"],
            }
        )

    async def create_project(self, name: str, description: str, user_id: str | None = None) -> ProjectSummary:
        # 设计注释：
        # 项目名和描述在入库前统一做 strip，避免前端、接口测试、脚本调用时留下首尾空白。
        # 这样后面搜索、展示和重命名比较都更稳定。
        #
        # 原因注释：
        # 这次要按登录用户隔离项目，所以创建项目时要把当前用户编号落库。
        # 没有登录态的旧调用依旧允许创建匿名项目，方便兼容现有测试和本地脚本。
        project = ProjectSummary(name=name.strip(), description=description.strip(), userId=user_id)
        await self._execute(
            """
            INSERT INTO projects (
                id, name, description, status, thumbnail_path, current_version, created_at, updated_at, user_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            project.id,
            project.name,
            project.description,
            project.status,
            project.thumbnail,
            project.currentVersion,
            _dt(project.createdAt),
            _dt(project.updatedAt),
            project.userId,
        )
        return project

    async def update_project(self, project_id: str, *, name: str | None = None, description: str | None = None) -> ProjectSummary | None:
        """
        接口注释：
        更新项目基础信息；当前主要用于重命名项目。

        教学注释：
        这里只改项目表自己的字段，不去碰版本、任务、产物这些派生数据。
        因为"项目名"属于展示层面的基础信息，改名不应该制造新版本，也不应该重跑 Agent。
        """

        project = await self.get_project(project_id)
        if project is None:
            return None

        next_name = project.name if name is None else name.strip()
        next_description = project.description if description is None else description.strip()
        updated_at = _dt()
        await self._execute(
            """
            UPDATE projects
            SET name = $1, description = $2, updated_at = $3
            WHERE id = $4
            """,
            next_name, next_description, updated_at, project_id,
        )
        row = await self._query_one("SELECT * FROM projects WHERE id = $1", project_id)
        return self._row_to_project(row) if row else None

    async def delete_project(self, project_id: str) -> bool:
        """
        接口注释：
        删除项目以及该项目名下的关联数据和本地文件。

        设计注释：
        当前表结构里很多关系还没有统一靠外键级联，
        所以这里必须手工按顺序清理。
        这样才能避免"项目记录删了，但任务、版本、草稿、上传文件还残留"的脏数据。
        """

        project = await self.get_project(project_id)
        if project is None:
            return False

        uploads = await self.list_project_uploads(project_id)
        task_rows = await self._query_all(
            "SELECT id FROM tasks WHERE project_id = $1",
            project_id,
        )
        task_ids = [str(row["id"]) for row in task_rows]

        related_file_paths: list[str] = []
        if project.thumbnail:
            related_file_paths.append(project.thumbnail)
        for upload in uploads:
            if upload.filePath:
                related_file_paths.append(upload.filePath)
            if upload.thumbnailUrl:
                related_file_paths.append(upload.thumbnailUrl)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM step_records WHERE task_statistics_id IN (SELECT id FROM task_statistics WHERE project_id = $1)",
                    project_id,
                )
                await conn.execute("DELETE FROM task_statistics WHERE project_id = $1", project_id)
                if task_ids:
                    # 设计注释：
                    # asyncpg 不支持 IN ($1) 传一个列表展开的语法，
                    # 需要用 ANY($1::text[]) 搭配数组参数。
                    await conn.execute(
                        "DELETE FROM agent_artifacts WHERE task_id = ANY($1::text[])",
                        task_ids,
                    )
                await conn.execute("DELETE FROM tasks WHERE project_id = $1", project_id)
                await conn.execute("DELETE FROM generation_tasks WHERE project_id = $1", project_id)
                await conn.execute("DELETE FROM messages WHERE project_id = $1", project_id)
                await conn.execute("DELETE FROM artifacts WHERE project_id = $1", project_id)
                await conn.execute("DELETE FROM code_files WHERE project_id = $1", project_id)
                await conn.execute("DELETE FROM agent_artifacts WHERE project_id = $1", project_id)
                await conn.execute("DELETE FROM code_file_locks WHERE project_id = $1", project_id)
                await conn.execute("DELETE FROM project_file_drafts WHERE project_id = $1", project_id)
                await conn.execute("DELETE FROM project_modules WHERE project_id = $1", project_id)
                await conn.execute("DELETE FROM project_versions WHERE project_id = $1", project_id)
                await conn.execute("DELETE FROM uploaded_files WHERE project_id = $1", project_id)
                await conn.execute("DELETE FROM projects WHERE id = $1", project_id)

        for file_path in related_file_paths:
            self._delete_project_local_file(file_path)
        return True

    async def create_temp_user(self, email: str, password_hash: str, name: str, avatar_url: str | None = None) -> TempUser:
        user = TempUser(
            email=email,
            passwordHash=password_hash,
            name=name,
            avatarUrl=avatar_url or "/avatars/default.png",
        )
        await self._execute(
            """
            INSERT INTO temp_users (
                id, email, password_hash, name, avatar_url, real_user_id, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            user.id,
            user.email,
            user.passwordHash,
            user.name,
            user.avatarUrl,
            user.realUserId,
            _dt(user.createdAt),
            _dt(user.updatedAt),
        )
        row = await self._query_one("SELECT * FROM temp_users WHERE id = $1", user.id)
        if row is None:
            raise KeyError(user.id)
        return self._row_to_temp_user(row)

    async def get_temp_user_by_email(self, email: str) -> TempUser | None:
        row = await self._query_one(
            "SELECT * FROM temp_users WHERE LOWER(email) = LOWER($1) LIMIT 1",
            email,
        )
        return self._row_to_temp_user(row) if row else None

    async def get_temp_user_by_id(self, user_id: str) -> TempUser | None:
        row = await self._query_one("SELECT * FROM temp_users WHERE id = $1 LIMIT 1", user_id)
        return self._row_to_temp_user(row) if row else None

    async def create_auth_token(self, user_id: str, token: str) -> AuthTokenRecord:
        record = AuthTokenRecord(
            userId=user_id,
            tokenHash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        )
        await self._execute(
            """
            INSERT INTO auth_tokens (id, user_id, token_hash, created_at, revoked_at)
            VALUES ($1, $2, $3, $4, $5)
            """,
            record.id,
            record.userId,
            record.tokenHash,
            _dt(record.createdAt),
            None,
        )
        row = await self._query_one("SELECT * FROM auth_tokens WHERE id = $1", record.id)
        if row is None:
            raise KeyError(record.id)
        return self._row_to_auth_token(row)

    async def get_temp_user_by_token(self, token: str) -> TempUser | None:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        row = await self._query_one(
            """
            SELECT u.*
            FROM auth_tokens t
            JOIN temp_users u ON u.id = t.user_id
            WHERE t.token_hash = $1 AND t.revoked_at IS NULL
            ORDER BY t.created_at DESC
            LIMIT 1
            """,
            token_hash,
        )
        return self._row_to_temp_user(row) if row else None

    async def revoke_auth_token(self, token: str) -> bool:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        result = await self._execute(
            """
            UPDATE auth_tokens
            SET revoked_at = $1
            WHERE token_hash = $2 AND revoked_at IS NULL
            """,
            _dt(), token_hash,
        )
        # asyncpg execute returns a status string like "UPDATE 1"
        return result.split()[-1] != "0"

    async def list_projects(self, page: int, limit: int, search: str | None, user_id: str | None = None) -> ListProjectsResponse:
        filters: list[str] = []
        params: list[Any] = []
        param_idx = 0
        # 设计注释：
        # 首页项目列表现在按"当前用户是谁"过滤。
        # 登录用户只能看到自己的项目；匿名访问只能看到未绑定用户的匿名项目。
        if user_id is None:
            filters.append("user_id IS NULL")
        else:
            param_idx += 1
            filters.append(f"user_id = ${param_idx}")
            params.append(user_id)
        if search:
            param_idx += 1
            filters.append(f"(LOWER(name) LIKE ${param_idx} OR LOWER(description) LIKE ${param_idx})")
            keyword = f"%{search.lower()}%"
            params.append(keyword)

        where = f"WHERE {' AND '.join(filters)}" if filters else ""

        total = await self._query_val(f"SELECT COUNT(*) FROM projects {where}", *params)
        total = int(total) if total else 0
        total_pages = max(1, math.ceil(total / limit)) if limit else 1
        offset = max(0, (page - 1) * limit)

        param_idx += 1
        limit_placeholder = f"${param_idx}"
        param_idx += 1
        offset_placeholder = f"${param_idx}"

        rows = await self._query_all(
            f"""
            SELECT * FROM projects
            {where}
            ORDER BY updated_at DESC
            LIMIT {limit_placeholder} OFFSET {offset_placeholder}
            """,
            *params, limit, offset,
        )
        return ListProjectsResponse(
            projects=[self._row_to_project(row) for row in rows],
            total=total,
            page=page,
            totalPages=total_pages,
        )

    async def get_project(self, project_id: str) -> ProjectSummary | None:
        row = await self._query_one("SELECT * FROM projects WHERE id = $1", project_id)
        return self._row_to_project(row) if row else None

    async def touch_project(self, project_id: str, *, status: str | None = None) -> ProjectSummary:
        project = await self.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        updated_at = _dt()
        next_status = status or project.status
        await self._execute(
            "UPDATE projects SET status = $1, updated_at = $2 WHERE id = $3",
            next_status, updated_at, project_id,
        )
        row = await self._query_one("SELECT * FROM projects WHERE id = $1", project_id)
        if row is None:
            raise KeyError(project_id)
        return self._row_to_project(row)

    async def create_upload(
        self,
        file_name: str,
        file_type: str,
        file_size: int,
        content_preview: str | None = None,
        project_id: str | None = None,
    ) -> UploadedFile:
        uploaded = UploadedFile(
            fileName=file_name,
            filePath=f"/uploads/{new_id()}-{file_name}",
            fileType=file_type,  # type: ignore[arg-type]
            fileSize=file_size,
            contentPreview=content_preview,
            projectId=project_id,
            isTemporary=project_id is None,
        )
        await self._execute(
            """
            INSERT INTO uploaded_files (
                id, user_id, project_id, file_name, file_path, file_type, file_size, content_preview, thumbnail_path, is_temporary, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            uploaded.id,
            uploaded.userId,
            uploaded.projectId,
            uploaded.fileName,
            uploaded.filePath,
            uploaded.fileType,
            uploaded.fileSize,
            uploaded.contentPreview,
            uploaded.thumbnailUrl,
            uploaded.isTemporary,
            _dt(uploaded.createdAt),
        )
        return uploaded

    async def write_upload_content(self, upload_id: str, content: bytes) -> Path:
        uploads = await self.get_uploads([upload_id])
        if not uploads:
            raise KeyError(upload_id)
        await self.write_upload_content_blob(upload_id, content)
        target_path = self._upload_disk_path(uploads[0].filePath)
        if delete_local_files_after_persist_enabled():
            target_path.unlink(missing_ok=True)
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(content)
        return target_path

    async def write_upload_content_blob(self, upload_id: str, content: bytes) -> None:
        await self._execute(
            """
            INSERT INTO uploaded_file_contents (upload_id, content_blob, created_at)
            VALUES ($1, $2, $3)
            ON CONFLICT(upload_id) DO UPDATE SET content_blob = EXCLUDED.content_blob
            """,
            upload_id, content, _dt(),
        )

    async def read_upload_content_blob(self, upload_id: str) -> bytes | None:
        row = await self._query_one(
            "SELECT content_blob FROM uploaded_file_contents WHERE upload_id = $1",
            upload_id,
        )
        if row is None:
            return None
        content = row["content_blob"]
        return bytes(content) if content is not None else None

    async def delete_upload_disk_cache(self, upload_id: str) -> None:
        uploads = await self.get_uploads([upload_id])
        if not uploads:
            return
        self._upload_disk_path(uploads[0].filePath).unlink(missing_ok=True)

    async def read_upload_content(self, upload_id: str) -> bytes | None:
        blob_content = await self.read_upload_content_blob(upload_id)
        if blob_content is not None:
            return blob_content
        uploads = await self.get_uploads([upload_id])
        if not uploads:
            return None
        target_path = self._upload_disk_path(uploads[0].filePath)
        if not target_path.exists():
            return None
        content = target_path.read_bytes()
        await self.write_upload_content_blob(upload_id, content)
        if delete_local_files_after_persist_enabled():
            target_path.unlink(missing_ok=True)
        return content

    async def list_upload_analysis_details(self, upload_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not upload_ids:
            return {}
        rows = await self._query_all(
            """
            SELECT id, analysis_summary, analysis_status, analysis_error, analysis_updated_at
            FROM uploaded_files
            WHERE id = ANY($1::text[])
            """,
            upload_ids,
        )
        details_by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            details_by_id[row["id"]] = {
                "summary": row["analysis_summary"],
                "status": row["analysis_status"],
                "error": row["analysis_error"],
                "updatedAt": row["analysis_updated_at"],
            }
        return details_by_id

    async def update_upload_analysis(
        self,
        upload_id: str,
        *,
        status: str,
        summary: str | None = None,
        error: str | None = None,
    ) -> None:
        await self._execute(
            """
            UPDATE uploaded_files
            SET analysis_summary = $1, analysis_status = $2, analysis_error = $3, analysis_updated_at = $4
            WHERE id = $5
            """,
            summary, status, error, _dt(), upload_id,
        )

    async def get_uploads(self, upload_ids: list[str]) -> list[UploadedFile]:
        if not upload_ids:
            return []
        rows = await self._query_all(
            "SELECT * FROM uploaded_files WHERE id = ANY($1::text[])",
            upload_ids,
        )
        uploads_by_id = {row["id"]: self._row_to_upload(row) for row in rows}
        return [uploads_by_id[upload_id] for upload_id in upload_ids if upload_id in uploads_by_id]

    async def assign_uploads_to_project(self, upload_ids: list[str], project_id: str) -> list[UploadedFile]:
        if not upload_ids:
            return []
        uploads = await self.get_uploads(upload_ids)
        assignable_ids = [
            upload.id
            for upload in uploads
            if upload.projectId in {None, project_id}
        ]
        if assignable_ids:
            await self._execute(
                """
                UPDATE uploaded_files
                SET project_id = $1, is_temporary = false
                WHERE id = ANY($2::text[])
                """,
                project_id, assignable_ids,
            )
        return await self.get_uploads(assignable_ids)

    async def list_project_uploads(self, project_id: str) -> list[UploadedFile]:
        rows = await self._query_all(
            """
            SELECT * FROM uploaded_files
            WHERE project_id = $1
            ORDER BY created_at ASC
            """,
            project_id,
        )
        return [self._row_to_upload(row) for row in rows]

    async def add_message(self, message: Message) -> Message:
        await self._execute(
            """
            INSERT INTO messages (id, project_id, role, type, content, metadata, parent_id, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            message.id,
            message.projectId,
            message.role,
            message.type,
            message.content,
            _json_dumps(message.metadata),
            message.parentId,
            _dt(message.createdAt),
        )
        await self.touch_project(message.projectId)
        row = await self._query_one("SELECT * FROM messages WHERE id = $1", message.id)
        if row is None:
            raise KeyError(message.id)
        return self._row_to_message(row)

    async def update_message(
        self,
        message_id: str,
        *,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
        parent_id: str | None = None,
    ) -> Message:
        row = await self._query_one("SELECT * FROM messages WHERE id = $1", message_id)
        if row is None:
            raise KeyError(message_id)
        current = self._row_to_message(row)
        next_content = current.content if content is None else content
        next_metadata = current.metadata if metadata is None else metadata
        next_parent_id = current.parentId if parent_id is None else parent_id
        await self._execute(
            """
            UPDATE messages
            SET content = $1, metadata = $2, parent_id = $3
            WHERE id = $4
            """,
            next_content,
            _json_dumps(next_metadata),
            next_parent_id,
            message_id,
        )
        await self.touch_project(current.projectId)
        updated_row = await self._query_one("SELECT * FROM messages WHERE id = $1", message_id)
        if updated_row is None:
            raise KeyError(message_id)
        return self._row_to_message(updated_row)

    async def list_messages(self, project_id: str, page: int, limit: int) -> tuple[list[Message], int]:
        total = await self._query_val(
            "SELECT COUNT(*) FROM messages WHERE project_id = $1",
            project_id,
        )
        total = int(total) if total else 0
        offset = max(0, (page - 1) * limit)
        rows = await self._query_all(
            """
            SELECT * FROM messages
            WHERE project_id = $1
            ORDER BY created_at ASC
            LIMIT $2 OFFSET $3
            """,
            project_id, limit, offset,
        )
        return [self._row_to_message(row) for row in rows], total

    async def get_latest_task_interaction_message(self, project_id: str, task_id: str) -> Message | None:
        rows = await self._query_all(
            """
            SELECT * FROM messages
            WHERE project_id = $1
            ORDER BY created_at DESC
            """,
            project_id,
        )
        for row in rows:
            message = self._row_to_message(row)
            if message.type not in {"select_options", "input_form"}:
                continue
            metadata = message.metadata if isinstance(message.metadata, dict) else {}
            if str(metadata.get("taskId") or "").strip() != task_id:
                continue
            return message
        return None

    async def create_task(
        self,
        project_id: str,
        task_type: str,
        *,
        status: str,
        input_data: dict[str, Any],
        parent_task_id: str | None = None,
    ) -> TaskState:
        task = TaskState(
            projectId=project_id,
            taskType=task_type,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            inputData=input_data,
            parentTaskId=parent_task_id,
            startedAt=utc_now() if status == "running" else None,
        )
        await self._execute(
            """
            INSERT INTO tasks (
                id, project_id, task_type, status, input_data, output_data, error_message, parent_task_id, created_at, started_at, completed_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            task.id,
            task.projectId,
            task.taskType,
            task.status,
            _json_dumps(task.inputData) or "{}",
            _json_dumps(task.outputData),
            task.errorMessage,
            task.parentTaskId,
            _dt(task.createdAt),
            _dt(task.startedAt) if task.startedAt else None,
            None,
        )
        await self.touch_project(project_id, status="running" if status == "running" else None)
        row = await self._query_one("SELECT * FROM tasks WHERE id = $1", task.id)
        if row is None:
            raise KeyError(task.id)
        return self._row_to_task(row)

    async def get_task(self, task_id: str) -> TaskState | None:
        row = await self._query_one("SELECT * FROM tasks WHERE id = $1", task_id)
        return self._row_to_task(row) if row else None

    async def list_task_states(self, project_id: str) -> list[TaskState]:
        rows = await self._query_all(
            "SELECT * FROM tasks WHERE project_id = $1 ORDER BY created_at ASC",
            project_id,
        )
        return [self._row_to_task(row) for row in rows]

    async def list_tasks(self, project_id: str) -> list[TaskState]:
        """
        接口注释：
        返回项目下的全部任务。

        教学注释：
        这里保留 `list_tasks` 这个更短的名字，
        是为了让路由层和测试代码在表达"列出这个项目的任务"时更直白。
        真正实现继续复用 `list_task_states`，避免两份查询逻辑分叉。
        """

        return await self.list_task_states(project_id)

    async def list_tasks_by_status(self, statuses: list[str]) -> list[TaskState]:
        if not statuses:
            return []
        rows = await self._query_all(
            "SELECT * FROM tasks WHERE status = ANY($1::text[]) ORDER BY created_at ASC",
            statuses,
        )
        return [self._row_to_task(row) for row in rows]

    async def get_latest_task(self, project_id: str) -> TaskState | None:
        row = await self._query_one(
            "SELECT * FROM tasks WHERE project_id = $1 ORDER BY created_at DESC LIMIT 1",
            project_id,
        )
        return self._row_to_task(row) if row else None

    async def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        error_message: str | None = None,
        completed: bool = False,
    ) -> TaskState:
        current = await self.get_task(task_id)
        if current is None:
            raise KeyError(task_id)
        next_status = status or current.status
        next_input = current.inputData if input_data is None else input_data
        next_output = current.outputData if output_data is None else output_data
        next_error = current.errorMessage if error_message is None else error_message
        started_at = current.startedAt or (utc_now() if next_status == "running" else None)
        completed_at = utc_now() if completed else current.completedAt
        await self._execute(
            """
            UPDATE tasks
            SET status = $1, input_data = $2, output_data = $3, error_message = $4, started_at = $5, completed_at = $6
            WHERE id = $7
            """,
            next_status,
            _json_dumps(next_input) or "{}",
            _json_dumps(next_output),
            next_error,
            _dt(started_at) if started_at else None,
            _dt(completed_at) if completed_at else None,
            task_id,
        )
        project_status = next_status if next_status in {"running", "waiting_user", "completed", "failed", "cancelled"} else None
        await self.touch_project(current.projectId, status=project_status)
        row = await self._query_one("SELECT * FROM tasks WHERE id = $1", task_id)
        if row is None:
            raise KeyError(task_id)
        return self._row_to_task(row)

    async def transition_task_status_if_current(
        self,
        task_id: str,
        *,
        expected_status: str,
        next_status: str,
        output_data: dict[str, Any] | None = None,
    ) -> TaskState | None:
        """
        接口注释：
        只有当任务当前状态等于 expected_status 时，才把它切到 next_status。
        成功时返回最新任务；如果状态已经被别人改掉了，就返回 None。

        设计注释：
        这个方法专门用来处理"确认按钮被重复点击"这类并发入口。
        普通的 update_task 是覆盖式更新，不适合拿来做"只允许第一次成功"的抢占。
        """

        current = await self.get_task(task_id)
        if current is None:
            raise KeyError(task_id)
        if current.status != expected_status:
            return None

        started_at = current.startedAt or (utc_now() if next_status == "running" else None)
        completed_at = current.completedAt
        next_output = current.outputData if output_data is None else output_data
        result = await self._execute(
            """
            UPDATE tasks
            SET status = $1, output_data = $2, started_at = $3, completed_at = $4
            WHERE id = $5 AND status = $6
            """,
            next_status,
            _json_dumps(next_output),
            _dt(started_at) if started_at else None,
            _dt(completed_at) if completed_at else None,
            task_id,
            expected_status,
        )
        # asyncpg execute returns a status string like "UPDATE 1"
        if result.split()[-1] == "0":
            return None

        project_status = next_status if next_status in {"running", "waiting_user", "completed", "failed", "cancelled"} else None
        await self.touch_project(current.projectId, status=project_status)
        row = await self._query_one("SELECT * FROM tasks WHERE id = $1", task_id)
        if row is None:
            raise KeyError(task_id)
        return self._row_to_task(row)

    async def create_generation_task(self, project_id: str, task_name: str) -> GenerationTask:
        task = GenerationTask(projectId=project_id, taskName=task_name)
        await self._execute(
            """
            INSERT INTO generation_tasks (
                id, project_id, task_name, status, progress, error_message, started_at, completed_at, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            task.id,
            task.projectId,
            task.taskName,
            task.status,
            task.progress,
            task.errorMessage,
            None,
            None,
            _dt(task.createdAt),
        )
        row = await self._query_one("SELECT * FROM generation_tasks WHERE id = $1", task.id)
        if row is None:
            raise KeyError(task.id)
        return self._row_to_generation_task(row)

    async def update_generation_task(
        self,
        generation_task_id: str,
        project_id: str,
        *,
        status: str,
        progress: int,
        error_message: str | None = None,
    ) -> GenerationTask:
        current_row = await self._query_one(
            "SELECT * FROM generation_tasks WHERE id = $1 AND project_id = $2",
            generation_task_id, project_id,
        )
        if current_row is None:
            raise KeyError(generation_task_id)
        current = self._row_to_generation_task(current_row)
        started_at = current.startedAt or utc_now()
        completed_at = utc_now() if status in {"completed", "failed"} else current.completedAt
        next_error = current.errorMessage if error_message is None else error_message
        await self._execute(
            """
            UPDATE generation_tasks
            SET status = $1, progress = $2, error_message = $3, started_at = $4, completed_at = $5
            WHERE id = $6 AND project_id = $7
            """,
            status,
            progress,
            next_error,
            _dt(started_at),
            _dt(completed_at) if completed_at else None,
            generation_task_id,
            project_id,
        )
        row = await self._query_one(
            "SELECT * FROM generation_tasks WHERE id = $1 AND project_id = $2",
            generation_task_id, project_id,
        )
        if row is None:
            raise KeyError(generation_task_id)
        return self._row_to_generation_task(row)

    async def list_generation_tasks(self, project_id: str) -> list[GenerationTask]:
        rows = await self._query_all(
            "SELECT * FROM generation_tasks WHERE project_id = $1 ORDER BY created_at ASC",
            project_id,
        )
        return [self._row_to_generation_task(row) for row in rows]

    async def create_statistics(self, project_id: str, task_id: str, *, model_used: str | None = None) -> TaskStatistics:
        stats = TaskStatistics(projectId=project_id, taskId=task_id)
        if model_used:
            stats.modelUsed = model_used
        await self._execute(
            """
            INSERT INTO task_statistics (
                id, project_id, task_id, started_at, completed_at, total_duration, steps_count, items_read,
                input_tokens, output_tokens, total_tokens, cost_amount, model_used, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            """,
            stats.id,
            stats.projectId,
            stats.taskId,
            _dt(stats.startedAt),
            None,
            stats.totalDuration,
            stats.stepsCount,
            stats.itemsRead,
            stats.inputTokens,
            stats.outputTokens,
            stats.totalTokens,
            stats.costAmount,
            stats.modelUsed,
            _dt(stats.createdAt),
        )
        row = await self._query_one("SELECT * FROM task_statistics WHERE task_id = $1", task_id)
        if row is None:
            raise KeyError(task_id)
        return self._row_to_statistics(row)

    async def get_statistics(self, task_id: str) -> TaskStatistics | None:
        row = await self._query_one("SELECT * FROM task_statistics WHERE task_id = $1", task_id)
        return self._row_to_statistics(row) if row else None

    async def update_statistics(self, task_id: str, **fields: Any) -> TaskStatistics:
        mapping = {
            "completedAt": "completed_at",
            "totalDuration": "total_duration",
            "stepsCount": "steps_count",
            "itemsRead": "items_read",
            "inputTokens": "input_tokens",
            "outputTokens": "output_tokens",
            "totalTokens": "total_tokens",
            "costAmount": "cost_amount",
            "modelUsed": "model_used",
        }
        assignments: list[str] = []
        params: list[Any] = []
        param_idx = 0
        for key, value in fields.items():
            column = mapping.get(key)
            if column is None:
                continue
            param_idx += 1
            assignments.append(f"{column} = ${param_idx}")
            if key == "completedAt" and value is not None:
                params.append(_dt(value))
            else:
                params.append(value)
        if assignments:
            param_idx += 1
            await self._execute(
                f"UPDATE task_statistics SET {', '.join(assignments)} WHERE task_id = ${param_idx}",
                *params, task_id,
            )
        stats = await self.get_statistics(task_id)
        if stats is None:
            raise KeyError(task_id)
        return stats

    async def add_step_record(
        self,
        task_id: str,
        step_name: str,
        step_type: str,
        *,
        duration: float,
        tokens_used: int,
        cost: float,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> StepRecord:
        stats = await self.get_statistics(task_id)
        if stats is None:
            raise KeyError(task_id)
        step = StepRecord(
            taskStatisticsId=stats.id,
            stepName=step_name,
            stepType=step_type,  # type: ignore[arg-type]
            duration=duration,
            tokensUsed=tokens_used,
            cost=cost,
            status=status,  # type: ignore[arg-type]
            metadata=metadata,
        )
        await self._execute(
            """
            INSERT INTO step_records (
                id, task_statistics_id, step_name, step_type, duration, tokens_used, cost, status, metadata, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            step.id,
            step.taskStatisticsId,
            step.stepName,
            step.stepType,
            step.duration,
            step.tokensUsed,
            step.cost,
            step.status,
            _json_dumps(step.metadata),
            _dt(step.createdAt),
        )
        steps_count = await self._query_val(
            "SELECT COUNT(*) FROM step_records WHERE task_statistics_id = $1",
            stats.id,
        )
        steps_count = int(steps_count) if steps_count else 0
        await self._execute(
            "UPDATE task_statistics SET steps_count = $1 WHERE id = $2",
            steps_count, stats.id,
        )
        row = await self._query_one("SELECT * FROM step_records WHERE id = $1", step.id)
        if row is None:
            raise KeyError(step.id)
        return self._row_to_step(row)

    async def list_step_records(self, task_id: str) -> list[StepRecord]:
        stats = await self.get_statistics(task_id)
        if stats is None:
            return []
        rows = await self._query_all(
            "SELECT * FROM step_records WHERE task_statistics_id = $1 ORDER BY created_at ASC",
            stats.id,
        )
        return [self._row_to_step(row) for row in rows]

    async def replace_modules(self, project_id: str, modules: list[dict[str, Any]]) -> list[ProjectModule]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM project_modules WHERE project_id = $1", project_id)
                records: list[ProjectModule] = []
                for module in modules:
                    # 接口注释：
                    # 模块选择这块历史上存在两套字段命名：
                    # 1. 前端/工作流常用的 `label/labelEn/checked`
                    # 2. 测试和部分旧逻辑里还在用的 `name/nameEn/isSelected`
                    # 这里统一做兼容，避免恢复流程或测试因为字段名不同直接报错。
                    label = str(
                        module.get("label")
                        or module.get("name")
                        or module.get("id")
                        or "Unnamed Module"
                    )
                    label_en = str(
                        module.get("labelEn")
                        or module.get("nameEn")
                        or label
                    )
                    record = ProjectModule(
                        id=module.get("id", new_id()),
                        projectId=project_id,
                        name=label,
                        nameEn=label_en,
                        isSelected=bool(
                            module.get("checked")
                            if module.get("checked") is not None
                            else module.get("isSelected", True)
                        ),
                    )
                    await conn.execute(
                        """
                        INSERT INTO project_modules (id, project_id, name, name_en, is_selected, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        record.id,
                        record.projectId,
                        record.name,
                        record.nameEn,
                        record.isSelected,
                        _dt(record.createdAt),
                    )
                    records.append(record)
                return records

    async def get_modules(self, project_id: str) -> list[ProjectModule]:
        rows = await self._query_all(
            "SELECT * FROM project_modules WHERE project_id = $1 ORDER BY created_at ASC",
            project_id,
        )
        return [self._row_to_module(row) for row in rows]

    async def set_selected_modules(self, project_id: str, selected_ids: list[str]) -> list[ProjectModule]:
        selected = set(selected_ids)
        rows = await self._query_all(
            "SELECT * FROM project_modules WHERE project_id = $1 ORDER BY created_at ASC",
            project_id,
        )
        for row in rows:
            next_selected = row["id"] in selected if selected else bool(row["is_selected"])
            await self._execute(
                "UPDATE project_modules SET is_selected = $1 WHERE project_id = $2 AND id = $3",
                next_selected, project_id, row["id"],
            )
        return await self.get_modules(project_id)

    async def upsert_artifact(
        self,
        project_id: str,
        artifact_type: ArtifactType,
        title: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        project = await self.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        # 设计注释：
        # 这里的语义应该是"同一版本同一种产物只保留最新一份"。
        # 过去虽然函数名叫 upsert，但实现一直是纯 INSERT，
        # 一旦同一阶段重复保存，就会把 `artifacts/ui.md` 之类的文件叠出多条。
        await self._execute(
            "DELETE FROM artifacts WHERE project_id = $1 AND version = $2 AND type = $3",
            project_id, project.currentVersion, artifact_type,
        )
        artifact = Artifact(
            projectId=project_id,
            version=project.currentVersion,
            type=artifact_type,
            title=title,
            content=content,
            metadata=metadata,
        )
        await self._execute(
            """
            INSERT INTO artifacts (id, project_id, version, type, title, content, metadata, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            artifact.id,
            artifact.projectId,
            artifact.version,
            artifact.type,
            artifact.title,
            artifact.content,
            _json_dumps(artifact.metadata),
            _dt(artifact.createdAt),
        )
        row = await self._query_one("SELECT * FROM artifacts WHERE id = $1", artifact.id)
        if row is None:
            raise KeyError(artifact.id)
        return self._row_to_artifact(row)

    async def list_artifacts(self, project_id: str) -> list[Artifact]:
        rows = await self._query_all(
            "SELECT * FROM artifacts WHERE project_id = $1 ORDER BY created_at ASC",
            project_id,
        )
        return [self._row_to_artifact(row) for row in rows]

    async def list_artifacts_for_version(self, project_id: str, version: int) -> list[Artifact]:
        rows = await self._query_all(
            """
            SELECT * FROM artifacts
            WHERE project_id = $1 AND version = $2
            ORDER BY type ASC, created_at ASC
            """,
            project_id, version,
        )
        # 教学注释：
        # 新数据会被唯一索引挡住，但为了兼容历史脏数据，
        # 这里仍按 type 做一次"保留最后一条"的兜底去重。
        latest_by_type: dict[str, Artifact] = {}
        for row in rows:
            record = self._row_to_artifact(row)
            latest_by_type[record.type] = record
        return [latest_by_type[key] for key in sorted(latest_by_type)]

    async def get_artifact(
        self,
        project_id: str,
        artifact_type: ArtifactType,
        version: int | None = None,
    ) -> Artifact | None:
        if version is None:
            row = await self._query_one(
                """
                SELECT * FROM artifacts
                WHERE project_id = $1 AND type = $2
                ORDER BY version DESC, created_at DESC
                LIMIT 1
                """,
                project_id, artifact_type,
            )
        else:
            row = await self._query_one(
                """
                SELECT * FROM artifacts
                WHERE project_id = $1 AND type = $2 AND version = $3
                ORDER BY created_at DESC
                LIMIT 1
                """,
                project_id, artifact_type, version,
            )
            if row is None:
                row = await self._query_one(
                    """
                    SELECT * FROM artifacts
                    WHERE project_id = $1 AND type = $2 AND version <= $3
                    ORDER BY version DESC, created_at DESC
                    LIMIT 1
                    """,
                    project_id, artifact_type, version,
                )
        return self._row_to_artifact(row) if row else None

    async def replace_code_files(self, project_id: str, version: int, files: list[dict[str, Any]]) -> list[CodeFile]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM code_files WHERE project_id = $1 AND version = $2", project_id, version)
                created: list[CodeFile] = []
                for file in files:
                    record = CodeFile(
                        projectId=project_id,
                        version=version,
                        filePath=file["filePath"],
                        content=file["content"],
                    )
                    await conn.execute(
                        """
                        INSERT INTO code_files (id, project_id, version, file_path, content, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        record.id,
                        record.projectId,
                        record.version,
                        record.filePath,
                        record.content,
                        _dt(record.createdAt),
                    )
                    created.append(record)
                return created

    async def register_agent_artifacts(
        self,
        project_id: str,
        *,
        version: int,
        task_id: str | None,
        agent_name: str,
        artifacts: list[dict[str, Any]],
    ) -> list[AgentArtifactRecord]:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM agent_artifacts WHERE project_id = $1 AND version = $2 AND agent = $3",
                    project_id, version, agent_name,
                )
                created: list[AgentArtifactRecord] = []
                latest_artifacts_by_file_name: dict[str, dict[str, Any]] = {}
                for artifact in artifacts:
                    file_name = str(artifact["fileName"])
                    latest_artifacts_by_file_name[file_name] = artifact
                for artifact in latest_artifacts_by_file_name.values():
                    record = AgentArtifactRecord(
                        projectId=project_id,
                        version=version,
                        taskId=task_id,
                        agent=agent_name,
                        fileName=str(artifact["fileName"]),
                        fileType=str(artifact.get("fileType") or "text"),
                        contentType=str(artifact.get("contentType") or "text/plain"),
                        content=artifact.get("content"),
                        isPrimarySource=bool(artifact.get("isPrimarySource")),
                        mappedArtifactTypes=list(artifact.get("mappedArtifactTypes") or []),
                    )
                    await conn.execute(
                        """
                        INSERT INTO agent_artifacts (
                            id, project_id, version, task_id, agent, file_name, file_type,
                            content_type, content, is_primary_source, mapped_artifact_types, created_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                        """,
                        record.id,
                        record.projectId,
                        record.version,
                        record.taskId,
                        record.agent,
                        record.fileName,
                        record.fileType,
                        record.contentType,
                        record.content,
                        record.isPrimarySource,
                        _json_dumps(record.mappedArtifactTypes) or "[]",
                        _dt(record.createdAt),
                    )
                    created.append(record)
                return created

    async def list_agent_artifacts(
        self,
        project_id: str,
        *,
        version: int | None = None,
        agent_name: str | None = None,
    ) -> list[AgentArtifactRecord]:
        resolved_version = version
        if resolved_version is None:
            row = await self._query_one(
                "SELECT MAX(version) AS version FROM agent_artifacts WHERE project_id = $1",
                project_id,
            )
            resolved_version = int(row["version"]) if row and row["version"] is not None else None
        if resolved_version is None:
            return []
        if agent_name:
            rows = await self._query_all(
                """
                SELECT * FROM agent_artifacts
                WHERE project_id = $1 AND version <= $2 AND agent = $3
                ORDER BY version DESC, created_at DESC
                """,
                project_id, resolved_version, agent_name,
            )
        else:
            rows = await self._query_all(
                """
                SELECT * FROM agent_artifacts
                WHERE project_id = $1 AND version <= $2
                ORDER BY version DESC, created_at DESC
                """,
                project_id, resolved_version,
            )

        # 设计注释：
        # 这里返回"截至目标版本仍然可见的最新文件"，而不是只看单一版本。
        # 这样进入下一阶段后，前一阶段没有重新生成的文件也不会从界面上消失。
        latest_by_identity: dict[tuple[str, str], AgentArtifactRecord] = {}
        for row in rows:
            record = self._row_to_agent_artifact(row)
            identity = (record.agent, record.fileName)
            if identity not in latest_by_identity:
                latest_by_identity[identity] = record
        return sorted(latest_by_identity.values(), key=lambda record: (record.agent, record.fileName))

    async def list_agent_artifacts_for_version(
        self,
        project_id: str,
        *,
        version: int,
        agent_name: str | None = None,
    ) -> list[AgentArtifactRecord]:
        if agent_name:
            rows = await self._query_all(
                """
                SELECT * FROM agent_artifacts
                WHERE project_id = $1 AND version = $2 AND agent = $3
                ORDER BY agent ASC, file_name ASC, created_at ASC
                """,
                project_id, version, agent_name,
            )
        else:
            rows = await self._query_all(
                """
                SELECT * FROM agent_artifacts
                WHERE project_id = $1 AND version = $2
                ORDER BY agent ASC, file_name ASC, created_at ASC
                """,
                project_id, version,
            )
        latest_by_identity: dict[tuple[str, str], AgentArtifactRecord] = {}
        for row in rows:
            record = self._row_to_agent_artifact(row)
            latest_by_identity[(record.agent, record.fileName)] = record
        return sorted(latest_by_identity.values(), key=lambda record: (record.agent, record.fileName))

    async def get_agent_artifact(
        self,
        project_id: str,
        agent_name: str,
        file_name: str,
        *,
        version: int | None = None,
    ) -> AgentArtifactRecord | None:
        resolved_version = version
        if resolved_version is None:
            row = await self._query_one(
                """
                SELECT MAX(version) AS version
                FROM agent_artifacts
                WHERE project_id = $1 AND agent = $2
                """,
                project_id, agent_name,
            )
            resolved_version = int(row["version"]) if row and row["version"] is not None else None
        if resolved_version is None:
            return None
        row = await self._query_one(
            """
            SELECT * FROM agent_artifacts
            WHERE project_id = $1 AND version <= $2 AND agent = $3 AND file_name = $4
            ORDER BY version DESC, created_at DESC
            LIMIT 1
            """,
            project_id, resolved_version, agent_name, file_name,
        )
        return self._row_to_agent_artifact(row) if row else None

    async def get_code_file_lock(self, project_id: str, file_path: str) -> CodeFileLock | None:
        row = await self._query_one(
            """
            SELECT * FROM code_file_locks
            WHERE project_id = $1 AND file_path = $2
            LIMIT 1
            """,
            project_id, file_path,
        )
        if row is None:
            return None
        lock = self._row_to_code_file_lock(row)
        if self._is_lock_expired(lock):
            await self._execute("DELETE FROM code_file_locks WHERE id = $1", lock.id)
            return None
        return lock

    async def acquire_code_file_lock(self, project_id: str, file_path: str, version: int, user_id: str) -> tuple[CodeFileLock, bool]:
        existing = await self.get_code_file_lock(project_id, file_path)
        timestamp = utc_now()
        if existing and existing.lockedBy != user_id:
            return existing, True
        if existing:
            await self._execute(
                """
                UPDATE code_file_locks
                SET version = $1, locked_by = $2, updated_at = $3
                WHERE id = $4
                """,
                version, user_id, _dt(timestamp), existing.id,
            )
            refreshed = await self._query_one("SELECT * FROM code_file_locks WHERE id = $1", existing.id)
            if refreshed is None:
                raise KeyError(existing.id)
            return self._row_to_code_file_lock(refreshed), False
        lock = CodeFileLock(
            projectId=project_id,
            filePath=file_path,
            version=version,
            lockedBy=user_id,
            lockedAt=timestamp,
            updatedAt=timestamp,
        )
        await self._execute(
            """
            INSERT INTO code_file_locks (id, project_id, file_path, version, locked_by, locked_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            lock.id,
            lock.projectId,
            lock.filePath,
            lock.version,
            lock.lockedBy,
            _dt(lock.lockedAt),
            _dt(lock.updatedAt),
        )
        return lock, False

    async def touch_code_file_lock(self, project_id: str, file_path: str, user_id: str, version: int | None = None) -> CodeFileLock | None:
        existing = await self.get_code_file_lock(project_id, file_path)
        if existing is None or existing.lockedBy != user_id:
            return None
        timestamp = utc_now()
        next_version = version or existing.version
        await self._execute(
            """
            UPDATE code_file_locks
            SET version = $1, updated_at = $2
            WHERE id = $3
            """,
            next_version, _dt(timestamp), existing.id,
        )
        refreshed = await self._query_one("SELECT * FROM code_file_locks WHERE id = $1", existing.id)
        if refreshed is None:
            return None
        return self._row_to_code_file_lock(refreshed)

    async def release_code_file_lock(self, project_id: str, file_path: str, user_id: str) -> bool:
        existing = await self.get_code_file_lock(project_id, file_path)
        if existing is None:
            return False
        if existing.lockedBy != user_id:
            return False
        await self._execute("DELETE FROM code_file_locks WHERE id = $1", existing.id)
        return True

    async def list_project_file_drafts(self, project_id: str) -> list[ProjectFileDraft]:
        rows = await self._query_all(
            """
            SELECT * FROM project_file_drafts
            WHERE project_id = $1
            ORDER BY updated_at ASC, file_path ASC
            """,
            project_id,
        )
        return [self._row_to_project_file_draft(row) for row in rows]

    async def get_project_file_draft(self, project_id: str, file_path: str) -> ProjectFileDraft | None:
        row = await self._query_one(
            """
            SELECT * FROM project_file_drafts
            WHERE project_id = $1 AND file_path = $2
            LIMIT 1
            """,
            project_id, file_path,
        )
        return self._row_to_project_file_draft(row) if row else None

    async def upsert_project_file_draft(
        self,
        project_id: str,
        file_path: str,
        *,
        content: str,
        base_version: int,
        stage: str,
        source_type: str,
        updated_by: str | None = None,
    ) -> ProjectFileDraft:
        """
        接口注释：
        保存或更新项目里的单个文件草稿。

        设计注释：
        草稿和正式版本是两套状态。
        这里不会推进 `currentVersion`，只会覆盖当前项目的未提交修改。
        """

        existing = await self.get_project_file_draft(project_id, file_path)
        timestamp = utc_now()
        if existing is None:
            draft = ProjectFileDraft(
                projectId=project_id,
                filePath=file_path,
                content=content,
                baseVersion=base_version,
                stage=stage,
                sourceType=source_type,
                updatedBy=updated_by,
                createdAt=timestamp,
                updatedAt=timestamp,
            )
            await self._execute(
                """
                INSERT INTO project_file_drafts (
                    id, project_id, file_path, content, base_version, stage, source_type, updated_by, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                draft.id,
                draft.projectId,
                draft.filePath,
                draft.content,
                draft.baseVersion,
                draft.stage,
                draft.sourceType,
                draft.updatedBy,
                _dt(draft.createdAt),
                _dt(draft.updatedAt),
            )
            return draft
        await self._execute(
            """
            UPDATE project_file_drafts
            SET content = $1, base_version = $2, stage = $3, source_type = $4, updated_by = $5, updated_at = $6
            WHERE id = $7
            """,
            content,
            base_version,
            stage,
            source_type,
            updated_by,
            _dt(timestamp),
            existing.id,
        )
        refreshed = await self._query_one("SELECT * FROM project_file_drafts WHERE id = $1", existing.id)
        if refreshed is None:
            raise KeyError(existing.id)
        return self._row_to_project_file_draft(refreshed)

    async def delete_project_file_draft(self, project_id: str, file_path: str) -> bool:
        draft = await self.get_project_file_draft(project_id, file_path)
        if draft is None:
            return False
        await self._execute("DELETE FROM project_file_drafts WHERE id = $1", draft.id)
        return True

    async def clear_project_file_drafts(self, project_id: str) -> None:
        await self._execute("DELETE FROM project_file_drafts WHERE project_id = $1", project_id)

    async def list_code_files(self, project_id: str, version: int | None = None) -> list[CodeFile]:
        resolved_version = version
        if resolved_version is None:
            row = await self._query_one(
                "SELECT MAX(version) AS version FROM code_files WHERE project_id = $1",
                project_id,
            )
            resolved_version = int(row["version"]) if row and row["version"] is not None else None
        else:
            row = await self._query_one(
                "SELECT MAX(version) AS version FROM code_files WHERE project_id = $1 AND version <= $2",
                project_id, resolved_version,
            )
            resolved_version = int(row["version"]) if row and row["version"] is not None else None
        if resolved_version is None:
            return []
        rows = await self._query_all(
            """
            SELECT * FROM code_files
            WHERE project_id = $1 AND version = $2
            ORDER BY file_path ASC
            """,
            project_id, resolved_version,
        )
        return [self._row_to_code_file(row) for row in rows]

    async def get_code_file(self, project_id: str, file_path: str, version: int | None = None) -> CodeFile | None:
        if version is None:
            row = await self._query_one(
                """
                SELECT * FROM code_files
                WHERE project_id = $1 AND file_path = $2
                ORDER BY version DESC, created_at DESC
                LIMIT 1
                """,
                project_id, file_path,
            )
        else:
            row = await self._query_one(
                """
                SELECT * FROM code_files
                WHERE project_id = $1 AND file_path = $2 AND version <= $3
                ORDER BY version DESC, created_at DESC
                LIMIT 1
                """,
                project_id, file_path, version,
            )
        return self._row_to_code_file(row) if row else None

    async def _latest_project_data_version(self, project_id: str) -> int | None:
        candidates = []
        for table_name in ("artifacts", "code_files", "agent_artifacts"):
            row = await self._query_one(f"SELECT MAX(version) AS version FROM {table_name} WHERE project_id = $1", project_id)
            if row is not None and row["version"] is not None:
                candidates.append(int(row["version"]))
        if not candidates:
            return None
        return max(candidates)

    async def get_version_record(self, project_id: str, version: int) -> ProjectVersion | None:
        row = await self._query_one(
            """
            SELECT * FROM project_versions
            WHERE project_id = $1 AND version = $2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            project_id, version,
        )
        return self._row_to_version(row) if row else None

    async def update_version_snapshot(
        self,
        project_id: str,
        version: int,
        *,
        state_manifest: dict[str, Any] | None = None,
        modules_snapshot: list[dict[str, Any]] | None = None,
    ) -> ProjectVersion | None:
        current = await self.get_version_record(project_id, version)
        if current is None:
            return None
        await self._execute(
            """
            UPDATE project_versions
            SET state_manifest = $1, modules_snapshot = $2
            WHERE project_id = $3 AND version = $4
            """,
            _json_dumps(state_manifest or current.stateManifest) or "{}",
            _json_dumps(modules_snapshot or current.modulesSnapshot) or "[]",
            project_id,
            version,
        )
        return await self.get_version_record(project_id, version)

    async def create_version(
        self,
        project_id: str,
        description: str,
        changes: list[dict[str, Any]],
        *,
        version_kind: str = "generation",
        source_version: int | None = None,
        restored_from_version: int | None = None,
        created_by_type: str = "system",
        created_by: str | None = None,
        state_manifest: dict[str, Any] | None = None,
        modules_snapshot: list[dict[str, Any]] | None = None,
    ) -> ProjectVersion:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                project = await self.get_project(project_id)
                if project is None:
                    raise KeyError(project_id)
                latest_data_version = await self._latest_project_data_version(project_id)
                resolved_version = max(project.currentVersion, latest_data_version or project.currentVersion)
                if resolved_version != project.currentVersion:
                    updated_at = _dt()
                    await conn.execute(
                        "UPDATE projects SET current_version = $1, updated_at = $2 WHERE id = $3",
                        resolved_version, updated_at, project_id,
                    )
                await conn.execute("UPDATE project_versions SET is_current = false WHERE project_id = $1", project_id)
                version = ProjectVersion(
                    projectId=project_id,
                    version=resolved_version,
                    versionKind=version_kind,  # type: ignore[arg-type]
                    sourceVersion=source_version,
                    restoredFromVersion=restored_from_version,
                    createdByType=created_by_type,  # type: ignore[arg-type]
                    createdBy=created_by,
                    description=description,
                    changes=changes,
                    stateManifest=state_manifest or {},
                    modulesSnapshot=modules_snapshot or [],
                    isCurrent=True,
                )
                await conn.execute(
                    """
                    INSERT INTO project_versions (
                        id, project_id, version, version_kind, source_version, restored_from_version,
                        created_by_type, created_by, description, changes, state_manifest, modules_snapshot,
                        is_current, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    """,
                    version.id,
                    version.projectId,
                    version.version,
                    version.versionKind,
                    version.sourceVersion,
                    version.restoredFromVersion,
                    version.createdByType,
                    version.createdBy,
                    version.description,
                    _json_dumps(version.changes) or "[]",
                    _json_dumps(version.stateManifest) or "{}",
                    _json_dumps(version.modulesSnapshot) or "[]",
                    version.isCurrent,
                    _dt(version.createdAt),
                )
        row = await self._query_one("SELECT * FROM project_versions WHERE id = $1", version.id)
        if row is None:
            raise KeyError(version.id)
        return self._row_to_version(row)

    async def bump_project_version(self, project_id: str) -> ProjectSummary:
        project = await self.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        current_version = project.currentVersion + 1
        updated_at = _dt()
        await self._execute(
            "UPDATE projects SET current_version = $1, updated_at = $2 WHERE id = $3",
            current_version, updated_at, project_id,
        )
        row = await self._query_one("SELECT * FROM projects WHERE id = $1", project_id)
        if row is None:
            raise KeyError(project_id)
        return self._row_to_project(row)

    async def list_versions(self, project_id: str) -> list[ProjectVersion]:
        rows = await self._query_all(
            "SELECT * FROM project_versions WHERE project_id = $1 ORDER BY created_at ASC",
            project_id,
        )
        return [self._row_to_version(row) for row in rows]


store = AsyncPostgresStore()
