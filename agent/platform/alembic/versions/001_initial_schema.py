"""初始 schema — 从 store.py _create_schema 基线化。

Revision ID: 001
Revises: None
Create Date: 2026-04-14

设计注释：
这个迁移代表当前 PostgreSQL schema 的完整状态。
已有数据库跳过（CREATE TABLE IF NOT EXISTS），新数据库从这里建表。
后续改表用 alembic revision --autogenerate 或手写新迁移文件。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
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
    """)
    op.execute("""
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
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_file_contents (
            upload_id TEXT PRIMARY KEY,
            content_blob BYTEA NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            FOREIGN KEY(upload_id) REFERENCES uploaded_files(id) ON DELETE CASCADE
        )
    """)
    op.execute("""
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
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ
        )
    """)
    op.execute("""
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
    """)
    op.execute("""
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
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS code_files (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("""
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
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS code_file_locks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            version INTEGER NOT NULL,
            locked_by TEXT NOT NULL,
            locked_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("""
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
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS project_modules (
            row_id SERIAL PRIMARY KEY,
            id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            name_en TEXT NOT NULL,
            is_selected BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("""
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
    """)
    op.execute("""
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
    """)
    op.execute("""
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
    """)
    op.execute("""
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
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL,
            input_data JSONB NOT NULL DEFAULT '{}',
            output_data JSONB,
            error_message TEXT,
            parent_task_id TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ
        )
    """)

    # Indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_projects_updated_at ON projects(updated_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_messages_project_created ON messages(project_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_temp_users_email ON temp_users(email)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_created ON auth_tokens(user_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_project_type_created ON artifacts(project_id, type, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_code_files_project_version_path ON code_files(project_id, version, file_path)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_artifacts_project_version_agent ON agent_artifacts(project_id, version, agent, created_at)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_code_file_locks_project_path ON code_file_locks(project_id, file_path)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_project_file_drafts_project_path ON project_file_drafts(project_id, file_path)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_project_file_drafts_project_updated ON project_file_drafts(project_id, updated_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_modules_project_created ON project_modules(project_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_generation_tasks_project_created ON generation_tasks(project_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_versions_project_created ON project_versions(project_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_steps_stats_created ON step_records(task_statistics_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project_created ON tasks(project_id, created_at)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_artifacts_project_version_type ON artifacts(project_id, version, type)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_artifacts_project_version_agent_file ON agent_artifacts(project_id, version, agent, file_name)")


def downgrade() -> None:
    for table in [
        "step_records", "task_statistics", "tasks", "generation_tasks",
        "project_versions", "project_modules", "project_file_drafts",
        "code_file_locks", "agent_artifacts", "code_files", "artifacts",
        "messages", "auth_tokens", "temp_users",
        "uploaded_file_contents", "uploaded_files", "projects",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
