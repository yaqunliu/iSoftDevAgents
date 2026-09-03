from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
from io import BytesIO
import logging
import os
import secrets

import asyncpg
from typing import Annotated, Awaitable
from urllib.parse import quote
import zipfile

from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader

from app.agents.orchestrator import agent_orchestrator, shutdown_agent_executor
from app.localization import normalize_locale
from app.schemas import (
    AgentEvent,
    AgentArtifactsByAgentResponse,
    AgentArtifactsResponse,
    AuthResponse,
    CodeFileLock,
    CodeFileLockRequest,
    ConfirmProjectRequest,
    CreateProjectRequest,
    CurrentUserResponse,
    CurrentTaskResponse,
    TaskRoundSnapshot,
    GenerateProjectRequest,
    ListMessagesResponse,
    ListTasksResponse,
    LoginRequest,
    LogoutResponse,
    Message,
    ModifyProjectRequest,
    RegisterRequest,
    SendMessageRequest,
    StatisticsResponse,
    StepsResponse,
    UploadedFile,
    UpdateProjectRequest,
    UpdateArtifactRequest,
    UpdateCodeFileRequest,
    UpdateProjectFileDraftRequest,
    CommitProjectDraftsRequest,
    VersionsResponse,
    utc_now,
)
from app.services.project_naming import generate_project_name
from app.services.store import store
from app.services.workflow import (
    _statistics_payload,
    _build_generate_resume_plan,
    build_current_reference_snapshot,
    build_planned_artifact_files_for_task,
    cancel_task,
    cancel_running_task_sync,
    continue_after_confirmation,
    recover_incomplete_tasks,
    restore_waiting_task_from_interaction_message,
    start_generate_flow,
    start_modify_flow,
    submit_requirements_feedback,
)
from app.ws.manager import ws_manager

app = FastAPI(
    title="iSoftDevAgents Python API",
    version="0.1.0",
)

logger = logging.getLogger("uvicorn.error")
_APP_TASK_SHUTDOWN_TIMEOUT_SECONDS = float(os.getenv("ISOFTDEVAGENTS_APP_TASK_SHUTDOWN_TIMEOUT_SECONDS") or "8.0")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _ensure_scheduled_task_state() -> set[asyncio.Task]:
    """
    接口注释：
    返回当前应用内登记的长任务集合；如果还没初始化，就先创建。

    设计注释：
    这里登记的是"会跑很久的 Agent 流程"，不是普通 HTTP 请求。
    以前把它们交给 FastAPI BackgroundTasks 管，服务退出时只能被动等待。
    现在改成应用自己登记，shutdown 时就能主动取消和回收。
    """

    tasks = getattr(app.state, "scheduled_background_tasks", None)
    if tasks is None:
        tasks = set()
        app.state.scheduled_background_tasks = tasks
    return tasks


def _spawn_scheduled_app_task(
    operation: Awaitable[object],
    *,
    task_label: str,
    project_id: str | None = None,
    task_id: str | None = None,
) -> asyncio.Task:
    """
    接口注释：
    在当前服务进程里启动一个受控长任务，并登记到应用级任务表。

    教学注释：
    这里专门替代 FastAPI BackgroundTasks。
    目标不是"后台偷偷跑"，而是：
    1. API 返回要快
    2. 任务要可观察
    3. 服务关闭时要能统一取消
    """

    tracked_tasks = _ensure_scheduled_task_state()

    async def runner() -> None:
        try:
            await operation
        except asyncio.CancelledError:
            logger.info(
                "[APP TASK] cancelled label=%s project_id=%s task_id=%s",
                task_label,
                project_id or "-",
                task_id or "-",
            )
            raise
        except Exception:
            logger.exception(
                "[APP TASK] failed label=%s project_id=%s task_id=%s",
                task_label,
                project_id or "-",
                task_id or "-",
            )
        finally:
            tracked_tasks.discard(asyncio.current_task())

    task = asyncio.create_task(runner(), name=f"app-task:{task_label}:{task_id or '-'}")
    setattr(task, "_isoftdev_task_label", task_label)
    setattr(task, "_isoftdev_project_id", project_id)
    setattr(task, "_isoftdev_task_id", task_id)
    tracked_tasks.add(task)
    logger.info(
        "[APP TASK] scheduled label=%s project_id=%s task_id=%s active=%s",
        task_label,
        project_id or "-",
        task_id or "-",
        len(tracked_tasks),
    )
    return task


async def _cancel_project_scheduled_tasks(project_id: str) -> None:
    """
    接口注释：
    取消当前项目名下仍在运行的应用级后台任务。

    设计注释：
    删除项目时不能只删数据库。
    如果后台任务还在继续写消息、产物或代码文件，项目删完后它又回头写入，
    就会制造一批新的脏数据。
    所以这里先按项目维度把已登记的长任务停掉。
    """

    matching_tasks = [
        task
        for task in list(_ensure_scheduled_task_state())
        if getattr(task, "_isoftdev_project_id", None) == project_id
    ]
    if not matching_tasks:
        return

    for task in matching_tasks:
        tracked_task_id = getattr(task, "_isoftdev_task_id", None)
        if isinstance(tracked_task_id, str) and tracked_task_id:
            cancel_running_task_sync(tracked_task_id)
        task.cancel()

    with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
        await asyncio.wait_for(
            asyncio.gather(*matching_tasks, return_exceptions=True),
            timeout=2.0,
        )


async def _await_scheduled_app_tasks_shutdown(*, timeout_seconds: float = _APP_TASK_SHUTDOWN_TIMEOUT_SECONDS) -> None:
    tracked_tasks = list(_ensure_scheduled_task_state())
    if not tracked_tasks:
        return

    logger.info(
        "[APP TASK] shutdown_begin active=%s timeout=%.1fs",
        len(tracked_tasks),
        timeout_seconds,
    )

    for task in tracked_tasks:
        tracked_task_id = getattr(task, "_isoftdev_task_id", None)
        if isinstance(tracked_task_id, str) and tracked_task_id:
            cancel_running_task_sync(tracked_task_id)
        task.cancel()

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(
            asyncio.gather(*tracked_tasks, return_exceptions=True),
            timeout=timeout_seconds,
        )

    remaining = [task for task in _ensure_scheduled_task_state() if not task.done()]
    logger.info(
        "[APP TASK] shutdown_end remaining=%s",
        len(remaining),
    )


def _ascii_download_filename(file_name: str) -> str:
    """
    接口注释：
    为下载响应头生成一个只含 ASCII 的兜底文件名。

    原因注释：
    Starlette 在写响应头时会按 latin-1 编码。
    如果我们把中文项目名直接塞进 `filename="..."`，这里就会直接抛异常。
    所以要准备一个纯 ASCII 版本给老式 `filename=` 用，再把真实 UTF-8 名字放进 `filename*=`。
    """

    normalized = str(file_name or "").replace("/", "-").replace("\\", "-").strip()
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").strip()
    safe_ascii = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in ascii_only)
    compact_ascii = "-".join(part for part in safe_ascii.split("-") if part)
    return compact_ascii or "project.zip"


def _download_content_disposition(file_name: str) -> str:
    normalized = str(file_name or "").replace("/", "-").replace("\\", "-").strip() or "project.zip"
    ascii_fallback = _ascii_download_filename(normalized)
    encoded_name = quote(normalized, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded_name}"


@app.middleware("http")
async def log_http_request_flow(request, call_next):
    """
    教学注释：这层日志不关心业务，只用来判断请求有没有真正进入 FastAPI。

    现在 `POST /messages` 看起来像是"前端已经发起 fetch，但后端业务路由完全没动静"。
    为了把问题从"路由里卡住"还是"路由前就没进来"分开，这里专门记录：
    1. 请求刚进入应用
    2. 请求正常返回
    3. 请求异常退出
    """

    logger.info(
        "[HTTP FLOW] enter method=%s path=%s query=%s",
        request.method,
        request.url.path,
        request.url.query,
    )
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "[HTTP FLOW] error method=%s path=%s",
            request.method,
            request.url.path,
        )
        raise
    logger.info(
        "[HTTP FLOW] exit method=%s path=%s status=%s",
        request.method,
        request.url.path,
        response.status_code,
    )
    return response


def _empty_statistics_response(*, started_at=None) -> StatisticsResponse:
    timestamp = started_at or utc_now()
    return StatisticsResponse(
        totalDuration=0,
        stepsCount=0,
        itemsRead=0,
        tokens={
            "input": 0,
            "output": 0,
            "total": 0,
        },
        cost=0,
        model=agent_orchestrator.get_model_name(),
        usageStatus="pending",
        reportedSteps=0,
        unreportedSteps=0,
        startedAt=timestamp,
        completedAt=None,
    )


def _event(event_type: str, data: dict[str, object]) -> dict[str, object]:
    return AgentEvent(type=event_type, data=data).model_dump(mode="json")


def _preview_log_text(value: str | None, *, limit: int = 120) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _log_user_action(
    action: str,
    *,
    project_id: str,
    task_id: str | None = None,
    detail: str | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    payload = {
        "project_id": project_id,
        "task_id": task_id or "-",
        "detail": detail or "",
        **(extra or {}),
    }
    logger.info(
        "[USER ACTION] %s project_id=%s task_id=%s detail=%s extra=%s",
        action,
        payload["project_id"],
        payload["task_id"],
        payload["detail"],
        {key: value for key, value in payload.items() if key not in {"project_id", "task_id", "detail"}},
    )


def _task_confirmation_kind(task) -> str | None:
    if task is None or not isinstance(task.outputData, dict):
        return None
    value = task.outputData.get("confirmationKind")
    return str(value) if isinstance(value, str) else None


def _task_active_phase(task) -> str:
    if task is None or not isinstance(task.outputData, dict):
        return ""
    return str(task.outputData.get("activePhase") or "").strip()


def _build_feature_tree_regeneration_prompt(original_prompt: str, feedback_text: str) -> str:
    """
    接口注释：
    把"原始项目请求"和"这次功能树调整说明"拼成一条新的分析提示词。

    设计注释：
    这里不是简单把用户备注塞到聊天里就算了，
    而是明确告诉 Requirements Agent：
    现在要回到功能树分析阶段，先按新的说明重新整理模块，再继续后面的流程。
    """

    cleaned_prompt = str(original_prompt or "").strip()
    cleaned_feedback = str(feedback_text or "").strip()
    if not cleaned_feedback:
        return cleaned_prompt
    if not cleaned_prompt:
        return cleaned_feedback
    return (
        f"{cleaned_prompt}\n\n"
        "Please regenerate the feature tree before continuing.\n"
        "Requested feature tree adjustments for this run:\n"
        f"{cleaned_feedback}"
    )


async def _resolve_user_response_task(project_id: str, requested_task_id: str | None):
    """
    为用户交互回传找到真正要继续执行的任务。

    之前这里只拿"项目最新任务"，一旦等待卡片属于较早的任务，
    但项目里后来又出现了更新的任务，反馈就会发错地方，Agent 也就不会继续跑。
    现在优先使用前端明确传回来的 taskId；只有前端没带时，才退回旧的兜底逻辑。
    """

    if requested_task_id:
        task = await store.get_task(requested_task_id)
        if (
            task is not None
            and task.projectId == project_id
            and task.status != "waiting_user"
            and await restore_waiting_task_from_interaction_message(project_id, task.id)
        ):
            task = await store.get_task(requested_task_id)
        if task is not None and task.projectId == project_id:
            return task

    latest_task = await store.get_latest_task(project_id)
    if (
        latest_task is not None
        and latest_task.status != "waiting_user"
        and await restore_waiting_task_from_interaction_message(project_id, latest_task.id)
    ):
        latest_task = await store.get_task(latest_task.id)
    if latest_task is not None and latest_task.status == "waiting_user":
        return latest_task

    for task in reversed(await store.list_task_states(project_id)):
        if task.status != "waiting_user" and await restore_waiting_task_from_interaction_message(project_id, task.id):
            refreshed_task = await store.get_task(task.id)
            if refreshed_task is not None:
                task = refreshed_task
        if task.status == "waiting_user":
            return task
    return latest_task


def _user_response_context_missing_http_error() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "errorType": "CONTEXT_EXPIRED",
            "message": "No waiting task is available for this response. Please refresh and try again.",
        },
    )


def _with_locale(input_data: dict[str, object], locale: str | None) -> dict[str, object]:
    payload = dict(input_data)
    payload["locale"] = normalize_locale(locale)
    return payload


async def _update_task_locale(task_id: str, locale: str | None) -> None:
    task = await store.get_task(task_id)
    if task is None:
        return
    payload = dict(task.inputData or {})
    payload["locale"] = normalize_locale(locale)
    await store.update_task(task_id, input_data=payload)


def _normalize_requirements_feedback_text(
    *,
    feedback_text: str | None,
    fallback_content: str | None,
    skip: bool,
) -> str:
    """
    把前端提交回来的需求反馈统一归一化。

    这里专门兜住两类会把流程带歪的输入：
    1. 前端空提交时的占位内容，比如 `Submitted form response.`
    2. 用户用自然语言表达"没有要改的"，比如"没有反馈""无需修改"

    Requirements Agent 的老代码只认识英文 `no`。
    如果这里不统一转成 `no`，Agent 就会误判成"用户给了修改意见"，
    然后回到当前阶段重新生成，表现出来就是业务范围确认后一直原地打转。
    """

    if skip:
        return "no"

    def normalize(value: str | None) -> str:
        return " ".join(str(value or "").strip().lower().split())

    candidate = str(feedback_text or "").strip()
    fallback = str(fallback_content or "").strip()
    normalized_candidate = normalize(candidate)
    normalized_fallback = normalize(fallback)

    no_feedback_values = {
        "",
        "no",
        "none",
        "no feedback",
        "no change",
        "no changes",
        "no changes needed",
        "no changes requested.",
        "no changes requested",
        "submitted form response.",
        "submitted form response",
        "没有反馈",
        "没反馈",
        "无反馈",
        "没有修改",
        "无修改",
        "无需修改",
        "不用修改",
        "不需要修改",
        "没有需要修改的地方",
        "没有要修改的地方",
        "没有问题",
        "没问题",
        "无需变更",
        "不用变更",
        "不需要变更",
        "无变更",
        "没有变更",
    }

    if normalized_candidate in no_feedback_values:
        if normalized_fallback and normalized_fallback not in no_feedback_values:
            return fallback
        return "no"

    if candidate:
        return candidate

    if normalized_fallback in no_feedback_values:
        return "no"

    return fallback or "no"


def _normalize_artifact_type(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized == "api_specs":
        return "api_spec"
    return normalized


def _infer_change_type(file_name: str) -> str:
    normalized = file_name.strip().lower().replace("\\", "/")
    if normalized.endswith("docs/prd.md") or "prd" in normalized:
        return "prd"
    if normalized.startswith("ui/") or normalized.endswith(".html") or normalized == "ui draft":
        return "ui"
    if "architecture" in normalized:
        return "architecture"
    if "api" in normalized:
        return "api_spec"
    return "code"


def _change_description(change_type: str, file_name: str, status: str) -> str:
    labels = {
        "prd": "PRD draft",
        "ui": "UI draft",
        "architecture": "architecture draft",
        "api_spec": "API design",
        "code": file_name,
    }
    action = {
        "Added": "Added",
        "Modified": "Updated",
        "Deleted": "Removed",
    }.get(status, status or "Updated")
    target = labels.get(change_type, file_name)
    return f"{action} {target}"


def _serialize_version_record(version) -> dict[str, object]:
    payload = version.model_dump(mode="json")
    enriched_changes: list[dict[str, object]] = []
    for raw_change in payload.get("changes", []):
        if not isinstance(raw_change, dict):
            continue
        file_name = str(raw_change.get("file") or "")
        status = str(raw_change.get("status") or "Modified")
        change_type = str(raw_change.get("type") or _infer_change_type(file_name))
        enriched_change = {
            **raw_change,
            "type": change_type,
            "description": str(
                raw_change.get("description") or _change_description(change_type, file_name or change_type, status)
            ),
        }
        enriched_changes.append(enriched_change)
    payload["changes"] = enriched_changes
    return payload


def _raise_file_parse_failed(message: str) -> None:
    raise HTTPException(
        status_code=400,
        detail={
            "errorType": "FILE_PARSE_FAILED",
            "message": message,
        },
    )


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt, digest = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return hmac.compare_digest(candidate, digest)


def _issue_auth_token(user_id: str) -> str:
    return f"{user_id}.{secrets.token_urlsafe(32)}"


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = authorization[len(prefix) :].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is empty")
    return token


async def _require_current_user(authorization: str | None):
    token = _bearer_token(authorization)
    user = await store.get_temp_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user, token


async def _resolve_current_user(authorization: str | None):
    """
    接口注释：
    尝试从请求头里解析当前登录用户；没有登录态时返回空。

    教学注释：
    这里和强制登录的 `_require_current_user` 分开，是为了兼容还没带鉴权头的旧测试与本地脚本。
    这样项目接口可以逐步收紧到"按用户隔离"，同时不把所有匿名调用一次性打断。
    """

    if not authorization:
        return None
    token = _bearer_token(authorization)
    return await store.get_temp_user_by_token(token)


async def _require_project_access(project_id: str, authorization: str | None):
    """
    接口注释：
    检查当前请求是否有权访问指定项目；无权时统一返回 404。

    设计注释：
    这里故意返回"项目不存在"，而不是"你无权访问"。
    这样可以避免把别的用户项目编号是否存在泄露给外部调用方。
    """

    current_user = await _resolve_current_user(authorization)
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    current_user_id = current_user.id if current_user is not None else None
    if project.userId != current_user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _resolve_websocket_token(websocket: WebSocket) -> str | None:
    authorization = websocket.headers.get("authorization")
    if authorization:
        try:
            return _bearer_token(authorization)
        except HTTPException:
            return None
    for key in ("access_token", "token"):
        value = websocket.query_params.get(key)
        if value:
            return value.strip() or None
    return None


def _validate_uploaded_content(file_name: str, file_type: str, content: bytes) -> None:
    normalized_name = file_name.lower()

    if not content:
        _raise_file_parse_failed(f"Uploaded file `{file_name}` is empty.")

    if file_type == "markdown":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            _raise_file_parse_failed(f"Failed to decode markdown file `{file_name}` as UTF-8.")
        if not normalized_name.endswith((".md", ".markdown", ".txt")):
            _raise_file_parse_failed(f"Unsupported markdown file extension for `{file_name}`.")
        return

    if file_type == "pdf":
        if not normalized_name.endswith(".pdf") or not content.startswith(b"%PDF-"):
            _raise_file_parse_failed(f"Uploaded file `{file_name}` is not a valid PDF document.")
        return

    if file_type == "image":
        valid_signatures = (
            content.startswith(b"\x89PNG\r\n\x1a\n"),
            content.startswith(b"\xff\xd8\xff"),
            content.startswith((b"GIF87a", b"GIF89a")),
            len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP",
        )
        if not any(valid_signatures):
            _raise_file_parse_failed(f"Uploaded file `{file_name}` is not a supported image format.")
        return

    _raise_file_parse_failed(f"Unsupported file type `{file_type}` for `{file_name}`.")


def _build_upload_preview(file_name: str, file_type: str, content: bytes) -> str:
    if file_type == "markdown":
        text = content.decode("utf-8").strip()
        compact = " ".join(text.split())
        return compact[:500]
    if file_type == "pdf":
        try:
            reader = PdfReader(BytesIO(content))
        except Exception:
            _raise_file_parse_failed(f"Uploaded file `{file_name}` could not be opened as a PDF.")
        pages: list[str] = []
        for page in reader.pages:
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            page_text = " ".join(page_text.split())
            if page_text:
                pages.append(page_text)
            if len(" ".join(pages)) >= 1000:
                break
        if not pages:
            return ""
        return " ".join(pages)[:1000]
    size_label = f"{len(content)} bytes"
    return f"{file_type.upper()} reference: {file_name} ({size_label})"


def _infer_code_language(file_path: str) -> str:
    lowered = file_path.lower()
    if lowered.endswith(".ts"):
        return "typescript"
    if lowered.endswith(".js"):
        return "javascript"
    if lowered.endswith(".json"):
        return "json"
    if lowered.endswith(".html"):
        return "html"
    if lowered.endswith((".yml", ".yaml")):
        return "yaml"
    if lowered.endswith(".md"):
        return "markdown"
    return "text"


ARTIFACT_CODE_PATHS: dict[str, str] = {
    "docs/PRD.md": "prd",
    "docs/Architecture.md": "architecture",
    "docs/API.yaml": "api_spec",
    "ui/index.html": "ui",
}

ARTIFACT_DISPLAY_PATHS: dict[str, str] = {
    "prd": "docs/PRD.md",
    "ui": "docs/UI.md",
    "architecture": "docs/Architecture.md",
    "api_spec": "docs/API.yaml",
}


def _phase_agent_name(phase: str | None) -> str | None:
    if not phase:
        return None
    if phase in {"queued", "reading_context", "requirements_analysis", "modules_ready", "waiting_for_module_confirmation", "requirements_feedback_required"}:
        return "requirements_agent"
    if phase == "requirements_drafts_started":
        return "requirements_agent"
    if phase == "architecture_generation_started":
        return "architecture_agent"
    if phase in {"artifact_generation_started", "artifact_generated", "waiting_for_artifact_review"}:
        return "architecture_agent"
    if phase in {"ui_generation_started", "ui_generation_completed"}:
        return "ui_agent"
    if phase in {"code_generation_started", "code_generation_completed", "artifact_review_completed"}:
        return "coding_agent"
    if phase in {"test_generation_started", "test_generation_completed"}:
        return "test_agent"
    if phase == "modification_started":
        return "requirements_agent"
    return None


def _build_code_tree(file_paths: list[str]) -> list[dict[str, object]]:
    root: dict[str, dict[str, object]] = {}
    for file_path in sorted(file_paths):
        parts = [segment for segment in file_path.split("/") if segment]
        cursor = root
        for index, part in enumerate(parts):
            is_last = index == len(parts) - 1
            node = cursor.setdefault(
                part,
                {
                    "name": part,
                    "type": "file" if is_last else "folder",
                    **({"path": "/".join(parts[: index + 1])} if is_last else {"children": {}}),
                },
            )
            if not is_last:
                cursor = node["children"]  # type: ignore[assignment]

    def serialize(nodes: dict[str, dict[str, object]]) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for name in sorted(nodes):
            node = nodes[name]
            if node["type"] == "folder":
                items.append(
                    {
                        "name": node["name"],
                        "type": "folder",
                        "children": serialize(node["children"]),  # type: ignore[arg-type]
                    }
                )
            else:
                items.append(
                    {
                        "name": node["name"],
                        "type": "file",
                        "path": node["path"],
                    }
                )
        return items

    return serialize(root)


def _code_file_response(record) -> dict[str, object]:
    return {
        "fileName": record.filePath.split("/")[-1],
        "path": record.filePath,
        "language": _infer_code_language(record.filePath),
        "content": record.content,
        "lineCount": len(record.content.splitlines()) if record.content else 0,
        "updatedAt": record.createdAt,
        "version": record.version,
        **_empty_draft_overlay_fields(),
    }


async def _selected_modules_snapshot(project_id: str) -> list[dict[str, object]]:
    """
    接口注释：
    读取当前项目模块勾选状态，并转成可直接写进版本记录的快照结构。
    """

    return [
        {
            "id": module.id,
            "name": module.name,
            "nameEn": module.nameEn,
            "isSelected": module.isSelected,
        }
        for module in await store.get_modules(project_id)
    ]


def _normalize_state_manifest(value: object | None) -> dict[str, object]:
    manifest = value if isinstance(value, dict) else {}
    return {
        "artifacts": [str(item) for item in manifest.get("artifacts", [])] if isinstance(manifest.get("artifacts"), list) else [],
        "codeFiles": [str(item) for item in manifest.get("codeFiles", [])] if isinstance(manifest.get("codeFiles"), list) else [],
        "agentArtifacts": (
            {
                str(agent_name): [str(file_name) for file_name in file_names]
                for agent_name, file_names in manifest.get("agentArtifacts", {}).items()
                if isinstance(agent_name, str) and isinstance(file_names, list)
            }
            if isinstance(manifest.get("agentArtifacts"), dict)
            else {}
        ),
    }


async def _get_exact_version_record(project_id: str, version: int):
    return await store.get_version_record(project_id, version)


def _build_state_manifest(*, artifacts, code_files, agent_artifacts) -> dict[str, object]:
    """
    接口注释：
    统一生成版本记录里的 `stateManifest`。

    教学注释：
    后面读取历史版本时，先看这个清单，再决定"这个版本是否真的拥有某个文件"。
    这样就不会再出现"明明看的是 v3，结果偷偷读到了 v2 残留内容"的情况。
    """

    agent_artifacts_by_agent: dict[str, list[str]] = {}
    for artifact in agent_artifacts:
        agent_artifacts_by_agent.setdefault(str(artifact.agent), []).append(str(artifact.fileName))
    return {
        "artifacts": sorted({str(artifact.type) for artifact in artifacts}),
        "codeFiles": sorted({str(code_file.filePath) for code_file in code_files}),
        "agentArtifacts": {
            agent_name: sorted(set(file_names))
            for agent_name, file_names in sorted(agent_artifacts_by_agent.items())
        },
    }


async def _load_exact_artifacts_snapshot(project_id: str, version: int):
    version_record = await _get_exact_version_record(project_id, version)
    if version_record is None:
        return await store.list_artifacts_for_version(project_id, version)
    manifest = _normalize_state_manifest(version_record.stateManifest)
    allowed_types = set(manifest["artifacts"])
    if not allowed_types:
        return []
    return [
        artifact
        for artifact in await store.list_artifacts_for_version(project_id, version)
        if artifact.type in allowed_types
    ]


async def _load_exact_code_snapshot(project_id: str, version: int):
    version_record = await _get_exact_version_record(project_id, version)
    if version_record is None:
        return [
            record
            for record in await store.list_code_files(project_id, version=version)
            if record.version == version
        ]
    manifest = _normalize_state_manifest(version_record.stateManifest)
    allowed_paths = [str(item) for item in manifest["codeFiles"]]
    if not allowed_paths:
        return []
    records_by_path = {
        record.filePath: record
        for record in await store.list_code_files(project_id, version=version)
        if record.version == version
    }
    snapshot = []
    for file_path in allowed_paths:
        record = records_by_path.get(file_path)
        if record is not None:
            snapshot.append(record)
    return snapshot


async def _load_exact_agent_outputs_snapshot(project_id: str, version: int):
    version_record = await _get_exact_version_record(project_id, version)
    if version_record is None:
        grouped_records: dict[str, list[object]] = {}
        for record in await store.list_agent_artifacts_for_version(project_id, version=version):
            grouped_records.setdefault(record.agent, []).append(record)
        return grouped_records
    manifest = _normalize_state_manifest(version_record.stateManifest)
    allowed_mapping = manifest["agentArtifacts"] if isinstance(manifest["agentArtifacts"], dict) else {}
    if not allowed_mapping:
        return {}
    grouped_records: dict[str, list[object]] = {}
    for record in await store.list_agent_artifacts_for_version(project_id, version=version):
        allowed_files = allowed_mapping.get(record.agent)
        if not isinstance(allowed_files, list) or record.fileName not in allowed_files:
            continue
        grouped_records.setdefault(record.agent, []).append(record)
    return grouped_records


async def _load_exact_modules_snapshot(project_id: str, version: int) -> list[dict[str, object]]:
    version_record = await _get_exact_version_record(project_id, version)
    if version_record is None:
        return []
    return [
        {
            "id": str(module.get("id") or ""),
            "name": str(module.get("name") or module.get("label") or module.get("id") or ""),
            "nameEn": str(module.get("nameEn") or module.get("labelEn") or module.get("name") or module.get("id") or ""),
            "isSelected": bool(module.get("isSelected", module.get("checked", True))),
        }
        for module in version_record.modulesSnapshot
        if isinstance(module, dict)
    ]


async def _code_file_exists_in_exact_snapshot(project_id: str, version: int, file_path: str) -> bool:
    version_record = await _get_exact_version_record(project_id, version)
    if version_record is None:
        return any(record.filePath == file_path for record in await _load_exact_code_snapshot(project_id, version))
    manifest = _normalize_state_manifest(version_record.stateManifest)
    return file_path in manifest["codeFiles"]


async def _artifact_exists_in_exact_snapshot(project_id: str, version: int, artifact_type: str) -> bool:
    version_record = await _get_exact_version_record(project_id, version)
    if version_record is None:
        return any(artifact.type == artifact_type for artifact in await _load_exact_artifacts_snapshot(project_id, version))
    manifest = _normalize_state_manifest(version_record.stateManifest)
    return artifact_type in manifest["artifacts"]


async def _current_draft_map(project_id: str) -> dict[str, object]:
    return {
        draft.filePath: draft
        for draft in await store.list_project_file_drafts(project_id)
    }


async def _drafts_apply_to_version(project_id: str, version: int) -> bool:
    project = await store.get_project(project_id)
    if project is None:
        return False
    return version == project.currentVersion


async def _snapshot_unified_file_contents_from_store(project_id: str, version: int) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for artifact in await _load_exact_artifacts_snapshot(project_id, version):
        snapshot[_artifact_virtual_path(artifact.type)] = artifact.content
    for agent_name, records in (await _load_exact_agent_outputs_snapshot(project_id, version)).items():
        for record in records:
            snapshot[_virtual_agent_path(agent_name, record.fileName)] = str(record.content or "")
    for code_file in await _load_exact_code_snapshot(project_id, version):
        snapshot[f"workspace/{code_file.filePath}"] = code_file.content
    return snapshot


def _snapshot_unified_file_contents_from_values(
    *,
    artifacts: list[object],
    code_files: list[object],
    agent_artifacts: list[object],
) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for artifact in artifacts:
        snapshot[_artifact_virtual_path(artifact.type)] = artifact.content
    for record in agent_artifacts:
        snapshot[_virtual_agent_path(record.agent, record.fileName)] = str(record.content or "")
    for code_file in code_files:
        file_path = getattr(code_file, "filePath", None)
        content = getattr(code_file, "content", None)
        if isinstance(file_path, str) and isinstance(content, str):
            snapshot[f"workspace/{file_path}"] = content
    return snapshot


def _compute_unified_snapshot_changes(previous_snapshot: dict[str, str], next_snapshot: dict[str, str]) -> list[dict[str, object]]:
    """
    接口注释：
    对比两个统一文件快照，生成版本历史里要展示的真实差异。

    教学注释：
    这里比较的是"统一路径 -> 文件内容"。
    所以前端能直接看到 requirements、artifacts、workspace 这些路径的新增、修改、删除。
    """

    changes: list[dict[str, object]] = []
    for file_path in sorted(set(previous_snapshot.keys()) | set(next_snapshot.keys())):
        if file_path not in previous_snapshot:
            changes.append({"file": file_path, "status": "Added"})
            continue
        if file_path not in next_snapshot:
            changes.append({"file": file_path, "status": "Deleted"})
            continue
        if previous_snapshot[file_path] != next_snapshot[file_path]:
            changes.append({"file": file_path, "status": "Modified"})
    return changes


def _draft_overlay_fields(draft) -> dict[str, object]:
    return {
        "hasDraft": True,
        "draftBaseVersion": draft.baseVersion,
        "draftUpdatedAt": draft.updatedAt,
        "draftUpdatedBy": draft.updatedBy,
    }


def _empty_draft_overlay_fields() -> dict[str, object]:
    return {
        "hasDraft": False,
        "draftBaseVersion": None,
        "draftUpdatedAt": None,
        "draftUpdatedBy": None,
    }


async def _workspace_draft_for_version(project_id: str, version: int, file_path: str):
    if not await _drafts_apply_to_version(project_id, version):
        return None
    return await store.get_project_file_draft(project_id, f"workspace/{file_path}")


async def _create_project_snapshot(
    project_id: str,
    *,
    version_kind: str,
    description: str,
    changes: list[dict[str, object]] | None,
    source_version: int | None,
    restored_from_version: int | None = None,
    created_by_type: str = "system",
    created_by: str | None = None,
    artifacts: list[object] | None = None,
    code_files: list[dict[str, str]] | None = None,
    agent_artifacts_by_agent: dict[str, list[object]] | None = None,
    modules_snapshot: list[dict[str, object]] | None = None,
):
    """
    接口注释：
    统一创建项目版本快照。

    这个入口负责：
    1. 推进项目版本号
    2. 写入该版本的 artifacts / code files / agent outputs
    3. 保存模块勾选快照
    4. 生成 stateManifest
    5. 创建 project_versions 记录
    """

    next_project = await store.bump_project_version(project_id)
    snapshot_artifacts = []
    for artifact in artifacts or []:
        restored = await store.upsert_artifact(
            project_id,
            artifact.type,
            artifact.title,
            artifact.content,
            metadata=artifact.metadata,
        )
        snapshot_artifacts.append(restored)

    snapshot_code_files = await store.replace_code_files(project_id, next_project.currentVersion, code_files or [])

    snapshot_agent_artifacts = []
    for agent_name, records in (agent_artifacts_by_agent or {}).items():
        restored_records = await store.register_agent_artifacts(
            project_id,
            version=next_project.currentVersion,
            task_id=None,
            agent_name=agent_name,
            artifacts=[
                {
                    "fileName": record.fileName,
                    "fileType": record.fileType,
                    "contentType": record.contentType,
                    "content": record.content,
                    "isPrimarySource": record.isPrimarySource,
                    "mappedArtifactTypes": list(record.mappedArtifactTypes),
                }
                for record in records
            ],
        )
        snapshot_agent_artifacts.extend(restored_records)

    manifest = _build_state_manifest(
        artifacts=snapshot_artifacts,
        code_files=snapshot_code_files,
        agent_artifacts=snapshot_agent_artifacts,
    )
    resolved_changes = list(changes or [])
    if source_version is not None and not resolved_changes:
        previous_snapshot = await _snapshot_unified_file_contents_from_store(project_id, source_version)
        next_snapshot = _snapshot_unified_file_contents_from_values(
            artifacts=snapshot_artifacts,
            code_files=snapshot_code_files,
            agent_artifacts=snapshot_agent_artifacts,
        )
        resolved_changes = _compute_unified_snapshot_changes(previous_snapshot, next_snapshot)
    version_record = await store.create_version(
        project_id,
        description,
        resolved_changes,
        version_kind=version_kind,
        source_version=source_version,
        restored_from_version=restored_from_version,
        created_by_type=created_by_type,
        created_by=created_by,
        state_manifest=manifest,
        modules_snapshot=list(modules_snapshot or []),
    )
    return next_project, version_record


async def _checkpoint_unversioned_current_snapshot(
    project_id: str,
    *,
    version_kind: str,
    description: str,
    source_version: int | None,
    created_by_type: str = "system",
    created_by: str | None = None,
):
    """
    接口注释：
    给"当前版本号已经推进，但还没有正式版本记录"的现场补一条可查看快照。

    设计注释：
    生成流程在进入 UI / Code / Test 前，会先把 `currentVersion` 推到新的工作版本。
    如果这时任务失败，项目就会落在"右上角已经是 v3，但历史列表里还没有 v3 记录"的半状态。
    重试前先把这份失败现场补成版本记录，用户才能在历史里回看上一轮失败代码，不会被新重试覆盖掉。
    """

    project = await store.get_project(project_id)
    if project is None:
        return None
    current_version = project.currentVersion
    if await store.get_version_record(project_id, current_version) is not None:
        return None

    resolved_source_version = source_version
    if not isinstance(resolved_source_version, int) or resolved_source_version < 1:
        resolved_source_version = max(1, current_version - 1)

    artifacts = await _load_exact_artifacts_snapshot(project_id, current_version)
    code_files = await _load_exact_code_snapshot(project_id, current_version)
    agent_artifacts_by_agent = await _load_exact_agent_outputs_snapshot(project_id, current_version)
    flattened_agent_artifacts = [
        record
        for records in agent_artifacts_by_agent.values()
        for record in records
    ]
    state_manifest = _build_state_manifest(
        artifacts=artifacts,
        code_files=code_files,
        agent_artifacts=flattened_agent_artifacts,
    )
    previous_snapshot = await _snapshot_unified_file_contents_from_store(project_id, resolved_source_version)
    current_snapshot = _snapshot_unified_file_contents_from_values(
        artifacts=artifacts,
        code_files=code_files,
        agent_artifacts=flattened_agent_artifacts,
    )
    changes = _compute_unified_snapshot_changes(previous_snapshot, current_snapshot)

    return await store.create_version(
        project_id,
        description,
        changes,
        version_kind=version_kind,
        source_version=resolved_source_version,
        created_by_type=created_by_type,
        created_by=created_by,
        state_manifest=state_manifest,
        modules_snapshot=await _selected_modules_snapshot(project_id),
    )


UNIFIED_STAGE_TO_AGENT: dict[str, str] = {
    "requirements": "requirements_agent",
    "architecture": "architecture_agent",
    "ui": "ui_agent",
    "coding": "coding_agent",
    "test": "test_agent",
}

UNIFIED_AGENT_TO_STAGE: dict[str, str] = {
    agent_name: stage_name
    for stage_name, agent_name in UNIFIED_STAGE_TO_AGENT.items()
}

UNIFIED_ARTIFACT_PATHS: dict[str, str] = {
    "prd": "artifacts/prd.md",
    "ui": "artifacts/ui.md",
    "architecture": "artifacts/architecture.md",
    "api_spec": "artifacts/api_spec.yaml",
}


def _artifact_virtual_path(artifact_type: str) -> str:
    return UNIFIED_ARTIFACT_PATHS.get(artifact_type, f"artifacts/{artifact_type}.md")


def _artifact_type_from_virtual_path(path: str) -> str | None:
    normalized = str(path or "").strip()
    for artifact_type, virtual_path in UNIFIED_ARTIFACT_PATHS.items():
        if normalized == virtual_path:
            return artifact_type
    return None


def _virtual_agent_path(agent_name: str, file_name: str) -> str:
    stage = UNIFIED_AGENT_TO_STAGE.get(agent_name, agent_name)
    return f"{stage}/{file_name}"


def _parse_virtual_agent_path(path: str) -> tuple[str, str] | None:
    normalized = str(path or "").strip().replace("\\", "/")
    if "/" not in normalized:
        return None
    stage, file_name = normalized.split("/", 1)
    agent_name = UNIFIED_STAGE_TO_AGENT.get(stage)
    if agent_name is None or not file_name.strip():
        return None
    return agent_name, file_name


def _derive_requirements_artifacts_from_records(
    *,
    prompt: str,
    selected_modules: list[dict[str, object]],
    records: list[object],
) -> dict[str, str]:
    raw_outputs = {
        record.fileName: str(record.content or "")
        for record in records
    }
    business_scope = raw_outputs.get("business_scope.md", "")
    feature_tree = raw_outputs.get("feature_tree.md", "")
    functional_requirements = raw_outputs.get("functional_requirements.md", "")
    non_functional_requirements = raw_outputs.get("non_functional_requirements.md", "")
    use_case_text = raw_outputs.get("use_case.md", "")
    module_labels = agent_orchestrator._requirements_agent_module_labels(feature_tree, selected_modules)
    use_cases = agent_orchestrator._parse_requirements_agent_use_cases(use_case_text)
    return {
        "prd": agent_orchestrator._requirements_agent_prd_from_outputs(
            prompt=prompt,
            selected_modules=selected_modules,
            business_scope=business_scope,
            feature_tree=feature_tree,
            functional_requirements=functional_requirements,
            non_functional_requirements=non_functional_requirements,
            use_cases=use_cases,
        ),
        "ui": agent_orchestrator._requirements_agent_ui_from_outputs(
            module_labels=module_labels,
            use_cases=use_cases,
        ),
        "api_spec": agent_orchestrator._requirements_agent_api_spec_from_outputs(
            module_labels=module_labels,
            use_cases=use_cases,
        ),
    }


async def _apply_project_file_change_to_snapshots(
    *,
    project_id: str,
    project_description: str,
    normalized_path: str,
    content: str,
    next_artifacts: list[object],
    next_code_files: list[dict[str, str]],
    next_agent_outputs: dict[str, list[object]],
    modules_snapshot: list[dict[str, object]],
) -> None:
    """
    接口注释：
    把一次统一文件修改应用到待提交快照里。

    设计注释：
    这里同时处理三类文件：
    - `workspace/...`
    - `artifacts/...`
    - 各阶段原始文件

    这样无论是"直接保存成版本"还是"先存草稿后统一提交"，
    都可以复用同一套修改规则，避免两条链路越改越不一致。
    """

    if normalized_path.startswith("workspace/"):
        target_file_path = normalized_path.removeprefix("workspace/")
        updated = False
        for item in next_code_files:
            if item["filePath"] != target_file_path:
                continue
            item["content"] = content
            updated = True
            break
        if not updated:
            raise HTTPException(status_code=404, detail="Project file not found")
        bound_artifact_type = ARTIFACT_CODE_PATHS.get(target_file_path)
        if bound_artifact_type is not None:
            for artifact in next_artifacts:
                if artifact.type == bound_artifact_type:
                    artifact.content = content
        return

    artifact_type = _artifact_type_from_virtual_path(normalized_path)
    if artifact_type is not None:
        updated = False
        for artifact in next_artifacts:
            if artifact.type != artifact_type:
                continue
            artifact.content = content
            updated = True
        if not updated:
            raise HTTPException(status_code=404, detail="Project file not found")
        bound_code_path = next((path for path, value in ARTIFACT_CODE_PATHS.items() if value == artifact_type), None)
        if bound_code_path is not None:
            for item in next_code_files:
                if item["filePath"] == bound_code_path:
                    item["content"] = content
        return

    agent_target = _parse_virtual_agent_path(normalized_path)
    if agent_target is None:
        raise HTTPException(status_code=404, detail="Project file not found")
    agent_name, target_file_name = agent_target
    records = next_agent_outputs.get(agent_name, [])
    updated = False
    for record in records:
        if record.fileName != target_file_name:
            continue
        record.content = content
        updated = True
        break
    if not updated:
        raise HTTPException(status_code=404, detail="Project file not found")

    if agent_name == "requirements_agent":
        task = await store.get_latest_task(project_id)
        prompt = str(task.inputData.get("prompt", "")) if task is not None else project_description
        selected_modules = [
            {
                "id": str(module.get("id") or ""),
                "label": str(module.get("name") or module.get("id") or ""),
                "labelEn": str(module.get("nameEn") or module.get("name") or module.get("id") or ""),
            }
            for module in modules_snapshot
            if bool(module.get("isSelected", True))
        ]
        derived_artifacts = _derive_requirements_artifacts_from_records(
            prompt=prompt,
            selected_modules=selected_modules,
            records=records,
        )
        for artifact in next_artifacts:
            if artifact.type in derived_artifacts:
                artifact.content = derived_artifacts[artifact.type]


async def _unified_file_entries(project_id: str, version: int) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    draft_map = await _current_draft_map(project_id) if await _drafts_apply_to_version(project_id, version) else {}

    for artifact in await _load_exact_artifacts_snapshot(project_id, version):
        draft = draft_map.get(_artifact_virtual_path(artifact.type))
        entries.append(
            {
                "path": _artifact_virtual_path(artifact.type),
                "fileName": _artifact_virtual_path(artifact.type).split("/")[-1],
                "stage": "artifacts",
                "sourceType": "system_derived",
                "derivedArtifactType": artifact.type,
                "contentType": "text/yaml" if artifact.type == "api_spec" else "text/markdown",
                "language": "yaml" if artifact.type == "api_spec" else "markdown",
                "isEditable": True,
                "version": artifact.version,
                "updatedAt": artifact.createdAt,
                **(_draft_overlay_fields(draft) if draft is not None else _empty_draft_overlay_fields()),
            }
        )

    for agent_name, records in (await _load_exact_agent_outputs_snapshot(project_id, version)).items():
        stage = UNIFIED_AGENT_TO_STAGE.get(agent_name, agent_name)
        for record in sorted(records, key=lambda item: item.fileName):
            draft = draft_map.get(_virtual_agent_path(agent_name, record.fileName))
            entries.append(
                {
                    "path": _virtual_agent_path(agent_name, record.fileName),
                    "fileName": record.fileName,
                    "stage": stage,
                    "sourceType": "agent_generated",
                    "derivedArtifactType": None,
                    "contentType": record.contentType,
                    "language": _infer_code_language(record.fileName),
                    "isEditable": True,
                    "version": record.version,
                    "updatedAt": record.createdAt,
                    **(_draft_overlay_fields(draft) if draft is not None else _empty_draft_overlay_fields()),
                }
            )

    for record in await _load_exact_code_snapshot(project_id, version):
        draft = draft_map.get(f"workspace/{record.filePath}")
        entries.append(
            {
                "path": f"workspace/{record.filePath}",
                "fileName": record.filePath.split("/")[-1],
                "stage": "workspace",
                "sourceType": "agent_generated",
                "derivedArtifactType": ARTIFACT_CODE_PATHS.get(record.filePath),
                "contentType": "text/plain",
                "language": _infer_code_language(record.filePath),
                "isEditable": True,
                "version": record.version,
                "updatedAt": record.createdAt,
                **(_draft_overlay_fields(draft) if draft is not None else _empty_draft_overlay_fields()),
            }
        )

    entries.sort(key=lambda item: str(item["path"]))

    # 设计注释：
    # 统一文件视图是前端看到的"逻辑文件系统"，同一路径不应该出现两次。
    # 即使底层因为历史脏数据或多来源快照出现重复，这里也再兜底一次，
    # 保证 UI 不会把同一个逻辑文件展示成两条。
    deduplicated_entries_by_path: dict[str, dict[str, object]] = {}
    for entry in entries:
        deduplicated_entries_by_path[str(entry["path"])] = entry
    return [deduplicated_entries_by_path[path] for path in sorted(deduplicated_entries_by_path)]


async def _unified_file_content(project_id: str, version: int, unified_path: str) -> dict[str, object] | None:
    normalized_path = str(unified_path or "").strip().replace("\\", "/")
    draft = await store.get_project_file_draft(project_id, normalized_path) if await _drafts_apply_to_version(project_id, version) else None

    if normalized_path.startswith("workspace/"):
        file_path = normalized_path.removeprefix("workspace/")
        record = next((item for item in await _load_exact_code_snapshot(project_id, version) if item.filePath == file_path), None)
        if record is None:
            return None
        return {
            "path": normalized_path,
            "fileName": record.filePath.split("/")[-1],
            "stage": "workspace",
            "sourceType": "agent_generated",
            "derivedArtifactType": ARTIFACT_CODE_PATHS.get(record.filePath),
            "contentType": "text/plain",
            "language": _infer_code_language(record.filePath),
            "isEditable": True,
            "content": draft.content if draft is not None else record.content,
            "version": record.version,
            "updatedAt": draft.updatedAt if draft is not None else record.createdAt,
            **(_draft_overlay_fields(draft) if draft is not None else _empty_draft_overlay_fields()),
        }

    artifact_type = _artifact_type_from_virtual_path(normalized_path)
    if artifact_type is not None:
        artifact = next((item for item in await _load_exact_artifacts_snapshot(project_id, version) if item.type == artifact_type), None)
        if artifact is None:
            return None
        return {
            "path": normalized_path,
            "fileName": normalized_path.split("/")[-1],
            "stage": "artifacts",
            "sourceType": "system_derived",
            "derivedArtifactType": artifact.type,
            "contentType": "text/yaml" if artifact.type == "api_spec" else "text/markdown",
            "language": "yaml" if artifact.type == "api_spec" else "markdown",
            "isEditable": True,
            "content": draft.content if draft is not None else artifact.content,
            "version": artifact.version,
            "updatedAt": draft.updatedAt if draft is not None else artifact.createdAt,
            **(_draft_overlay_fields(draft) if draft is not None else _empty_draft_overlay_fields()),
        }

    agent_target = _parse_virtual_agent_path(normalized_path)
    if agent_target is None:
        return None
    agent_name, file_name = agent_target
    record = next(
        (
            item
            for item in (await _load_exact_agent_outputs_snapshot(project_id, version)).get(agent_name, [])
            if item.fileName == file_name
        ),
        None,
    )
    if record is None:
        return None
    return {
        "path": normalized_path,
        "fileName": record.fileName,
        "stage": UNIFIED_AGENT_TO_STAGE.get(agent_name, agent_name),
        "sourceType": "agent_generated",
        "derivedArtifactType": None,
        "contentType": record.contentType,
        "language": _infer_code_language(record.fileName),
        "isEditable": True,
        "content": draft.content if draft is not None else str(record.content or ""),
        "version": record.version,
        "updatedAt": draft.updatedAt if draft is not None else record.createdAt,
        **(_draft_overlay_fields(draft) if draft is not None else _empty_draft_overlay_fields()),
    }


def _serialize_code_file_lock(lock: CodeFileLock | None) -> dict[str, object] | None:
    if lock is None:
        return None
    return lock.model_dump(mode="json", include={"filePath", "version", "lockedBy", "lockedAt", "updatedAt"})


def _module_folder_path(module_id: str) -> str:
    return f"src/{module_id}"


def _extract_mermaid_code(content: str) -> str:
    marker = "```mermaid"
    start = content.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = content.find("```", start)
    if end < 0:
        return content[start:].strip()
    return content[start:end].strip()


def _artifact_summary_line(content: str, fallback: str) -> str:
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("```"):
            continue
        return line
    return fallback


def _ui_route_for_file(file_path: str) -> str:
    normalized = file_path.replace("\\", "/")
    for prefix in ("ui/", "frontend/", "app/", "./"):
        if normalized.startswith(prefix):
            normalized = normalized.removeprefix(prefix)
            break
    if normalized in {"index.html", "index.htm"}:
        return "/"
    stem = normalized.rsplit(".", 1)[0]
    if stem.startswith("page_"):
        stem = stem[5:]
    stem = stem.replace("_", "-").replace(" ", "-").strip("-")
    return f"/{stem}" if stem else "/"


def _ui_page_name(file_path: str) -> str:
    normalized = file_path.replace("\\", "/")
    for prefix in ("ui/", "frontend/", "app/", "./"):
        if normalized.startswith(prefix):
            normalized = normalized.removeprefix(prefix)
            break
    normalized = normalized.rsplit("/", 1)[-1]
    stem = normalized.rsplit(".", 1)[0]
    if stem.lower() == "index":
        return "Home"
    stem = stem.replace("page_", "").replace("_", " ").replace("-", " ").strip()
    return " ".join(part.capitalize() for part in stem.split()) or "UI Draft"


def _normalize_download_archive_path(*parts: str) -> str:
    """
    接口注释：
    统一生成下载 ZIP 内部的相对路径。

    这里做三件小事：
    1. 统一成正斜杠
    2. 去掉空段、`.`、`..`
    3. 保证最终永远是相对路径，避免压缩包里出现异常目录结构
    """

    normalized_parts: list[str] = []
    for part in parts:
        for token in str(part).replace("\\", "/").split("/"):
            token = token.strip()
            if not token or token in {".", ".."}:
                continue
            normalized_parts.append(token)
    return "/".join(normalized_parts)


async def _download_bundle_entries(project_id: str, *, version: int | None) -> tuple[int, list[tuple[str, str]]]:
    """
    设计注释：
    下载包现在固定拆成两块：
    - `code/`：项目代码快照
    - `docs/<agent>/`：各 Agent 的原始文档产物

    这样用户下载后，能一眼分清"代码"和"文档"，
    也能知道文档分别来自哪个 Agent。
    """

    resolved_version = version if version is not None else (await store.get_project(project_id)).currentVersion
    code_files = await _load_exact_code_snapshot(project_id, resolved_version)
    grouped_agent_artifacts = await _load_exact_agent_outputs_snapshot(project_id, resolved_version)
    agent_artifacts = [
        artifact
        for records in grouped_agent_artifacts.values()
        for artifact in records
    ]

    entries: list[tuple[str, str]] = []
    for code_file in code_files:
        archive_path = _normalize_download_archive_path("code", code_file.filePath)
        if not archive_path:
            continue
        entries.append((archive_path, code_file.content))

    for artifact in agent_artifacts:
        archive_path = _normalize_download_archive_path("docs", artifact.agent, artifact.fileName)
        if not archive_path:
            continue
        entries.append((archive_path, artifact.content if isinstance(artifact.content, str) else str(artifact.content or "")))

    deduped_entries: list[tuple[str, str]] = []
    seen_paths: set[str] = set()
    for archive_path, content in entries:
        if archive_path in seen_paths:
            continue
        seen_paths.add(archive_path)
        deduped_entries.append((archive_path, content))

    return resolved_version, deduped_entries


async def _build_ui_pages_payload(project_id: str, artifact) -> list[dict[str, object]]:
    ui_files = [
        code_file
        for code_file in await store.list_code_files(project_id, version=artifact.version)
        if code_file.filePath.lower().endswith((".html", ".htm"))
        and (
            code_file.filePath.lower().startswith("ui/")
            or code_file.filePath.lower().startswith("frontend/")
            or code_file.filePath.lower().startswith("app/")
            or code_file.filePath.lower() in {"index.html", "./index.html"}
        )
    ]
    pages: list[dict[str, object]] = []
    for index, code_file in enumerate(ui_files, start=1):
        pages.append(
            {
                "id": f"{artifact.id}-page-{index}",
                "name": _ui_page_name(code_file.filePath),
                "route": _ui_route_for_file(code_file.filePath),
                "thumbnailUrl": None,
                "previewUrl": (
                    f"/api/projects/{project_id}/code/preview/{quote(code_file.filePath, safe='/')}"
                    f"?version={artifact.version}"
                ),
                "code": code_file.content,
            }
        )
    if pages:
        return pages
    return [
        {
            "id": f"{artifact.id}-page-1",
            "name": "UI Draft",
            "route": "/",
            "thumbnailUrl": None,
            "previewUrl": None,
            "code": artifact.content,
        }
    ]


async def _artifact_response(project_id: str, artifact) -> dict[str, object]:
    payload = artifact.model_dump(mode="json")
    metadata = artifact.metadata if isinstance(artifact.metadata, dict) else {}
    payload["updatedAt"] = artifact.createdAt
    payload["sourceFiles"] = list(metadata.get("sourceFiles") or [])
    payload["sourceAgent"] = str(metadata.get("sourceAgent") or "unknown")
    payload["sourceStatus"] = str(metadata.get("sourceStatus") or "unknown")
    payload["artifactKind"] = str(metadata.get("artifactKind") or "synthesized")
    payload["displayPath"] = str(metadata.get("displayPath") or ARTIFACT_DISPLAY_PATHS.get(artifact.type, artifact.title))
    payload["rawSourceAvailable"] = bool(
        metadata.get("rawSourceAvailable")
        if metadata.get("rawSourceAvailable") is not None
        else payload["sourceFiles"]
    )
    if artifact.type == "ui":
        payload["pages"] = await _build_ui_pages_payload(project_id, artifact)
    elif artifact.type == "architecture":
        payload["mermaidCode"] = _extract_mermaid_code(artifact.content)
        payload["description"] = _artifact_summary_line(artifact.content, "System architecture draft.")
    elif artifact.type == "api_spec":
        payload["format"] = "yaml"
    return payload


def _schedule_retry_task(
    *,
    project_id: str,
    new_task_id: str,
    task_type: str,
    input_data: dict[str, object],
    start_stage: str | None = None,
) -> None:
    prompt = str(input_data.get("prompt", ""))
    uploaded_files = input_data.get("uploadedFiles", [])
    if task_type == "generate":
        _spawn_scheduled_app_task(
            start_generate_flow(
                project_id,
                new_task_id,
                prompt,
                uploaded_files if isinstance(uploaded_files, list) else [],
                start_stage=start_stage,
            ),
            task_label="generate",
            project_id=project_id,
            task_id=new_task_id,
        )
        return
    if task_type in {"modify", "regenerate"}:
        _spawn_scheduled_app_task(
            start_modify_flow(
                project_id,
                new_task_id,
                prompt,
            ),
            task_label=task_type,
            project_id=project_id,
            task_id=new_task_id,
        )
        return
    if task_type == "rollback":
        source_version = input_data.get("sourceVersion")
        if not isinstance(source_version, int):
            raise HTTPException(
                status_code=400,
                detail={
                    "errorType": "CONTEXT_EXPIRED",
                "message": "Rollback retry is missing the sourceVersion context.",
            },
        )
        _spawn_scheduled_app_task(
            execute_rollback_task(
                project_id,
                new_task_id,
                source_version,
            ),
            task_label="rollback",
            project_id=project_id,
            task_id=new_task_id,
        )
        return
    raise HTTPException(
        status_code=400,
        detail={
            "errorType": "CONTEXT_EXPIRED",
            "message": f"Retry is not implemented for task type `{task_type}`.",
        },
    )


async def _broadcast_artifact_snapshot(project_id: str, source_version: int, *, override_path: str | None = None, override_content: str | None = None) -> None:
    for artifact in await _load_exact_artifacts_snapshot(project_id, source_version):
        bound_path = next((path for path, bound_type in ARTIFACT_CODE_PATHS.items() if bound_type == artifact.type), None)
        next_content = override_content if override_path and bound_path == override_path else artifact.content
        updated = await store.upsert_artifact(
            project_id,
            artifact.type,
            artifact.title,
            next_content,
            metadata=artifact.metadata,
        )
        await ws_manager.broadcast(
            project_id,
            _event(
                "artifact_update",
                {
                    "artifactType": updated.type,
                    "version": updated.version,
                    "action": "code_file_updated",
                },
            ),
        )


def _rollback_failure_response(source_version: int, message: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "errorType": "ROLLBACK_FAILED",
            "message": message,
        },
    )


async def _task_round_snapshot(project_id: str, task) -> TaskRoundSnapshot | None:
    messages, _ = await store.list_messages(project_id, 1, 200)
    task_messages = [
        message
        for message in messages
        if isinstance(message.metadata, dict) and message.metadata.get("taskId") == task.id
    ]
    anchor = next(
        (
            message
            for message in task_messages
            if message.role == "user"
            and message.type == "text"
            and message.metadata.get("taskRoundRole") == "anchor"
        ),
        None,
    )
    logs = [message for message in task_messages if message.type == "process_log"]
    latest_log = logs[-1] if logs else None
    if anchor is None and latest_log is None:
        return None
    updated_at = latest_log.createdAt if latest_log is not None else anchor.createdAt if anchor is not None else None
    latest_phase = None
    if latest_log is not None and isinstance(latest_log.metadata, dict):
        phase_value = latest_log.metadata.get("phase")
        latest_phase = str(phase_value) if phase_value is not None else None
    return TaskRoundSnapshot(
        taskId=task.id,
        status=task.status,
        anchorMessageId=anchor.id if anchor is not None else None,
        anchorContent=anchor.content if anchor is not None else None,
        logsCount=len(logs),
        latestLogId=latest_log.id if latest_log is not None else None,
        latestLog=latest_log.content if latest_log is not None else None,
        latestPhase=latest_phase,
        updatedAt=updated_at,
    )


async def _task_pending_agent_artifacts_version(project_id: str, task) -> int | None:
    output_data = task.outputData if isinstance(task.outputData, dict) else {}
    explicit_value = output_data.get("pendingAgentArtifactsVersion")
    if isinstance(explicit_value, int) and explicit_value >= 1:
        return explicit_value

    project = await store.get_project(project_id)
    if project is None:
        return None
    latest_artifacts = await store.list_agent_artifacts(project_id)
    if latest_artifacts:
        latest_version = latest_artifacts[0].version
        if latest_version > project.currentVersion and task.status in {"running", "waiting_user"}:
            return latest_version
    return None


async def _task_activity_payload(project_id: str, task) -> tuple[str | None, str | None, list[str]]:
    output_data = task.outputData if isinstance(task.outputData, dict) else {}
    round_snapshot = await _task_round_snapshot(project_id, task)
    active_phase = None
    if isinstance(output_data.get("activePhase"), str):
        active_phase = str(output_data["activePhase"])
    elif round_snapshot is not None and isinstance(round_snapshot.latestPhase, str):
        active_phase = round_snapshot.latestPhase

    active_agent = None
    if isinstance(output_data.get("activeAgent"), str):
        active_agent = str(output_data["activeAgent"])
    else:
        active_agent = _phase_agent_name(active_phase)

    ready = output_data.get("agentOutputsReady")
    if isinstance(ready, list):
        agent_outputs_ready = [str(item) for item in ready if str(item).strip()]
    else:
        project_obj = await store.get_project(project_id)
        current_version = project_obj.currentVersion if project_obj is not None else None
        live_version = await _task_pending_agent_artifacts_version(project_id, task)
        resolved_version = live_version if live_version is not None else current_version
        agent_outputs_ready = sorted({artifact.agent for artifact in await store.list_agent_artifacts(project_id, version=resolved_version)})
    return active_agent, active_phase, agent_outputs_ready


async def _mark_rollback_failed(task_id: str, source_version: int, message: str) -> None:
    await store.update_task(
        task_id,
        status="failed",
        output_data={"errorType": "ROLLBACK_FAILED", "sourceVersion": source_version},
        error_message=message,
        completed=True,
    )


async def execute_rollback_task(project_id: str, task_id: str, source_version: int) -> dict[str, object]:
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    versions = await store.list_versions(project_id)
    if not any(checkpoint.version == source_version for checkpoint in versions):
        message = f"Version {source_version} was not found for this project."
        await _mark_rollback_failed(task_id, source_version, message)
        raise _rollback_failure_response(source_version, message)
    snapshot = await _load_exact_artifacts_snapshot(project_id, source_version)
    snapshot_code_files = [
        {
            "filePath": code_file.filePath,
            "content": code_file.content,
        }
        for code_file in await _load_exact_code_snapshot(project_id, source_version)
    ]
    snapshot_agent_artifacts = await _load_exact_agent_outputs_snapshot(project_id, source_version)
    modules_snapshot = await _load_exact_modules_snapshot(project_id, source_version)
    if not snapshot and not snapshot_code_files and not snapshot_agent_artifacts:
        message = f"No artifact snapshot is available for version {source_version}."
        await _mark_rollback_failed(task_id, source_version, message)
        raise _rollback_failure_response(source_version, message)

    updated_project, restored_version = await _create_project_snapshot(
        project_id,
        version_kind="rollback",
        description=f"Rolled back to version {source_version}.",
        changes=None,
        source_version=project.currentVersion,
        restored_from_version=source_version,
        created_by_type="user",
        artifacts=snapshot,
        code_files=snapshot_code_files,
        agent_artifacts_by_agent=snapshot_agent_artifacts,
        modules_snapshot=modules_snapshot,
    )
    if modules_snapshot:
        await store.replace_modules(project_id, modules_snapshot)
    for artifact in snapshot:
        await ws_manager.broadcast(
            project_id,
            _event(
                "artifact_update",
                {
                    "artifactType": artifact.type,
                    "version": updated_project.currentVersion,
                    "action": "rolled_back",
                },
            ),
        )
    rollback_message = await store.add_message(
        Message(
            projectId=project_id,
            role="system",
            type="text",
            content=f"Rolled back to version {source_version}.",
        )
    )
    await store.update_task(
        task_id,
        status="completed",
        output_data={"sourceVersion": source_version, "newVersion": updated_project.currentVersion},
        completed=True,
    )
    await store.touch_project(project_id, status="completed")

    await ws_manager.broadcast(
        project_id,
        _event(
            "message",
            rollback_message.model_dump(mode="json"),
        ),
    )
    await ws_manager.broadcast(
        project_id,
        _event(
            "version_update",
            restored_version.model_dump(mode="json"),
        ),
    )

    return {
        "status": "success",
        "newVersion": updated_project.currentVersion,
        "message": f"Rolled back to version {source_version}",
    }


@app.get("/api/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/projects")
async def list_projects(
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 6,
    search: str | None = None,
    authorization: Annotated[str | None, Header()] = None,
):
    current_user = await _resolve_current_user(authorization)
    return await store.list_projects(page=page, limit=limit, search=search, user_id=current_user.id if current_user else None)


@app.post("/api/projects")
async def create_project(payload: CreateProjectRequest, authorization: Annotated[str | None, Header()] = None):
    raw_name = (payload.name or "").strip()
    resolved_name = raw_name or generate_project_name(payload.description)
    current_user = await _resolve_current_user(authorization)
    project = await store.create_project(resolved_name, payload.description, user_id=current_user.id if current_user else None)
    return {
        "id": project.id,
        "name": project.name,
        "status": project.status,
        "createdAt": project.createdAt,
    }


@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, payload: UpdateProjectRequest, authorization: Annotated[str | None, Header()] = None):
    normalized_name = payload.name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Project name is required")

    await _require_project_access(project_id, authorization)
    project = await store.update_project(project_id, name=normalized_name)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, authorization: Annotated[str | None, Header()] = None):
    project = await _require_project_access(project_id, authorization)

    # 教学注释：
    # 这里先停任务，再删数据。
    # 这样用户确认删除后，不会出现"任务刚被删掉，后台又补写了一条新消息"的反复横跳。
    for task in await store.list_tasks(project_id):
        cancel_running_task_sync(task.id)
    await _cancel_project_scheduled_tasks(project_id)

    deleted = await store.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "deleted"}


@app.post("/api/auth/register", response_model=AuthResponse)
async def register_user(payload: RegisterRequest):
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    if await store.get_temp_user_by_email(email) is not None:
        raise HTTPException(status_code=409, detail="Email is already registered")
    try:
        user = await store.create_temp_user(
            email=email,
            password_hash=_hash_password(payload.password),
            name=payload.name.strip(),
        )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(status_code=409, detail="Email is already registered") from exc
    token = _issue_auth_token(user.id)
    await store.create_auth_token(user.id, token)
    return AuthResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        avatarUrl=user.avatarUrl,
        token=token,
    )


@app.post("/api/auth/login", response_model=AuthResponse)
async def login_user(payload: LoginRequest):
    user = await store.get_temp_user_by_email(payload.email.strip().lower())
    if user is None or not _verify_password(payload.password, user.passwordHash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = _issue_auth_token(user.id)
    await store.create_auth_token(user.id, token)
    return AuthResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        avatarUrl=user.avatarUrl,
        token=token,
    )


@app.get("/api/users/me", response_model=CurrentUserResponse)
async def get_current_user(authorization: Annotated[str | None, Header()] = None):
    user, _ = await _require_current_user(authorization)
    return CurrentUserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        avatarUrl=user.avatarUrl,
    )


@app.post("/api/auth/logout", response_model=LogoutResponse)
async def logout_user(authorization: Annotated[str | None, Header()] = None):
    _, token = await _require_current_user(authorization)
    await store.revoke_auth_token(token)
    return LogoutResponse(message="Logout successful")


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str, authorization: Annotated[str | None, Header()] = None):
    return await _require_project_access(project_id, authorization)


@app.get("/api/projects/{project_id}/modules")
async def list_project_modules(project_id: str):
    if await store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    modules = await store.get_modules(project_id)
    return {
        "modules": [
            {
                "id": module.id,
                "name": module.name,
                "nameEn": module.nameEn,
                "isSelected": module.isSelected,
            }
            for module in modules
        ]
    }


@app.post("/api/projects/{project_id}/modules")
async def update_project_modules(project_id: str, payload: dict[str, list[str]]):
    if await store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    selected_modules = payload.get("selectedModules", [])
    if not isinstance(selected_modules, list):
        raise HTTPException(status_code=400, detail="selectedModules must be a list")
    modules = await store.set_selected_modules(project_id, [str(item) for item in selected_modules])
    return {
        "modules": [
            {
                "id": module.id,
                "name": module.name,
                "nameEn": module.nameEn,
                "isSelected": module.isSelected,
            }
            for module in modules
        ]
    }


@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    projectId: str | None = Form(default=None),
    type: str = Form(default="markdown"),
):
    content = await file.read()
    _validate_uploaded_content(file.filename or "upload.bin", type, content)
    uploaded = await store.create_upload(
        file_name=file.filename or "upload.bin",
        file_type=type,
        file_size=len(content),
        content_preview=_build_upload_preview(file.filename or "upload.bin", type, content),
        project_id=projectId,
    )
    await store.write_upload_content(uploaded.id, content)
    return uploaded


@app.post("/api/projects/{project_id}/generate")
async def generate_project(
    project_id: str,
    payload: GenerateProjectRequest,
    background_tasks: BackgroundTasks,
):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    _log_user_action(
        "generate_project",
        project_id=project_id,
        detail=_preview_log_text(payload.prompt),
        extra={
            "uploaded_file_count": len(payload.uploadedFiles),
            "locale": normalize_locale(payload.locale),
        },
    )
    upload_ids = [str(upload_id) for upload_id in payload.uploadedFiles]
    assigned_uploads = await store.assign_uploads_to_project(upload_ids, project_id)
    if upload_ids and len(assigned_uploads) != len(upload_ids):
        raise HTTPException(
            status_code=400,
            detail="One or more uploaded files could not be linked to this project.",
        )
    task = await store.create_task(
        project_id,
        "generate",
        status="running",
        input_data=_with_locale(
            {
                "prompt": payload.prompt,
                "uploadedFiles": [upload.id for upload in assigned_uploads],
            },
            payload.locale,
        ),
    )
    _spawn_scheduled_app_task(
        start_generate_flow(
            project_id,
            task.id,
            payload.prompt,
            [upload.id for upload in assigned_uploads],
        ),
        task_label="generate",
        project_id=project_id,
        task_id=task.id,
    )
    return {
        "projectId": project_id,
        "taskId": task.id,
        "status": "running",
        "message": "Generation started",
    }


@app.get("/api/projects/{project_id}/messages", response_model=ListMessagesResponse)
async def list_messages(
    project_id: str,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    if await store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    messages, total = await store.list_messages(project_id, page, limit)
    return ListMessagesResponse(messages=messages, total=total)


@app.post("/api/projects/{project_id}/messages")
async def send_message(
    project_id: str,
    payload: SendMessageRequest,
    background_tasks: BackgroundTasks,
):
    logger.info(
        "[API ENTER] send_message project_id=%s type=%s requested_task_id=%s parent_id=%s locale=%s has_response=%s",
        project_id,
        payload.type,
        payload.taskId or "-",
        payload.parentId or "-",
        normalize_locale(payload.locale),
        isinstance(payload.response, dict),
    )
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if payload.type == "text":
        _log_user_action(
            "send_text_message",
            project_id=project_id,
            detail=_preview_log_text(payload.content),
            extra={"locale": normalize_locale(payload.locale)},
        )
        latest_task = await store.get_latest_task(project_id)
        message_metadata: dict[str, object] | None = None
        if latest_task and latest_task.status == "waiting_user":
            confirmation_kind = _task_confirmation_kind(latest_task)
            if confirmation_kind == "artifact_review":
                project_upload_ids = [upload.id for upload in await store.list_project_uploads(project_id)]
                next_task = await store.create_task(
                    project_id,
                    "modify",
                    status="running",
                    input_data=_with_locale(
                        {
                            "prompt": payload.content or "",
                            "uploadedFiles": project_upload_ids,
                        },
                        payload.locale,
                    ),
                    parent_task_id=latest_task.id,
                )
                message_metadata = {
                    "taskId": next_task.id,
                    "taskRoundRole": "anchor",
                }
                message = await store.add_message(
                    Message(
                        projectId=project_id,
                        role="user",
                        type="text",
                        content=payload.content or "",
                        metadata=message_metadata,
                    )
                )
                _spawn_scheduled_app_task(
                    start_modify_flow(
                        project_id,
                        next_task.id,
                        payload.content or "",
                    ),
                    task_label="modify",
                    project_id=project_id,
                    task_id=next_task.id,
                )
            elif confirmation_kind in {"input_variables", "coverage_conflict"}:
                raise HTTPException(
                    status_code=400,
                    detail="The current task requires the active confirmation card instead of a free-form message.",
                )
            elif confirmation_kind == "requirements_feedback":
                raise HTTPException(
                    status_code=400,
                    detail="The current task requires the active feedback form instead of a free-form message.",
                )
            else:
                await _update_task_locale(latest_task.id, payload.locale)
                message_metadata = {"taskId": latest_task.id}
                message = await store.add_message(
                    Message(
                        projectId=project_id,
                        role="user",
                        type="text",
                        content=payload.content or "",
                        metadata=message_metadata,
                    )
                )
                _spawn_scheduled_app_task(
                    continue_after_confirmation(
                        project_id,
                        latest_task.id,
                        [],
                        None,
                        payload.content,
                    ),
                    task_label="confirm-continue",
                    project_id=project_id,
                    task_id=latest_task.id,
                )
        elif latest_task and latest_task.status in {"completed", "failed", "cancelled"}:
            project_upload_ids = [upload.id for upload in await store.list_project_uploads(project_id)]
            next_task = await store.create_task(
                project_id,
                "modify",
                status="running",
                input_data=_with_locale(
                    {
                        "prompt": payload.content or "",
                        "uploadedFiles": project_upload_ids,
                    },
                    payload.locale,
                ),
                parent_task_id=latest_task.id,
            )
            message_metadata = {
                "taskId": next_task.id,
                "taskRoundRole": "anchor",
            }
            message = await store.add_message(
                Message(
                    projectId=project_id,
                    role="user",
                    type="text",
                    content=payload.content or "",
                    metadata=message_metadata,
                )
            )
            _spawn_scheduled_app_task(
                start_modify_flow(
                    project_id,
                    next_task.id,
                    payload.content or "",
                ),
                task_label="modify",
                project_id=project_id,
                task_id=next_task.id,
            )
        else:
            message = await store.add_message(
                Message(
                    projectId=project_id,
                    role="user",
                    type="text",
                    content=payload.content or "",
                    metadata=message_metadata,
                )
            )
        return message

    logger.info(
        "[API STEP] send_message_before_add_user_response project_id=%s requested_task_id=%s",
        project_id,
        payload.taskId or "-",
    )
    message = await store.add_message(
        Message(
            projectId=project_id,
            role="user",
            type="user_response",
            content=payload.content or "The user submitted a response.",
            metadata=payload.response,
            parentId=payload.parentId,
        )
    )
    logger.info(
        "[API STEP] send_message_after_add_user_response project_id=%s message_id=%s",
        project_id,
        message.id,
    )
    variables = payload.response.get("variables") if isinstance(payload.response, dict) else None
    feedback_preview = ""
    if isinstance(variables, dict):
        feedback_preview = str(variables.get("feedback") or "").strip()
    logger.info(
        "[USER ACTION] user_response_received project_id=%s requested_task_id=%s locale=%s skip=%s content=%s feedback=%s response_keys=%s",
        project_id,
        payload.taskId or "-",
        normalize_locale(payload.locale),
        bool(isinstance(payload.response, dict) and payload.response.get("skip")),
        _preview_log_text(payload.content),
        _preview_log_text(feedback_preview),
        sorted(payload.response.keys()) if isinstance(payload.response, dict) else [],
    )
    logger.info(
        "[API STEP] send_message_before_resolve_task project_id=%s requested_task_id=%s",
        project_id,
        payload.taskId or "-",
    )
    latest_task = await _resolve_user_response_task(project_id, payload.taskId)
    logger.info(
        "[USER ACTION] user_response_resolved project_id=%s requested_task_id=%s resolved_task_id=%s resolved_status=%s resolved_confirmation_kind=%s",
        project_id,
        payload.taskId or "-",
        latest_task.id if latest_task is not None else "-",
        latest_task.status if latest_task is not None else "-",
        _task_confirmation_kind(latest_task) or "-",
    )
    if latest_task is None or latest_task.status != "waiting_user":
        logger.warning(
            "[USER ACTION] submit_user_response_ignored project_id=%s requested_task_id=%s resolved_task_id=%s resolved_status=%s",
            project_id,
            payload.taskId or "-",
            latest_task.id if latest_task is not None else "-",
            latest_task.status if latest_task is not None else "-",
        )
        raise _user_response_context_missing_http_error()

    await _update_task_locale(latest_task.id, payload.locale)
    confirmation_kind = _task_confirmation_kind(latest_task)
    _log_user_action(
        "submit_user_response",
        project_id=project_id,
        task_id=latest_task.id,
        detail=_preview_log_text(payload.content),
        extra={
            "requested_task_id": payload.taskId or "",
            "confirmation_kind": confirmation_kind or "",
            "locale": normalize_locale(payload.locale),
            "response_keys": sorted(payload.response.keys()) if isinstance(payload.response, dict) else [],
        },
    )
    if confirmation_kind == "requirements_feedback":
        feedback_text = ""
        if isinstance(variables, dict):
            feedback_text = str(variables.get("feedback") or "").strip()
        feedback_text = _normalize_requirements_feedback_text(
            feedback_text=feedback_text,
            fallback_content=str(payload.content or "").strip(),
            skip=bool(isinstance(payload.response, dict) and payload.response.get("skip")),
        )
        await submit_requirements_feedback(project_id, latest_task.id, feedback_text or "no")
    else:
        selected_ids = []
        if payload.response:
            selected_ids = payload.response.get("selectedIds", [])
        _spawn_scheduled_app_task(
            continue_after_confirmation(
                project_id,
                latest_task.id,
                selected_ids,
                payload.response,
            ),
            task_label="confirm-continue",
            project_id=project_id,
            task_id=latest_task.id,
        )
    return message


@app.get("/api/projects/{project_id}/tasks", response_model=ListTasksResponse)
async def list_generation_tasks(project_id: str):
    if await store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ListTasksResponse(tasks=await store.list_generation_tasks(project_id))


@app.get("/api/projects/{project_id}/statistics", response_model=StatisticsResponse)
async def get_statistics(project_id: str, task_id: str | None = None):
    if await store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    task = await store.get_task(task_id) if task_id else await store.get_latest_task(project_id)
    if task is None:
        if task_id:
            raise HTTPException(status_code=404, detail="Task not found")
        return _empty_statistics_response()
    payload = await _statistics_payload(task.id)
    if payload is None:
        return _empty_statistics_response(started_at=task.startedAt or task.createdAt)
    return payload


@app.get("/api/projects/{project_id}/steps", response_model=StepsResponse)
async def get_steps(project_id: str, task_id: str | None = None):
    if await store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    task = await store.get_task(task_id) if task_id else await store.get_latest_task(project_id)
    if task is None:
        if task_id:
            raise HTTPException(status_code=404, detail="Task not found")
        return StepsResponse(steps=[])
    return StepsResponse(steps=await store.list_step_records(task.id))


@app.get("/api/projects/{project_id}/agent-artifacts", response_model=AgentArtifactsResponse)
async def list_agent_artifacts(project_id: str, version: int | None = None):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    resolved_version = version if version is not None else project.currentVersion
    grouped: dict[str, list[object]] = {}
    for artifact in await store.list_agent_artifacts(project_id, version=resolved_version):
        grouped.setdefault(artifact.agent, []).append(artifact)
    return AgentArtifactsResponse(projectId=project_id, version=resolved_version, artifactsByAgent=grouped)


@app.get("/api/projects/{project_id}/agent-artifacts/{agent_name}", response_model=AgentArtifactsByAgentResponse)
async def list_agent_artifacts_by_agent(project_id: str, agent_name: str, version: int | None = None):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    resolved_version = version if version is not None else project.currentVersion
    return AgentArtifactsByAgentResponse(
        projectId=project_id,
        version=resolved_version,
        agent=agent_name,
        artifacts=await store.list_agent_artifacts(project_id, version=resolved_version, agent_name=agent_name),
    )


@app.get("/api/projects/{project_id}/agent-artifacts/{agent_name}/{file_name:path}")
async def get_agent_artifact(project_id: str, agent_name: str, file_name: str, version: int | None = None):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    resolved_version = version if version is not None else project.currentVersion
    artifact = await store.get_agent_artifact(project_id, agent_name, file_name, version=resolved_version)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Agent artifact not found")
    return artifact


@app.post("/api/projects/{project_id}/confirm")
async def confirm_continue(
    project_id: str,
    payload: ConfirmProjectRequest,
    background_tasks: BackgroundTasks,
):
    task = await store.get_task(payload.taskId)
    if task is None or task.projectId != project_id:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status == "running" and await restore_waiting_task_from_interaction_message(project_id, task.id):
        task = await store.get_task(task.id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "waiting_user":
        task_output_data = task.outputData if isinstance(task.outputData, dict) else {}
        if task_output_data.get("confirmationAcceptedAt"):
            raise HTTPException(status_code=409, detail=f"Confirmation already accepted; task is now {task.status}.")
        raise HTTPException(status_code=400, detail="Task is not waiting for confirmation")
    await _update_task_locale(task.id, payload.locale)
    _log_user_action(
        "confirm_continue",
        project_id=project_id,
        task_id=task.id,
        extra={
            "confirmation_kind": _task_confirmation_kind(task) or "",
            "selected_ids": payload.data.get("selectedIds", []),
            "locale": normalize_locale(payload.locale),
        },
    )
    selected_ids = payload.data.get("selectedIds", [])
    if _task_active_phase(task) == "waiting_for_module_confirmation":
        selected_ids = []
    next_output_data = dict(task.outputData) if isinstance(task.outputData, dict) else {}
    next_output_data["confirmationAcceptedAt"] = utc_now().isoformat()
    claimed_task = await store.transition_task_status_if_current(
        task.id,
        expected_status="waiting_user",
        next_status="running",
        output_data=next_output_data,
    )
    if claimed_task is None:
        latest_task = await store.get_task(task.id)
        latest_status = latest_task.status if latest_task is not None else "unknown"
        raise HTTPException(status_code=409, detail=f"Confirmation already accepted; task is now {latest_status}.")
    _spawn_scheduled_app_task(
        continue_after_confirmation(
            project_id,
            task.id,
            selected_ids,
            payload.data,
        ),
        task_label="confirm-continue",
        project_id=project_id,
        task_id=task.id,
    )
    return {"status": "confirmed", "nextStep": "running"}


@app.post("/api/projects/{project_id}/modify")
async def modify_project(
    project_id: str,
    payload: ModifyProjectRequest,
    background_tasks: BackgroundTasks,
):
    task = await store.get_task(payload.taskId)
    if task is None or task.projectId != project_id:
        raise HTTPException(status_code=404, detail="Task not found")
    _log_user_action(
        "modify_project",
        project_id=project_id,
        task_id=payload.taskId,
        detail=_preview_log_text(payload.content),
        extra={"locale": normalize_locale(payload.locale)},
    )
    confirmation_kind = _task_confirmation_kind(task)
    active_phase = _task_active_phase(task)
    if confirmation_kind == "artifact_review":
        project_upload_ids = [upload.id for upload in await store.list_project_uploads(project_id)]
        next_task = await store.create_task(
            project_id,
            "modify",
            status="running",
            input_data=_with_locale(
                {
                    "prompt": payload.content,
                    "uploadedFiles": project_upload_ids,
                },
                payload.locale,
            ),
            parent_task_id=task.id,
        )
        _spawn_scheduled_app_task(
            start_modify_flow(
                project_id,
                next_task.id,
                payload.content,
            ),
            task_label="modify",
            project_id=project_id,
            task_id=next_task.id,
        )
    elif active_phase == "waiting_for_module_confirmation":
        project_upload_ids = task.inputData.get("uploadedFiles", []) if isinstance(task.inputData, dict) else []
        base_prompt = str(task.inputData.get("prompt") or "") if isinstance(task.inputData, dict) else ""
        regenerated_prompt = _build_feature_tree_regeneration_prompt(base_prompt, payload.content)
        next_task = await store.create_task(
            project_id,
            "generate",
            status="running",
            input_data=_with_locale(
                {
                    "prompt": regenerated_prompt,
                    "uploadedFiles": project_upload_ids if isinstance(project_upload_ids, list) else [],
                },
                payload.locale,
            ),
            parent_task_id=task.id,
        )
        _spawn_scheduled_app_task(
            start_generate_flow(
                project_id,
                next_task.id,
                regenerated_prompt,
                project_upload_ids if isinstance(project_upload_ids, list) else [],
            ),
            task_label="generate",
            project_id=project_id,
            task_id=next_task.id,
        )
    else:
        await _update_task_locale(task.id, payload.locale)
        _spawn_scheduled_app_task(
            continue_after_confirmation(
                project_id,
                task.id,
                [],
                None,
                payload.content,
            ),
            task_label="confirm-continue",
            project_id=project_id,
            task_id=task.id,
        )
    return {"status": "running", "message": "Modification accepted"}


@app.post("/api/projects/{project_id}/tasks/{task_id}/cancel")
async def cancel_project_task(project_id: str, task_id: str):
    task = await store.get_task(task_id)
    if task is None or task.projectId != project_id:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in {"running", "waiting_user"}:
        raise HTTPException(status_code=400, detail=f"Task status is {task.status}; it cannot be cancelled.")
    await cancel_task(project_id, task_id)
    return {"status": "cancelled", "message": "Task cancelled"}


@app.post("/api/projects/{project_id}/tasks/{task_id}/retry")
async def retry_project_task(
    project_id: str,
    task_id: str,
    background_tasks: BackgroundTasks,
):
    original = await store.get_task(task_id)
    if original is None or original.projectId != project_id:
        raise HTTPException(status_code=404, detail="Task not found")
    if original.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Only failed or cancelled tasks can be retried.")
    if original.taskType not in {"generate", "modify", "regenerate", "rollback"}:
        raise HTTPException(
            status_code=400,
            detail={
                "errorType": "CONTEXT_EXPIRED",
                "message": f"Retry is not implemented for task type `{original.taskType}`.",
            },
        )
    retry_output_data: dict[str, object] = {}
    retry_start_stage: str | None = None
    if original.taskType == "generate":
        original_output = original.outputData if isinstance(original.outputData, dict) else {}
        await _checkpoint_unversioned_current_snapshot(
            project_id,
            version_kind="generation",
            description="Saved the latest failed generation snapshot before retrying the task.",
            source_version=(
                int(original_output.get("codeGenerationSourceVersion"))
                if isinstance(original_output.get("codeGenerationSourceVersion"), int)
                else None
            ),
            created_by_type="system",
            created_by="retry_preflight",
        )
        retry_plan = await _build_generate_resume_plan(project_id, task_id)
        retry_output_data.update(retry_plan)
        retry_start_stage = str(retry_plan.get("resumeFromStage") or "requirements_analysis")

    new_task = await store.create_task(
        project_id,
        original.taskType,
        status="running",
        input_data=original.inputData,
        parent_task_id=original.id,
    )
    if retry_output_data:
        await store.update_task(new_task.id, output_data=retry_output_data)
    _schedule_retry_task(
        project_id=project_id,
        new_task_id=new_task.id,
        task_type=original.taskType,
        input_data=original.inputData,
        start_stage=retry_start_stage,
    )
    return {"taskId": new_task.id, "status": "running"}


@app.get("/api/projects/{project_id}/task/current", response_model=CurrentTaskResponse)
async def get_current_task(project_id: str):
    if await store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    task = await store.get_latest_task(project_id)
    if task is None:
        return CurrentTaskResponse(task=None, status="idle")

    response = CurrentTaskResponse(task=task, status=task.status, round=await _task_round_snapshot(project_id, task))
    if task.status == "waiting_user":
        response.confirmationData = task.outputData
    if task.status in {"running", "waiting_user", "completed", "failed", "cancelled"}:
        try:
            response.statistics = await get_statistics(project_id, task.id)
        except HTTPException:
            response.statistics = None
    response.activeAgent, response.activePhase, response.agentOutputsReady = await _task_activity_payload(project_id, task)
    response.pendingAgentArtifactsVersion = await _task_pending_agent_artifacts_version(project_id, task)
    response.plannedArtifactFiles = await build_planned_artifact_files_for_task(project_id, task)
    return response


@app.post("/api/projects/{project_id}/artifacts/architecture/generate")
async def regenerate_architecture_artifact(
    project_id: str,
    background_tasks: BackgroundTasks,
):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    project_upload_ids = [upload.id for upload in await store.list_project_uploads(project_id)]
    latest_task = await store.get_latest_task(project_id)
    next_task = await store.create_task(
        project_id,
        "regenerate",
        status="running",
        input_data=_with_locale(
            {
                "prompt": (
                    "Regenerate the architecture draft for the current project. "
                    "Keep the implementation aligned with the latest confirmed requirements and existing artifacts."
                ),
                "uploadedFiles": project_upload_ids,
            },
            latest_task.inputData.get("locale") if latest_task else None,
        ),
        parent_task_id=latest_task.id if latest_task else None,
    )
    _spawn_scheduled_app_task(
        start_modify_flow(
            project_id,
            next_task.id,
            "Regenerate the architecture draft for the current project and keep the rest consistent.",
        ),
        task_label="regenerate",
        project_id=project_id,
        task_id=next_task.id,
    )
    return {
        "status": "generating",
        "message": "Architecture generation started",
        "taskId": next_task.id,
    }


@app.get("/api/projects/{project_id}/artifacts/api-specs")
async def get_api_specs(project_id: str, version: Annotated[int | None, Query(ge=1)] = None):
    if await store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if version is not None and not await _artifact_exists_in_exact_snapshot(project_id, version, "api_spec"):
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact = await store.get_artifact(project_id, "api_spec", version=version)
    if artifact is not None and version is not None and artifact.version != version:
        artifact = None
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    payload = await _artifact_response(project_id, artifact)
    payload["format"] = "yaml"
    return payload


@app.get("/api/projects/{project_id}/artifacts/{artifact_type}")
async def get_artifact(
    project_id: str,
    artifact_type: str,
    version: Annotated[int | None, Query(ge=1)] = None,
):
    if await store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    normalized_type = _normalize_artifact_type(artifact_type)  # type: ignore[arg-type]
    if version is not None and not await _artifact_exists_in_exact_snapshot(project_id, version, normalized_type):
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact = await store.get_artifact(
        project_id,
        normalized_type,
        version=version,
    )
    if artifact is not None and version is not None and artifact.version != version:
        artifact = None
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return await _artifact_response(project_id, artifact)


@app.put("/api/projects/{project_id}/artifacts/prd")
async def update_prd_artifact(project_id: str, payload: UpdateArtifactRequest):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    existing = await store.get_artifact(project_id, "prd")
    if existing is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    base_version = existing.version
    base_artifacts = await _load_exact_artifacts_snapshot(project_id, base_version)
    next_artifacts = []
    for artifact in base_artifacts:
        if artifact.type == "prd":
            artifact.content = payload.content
        next_artifacts.append(artifact)

    next_files = []
    for code_file in await _load_exact_code_snapshot(project_id, base_version):
        next_files.append(
            {
                "filePath": code_file.filePath,
                "content": payload.content if code_file.filePath == "docs/PRD.md" else code_file.content,
            }
        )
    next_project, version = await _create_project_snapshot(
        project_id,
        version_kind="artifact_edit",
        description="Updated PRD in edit mode.",
        changes=None,
        source_version=base_version,
        created_by_type="user",
        artifacts=next_artifacts,
        code_files=next_files,
        agent_artifacts_by_agent=await _load_exact_agent_outputs_snapshot(project_id, base_version),
        modules_snapshot=await _load_exact_modules_snapshot(project_id, base_version),
    )
    updated = await store.get_artifact(project_id, "prd", version=next_project.currentVersion)
    if updated is None:
        raise HTTPException(status_code=500, detail="Updated artifact could not be loaded")
    await store.touch_project(project_id, status="completed")

    await ws_manager.broadcast(
        project_id,
        _event(
            "artifact_update",
            {
                "artifactType": updated.type,
                "version": updated.version,
                "action": "edited",
            },
        ),
    )
    await ws_manager.broadcast(
        project_id,
        _event(
            "version_update",
            version.model_dump(mode="json"),
        ),
    )
    return updated


@app.get("/api/projects/{project_id}/versions", response_model=VersionsResponse)
async def list_versions(project_id: str):
    if await store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"versions": [_serialize_version_record(version) for version in await store.list_versions(project_id)]}


@app.post("/api/projects/{project_id}/versions/{version}/rollback")
async def rollback_project_version(project_id: str, version: int):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    versions = await store.list_versions(project_id)
    if not any(checkpoint.version == version for checkpoint in versions):
        raise HTTPException(
            status_code=404,
            detail={
                "errorType": "ROLLBACK_FAILED",
                "message": f"Version {version} was not found for this project.",
            },
        )
    latest_task = await store.get_latest_task(project_id)
    rollback_task = await store.create_task(
        project_id,
        "rollback",
        status="running",
        input_data=_with_locale(
            {"sourceVersion": version},
            latest_task.inputData.get("locale") if latest_task else None,
        ),
        parent_task_id=latest_task.id if latest_task else None,
    )

    return await execute_rollback_task(project_id, rollback_task.id, version)


@app.get("/api/projects/{project_id}/files")
async def list_project_files(project_id: str, version: Annotated[int | None, Query(ge=1)] = None):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    resolved_version = version or project.currentVersion
    files = await _unified_file_entries(project_id, resolved_version)
    return {
        "projectId": project_id,
        "version": resolved_version,
        "tree": _build_code_tree([str(item["path"]) for item in files]),
        "files": files,
    }


@app.get("/api/projects/{project_id}/files/{file_path:path}")
async def get_project_file(project_id: str, file_path: str, version: Annotated[int | None, Query(ge=1)] = None):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    resolved_version = version or project.currentVersion
    payload = await _unified_file_content(project_id, resolved_version, file_path)
    if payload is None:
        raise HTTPException(status_code=404, detail="Project file not found")
    return payload


@app.get("/api/projects/{project_id}/drafts")
async def list_project_file_drafts(project_id: str):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    drafts = await store.list_project_file_drafts(project_id)
    base_versions = sorted({draft.baseVersion for draft in drafts})
    return {
        "projectId": project_id,
        "baseVersion": base_versions[0] if base_versions else project.currentVersion,
        "currentVersion": project.currentVersion,
        "totalFiles": len(drafts),
        "files": [
            {
                "path": draft.filePath,
                "fileName": draft.filePath.split("/")[-1],
                "stage": draft.stage,
                "sourceType": draft.sourceType,
                "baseVersion": draft.baseVersion,
                "updatedAt": draft.updatedAt,
                "updatedBy": draft.updatedBy,
            }
            for draft in drafts
        ],
    }


@app.put("/api/projects/{project_id}/files/{file_path:path}/draft")
async def save_project_file_draft(project_id: str, file_path: str, payload: UpdateProjectFileDraftRequest):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    base_version = payload.version or project.currentVersion
    existing_file = await _unified_file_content(project_id, base_version, file_path)
    if existing_file is None:
        raise HTTPException(status_code=404, detail="Project file not found")

    existing_drafts = await store.list_project_file_drafts(project_id)
    existing_base_versions = {draft.baseVersion for draft in existing_drafts}
    if existing_base_versions and (len(existing_base_versions) > 1 or base_version not in existing_base_versions):
        raise HTTPException(
            status_code=409,
            detail="Project drafts were created from a different base version. Please commit or discard them first.",
        )
    if existing_base_versions and project.currentVersion not in existing_base_versions:
        raise HTTPException(
            status_code=409,
            detail="Project version changed after these drafts were created. Please commit or discard them first.",
        )

    normalized_path = str(file_path or "").strip().replace("\\", "/")
    await store.upsert_project_file_draft(
        project_id,
        normalized_path,
        content=payload.content,
        base_version=base_version,
        stage=str(existing_file.get("stage") or ""),
        source_type=str(existing_file.get("sourceType") or ""),
        updated_by=payload.userId,
    )
    updated_file = await _unified_file_content(project_id, project.currentVersion, normalized_path)
    if updated_file is None:
        raise HTTPException(status_code=500, detail="Draft file could not be loaded")
    return updated_file


@app.delete("/api/projects/{project_id}/files/{file_path:path}/draft")
async def discard_project_file_draft(project_id: str, file_path: str):
    if await store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    normalized_path = str(file_path or "").strip().replace("\\", "/")
    deleted = await store.delete_project_file_draft(project_id, normalized_path)
    return {"status": "discarded" if deleted else "missing", "filePath": normalized_path}


@app.post("/api/projects/{project_id}/drafts/commit")
async def commit_project_file_drafts(project_id: str, payload: CommitProjectDraftsRequest):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    drafts = await store.list_project_file_drafts(project_id)
    if not drafts:
        raise HTTPException(status_code=400, detail="No project drafts are available to commit")

    base_versions = sorted({draft.baseVersion for draft in drafts})
    if len(base_versions) != 1:
        raise HTTPException(status_code=409, detail="Project drafts have multiple base versions and cannot be committed together")
    base_version = base_versions[0]
    if base_version != project.currentVersion:
        raise HTTPException(status_code=409, detail="Project version changed after these drafts were created. Please review and re-save the drafts.")

    next_artifacts = list(await _load_exact_artifacts_snapshot(project_id, base_version))
    next_code_files = [
        {
            "filePath": record.filePath,
            "content": record.content,
        }
        for record in await _load_exact_code_snapshot(project_id, base_version)
    ]
    next_agent_outputs = {
        agent_name: list(records)
        for agent_name, records in (await _load_exact_agent_outputs_snapshot(project_id, base_version)).items()
    }
    modules_snapshot = await _load_exact_modules_snapshot(project_id, base_version)

    committed_paths: list[str] = []
    for draft in drafts:
        await _apply_project_file_change_to_snapshots(
            project_id=project_id,
            project_description=project.description,
            normalized_path=draft.filePath,
            content=draft.content,
            next_artifacts=next_artifacts,
            next_code_files=next_code_files,
            next_agent_outputs=next_agent_outputs,
            modules_snapshot=modules_snapshot,
        )
        committed_paths.append(draft.filePath)

    updated_project, version_record = await _create_project_snapshot(
        project_id,
        version_kind="file_edit",
        description=payload.description or f"Committed {len(committed_paths)} project draft file(s).",
        changes=None,
        source_version=base_version,
        created_by_type="user",
        created_by=payload.userId,
        artifacts=next_artifacts,
        code_files=next_code_files,
        agent_artifacts_by_agent=next_agent_outputs,
        modules_snapshot=modules_snapshot,
    )
    await store.clear_project_file_drafts(project_id)
    await ws_manager.broadcast(
        project_id,
        _event(
            "version_update",
            version_record.model_dump(mode="json"),
        ),
    )
    return {
        "status": "success",
        "projectId": project_id,
        "baseVersion": base_version,
        "newVersion": updated_project.currentVersion,
        "committedPaths": sorted(committed_paths),
    }


@app.put("/api/projects/{project_id}/files/{file_path:path}")
async def update_project_file(project_id: str, file_path: str, payload: UpdateCodeFileRequest):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    base_version = payload.version or project.currentVersion
    existing_file = await _unified_file_content(project_id, base_version, file_path)
    if existing_file is None:
        raise HTTPException(status_code=404, detail="Project file not found")

    exact_artifacts = await _load_exact_artifacts_snapshot(project_id, base_version)
    next_artifacts = list(exact_artifacts)
    exact_code_files = await _load_exact_code_snapshot(project_id, base_version)
    next_code_files = [
        {
            "filePath": record.filePath,
            "content": record.content,
        }
        for record in exact_code_files
    ]
    exact_agent_outputs = await _load_exact_agent_outputs_snapshot(project_id, base_version)
    next_agent_outputs = {
        agent_name: list(records)
        for agent_name, records in exact_agent_outputs.items()
    }
    modules_snapshot = await _load_exact_modules_snapshot(project_id, base_version)

    normalized_path = str(file_path or "").strip().replace("\\", "/")
    await _apply_project_file_change_to_snapshots(
        project_id=project_id,
        project_description=project.description,
        normalized_path=normalized_path,
        content=payload.content,
        next_artifacts=next_artifacts,
        next_code_files=next_code_files,
        next_agent_outputs=next_agent_outputs,
        modules_snapshot=modules_snapshot,
    )

    updated_project, _version_record = await _create_project_snapshot(
        project_id,
        version_kind="file_edit",
        description=f"Updated {normalized_path} from version {base_version}.",
        changes=None,
        source_version=base_version,
        created_by_type="user",
        created_by=payload.userId,
        artifacts=next_artifacts,
        code_files=next_code_files,
        agent_artifacts_by_agent=next_agent_outputs,
        modules_snapshot=modules_snapshot,
    )

    updated_file = await _unified_file_content(project_id, updated_project.currentVersion, normalized_path)
    if updated_file is None:
        raise HTTPException(status_code=500, detail="Updated project file could not be loaded")
    await ws_manager.broadcast(
        project_id,
        _event(
            "version_update",
            (await store.get_version_record(project_id, updated_project.currentVersion)).model_dump(mode="json"),
        ),
    )
    return updated_file


@app.get("/api/projects/{project_id}/code/files")
async def list_code_files(project_id: str, version: Annotated[int | None, Query(ge=1)] = None):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    resolved_version = version or project.currentVersion
    files = await _load_exact_code_snapshot(project_id, resolved_version)
    if not files:
        return {
            "projectId": project_id,
            "version": resolved_version,
            "tree": [],
        }
    return {
        "projectId": project_id,
        "version": resolved_version,
        "tree": _build_code_tree([file.filePath for file in files]),
    }


@app.get("/api/projects/{project_id}/code/files/{file_path:path}")
async def get_code_file(project_id: str, file_path: str, version: Annotated[int | None, Query(ge=1)] = None):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    resolved_version = version or project.currentVersion
    if version is not None and not await _code_file_exists_in_exact_snapshot(project_id, resolved_version, file_path):
        raise HTTPException(status_code=404, detail="Code file not found")
    record = await store.get_code_file(project_id, file_path, version=resolved_version)
    if record is not None and version is not None and record.version != resolved_version:
        record = None
    if record is None:
        raise HTTPException(status_code=404, detail="Code file not found")
    payload = _code_file_response(record)
    draft = await _workspace_draft_for_version(project_id, resolved_version, file_path)
    if draft is not None:
        payload["content"] = draft.content
        payload["lineCount"] = len(draft.content.splitlines()) if draft.content else 0
        payload["updatedAt"] = draft.updatedAt
        payload.update(_draft_overlay_fields(draft))
    payload["lock"] = _serialize_code_file_lock(await store.get_code_file_lock(project_id, file_path))
    return payload


@app.post("/api/projects/{project_id}/code/files/{file_path:path}/lock")
async def acquire_code_file_lock(project_id: str, file_path: str, payload: CodeFileLockRequest):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    record = await store.get_code_file(project_id, file_path, version=payload.version or project.currentVersion)
    if record is None:
        raise HTTPException(status_code=404, detail="Code file not found")
    lock, is_conflict = await store.acquire_code_file_lock(project_id, file_path, record.version, payload.userId)
    if is_conflict:
        raise HTTPException(
            status_code=409,
            detail={
                "errorType": "CODE_FILE_LOCKED",
                "message": f"{file_path} is currently being edited by {lock.lockedBy}.",
                "lock": _serialize_code_file_lock(lock),
            },
        )
    return {
        "filePath": record.filePath,
        "version": record.version,
        "lockedBy": lock.lockedBy,
        "lockedAt": lock.lockedAt,
        "updatedAt": lock.updatedAt,
        "isConflict": False,
    }


@app.delete("/api/projects/{project_id}/code/files/{file_path:path}/lock")
async def release_code_file_lock(
    project_id: str,
    file_path: str,
    userId: str,
):
    if await store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    released = await store.release_code_file_lock(project_id, file_path, userId)
    return {
        "status": "released" if released else "noop",
        "filePath": file_path,
    }


@app.put("/api/projects/{project_id}/code/files/{file_path:path}/autosave")
async def autosave_code_file(project_id: str, file_path: str, payload: UpdateCodeFileRequest):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if payload.userId is None or not payload.userId.strip():
        raise HTTPException(
            status_code=409,
            detail={
                "errorType": "CODE_FILE_LOCK_REQUIRED",
                "message": "Autosave requires an active editor lock.",
            },
        )
    target_version = payload.version or project.currentVersion
    if target_version != project.currentVersion:
        raise HTTPException(
            status_code=409,
            detail={
                "errorType": "AUTOSAVE_REQUIRES_CURRENT_VERSION",
                "message": "Autosave only supports the current project version.",
            },
        )

    lock = await store.touch_code_file_lock(project_id, file_path, payload.userId, target_version)
    if lock is None:
        raise HTTPException(
            status_code=409,
            detail={
                "errorType": "CODE_FILE_LOCK_REQUIRED",
                "message": "Autosave requires an active editor lock.",
            },
        )

    source_record = await store.get_code_file(project_id, file_path, version=project.currentVersion)
    if source_record is None or source_record.version != project.currentVersion:
        raise HTTPException(status_code=404, detail="Code file not found")

    base_snapshot = await _load_exact_code_snapshot(project_id, project.currentVersion)
    if not base_snapshot:
        raise HTTPException(status_code=404, detail="Code files not found")

    next_files: list[dict[str, str]] = []
    for code_file in base_snapshot:
        next_files.append(
            {
                "filePath": code_file.filePath,
                "content": payload.content if code_file.filePath == file_path else code_file.content,
            }
        )
    await store.replace_code_files(project_id, project.currentVersion, next_files)
    if file_path in ARTIFACT_CODE_PATHS:
        await _broadcast_artifact_snapshot(
            project_id,
            project.currentVersion,
            override_path=file_path,
            override_content=payload.content,
        )
    updated_record = await store.get_code_file(project_id, file_path, version=project.currentVersion)
    if updated_record is None:
        raise HTTPException(status_code=500, detail="Autosaved code file could not be loaded")
    response = _code_file_response(updated_record)
    response["lock"] = _serialize_code_file_lock(
        await store.touch_code_file_lock(project_id, file_path, payload.userId, updated_record.version)
    )
    return response


@app.put("/api/projects/{project_id}/code/files/{file_path:path}")
async def update_code_file(project_id: str, file_path: str, payload: UpdateCodeFileRequest):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    base_version = payload.version or project.currentVersion
    if not await _code_file_exists_in_exact_snapshot(project_id, base_version, file_path):
        raise HTTPException(status_code=404, detail="Code file not found")
    source_record = await store.get_code_file(project_id, file_path, version=base_version)
    if source_record is None or source_record.version != base_version:
        raise HTTPException(status_code=404, detail="Code file not found")

    base_snapshot = await _load_exact_code_snapshot(project_id, base_version)
    if not base_snapshot:
        raise HTTPException(status_code=404, detail="Code files not found")

    next_files: list[dict[str, str]] = []
    for code_file in base_snapshot:
        next_files.append(
            {
                "filePath": code_file.filePath,
                "content": payload.content if code_file.filePath == file_path else code_file.content,
            }
        )

    exact_artifacts = await _load_exact_artifacts_snapshot(project_id, base_version)
    next_artifacts = []
    for artifact in exact_artifacts:
        if ARTIFACT_CODE_PATHS.get(file_path) == artifact.type:
            artifact.content = payload.content
        next_artifacts.append(artifact)

    updated_project, version_record = await _create_project_snapshot(
        project_id,
        version_kind="code_edit",
        description=f"Updated {file_path} from version {base_version}.",
        changes=None,
        source_version=base_version,
        created_by_type="user",
        created_by=payload.userId,
        artifacts=next_artifacts,
        code_files=next_files,
        agent_artifacts_by_agent=await _load_exact_agent_outputs_snapshot(project_id, base_version),
        modules_snapshot=await _load_exact_modules_snapshot(project_id, base_version),
    )
    if file_path in ARTIFACT_CODE_PATHS:
        await _broadcast_artifact_snapshot(
            project_id,
            updated_project.currentVersion,
            override_path=file_path,
            override_content=payload.content,
        )
    await store.touch_project(project_id, status="completed")
    await ws_manager.broadcast(
        project_id,
        _event(
            "version_update",
            version_record.model_dump(mode="json"),
        ),
    )
    updated_record = await store.get_code_file(project_id, file_path, version=updated_project.currentVersion)
    if updated_record is None:
        raise HTTPException(status_code=500, detail="Updated code file could not be loaded")
    response = _code_file_response(updated_record)
    if payload.userId:
        response["lock"] = _serialize_code_file_lock(
            await store.touch_code_file_lock(project_id, file_path, payload.userId, updated_record.version)
        )
    else:
        response["lock"] = _serialize_code_file_lock(await store.get_code_file_lock(project_id, file_path))
    return response


@app.get("/api/projects/{project_id}/code/modules")
async def list_code_modules(project_id: str, version: Annotated[int | None, Query(ge=1)] = None):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    resolved_version = version or project.currentVersion
    code_files = await _load_exact_code_snapshot(project_id, resolved_version)
    if not code_files:
        return {"modules": []}

    if version is None:
        modules = [module for module in await store.get_modules(project_id) if module.isSelected]
    else:
        modules = [
            module
            for module in await _load_exact_modules_snapshot(project_id, resolved_version)
            if bool(module.get("isSelected"))
        ]
    payload: list[dict[str, object]] = []
    for module in modules:
        module_id = module.id if hasattr(module, "id") else str(module.get("id") or "")
        module_name = module.name if hasattr(module, "name") else str(module.get("name") or module.get("id") or "")
        folder_path = _module_folder_path(module_id)
        module_files = [code_file for code_file in code_files if code_file.filePath.startswith(f"{folder_path}/")]
        payload.append(
            {
                "id": module_id,
                "name": module_name,
                "nameEn": module_id,
                "folderPath": folder_path,
                "fileCount": len(module_files),
                "lineCount": sum(len(code_file.content.splitlines()) for code_file in module_files if code_file.content),
            }
        )

    payload.sort(key=lambda item: str(item["folderPath"]))
    return {"modules": payload}


@app.get("/api/projects/{project_id}/code/preview/{file_path:path}", response_class=HTMLResponse)
async def preview_code_file(project_id: str, file_path: str, version: Annotated[int | None, Query(ge=1)] = None):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not file_path.lower().endswith((".html", ".htm")):
        raise HTTPException(status_code=400, detail="Only HTML files support inline preview.")
    resolved_version = version or project.currentVersion
    if version is not None and not await _code_file_exists_in_exact_snapshot(project_id, resolved_version, file_path):
        raise HTTPException(status_code=404, detail="Code file not found")
    record = await store.get_code_file(project_id, file_path, version=resolved_version)
    if record is not None and version is not None and record.version != resolved_version:
        record = None
    if record is None:
        raise HTTPException(status_code=404, detail="Code file not found")
    draft = await _workspace_draft_for_version(project_id, resolved_version, file_path)
    return HTMLResponse(draft.content if draft is not None else record.content)


@app.get("/api/projects/{project_id}/code/download")
async def download_code_snapshot(project_id: str, version: Annotated[int | None, Query(ge=1)] = None):
    project = await store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    resolved_version, entries = await _download_bundle_entries(project_id, version=version)
    if not entries:
        raise HTTPException(status_code=404, detail="No downloadable code or docs found")

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for archive_path, content in entries:
            archive.writestr(archive_path, content)

    filename = f"{project.name or 'project'}-v{resolved_version}.zip".replace("/", "-")
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": _download_content_disposition(filename),
        },
    )


@app.get("/api/projects/{project_id}/references/current", response_model=list[UploadedFile])
async def list_current_references(project_id: str, task_id: str | None = None):
    if await store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    task = await store.get_task(task_id) if task_id else await store.get_latest_task(project_id)
    if task is None:
        return []
    upload_ids = task.inputData.get("uploadedFiles", [])
    if not isinstance(upload_ids, list):
        return []
    return await build_current_reference_snapshot([str(upload_id) for upload_id in upload_ids])


@app.get("/api/projects/{project_id}/references", response_model=list[UploadedFile])
async def list_project_references(project_id: str):
    if await store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return await store.list_project_uploads(project_id)


@app.websocket("/api/projects/{project_id}/ws")
async def project_ws(project_id: str, websocket: WebSocket):
    if await store.get_project(project_id) is None:
        logger.warning("WebSocket rejected: project_id=%s reason=project_not_found", project_id)
        await websocket.close(code=1008, reason="Project not found")
        return
    token = _resolve_websocket_token(websocket)
    if token is None or await store.get_temp_user_by_token(token) is None:
        logger.warning("WebSocket rejected: project_id=%s reason=authentication_required", project_id)
        await websocket.close(code=1008, reason="Authentication required")
        return
    logger.info("WebSocket session opening: project_id=%s", project_id)
    await ws_manager.connect(project_id, websocket)
    try:
        while True:
            payload = await websocket.receive_json()
            message_type = payload.get("type")
            logger.info(
                "WebSocket message received: project_id=%s message_type=%s payload_keys=%s",
                project_id,
                message_type,
                sorted(payload.keys()),
            )
            if message_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if message_type == "user_message":
                await ws_manager.broadcast(
                    project_id,
                    {
                        "type": "message",
                        "data": payload.get("data", {}),
                    },
                )
            elif message_type == "user_response":
                await ws_manager.broadcast(
                    project_id,
                    {
                        "type": "user_response_ack",
                        "data": payload.get("data", {}),
                    },
                )
            else:
                logger.warning(
                    "WebSocket unsupported message: project_id=%s message_type=%s",
                    project_id,
                    message_type,
                )
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {"message": f"Unsupported websocket message type: {message_type}"},
                    }
                )
    except WebSocketDisconnect:
        logger.info("WebSocket session closed by client: project_id=%s", project_id)
        await ws_manager.disconnect(project_id, websocket)
    except Exception:
        logger.exception("WebSocket session failed: project_id=%s", project_id)
        await ws_manager.disconnect(project_id, websocket)
        raise


@app.on_event("startup")
async def startup_event() -> None:
    # 原因注释：
    # uvicorn 在某些部署模式下不会自动给 root logger 挂 handler，
    # 导致所有 logger.info / terminal_logger.info 的输出被丢弃。
    # 这里确保至少有一个 StreamHandler 输出到 stderr。
    import logging as _logging
    root = _logging.getLogger()
    if not root.handlers:
        handler = _logging.StreamHandler()
        handler.setFormatter(_logging.Formatter("%(levelname)-5s %(name)s: %(message)s"))
        root.addHandler(handler)
    if root.level > _logging.INFO:
        root.setLevel(_logging.INFO)

    from app.config import database_url
    dsn = database_url()
    await store.initialize(dsn)

    # Alembic 自动迁移：启动时升级到最新 schema
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_command
        from pathlib import Path

        alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
        if alembic_ini.exists():
            alembic_cfg = AlembicConfig(str(alembic_ini))
            alembic_cfg.set_main_option("sqlalchemy.url", dsn)
            alembic_command.upgrade(alembic_cfg, "head")
            logger.info("[STARTUP] Alembic migration completed (upgrade to head)")
        else:
            logger.warning("[STARTUP] alembic.ini not found at %s, skipping migration", alembic_ini)
    except Exception:
        logger.warning("[STARTUP] Alembic migration failed, continuing with existing schema", exc_info=True)

    # Event loop 阻塞检测器：超过 200ms 未响应就打 WARNING
    loop = asyncio.get_running_loop()
    loop.slow_callback_duration = 0.2  # 200ms 阈值
    loop.set_debug(True)

    _ensure_scheduled_task_state()
    requirements_runtime = agent_orchestrator.requirements_agent_runtime_diagnostics()
    logger.info(
        (
            "Requirements Agent runtime: bridge_mode=%s enabled=%s runtime_available=%s "
            "python_bin=%s python_exists=%s site_packages_dir=%s site_packages_exists=%s model=%s"
        ),
        requirements_runtime["bridge_mode"],
        requirements_runtime["enabled"],
        requirements_runtime["runtime_available"],
        requirements_runtime["python_bin"],
        requirements_runtime["python_exists"],
        requirements_runtime["site_packages_dir"],
        requirements_runtime["site_packages_exists"],
        requirements_runtime["model"],
    )
    await recover_incomplete_tasks()
    await asyncio.sleep(0)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await _await_scheduled_app_tasks_shutdown()
    shutdown_agent_executor(wait=False)
    await store.close()
