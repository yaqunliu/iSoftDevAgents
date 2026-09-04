from __future__ import annotations

import asyncio
import inspect
import io
import importlib.util
import json
import logging
import os
import re
import shutil
import site
import subprocess
import sys
import tempfile
import threading
import time
import yaml
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.config import delete_local_files_after_persist_enabled, load_local_env_files
from app.localization import normalize_locale, t
from app.agents.requirements_bridge import (
    RequirementsAgentBridgeExecutionError,
)
from app.agents.unified_bridge import UIAgentRuntimeError, agent_bridge

_last_usage_metadata: ContextVar[dict[str, Any] | None] = ContextVar("last_usage_metadata", default=None)
logger = logging.getLogger(__name__)
terminal_logger = logging.getLogger("uvicorn.error")

load_local_env_files()

StatusCallback = Callable[[str], Awaitable[None]]
ArtifactFileCallback = Callable[[dict[str, Any]], Awaitable[None]]
HumanFeedbackRequestCallback = Callable[[dict[str, Any]], Awaitable[None]]


def _normalize_env_path(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        normalized = normalized[1:-1]
    normalized = normalized.strip()
    return normalized or None


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _truncate_for_log(text: str, *, limit: int = 240) -> str:
    normalized = " ".join(str(text).split()).strip()
    if len(normalized) <= limit:
        return normalized
    if limit < 40:
        return normalized[:limit].rstrip() + "...[truncated]"
    retry_start = re.search(r"Failed after\s+\d+\s+retries:", normalized)
    if retry_start is not None:
        suffix = normalized[retry_start.start():].strip()
        head_length = max(20, limit - len("...[truncated]...") - len(suffix))
        if head_length < len(normalized):
            head = normalized[:head_length].rstrip()
            return f"{head}...[truncated]...{suffix}"
    head_length = max(20, int(limit * 0.4))
    tail_length = max(30, limit - head_length - len("...[truncated]..."))
    head = normalized[:head_length].rstrip()
    tail = normalized[-tail_length:].lstrip()
    if not tail:
        return head + "...[truncated]"
    return f"{head}...[truncated]...{tail}"


def _extract_retry_summary(text: str) -> str | None:
    """
    接口注释：
    从 Requirements Agent 的异常文本里提炼“最后一次重试后的结论”。

    设计注释：
    之前日志只打了 stdout/stderr 开头预览，用户很容易只看到 `Attempt 1/5`，
    误以为系统没有继续重试。这里把 `Failed after 5 retries: ...` 单独抽出来，
    排查时一眼就能看出到底有没有重试满，以及最后失败在哪个字段。
    """

    normalized = " ".join(str(text).split()).strip()
    if not normalized:
        return None
    match = re.search(r"(\[[^\]]+\]\s+Failed after\s+\d+\s+retries:\s+.+)", normalized)
    if match:
        return match.group(1).strip()
    return None


_REQUIREMENTS_STREAM_FILE_HINTS = {
    "SurveyCrew": "survey.md",
    "DraftContentDiagramCrew": "draft_context_diagram.md",
    "DraftEventListCrew": "draft_event_list.md",
    "UserIntroductionDev": "user_introduction.md",
    "FeatureTreeDev": "feature_tree.md",
    "BusinessScopeDev": "business_scope.md",
    "UserCaseCrew": "use_case.md",
    "NFRCrew": "non_functional_requirements.md",
    "UsageScenarioCrew": "usage_scenario.md",
    "STDCrew": "state_transition_diagram.md",
    "FRCrew": "functional_requirements.md",
    "DataFlowDiagramCrew": "data_flow_diagram.md",
    "ERDCrew": "entity_relationship_diagram.md",
    "DataDictionaryCrew": "data_dictionary.md",
    "DialogMapCrew": "dialog_map.md",
    "ExtractDocumentCrew": "document_skeleton.md",
    "DocContentCrew": "doc_content.md",
    "ChapterDependenceCrew": "chapter_dependence.md",
    "ArtifactPlanningCrew": "artifact_planning.md",
}

_REQUIREMENTS_ANALYSIS_CONSOLE_FILES = {
    "feature_tree.md",
}


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _cleanup_path_if_configured(path: Path | None) -> None:
    """
    接口注释：
    在零残留模式下删除成功路径留下的临时目录或文件。

    原因注释：
    这里故意只处理“成功后可安全清理”的路径。
    失败调试包要不要保留，由失败分支自己决定，不能在这里误删。
    """

    if path is None or not delete_local_files_after_persist_enabled():
        return
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    except FileNotFoundError:
        return


class _CapturingLineWriter(io.TextIOBase):
    def __init__(
        self,
        *,
        chunks: list[str],
        on_line: Callable[[str], None] | None = None,
    ) -> None:
        self._chunks = chunks
        self._on_line = on_line
        self._buffer = ""

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._chunks.append(text)
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if self._on_line is not None:
                self._on_line(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer and self._on_line is not None:
            self._on_line(self._buffer)
        self._buffer = ""


_UI_AGENT_REQUIRED_CORE_FILES = (
    "page_descriptions.json",
    "dar_model.json",
    "app/index.html",
    "app/css/style.css",
    "app/js/index.js",
)

_TEST_AGENT_REQUIRED_FILES = (
    "memory/test_plan.json",
    "{dataset_name}_test_plan.md",
    "{dataset_name}_testcase.md",
)


class RequirementsPromptBridgeSession:
    """
    保存当前任务对应的活输入桥接会话。

    这次改造的目标不是把等待反馈变成“内存里记一个字符串”，
    而是明确记录：现在有没有活的 provider、当前等待卡片长什么样、
    以及这个会话是不是已经被关闭。
    """

    def __init__(self, *, provider: Any) -> None:
        self.provider = provider
        self.lock = threading.Lock()
        self.pending_request: dict[str, Any] | None = None
        self.closed = False


# ---------------------------------------------------------------------------
# 专用 Agent 线程池
# ---------------------------------------------------------------------------
# Agent 子进程（coding / ui / test / requirements / architecture）每个运行 30-60 分钟。
# 如果它们和短时 DB 查询共用 Python 默认 ThreadPoolExecutor，Agent 占满线程后
# HTTP handler 的 asyncio.to_thread(store.xxx) 拿不到线程，API 就会卡死。
# 这里给 Agent 一个独立线程池，默认池留给短时 IO。
# ---------------------------------------------------------------------------
_AGENT_EXECUTOR_MAX_WORKERS = int(
    os.getenv("ISOFTDEVAGENTS_AGENT_EXECUTOR_MAX_WORKERS") or "10"
)
_agent_executor = ThreadPoolExecutor(
    max_workers=_AGENT_EXECUTOR_MAX_WORKERS,
    thread_name_prefix="agent-worker",
)


async def _run_in_agent_executor(fn: Callable[[], Any]) -> Any:
    """在专用 Agent 线程池中执行长时间运行的同步函数。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_agent_executor, fn)


def shutdown_agent_executor(*, wait: bool = True) -> None:
    """关闭专用 Agent 线程池，由 app shutdown 调用。"""
    _agent_executor.shutdown(wait=wait, cancel_futures=True)


class AgentOrchestrator:
    """Central orchestration entrypoint for backend task execution."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 90.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("ISOFTDEVAGENTS_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.getenv("ISOFTDEVAGENTS_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        self.model = model or os.getenv("ISOFTDEVAGENTS_LLM_MODEL") or os.getenv("OPENAI_MODEL") or ""
        self.timeout = timeout
        # 设计注释：
        # Requirements / Architecture / Coding 这些 Agent 的真实运行时间远大于普通 HTTP 请求。
        # 尤其 Requirements Agent 现在还会经历多轮“生成文档 -> 等待人工确认 -> 继续生成 SRS”的长链路。
        # 所以这里把默认总超时基线抬到 3600 秒，避免在没有显式环境变量时过早被平台超时截断。
        default_agent_timeout = float(os.getenv("ISOFTDEVAGENTS_AGENT_TIMEOUT") or max(timeout * 4, 3600.0))
        self.analysis_agent_timeout = float(
            os.getenv("ISOFTDEVAGENTS_ANALYSIS_AGENT_TIMEOUT") or max(default_agent_timeout, 3600.0)
        )
        self.generation_agent_timeout = float(
            os.getenv("ISOFTDEVAGENTS_GENERATION_AGENT_TIMEOUT") or max(default_agent_timeout, 3600.0)
        )
        # 设计注释：
        # 这里把“生成类阶段”的超时继续细分到每个 Agent。
        # 这样用户可以只放大 UI 或 Architecture 的预算，而不用把整轮全部一起拉长。
        self.architecture_agent_timeout = float(
            os.getenv("ISOFTDEVAGENTS_ARCHITECTURE_AGENT_TIMEOUT") or self.generation_agent_timeout
        )
        self.ui_agent_timeout = float(os.getenv("ISOFTDEVAGENTS_UI_AGENT_TIMEOUT") or self.generation_agent_timeout)
        self.coding_agent_timeout = float(
            os.getenv("ISOFTDEVAGENTS_CODING_AGENT_TIMEOUT") or self.generation_agent_timeout
        )
        self.test_agent_timeout = float(os.getenv("ISOFTDEVAGENTS_TEST_AGENT_TIMEOUT") or self.generation_agent_timeout)
        self.debug_agent_stdio = _env_flag("ISOFTDEVAGENTS_AGENT_DEBUG_STDIO", default=False)
        self.platform_root = Path(__file__).resolve().parents[2]
        self.repo_root = Path(__file__).resolve().parents[4]
        self.agent_root = self.repo_root / "agent"
        self._requirements_prompt_sessions: dict[str, RequirementsPromptBridgeSession] = {}
        self._requirements_feedback_sessions_lock = threading.Lock()

    def get_model_name(self) -> str:
        """返回当前配置的模型名。"""
        return self.model or "agent/unconfigured"

    def requirements_agent_runtime_diagnostics(self) -> dict[str, Any]:
        """
        返回需求 Agent 运行环境的关键信息。

        这个方法专门给启动日志和排查问题用，避免每次都靠人工去猜
        当前到底用了哪个 Python、依赖是不是可用、是不是在走新的桥梁方式。
        """

        python_bin = self._requirements_agent_python_bin()
        site_packages_dir = self._requirements_agent_site_packages_dir()
        return {
            "enabled": self._requirements_agent_enabled(),
            "python_bin": python_bin,
            "python_exists": bool(python_bin and python_bin != "python3" and Path(python_bin).exists())
            if python_bin != "python3"
            else shutil.which("python3") is not None,
            "site_packages_dir": site_packages_dir,
            "site_packages_exists": bool(site_packages_dir and Path(site_packages_dir).exists()),
            "runtime_available": self._requirements_agent_runtime_available(),
            "bridge_mode": "inprocess_function_bridge",
            "model": self._litellm_model_name(),
        }

    def is_remote_enabled(self) -> bool:
        """检查 LLM 远程服务是否已配置。"""
        return bool(self.base_url and self.api_key and self.model)

    def missing_runtime_variables(self) -> list[dict[str, Any]]:
        """列出缺失的必要运行时环境变量。"""
        missing: list[dict[str, Any]] = []
        if not self.base_url:
            missing.append(
                {
                    "id": "OPENAI_BASE_URL",
                    "label": "OpenAI-Compatible Base URL",
                    "type": "text",
                    "required": True,
                    "placeholder": "https://api.example.com/v1",
                }
            )
        if not self.api_key:
            missing.append(
                {
                    "id": "OPENAI_API_KEY",
                    "label": "OpenAI-Compatible API Key",
                    "type": "password",
                    "required": True,
                    "placeholder": "sk-...",
                }
            )
        if not self.model:
            missing.append(
                {
                    "id": "OPENAI_MODEL",
                    "label": "Model Name",
                    "type": "text",
                    "required": True,
                    "placeholder": "moonshot/kimi-k2.5",
                }
            )
        return missing

    def apply_runtime_variables(self, variables: dict[str, Any] | None) -> None:
        """应用前端提交的运行时变量（API Key 等）。"""
        if not variables:
            return
        normalized = {str(key): str(value).strip() for key, value in variables.items() if value is not None}
        base_url = normalized.get("OPENAI_BASE_URL") or normalized.get("ISOFTDEVAGENTS_LLM_BASE_URL")
        api_key = normalized.get("OPENAI_API_KEY") or normalized.get("ISOFTDEVAGENTS_LLM_API_KEY")
        model = normalized.get("OPENAI_MODEL") or normalized.get("ISOFTDEVAGENTS_LLM_MODEL")

        if base_url:
            self.base_url = base_url.rstrip("/")
            os.environ["OPENAI_BASE_URL"] = self.base_url
            os.environ["ISOFTDEVAGENTS_LLM_BASE_URL"] = self.base_url
        if api_key:
            self.api_key = api_key
            os.environ["OPENAI_API_KEY"] = self.api_key
            os.environ["ISOFTDEVAGENTS_LLM_API_KEY"] = self.api_key
        if model:
            self.model = model
            os.environ["OPENAI_MODEL"] = self.model
            os.environ["ISOFTDEVAGENTS_LLM_MODEL"] = self.model

    def _requirements_feedback_output_files(self, output_root: Path) -> list[str]:
        """列出 Requirements Agent 输出目录中的文件相对路径。"""
        if not output_root.exists():
            return []
        return [
            path.relative_to(output_root).as_posix()
            for path in sorted(candidate for candidate in output_root.rglob("*") if candidate.is_file())
        ]

    def _publish_requirements_prompt_waiting(
        self,
        *,
        task_id: str,
        waiting_payload: dict[str, Any],
        output_root: Path,
        feedback_request_callback: HumanFeedbackRequestCallback | None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """
        把 provider 发出的“已进入等待输入”事件继续转成平台原有的等待卡片消息。

        provider 只关心 prompt 本身；任务状态、Agent 名称、输出目录这些平台字段，
        仍然由 orchestrator 在这里补齐，避免 Requirements Agent 反过来依赖平台协议。
        """

        session = self._get_requirements_prompt_session(task_id)
        if session is None:
            return
        with session.lock:
            if session.closed:
                return

        request_payload = {
            "taskId": task_id,
            "promptText": str(waiting_payload.get("promptText") or "").strip(),
            "checkpoint": waiting_payload.get("checkpoint"),
            "phase": "requirements_drafts_started",
            "agentName": "requirements_agent",
            "outputDir": str(output_root),
            "outputFiles": [
                str(item)
                for item in (waiting_payload.get("outputFiles") or self._requirements_feedback_output_files(output_root))
            ],
        }
        with session.lock:
            if session.closed:
                return
            session.pending_request = request_payload

        if feedback_request_callback is None:
            return

        if loop is not None:
            future = asyncio.run_coroutine_threadsafe(feedback_request_callback(request_payload), loop)
            future.result(timeout=10)
            return

        asyncio.run(feedback_request_callback(request_payload))

    def _create_requirements_prompt_session(self, task_id: str, *, provider: Any) -> RequirementsPromptBridgeSession:
        """为指定任务创建 Requirements Agent 人工反馈会话。"""
        with self._requirements_feedback_sessions_lock:
            existing = self._requirements_prompt_sessions.pop(task_id, None)
            session = RequirementsPromptBridgeSession(provider=provider)
            self._requirements_prompt_sessions[task_id] = session
        if existing is not None:
            with existing.lock:
                existing.closed = True
                existing.pending_request = None
            try:
                existing.provider.close()
            except Exception:
                logger.debug("Closing previous prompt bridge session failed.", exc_info=True)
        return session

    def _get_requirements_prompt_session(self, task_id: str) -> RequirementsPromptBridgeSession | None:
        """获取指定任务的 Requirements Agent 人工反馈会话。"""
        with self._requirements_feedback_sessions_lock:
            return self._requirements_prompt_sessions.get(task_id)

    def _close_requirements_prompt_session(self, task_id: str) -> None:
        """关闭并清理指定任务的 Requirements Agent 人工反馈会话。"""
        with self._requirements_feedback_sessions_lock:
            session = self._requirements_prompt_sessions.pop(task_id, None)
        if session is None:
            return
        with session.lock:
            session.closed = True
            session.pending_request = None
        try:
            session.provider.close()
        except Exception:
            logger.debug("Closing prompt bridge provider failed.", exc_info=True)

    def _inject_requirements_feedback(self, task_id: str, feedback_text: str) -> bool:
        """向等待中的 Requirements Agent 注入用户反馈文本。"""
        session = self._get_requirements_prompt_session(task_id)
        if session is None:
            return False
        with session.lock:
            if session.closed or session.pending_request is None:
                return False
        injected = session.provider.inject_text(str(feedback_text or "").strip() or "no")
        if injected:
            with session.lock:
                session.pending_request = None
        return injected

    def submit_requirements_feedback(self, task_id: str, feedback: str) -> bool:
        """向等待中的 Requirements Agent 注入用户反馈。"""
        return self._inject_requirements_feedback(task_id, feedback)

    def _requirements_prompt_session_is_waiting(self, task_id: str | None) -> bool:
        """
        判断当前任务是不是正停在人工反馈等待点。

        这次桥接改造以后，Requirements Agent 是真的阻塞在 prompt 上等输入。
        所以后端的总超时不能继续把这段“纯等待用户操作”的时间也算进去，
        否则用户哪怕只是正常看文档、点一下“没有修改”，后面的 SRS 生成预算也会被白白吃掉。
        """

        if not task_id:
            return False
        session = self._get_requirements_prompt_session(task_id)
        if session is None:
            return False
        with session.lock:
            return not session.closed and session.pending_request is not None

    async def _await_requirements_agent_result(
        self,
        agent_task: "asyncio.Task[dict[str, Any]]",
        *,
        timeout: float,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """
        等待 Requirements Agent 结束，同时把“等待人工反馈”的时间从运行超时里扣掉。

        教学注释：
        这里不用一次性 `wait_for(..., timeout=...)`，而是切成很短的时间片轮询。
        只有 Requirements Agent 真正在跑后续步骤时，才消耗 timeout 预算；
        如果它正停在 prompt 等用户输入，这段时间不记入超时。
        """

        if timeout <= 0:
            return await agent_task

        loop = asyncio.get_running_loop()
        remaining_timeout = float(timeout)
        poll_seconds = 0.2

        while True:
            slice_timeout = min(poll_seconds, remaining_timeout)
            started_at = loop.time()
            try:
                return await asyncio.wait_for(asyncio.shield(agent_task), timeout=slice_timeout)
            except asyncio.TimeoutError:
                elapsed = loop.time() - started_at
                if not self._requirements_prompt_session_is_waiting(task_id):
                    remaining_timeout -= elapsed
                    if remaining_timeout <= 0:
                        raise
                continue

    def consume_last_usage_metadata(self) -> dict[str, Any] | None:
        """取出并清空最近一次 Agent 运行的 Usage 元数据。"""
        metadata = _last_usage_metadata.get()
        _last_usage_metadata.set(None)
        return metadata

    def clear_last_usage_metadata(self) -> None:
        """清空最近一次 Agent 运行的 Usage 元数据。"""
        _last_usage_metadata.set(None)

    def _normalize_usage_metadata(
        self,
        usage_payload: Any,
        *,
        default_model: str | None = None,
    ) -> dict[str, Any] | None:
        """
        把不同 Agent 返回的 Usage 统一整理成后端项目统计能直接识别的结构。

        这里故意做得宽松一些，因为有的 Agent 返回的是我们自己的字典，
        有的返回的是 CrewAI 的对象，还有的字段名是 prompt_tokens 这种下划线风格。
        统一以后，后面的工作流层就不用再分别兼容每一种写法了。
        """

        if usage_payload is None:
            return None

        raw_payload = usage_payload
        if hasattr(raw_payload, "model_dump"):
            raw_payload = raw_payload.model_dump()
        elif hasattr(raw_payload, "dict"):
            raw_payload = raw_payload.dict()
        elif not isinstance(raw_payload, dict):
            raw_payload = {
                "inputTokens": getattr(raw_payload, "prompt_tokens", 0),
                "outputTokens": getattr(raw_payload, "completion_tokens", 0),
                "totalTokens": getattr(raw_payload, "total_tokens", 0),
                "successfulRequests": getattr(raw_payload, "successful_requests", 0),
            }

        if not isinstance(raw_payload, dict):
            return None

        input_tokens = _int_value(raw_payload.get("inputTokens"))
        if input_tokens <= 0:
            input_tokens = _int_value(raw_payload.get("promptTokens") or raw_payload.get("prompt_tokens"))

        output_tokens = _int_value(raw_payload.get("outputTokens"))
        if output_tokens <= 0:
            output_tokens = _int_value(raw_payload.get("completionTokens") or raw_payload.get("completion_tokens"))

        total_tokens = _int_value(raw_payload.get("totalTokens"))
        if total_tokens <= 0:
            total_tokens = _int_value(raw_payload.get("total_tokens"))
        if total_tokens <= 0 and (input_tokens > 0 or output_tokens > 0):
            total_tokens = input_tokens + output_tokens

        successful_requests = _int_value(raw_payload.get("successfulRequests") or raw_payload.get("successful_requests"))
        cost_amount = _float_value(raw_payload.get("costAmount") or raw_payload.get("cost_amount"))
        model = str(raw_payload.get("model") or default_model or self._litellm_model_name()).strip()

        if total_tokens <= 0 and input_tokens <= 0 and output_tokens <= 0 and successful_requests <= 0 and cost_amount <= 0:
            return None

        return {
            "model": model or self._litellm_model_name(),
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": total_tokens,
            "costAmount": cost_amount,
        }

    def _merge_usage_metadata(self, *usage_payloads: Any, default_model: str | None = None) -> dict[str, Any] | None:
        """
        把多个阶段的 Usage 相加。

        这个方法主要给“需求 + 架构一起生成”这种复合流程使用。
        否则前一个阶段的用量会被后一个阶段覆盖，项目总用量就会偏小。
        """

        normalized_payloads = [
            payload
            for payload in (
                self._normalize_usage_metadata(item, default_model=default_model)
                for item in usage_payloads
            )
            if payload is not None
        ]
        if not normalized_payloads:
            return None

        last_payload = normalized_payloads[-1]
        return {
            "model": str(last_payload.get("model") or default_model or self._litellm_model_name()).strip()
            or self._litellm_model_name(),
            "inputTokens": sum(_int_value(item.get("inputTokens")) for item in normalized_payloads),
            "outputTokens": sum(_int_value(item.get("outputTokens")) for item in normalized_payloads),
            "totalTokens": sum(_int_value(item.get("totalTokens")) for item in normalized_payloads),
            "costAmount": sum(_float_value(item.get("costAmount")) for item in normalized_payloads),
        }

    def _set_last_usage_metadata(self, usage_payload: Any, *, default_model: str | None = None) -> dict[str, Any] | None:
        """标准化并保存最近一次 Agent 运行的 Usage 元数据。"""
        normalized = self._normalize_usage_metadata(usage_payload, default_model=default_model)
        _last_usage_metadata.set(normalized)
        return normalized

    async def _emit_status(
        self,
        status_callback,
        line: str | None,
        *,
        agent_name: str,
        locale: str = "en",
    ) -> None:
        """异步转发一行 Agent 进度文本到前端回调。"""
        if status_callback is None or not line:
            return
        cleaned = self._curate_status_line(line, locale=locale)
        if not cleaned:
            return
        await status_callback(f"{agent_name}: {cleaned}")

    def _curate_status_line(self, line: str, *, locale: str = "en") -> str | None:
        """清理并过滤 Agent 状态行，移除噪音和内部标记。"""
        normalized_locale = normalize_locale(locale)
        cleaned = re.sub(r"\x1b\[[0-9;]*m", "", line)
        cleaned = cleaned.replace("\r", " ").strip()
        if not cleaned:
            return None
        cleaned = re.sub(r"^[\s\|\[\]\(\)<>:;,*`'\"#=_\-~•·→✔❌╭╮╰╯│─]+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"^[A-Za-z0-9_/-]+]\s*", "", cleaned)
        cleaned = re.sub(r"[\s\|\[\]\(\)<>:;,*`'\"#=_\-~•·→✔❌╭╮╰╯│─]+$", "", cleaned).strip()
        if not cleaned:
            return None
        lowered = cleaned.lower()
        if lowered in {"tracing status"}:
            return None
        if "no external references provided" in lowered:
            return None
        if "set tracing=true" in lowered:
            return None
        if "crewai traces enable" in lowered:
            return None
        if "crewai_tracing_enabled" in lowered:
            return None
        if "tracing is disabled" in lowered:
            return None
        if "to enable tracing" in lowered:
            return None
        if "previous output:" in lowered and "user feedback:" in lowered:
            return None
        if lowered in {"project request", "selected modules", "reference materials", "existing artifacts"}:
            return None
        if "-->" in cleaned or lowered.startswith("flowchart ") or lowered.startswith("graph ") or lowered.startswith("subgraph ") or lowered == "end":
            return None
        if "code generation pipeline start" in lowered:
            return t(normalized_locale, "status.code_pipeline_started")
        if "code generation pipeline complete" in lowered:
            return t(normalized_locale, "status.code_pipeline_completed")
        feedback_placeholder = t(normalized_locale, "status.no_human_feedback")
        for candidate in (
            "本轮没有人类意见",
            "本轮没有人类反馈",
            "本轮没有人工意见",
            "本轮没有人工反馈。",
            "本轮没有人工反馈",
            "No human feedback in this round.",
            "No human feedback in this round",
        ):
            if candidate in cleaned:
                cleaned = cleaned.replace(candidate, feedback_placeholder)
                break
        return cleaned[:240]

    def _sync_status_emitter(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        agent_name: str,
        status_callback: StatusCallback | None,
        locale: str = "en",
        task_id: str | None = None,
        stream_kind: str = "stdout",
    ) -> Callable[[str | None], None]:
        """创建同步状态回调，用于 Agent 工作线程向 event loop 转发进度文本。"""
        def emit(line: str | None) -> None:
            if task_id and line:
                self._update_running_agent_runtime(
                    task_id,
                    runtime_state="running",
                    **({f"{stream_kind}_preview": str(line).strip()} if str(line).strip() else {}),
                )
            if status_callback is None or not line or loop.is_closed():
                return
            future = asyncio.run_coroutine_threadsafe(
                self._emit_status(status_callback, line, agent_name=agent_name, locale=locale),
                loop,
            )
            try:
                future.result(timeout=10)
            except Exception:
                logger.debug("Streaming status callback failed for %s.", agent_name, exc_info=True)

        return emit

    def _sync_artifact_file_emitter(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        artifact_file_callback: ArtifactFileCallback | None,
    ) -> Callable[[dict[str, Any]], None]:
        """创建同步回调，转发 Agent 产出的文件事件。"""
        def emit(payload: dict[str, Any]) -> None:
            if artifact_file_callback is None or loop.is_closed():
                return
            future = asyncio.run_coroutine_threadsafe(
                artifact_file_callback(payload),
                loop,
            )
            try:
                future.result(timeout=10)
            except Exception:
                logger.debug("Artifact file callback failed.", exc_info=True)

        return emit

    def _sync_runtime_event_emitter(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        runtime_event_callback: Any = None,
        agent_name: str,
        task_id: str | None = None,
    ) -> Callable[[dict[str, Any]], None]:
        """创建同步回调，转发 Agent 运行时状态快照（仅供工作线程调用）。"""
        async def emit_async(payload: dict[str, Any]) -> None:
            if runtime_event_callback is None:
                return
            result = runtime_event_callback(payload)
            if inspect.isawaitable(result):
                await result

        def emit(payload: dict[str, Any]) -> None:
            if task_id:
                self._update_running_agent_runtime(
                    task_id,
                    runtime_pid=payload.get("runtimePid"),
                    runtime_state=payload.get("runtimeState"),
                    latest_output_file=payload.get("latestOutputFile"),
                    output_root=payload.get("outputDir"),
                    last_runtime_snapshot=dict(payload),
                )
            if runtime_event_callback is None or loop.is_closed():
                return
            future = asyncio.run_coroutine_threadsafe(
                emit_async(payload),
                loop,
            )
            try:
                future.result(timeout=10)
            except Exception:
                logger.debug("Runtime event callback failed for %s.", agent_name, exc_info=True)

        return emit

    def _register_running_agent_runtime(
        self,
        *,
        task_id: str | None,
        agent_name: str,
        cancel_event: threading.Event,
        completion_event: threading.Event,
        runtime_home: Path | None = None,
        output_root: Path | None = None,
    ) -> None:
        """注册一个正在运行的 Agent 到全局追踪表。"""
        if not task_id:
            return
        from app.services.workflow import register_running_task

        register_running_task(
            task_id,
            cancel_event=cancel_event,
            completion_event=completion_event,
            agent_name=agent_name,
            runtime_home=str(runtime_home) if runtime_home is not None else None,
            output_root=str(output_root) if output_root is not None else None,
            runtime_state="starting",
        )

    def _update_running_agent_runtime(self, task_id: str | None, **updates: Any) -> None:
        """更新运行中 Agent 的状态信息。"""
        if not task_id:
            return
        from app.services.workflow import update_running_task

        update_running_task(task_id, **updates)

    def _mark_running_agent_completion(
        self,
        *,
        task_id: str | None,
        completion_event: threading.Event | None,
        runtime_state: str,
    ) -> None:
        """标记 Agent 运行完成并触发 completion event。"""
        if completion_event is not None:
            completion_event.set()
        if not task_id:
            return
        from app.services.workflow import mark_running_task_completion

        mark_running_task_completion(task_id, runtime_state=runtime_state)

    def _unregister_running_agent_runtime(self, task_id: str | None) -> None:
        """从全局追踪表移除 Agent。"""
        if not task_id:
            return
        from app.services.workflow import unregister_running_task

        unregister_running_task(task_id)

    def _run_streaming_subprocess(
        self,
        command: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        timeout: float,
        loop: asyncio.AbstractEventLoop,
        agent_name: str,
        status_callback: StatusCallback | None,
        locale: str = "en",
        stdout_handle: io.TextIOBase | None = None,
        stderr_handle: io.TextIOBase | None = None,
    ) -> tuple[str, str]:
        """运行子进程并实时捕获 stdout/stderr 流。"""
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        emit = self._sync_status_emitter(
            loop=loop,
            agent_name=agent_name,
            status_callback=status_callback,
            locale=locale,
        )

        def drain(stream: io.TextIOBase | None, chunks: list[str], target: io.TextIOBase | None) -> None:
            if stream is None:
                return
            try:
                for line in iter(stream.readline, ""):
                    chunks.append(line)
                    if target is not None:
                        target.write(line)
                        target.flush()
                    self._log_agent_stream_line(agent_name, "stdout" if stream is process.stdout else "stderr", line)
                    emit(line)
            finally:
                stream.close()

        stdout_thread = threading.Thread(target=drain, args=(process.stdout, stdout_chunks, stdout_handle), daemon=True)
        stderr_thread = threading.Thread(target=drain, args=(process.stderr, stderr_chunks, stderr_handle), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            stdout_text = "".join(stdout_chunks)
            stderr_text = "".join(stderr_chunks)
            raise subprocess.TimeoutExpired(cmd=command, timeout=timeout, output=stdout_text, stderr=stderr_text)

        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
        stdout_text = "".join(stdout_chunks)
        stderr_text = "".join(stderr_chunks)
        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, command, output=stdout_text, stderr=stderr_text)
        return stdout_text, stderr_text

    def _log_agent_stream_line(self, agent_name: str, stream_name: str, line: str) -> None:
        """在调试模式下将 Agent 的流式输出打到终端日志。"""
        if not self.debug_agent_stdio:
            return
        text = str(line).rstrip()
        if not text:
            return
        terminal_logger.info(f"[{agent_name} {stream_name}] {text}")

    def _extract_requirements_stream_file_name(self, line: str) -> str | None:
        """从 Requirements Agent 的流式输出行中提取文件名。"""
        normalized = " ".join(str(line).split()).strip()
        if not normalized:
            return None

        crew_match = re.search(r"\[([A-Za-z0-9_]+)\]\s+Attempt\s+\d+/\d+", normalized)
        if crew_match:
            return _REQUIREMENTS_STREAM_FILE_HINTS.get(crew_match.group(1))

        explicit_file_match = re.search(
            r"([A-Za-z0-9_./-]+\.(?:md|markdown|txt|json|yaml|yml|html|htm|ts|tsx|js|jsx|py|css|svg))",
            normalized,
            flags=re.IGNORECASE,
        )
        if explicit_file_match:
            return explicit_file_match.group(1)
        return None

    def _requirements_console_allows_file(self, *, mode: str, file_name: str) -> bool:
        """判断指定文件是否允许在当前模式的控制台中展示。"""
        normalized = Path(file_name).name.strip().lower()
        if not normalized:
            return False
        if mode == "analysis":
            return normalized in _REQUIREMENTS_ANALYSIS_CONSOLE_FILES
        return True

    def _summarize_requirements_stream_line(self, line: str, *, mode: str) -> str | None:
        """
        把 Requirements Agent 大量原始 stdout 压缩成适合人看的进度日志。

        控制台里我们主要保留四类信息：
        1. 当前在执行哪个任务
        2. 当前涉及哪个输出文件
        3. 当前正在等待用户查看哪个文件并给反馈
        4. 当前是哪一个子步骤执行失败

        这样终端就不会再被 system prompt、长段正文、富文本框线刷屏。
        但一旦某个 requirements 子步骤真的失败，日志里必须能直接看到失败点，
        否则外层只剩一个笼统的 Crew Failure，定位会非常痛苦。
        """

        normalized = " ".join(str(line).split()).strip()
        if not normalized:
            return None

        task_match = re.search(r"\bName:\s*([A-Za-z0-9_.-]+)", normalized)
        if task_match:
            task_name = task_match.group(1)
            if task_name.lower() == "search":
                return None
            return f"[Requirements Agent task] {task_name}"

        failed_match = re.search(
            r"\[([A-Za-z0-9_]+)\]\s+Failed(?:\s+attempt\s+(\d+))?:\s*(.+)",
            normalized,
        )
        if failed_match:
            step_name = failed_match.group(1)
            attempt_no = failed_match.group(2)
            error_text = failed_match.group(3).strip()
            attempt_suffix = f" attempt={attempt_no}" if attempt_no else ""
            return f"[Requirements Agent error] step={step_name}{attempt_suffix} message={error_text}"

        waiting_file = self._extract_requirements_stream_file_name(normalized)
        if "请查看现有的" in normalized and waiting_file and self._requirements_console_allows_file(mode=mode, file_name=waiting_file):
            return f"[Requirements Agent waiting_for_feedback] file={waiting_file}"

        output_file = self._extract_requirements_stream_file_name(normalized)
        if output_file and self._requirements_console_allows_file(mode=mode, file_name=output_file):
            return f"[Requirements Agent file] {output_file}"

        return None

    async def analyze_prompt(
        self,
        prompt: str,
        reference_materials: list[dict[str, Any]] | None = None,
        locale: str = "en",
        status_callback: StatusCallback | None = None,
        usage_event_callback: Any = None,
    ) -> dict[str, Any]:
        """调用 Requirements Agent 分析用户需求，返回建议的功能模块列表。"""
        reference_materials = reference_materials or []
        _last_usage_metadata.set(None)
        agent_analysis = await self._analyze_with_requirements_agent(
            prompt,
            reference_materials,
            locale=locale,
            status_callback=status_callback,
            usage_event_callback=usage_event_callback,
        )
        if agent_analysis is None:
            raise RuntimeError("Requirements Agent did not return a usable analysis result.")
        modules = self._normalize_analysis_modules(agent_analysis.get("modules"))
        modules = self._repair_analysis_modules_for_prompt(prompt, modules)
        if not modules:
            raise RuntimeError("Requirements Agent did not return any usable feature modules.")
        summary = str(agent_analysis.get("summary") or "").strip() or "Requirement analysis is complete. Please confirm the suggested feature modules."
        meta = agent_analysis.get("_meta") if isinstance(agent_analysis.get("_meta"), dict) else {}
        payload = {
            "summary": summary,
            "modules": modules,
        }
        enriched = self._with_analysis_meta(
            payload,
            source=str(meta.get("source") or "requirements_agent"),
            reason=str(meta.get("reason") or "") or None,
        )
        if isinstance(enriched.get("_meta"), dict):
            enriched["_meta"].update(
                {
                    key: value
                    for key, value in meta.items()
                    if key not in {"source", "reason"}
                }
            )
        return enriched

    async def build_artifacts(
        self,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        reference_materials: list[dict[str, Any]] | None = None,
        existing_artifacts: list[dict[str, Any]] | None = None,
        locale: str = "en",
        status_callback: StatusCallback | None = None,
        artifact_file_callback: ArtifactFileCallback | None = None,
    ) -> dict[str, Any]:
        """依次调用 Requirements + Architecture Agent 生成全套需求和架构制品。"""
        reference_materials = reference_materials or []
        existing_artifacts = existing_artifacts or []
        self.clear_last_usage_metadata()
        requirements_agent_payload = await self.build_requirements_drafts(
            prompt=prompt,
            selected_modules=selected_modules,
            reference_materials=reference_materials,
            existing_artifacts=existing_artifacts,
            locale=locale,
            status_callback=status_callback,
            artifact_file_callback=artifact_file_callback,
        )
        requirements_usage = self.consume_last_usage_metadata()
        if status_callback is not None:
            await status_callback("Architecture Agent: Generating analysis_task_output.txt.")
        architecture_agent_payload = await self.build_architecture_draft(
            prompt=prompt,
            selected_modules=selected_modules,
            reference_materials=reference_materials,
            existing_artifacts=existing_artifacts,
            locale=locale,
            status_callback=status_callback,
        )
        architecture_usage = self.consume_last_usage_metadata()
        self._set_last_usage_metadata(
            self._merge_usage_metadata(
                requirements_usage,
                architecture_usage,
                default_model=self._litellm_model_name(),
            ),
            default_model=self._litellm_model_name(),
        )
        return self.compose_artifacts(
            prompt=prompt,
            selected_modules=selected_modules,
            requirements_payload=requirements_agent_payload,
            architecture_payload=architecture_agent_payload,
        )

    async def build_requirements_drafts(
        self,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        task_id: str | None = None,
        reference_materials: list[dict[str, Any]] | None = None,
        existing_artifacts: list[dict[str, Any]] | None = None,
        locale: str = "en",
        status_callback: StatusCallback | None = None,
        artifact_file_callback: ArtifactFileCallback | None = None,
        human_feedback_callback: HumanFeedbackRequestCallback | None = None,
        usage_event_callback: Any = None,
        runtime_event_callback: Any = None,
    ) -> dict[str, Any]:
        """调用 Requirements Agent 生成需求草稿（含人工确认交互）。"""
        reference_materials = reference_materials or []
        existing_artifacts = existing_artifacts or []
        self.clear_last_usage_metadata()
        requirements_agent_payload = await self._build_with_requirements_agent_artifacts(
            task_id=task_id,
            prompt=prompt,
            selected_modules=selected_modules,
            reference_materials=reference_materials,
            existing_artifacts=existing_artifacts,
            locale=locale,
            status_callback=status_callback,
            artifact_file_callback=artifact_file_callback,
            human_feedback_callback=human_feedback_callback,
            usage_event_callback=usage_event_callback,
            runtime_event_callback=runtime_event_callback,
        )
        if requirements_agent_payload is None:
            # 这里把最常见的失败形态直接讲清楚。
            # 目前 full 模式真正可交付的核心文件是 SRS.md，
            # 如果只产出了 business_scope.md 这类前半段文件，平台无法继续后续合成。
            raise RuntimeError(
                "Requirements Agent did not return the required draft artifacts. "
                "The run likely stopped before producing the required file (missing SRS.md); "
                "check the backend logs and debug bundle for stdout/stderr."
            )
        self._set_last_usage_metadata(
            requirements_agent_payload.get("usage"),
            default_model=self._litellm_model_name(),
        )
        return requirements_agent_payload

    async def build_architecture_draft(
        self,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        reference_materials: list[dict[str, Any]] | None = None,
        existing_artifacts: list[dict[str, Any]] | None = None,
        locale: str = "en",
        task_id: str | None = None,
        status_callback: StatusCallback | None = None,
        usage_event_callback: Any = None,
        runtime_event_callback: Any = None,
    ) -> dict[str, Any]:
        """调用 Architecture Agent 生成架构文档。"""
        reference_materials = reference_materials or []
        existing_artifacts = existing_artifacts or []
        if status_callback is not None:
            await status_callback("Architecture Agent: Generating analysis_task_output.txt.")
        architecture_agent_payload = await self._build_with_architecture_agent(
            prompt=prompt,
            selected_modules=selected_modules,
            reference_materials=reference_materials,
            existing_artifacts=existing_artifacts,
            locale=locale,
            task_id=task_id,
            status_callback=status_callback,
            usage_event_callback=usage_event_callback,
            runtime_event_callback=runtime_event_callback,
        )
        if architecture_agent_payload is None or not architecture_agent_payload.get("architecture"):
            raise RuntimeError("Architecture Agent did not return the architecture draft.")
        self._set_last_usage_metadata(
            architecture_agent_payload.get("usage"),
            default_model=self._litellm_model_name(),
        )
        return architecture_agent_payload

    def compose_artifacts(
        self,
        *,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        requirements_payload: dict[str, Any],
        architecture_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """合并 Requirements 和 Architecture 的产出为统一制品。"""
        normalized = self._normalize_artifacts(
            prompt=prompt,
            payload={
                "prd": requirements_payload.get("prd"),
                "ui": requirements_payload.get("ui"),
                "architecture": architecture_payload.get("architecture"),
                "api_spec": requirements_payload.get("api_spec"),
            },
            selected_modules=selected_modules,
        )
        normalized["_meta"] = {
            "requirements": dict(requirements_payload.get("_meta") or {}),
            "architecture": dict(architecture_payload.get("_meta") or {}),
        }
        return normalized

    async def build_code_files(
        self,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        artifacts: dict[str, Any],
        locale: str = "en",
        task_id: str | None = None,
        status_callback: StatusCallback | None = None,
        usage_event_callback: Any = None,
        runtime_event_callback: Any = None,
    ) -> list[dict[str, str]]:
        """调用 Coding Agent 生成代码文件。"""
        coding_agent_files = await self._build_with_coding_agent(
            prompt=prompt,
            selected_modules=selected_modules,
            artifacts=artifacts,
            locale=locale,
            task_id=task_id,
            status_callback=status_callback,
            usage_event_callback=usage_event_callback,
            runtime_event_callback=runtime_event_callback,
        )
        coding_usage = None
        if isinstance(coding_agent_files, dict):
            coding_usage = coding_agent_files.get("usage")
            coding_agent_files = coding_agent_files.get("files")
        if not coding_agent_files:
            raise RuntimeError("Coding Agent did not return any generated code files.")
        if coding_usage is not None:
            self._set_last_usage_metadata(coding_usage, default_model=self._litellm_model_name())
        return coding_agent_files

    async def build_ui_files(
        self,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        artifacts: dict[str, Any],
        *,
        use_case_text: str,
        dialog_map_text: str,
        locale: str = "en",
        task_id: str | None = None,
        status_callback: StatusCallback | None = None,
        usage_event_callback: Any = None,
        runtime_event_callback: Any = None,
    ) -> list[dict[str, str]]:
        """调用 UI Agent 生成前端 UI 文件。"""
        ui_agent_files = await self._build_with_ui_agent(
            prompt=prompt,
            selected_modules=selected_modules,
            artifacts=artifacts,
            use_case_text=use_case_text,
            dialog_map_text=dialog_map_text,
            locale=locale,
            task_id=task_id,
            status_callback=status_callback,
            usage_event_callback=usage_event_callback,
            runtime_event_callback=runtime_event_callback,
        )
        ui_usage = None
        if isinstance(ui_agent_files, dict):
            ui_usage = ui_agent_files.get("usage")
            ui_agent_files = ui_agent_files.get("files")
        validated_ui_files = self._validate_ui_output_files(ui_agent_files or [])
        if ui_usage is not None:
            self._set_last_usage_metadata(ui_usage, default_model=self._litellm_model_name())
        return validated_ui_files

    async def build_test_files(
        self,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        artifacts: dict[str, Any],
        *,
        code_files: list[dict[str, Any]] | None = None,
        locale: str = "en",
        task_id: str | None = None,
        status_callback: StatusCallback | None = None,
        usage_event_callback: Any = None,
        runtime_event_callback: Any = None,
    ) -> list[dict[str, str]]:
        """调用 Test Agent 生成测试用例和计划。"""
        test_agent_files = await self._build_with_test_agent(
            prompt=prompt,
            selected_modules=selected_modules,
            artifacts=artifacts,
            code_files=code_files,
            locale=locale,
            task_id=task_id,
            status_callback=status_callback,
            usage_event_callback=usage_event_callback,
            runtime_event_callback=runtime_event_callback,
        )
        test_usage = None
        if isinstance(test_agent_files, dict):
            test_usage = test_agent_files.get("usage")
            test_agent_files = test_agent_files.get("files")
        validated_test_files = self._validate_test_output_files(
            test_agent_files or [],
            dataset_name=self._project_name_from_prompt(prompt),
        )
        if test_usage is not None:
            self._set_last_usage_metadata(test_usage, default_model=self._litellm_model_name())
        return validated_test_files

    def _with_analysis_meta(self, payload: dict[str, Any], *, source: str, reason: str | None = None) -> dict[str, Any]:
        """在分析结果上附加 _meta 来源信息。"""
        enriched = dict(payload)
        meta: dict[str, Any] = {"source": source}
        if reason:
            meta["reason"] = reason
        enriched["_meta"] = meta
        return enriched

    def _normalize_analysis_modules(self, modules: Any) -> list[dict[str, Any]]:
        """标准化分析阶段返回的模块列表格式。"""
        if not isinstance(modules, list):
            return []
        normalized_modules: list[dict[str, Any]] = []
        for item in modules[:6]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("labelEn") or item.get("label") or "Core Module").strip() or "Core Module"
            module_id = str(item.get("id") or label.lower().replace(" ", "-")).strip() or "core-module"
            normalized_modules.append(
                {
                    "id": module_id,
                    "label": label,
                    "labelEn": label,
                    "description": str(item.get("description") or "Core project capability.").strip(),
                    "checked": bool(item.get("checked", True)),
                }
            )
        return normalized_modules

    def _litellm_model_name(self) -> str:
        """返回 LiteLLM 格式的模型名（如 openai/gpt-5.4）。"""
        model = self.model.strip()
        if not model:
            return model
        if model.startswith(("openai/", "azure/", "anthropic/", "gemini/", "bedrock/")):
            return model
        if self.base_url:
            return f"openai/{model}"
        return model

    def _canonical_model_name(self) -> str:
        """
        返回平台内部保存的标准模型名。

        接口注释：
        这里不按某个 Agent 的特殊规则加工，只返回“当前平台认定的模型名”。
        真正发给不同 Agent 之前，再由 `_runtime_model_name(...)` 做最后一跳转换。
        """

        return self.model.strip()

    def _runtime_model_name(self, target: str) -> str:
        """
        按运行时类型返回最终要传给 Agent 的模型名。

        设计注释：
        现在平台里有两类调用栈：
        1. CrewAI / LiteLLM 风格：通常能接受 `openai/gpt-5.4`
        2. OpenAI SDK 直连风格：很多兼容服务只接受 `gpt-5.4`
        所以这里统一收口，避免每个 Agent 各自猜模型名格式。
        """

        canonical_model = self._canonical_model_name()
        if not canonical_model:
            return canonical_model

        if target == "openai_sdk":
            for prefix in ("openai/", "azure/", "anthropic/", "gemini/", "bedrock/"):
                if canonical_model.startswith(prefix):
                    return canonical_model[len(prefix) :].strip()
            return canonical_model

        if target in {"crewai", "requirements_bridge"}:
            if canonical_model.startswith(("openai/", "azure/", "anthropic/", "gemini/", "bedrock/")):
                return canonical_model
            if self.base_url:
                return f"openai/{canonical_model}"
            return canonical_model

        return canonical_model

    def _architecture_agent_enabled(self) -> bool:
        """检查 Architecture Agent 是否启用。"""
        explicit = os.getenv("ISOFTDEVAGENTS_ENABLE_ARCH_AGENT")
        if explicit is not None:
            return explicit.strip().lower() in {"1", "true", "yes", "on"}
        return "unittest" not in sys.modules

    def _architecture_agent_python_bin(self) -> str:
        """返回 Architecture Agent 使用的 Python 解释器路径。"""
        explicit = _normalize_env_path(os.getenv("ISOFTDEVAGENTS_ARCH_AGENT_PYTHON_BIN"))
        if explicit:
            if Path(explicit).exists():
                return explicit
            logger.warning(
                "Configured Architecture Agent python does not exist, falling back to auto-detection. path=%s",
                explicit,
            )
        candidate = self.agent_root / "Architecture Agent" / ".venv" / "bin" / "python"
        if candidate.exists():
            return str(candidate)
        return "python3"

    def _architecture_agent_runtime_available(self) -> bool:
        """检查 Architecture Agent 的运行环境是否就绪。"""
        python_bin = self._architecture_agent_python_bin().strip()
        if python_bin and python_bin != "python3":
            return Path(python_bin).exists()
        return self._python_runtime_has_module(python_bin or "python3", "crewai")

    def _architecture_agent_output_root(self) -> Path:
        """
        接口注释：
        返回 Architecture Agent 默认写输出目录的根路径。

        教学注释：
        架构 Agent 的真实产物目录不是临时目录，而是
        `Architecture Agent/data/output/` 下面按项目继续分子目录。
        调试包这里保留这棵根目录，是为了超时或异常时还能把最近产物一起拷走。
        """

        return self.agent_root / "Architecture Agent" / "data" / "output"

    def _architecture_agent_python_uses_parent_sitepackages(self) -> bool:
        """判断 Architecture Agent 是否使用系统级 site-packages。"""
        return self._architecture_agent_python_bin().strip() == "python3"

    def _requirements_agent_enabled(self) -> bool:
        """检查 Requirements Agent 是否启用。"""
        explicit = os.getenv("ISOFTDEVAGENTS_ENABLE_REAGENT")
        if explicit is not None:
            return explicit.strip().lower() in {"1", "true", "yes", "on"}
        return "unittest" not in sys.modules

    def _requirements_agent_python_bin(self) -> str:
        """返回 Requirements Agent 使用的 Python 解释器路径。"""
        explicit = _normalize_env_path(os.getenv("ISOFTDEVAGENTS_REAGENT_PYTHON_BIN"))
        if explicit:
            if Path(explicit).exists():
                return explicit
            logger.warning(
                "Configured Requirements Agent python does not exist, falling back to auto-detection. path=%s",
                explicit,
            )
        candidate = self.agent_root / "Requirements Agent" / "reagent" / ".venv" / "bin" / "python"
        if candidate.exists():
            return str(candidate)
        return "python3"

    def _requirements_agent_full_entrypoint(self) -> str:
        """返回 Requirements Agent 完整生成模式的入口脚本路径。"""
        adapter_entrypoint = self.platform_root / "app" / "agents" / "reagent_adapter.py"
        if adapter_entrypoint.exists():
            return str(adapter_entrypoint)
        return str(self.agent_root / "Requirements Agent" / "reagent" / "src" / "reagent" / "main.py")

    def _requirements_agent_analysis_entrypoint(self) -> str:
        """返回 Requirements Agent 分析模式的入口脚本路径。"""
        return self._requirements_agent_full_entrypoint()

    def _requirements_agent_runtime_available(self) -> bool:
        """检查 Requirements Agent 的运行环境是否就绪。"""
        site_packages_dir = self._requirements_agent_site_packages_dir()
        if site_packages_dir and Path(site_packages_dir).exists():
            return True
        python_bin = self._requirements_agent_python_bin().strip()
        return self._python_runtime_has_module(python_bin or "python3", "crewai")

    def _requirements_agent_python_uses_parent_sitepackages(self) -> bool:
        """判断 Requirements Agent 是否使用系统级 site-packages。"""
        return self._requirements_agent_python_bin().strip() == "python3"

    def _requirements_agent_site_packages_dir(self) -> str | None:
        """返回 Requirements Agent 的 site-packages 目录。"""
        explicit = _normalize_env_path(os.getenv("ISOFTDEVAGENTS_REAGENT_SITE_PACKAGES"))
        if explicit:
            return explicit
        lib_root = self.agent_root / "Requirements Agent" / "reagent" / ".venv" / "lib"
        if not lib_root.exists():
            return None
        matches = sorted(lib_root.glob("python*/site-packages"))
        if matches:
            return str(matches[0])
        return None

    def _requirements_agent_tasks_config_path(self, runtime_home: Path) -> Path:
        """返回 Requirements Agent 的运行时 tasks 配置文件路径。"""
        # Avoid the generic tasks.runtime.yaml filename because the agent-side
        # bootstrap rewrites that specific name with its own default merged config.
        return runtime_home / "tasks.backend.runtime.yaml"

    def _coding_agent_enabled(self) -> bool:
        """检查 Coding Agent 是否启用。"""
        explicit = os.getenv("ISOFTDEVAGENTS_ENABLE_CODING_AGENT")
        if explicit is not None:
            return explicit.strip().lower() in {"1", "true", "yes", "on"}
        return "unittest" not in sys.modules

    def _coding_agent_python_bin(self) -> str:
        """返回 Coding Agent 使用的 Python 解释器路径。"""
        explicit = _normalize_env_path(os.getenv("ISOFTDEVAGENTS_CODING_AGENT_PYTHON_BIN"))
        if explicit:
            if Path(explicit).exists():
                return explicit
            logger.warning(
                "Configured Coding Agent python does not exist, falling back to auto-detection. path=%s",
                explicit,
            )
        candidate = self.agent_root / "Coding Agent" / ".venv" / "bin" / "python"
        if candidate.exists():
            return str(candidate)
        return "python3"

    def _coding_agent_site_packages_dir(self) -> str | None:
        """返回 Coding Agent 的 site-packages 目录。"""
        explicit = _normalize_env_path(os.getenv("ISOFTDEVAGENTS_CODING_AGENT_SITE_PACKAGES"))
        if explicit:
            return explicit
        candidates = [
            self.agent_root / "Coding Agent" / ".venv" / "lib",
            self.agent_root / "Requirements Agent" / "reagent" / ".venv" / "lib",
        ]
        for lib_root in candidates:
            if not lib_root.exists():
                continue
            matches = sorted(lib_root.glob("python*/site-packages"))
            if matches:
                return str(matches[0])
        return None

    def _coding_agent_runtime_available(self) -> bool:
        """检查 Coding Agent 的运行环境是否就绪。"""
        python_bin = self._coding_agent_python_bin().strip()
        if python_bin and python_bin != "python3":
            return Path(python_bin).exists()
        site_packages_dir = self._coding_agent_site_packages_dir()
        if site_packages_dir:
            return Path(site_packages_dir).exists()
        return importlib.util.find_spec("crewai") is not None

    def _ui_agent_enabled(self) -> bool:
        """检查 UI Agent 是否启用。"""
        explicit = os.getenv("ISOFTDEVAGENTS_ENABLE_UI_AGENT")
        if explicit is not None:
            return explicit.strip().lower() in {"1", "true", "yes", "on"}
        return "unittest" not in sys.modules

    def _ui_agent_runtime_available(self) -> bool:
        """检查 UI Agent 的运行环境是否就绪。"""
        ui_root = self.agent_root / "UI Agent"
        if not (ui_root / "ui_runtime_bridge.py").exists():
            return False
        return importlib.util.find_spec("openai") is not None

    def _test_agent_enabled(self) -> bool:
        """检查 Test Agent 是否启用。"""
        explicit = os.getenv("ISOFTDEVAGENTS_ENABLE_TEST_AGENT")
        if explicit is not None:
            return explicit.strip().lower() in {"1", "true", "yes", "on"}
        return "unittest" not in sys.modules

    def _test_agent_site_packages_dir(self) -> str | None:
        """返回 Test Agent 的 site-packages 目录。"""
        explicit = _normalize_env_path(os.getenv("ISOFTDEVAGENTS_TEST_AGENT_SITE_PACKAGES"))
        if explicit:
            return explicit
        lib_root = self.agent_root / "TestAgent" / ".venv" / "lib"
        if not lib_root.exists():
            return None
        matches = sorted(lib_root.glob("python*/site-packages"))
        if matches:
            return str(matches[0])
        return None

    def _ui_agent_python_bin(self) -> str:
        """返回 UI Agent 使用的 Python 解释器路径。"""
        explicit = _normalize_env_path(os.getenv("ISOFTDEVAGENTS_UI_AGENT_PYTHON_BIN"))
        if explicit:
            if Path(explicit).exists():
                return explicit
            logger.warning(
                "Configured UI Agent python does not exist, falling back to auto-detection. path=%s",
                explicit,
            )
        candidate = self.agent_root / "UI Agent" / ".venv" / "bin" / "python"
        if candidate.exists():
            return str(candidate)
        return "python3"

    def _test_agent_python_bin(self) -> str:
        """返回 Test Agent 使用的 Python 解释器路径。"""
        explicit = _normalize_env_path(os.getenv("ISOFTDEVAGENTS_TEST_AGENT_PYTHON_BIN"))
        if explicit:
            if Path(explicit).exists():
                return explicit
            logger.warning(
                "Configured Test Agent python does not exist, falling back to auto-detection. path=%s",
                explicit,
            )
        candidate = self.agent_root / "TestAgent" / ".venv" / "bin" / "python"
        if candidate.exists():
            return str(candidate)
        return "python3"

    def _test_agent_runtime_available(self) -> bool:
        """检查 Test Agent 的运行环境是否就绪。"""
        test_agent_root = self.agent_root / "TestAgent"
        if not (test_agent_root / "agent.py").exists():
            return False
        site_packages_dir = self._test_agent_site_packages_dir()
        if site_packages_dir:
            return Path(site_packages_dir).exists()
        return importlib.util.find_spec("crewai") is not None

    def _python_runtime_has_module(self, python_bin: str, module_name: str) -> bool:
        """探测指定 Python 解释器是否安装了某个模块。"""
        candidate = (python_bin or "").strip() or "python3"
        try:
            probe = subprocess.run(
                [
                    candidate,
                    "-c",
                    (
                        "import importlib.util, sys; "
                        f"sys.exit(0 if importlib.util.find_spec('{module_name}') else 1)"
                    ),
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            return False
        return probe.returncode == 0

    async def _build_with_coding_agent(
        self,
        *,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        artifacts: dict[str, Any],
        locale: str = "en",
        task_id: str | None = None,
        status_callback: StatusCallback | None = None,
        usage_event_callback: Any = None,
        runtime_event_callback: Any = None,
    ) -> list[dict[str, str]] | None:
        """Coding Agent 的执行入口：准备环境、启动 Agent、处理超时和异常。"""
        if not self._coding_agent_enabled():
            return None
        if not self.is_remote_enabled():
            return None
        if not self._coding_agent_runtime_available():
            return None

        coding_agent_root = self.agent_root / "Coding Agent" / "agent"
        if not (coding_agent_root / "app.py").exists():
            return None

        loop = asyncio.get_running_loop()
        runtime_home = Path(tempfile.mkdtemp(prefix="coding-agent-runtime-"))
        output_root = runtime_home / "generated"

        async def emit_coding_usage_payload(payload: dict[str, Any]) -> None:
            if usage_event_callback is None:
                return
            await usage_event_callback(
                self._normalize_usage_metadata(
                    payload,
                    default_model=self._runtime_model_name("crewai"),
                )
            )

        def forward_coding_usage_payload(payload: dict[str, Any]) -> None:
            if usage_event_callback is None or loop.is_closed():
                return
            asyncio.run_coroutine_threadsafe(
                emit_coding_usage_payload(payload),
                loop,
            )

        forward_coding_runtime_event = self._sync_runtime_event_emitter(
            loop=loop,
            runtime_event_callback=runtime_event_callback,
            agent_name="coding_agent",
            task_id=task_id,
        )

        cancel_event = threading.Event()
        completion_event = threading.Event()

        def run_coding_agent() -> dict[str, Any]:
            completion_state = "stopped"
            try:
                return agent_bridge.run_code_agent(
                    code_agent_root=coding_agent_root,
                    runtime_home=runtime_home,
                    python_bin=self._coding_agent_python_bin(),
                    project_manifest=self._build_coding_agent_project_manifest(
                        prompt=prompt,
                        selected_modules=selected_modules,
                        artifacts=artifacts,
                    ),
                    semantic_model=self._build_coding_agent_semantic_model(
                        prompt=prompt,
                        selected_modules=selected_modules,
                        artifacts=artifacts,
                    ),
                    srs_text=str(artifacts.get("prd") or ""),
                    architecture_text=str(artifacts.get("architecture") or ""),
                    api_spec_text=str(artifacts.get("api_spec") or ""),
                    output_root=output_root,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    model=self._runtime_model_name("crewai"),
                    stdout_line_handler=self._sync_status_emitter(
                        loop=loop,
                        agent_name="Coding Agent",
                        status_callback=status_callback,
                        locale=locale,
                        task_id=task_id,
                    ),
                    stderr_line_handler=self._sync_status_emitter(
                        loop=loop,
                        agent_name="Coding Agent stderr",
                        status_callback=status_callback,
                        locale=locale,
                        task_id=task_id,
                        stream_kind="stderr",
                    ),
                    usage_callback=forward_coding_usage_payload,
                    runtime_event_callback=forward_coding_runtime_event,
                    cancel_event=cancel_event,
                )
            except asyncio.CancelledError:
                completion_state = "cancelled"
                raise
            except Exception:
                completion_state = "failed"
                raise
            finally:
                self._mark_running_agent_completion(
                    task_id=task_id,
                    completion_event=completion_event,
                    runtime_state=completion_state,
                )

        try:
            self._register_running_agent_runtime(
                task_id=task_id,
                agent_name="coding_agent",
                cancel_event=cancel_event,
                completion_event=completion_event,
                runtime_home=runtime_home,
                output_root=output_root,
            )
            # Code 阶段现在只允许真实 Code Agent 产出文件。
            # 这里把平台整理好的输入合同交给统一桥梁，桥梁再直接函数调用 Agent。
            runtime_result = await asyncio.wait_for(
                _run_in_agent_executor(run_coding_agent),
                timeout=self.coding_agent_timeout,
            )
        except asyncio.TimeoutError as exc:
            cancel_event.set()
            debug_bundle = self._persist_agent_debug_bundle(
                agent_name="coding-agent",
                output_root=output_root,
                context={
                    "projectName": self._project_name_from_prompt(prompt),
                    "model": self._litellm_model_name(),
                    "reason": "timeout",
                    "stage": "code_generation",
                    "timeout": self.coding_agent_timeout,
                },
                extra_paths={
                    # 教学注释：
                    # Code Agent 的真实输入和中间状态都在 runtime_home 里。
                    # 超时后把整棵目录一起保留下来，后面排查时才能看到传给 Agent 的合同文件。
                    "runtime-home": runtime_home,
                },
            )
            logger.exception("Coding Agent timed out after %.1fs.", self.coding_agent_timeout)
            if debug_bundle is not None:
                logger.error("Coding Agent debug bundle saved to %s", debug_bundle)
            _cleanup_path_if_configured(runtime_home)
            raise RuntimeError(f"Coding Agent timed out after {int(self.coding_agent_timeout)}s.") from exc
        except asyncio.CancelledError as exc:
            cancel_event.set()
            debug_bundle = self._persist_agent_debug_bundle(
                agent_name="coding-agent",
                output_root=output_root,
                context={
                    "projectName": self._project_name_from_prompt(prompt),
                    "model": self._litellm_model_name(),
                    "reason": "cancelled",
                    "stage": "code_generation",
                },
                extra_paths={"runtime-home": runtime_home},
            )
            if debug_bundle is not None:
                logger.error("Coding Agent cancelled; debug bundle saved to %s", debug_bundle)
            _cleanup_path_if_configured(runtime_home)
            raise
        except Exception as exc:
            cancel_event.set()
            debug_bundle = self._persist_agent_debug_bundle(
                agent_name="coding-agent",
                output_root=output_root,
                context={
                    "projectName": self._project_name_from_prompt(prompt),
                    "model": self._litellm_model_name(),
                    "reason": "runtime_exception",
                    "stage": "code_generation",
                    "error": str(exc),
                },
                extra_paths={
                    "runtime-home": runtime_home,
                },
            )
            logger.exception("Coding Agent execution failed.")
            if debug_bundle is not None:
                logger.error("Coding Agent debug bundle saved to %s", debug_bundle)
            _cleanup_path_if_configured(runtime_home)
            return None
        finally:
            self._unregister_running_agent_runtime(task_id)
        files = runtime_result.get("files") if isinstance(runtime_result, dict) else None
        usage = runtime_result.get("usage") if isinstance(runtime_result, dict) else None
        self._set_last_usage_metadata(usage, default_model=self._litellm_model_name())
        _cleanup_path_if_configured(runtime_home)
        return files or None

    async def _build_with_ui_agent(
        self,
        *,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        artifacts: dict[str, Any],
        use_case_text: str,
        dialog_map_text: str,
        locale: str = "en",
        task_id: str | None = None,
        status_callback: StatusCallback | None = None,
        usage_event_callback: Any = None,
        runtime_event_callback: Any = None,
    ) -> list[dict[str, str]] | None:
        """UI Agent 的执行入口。"""
        if not self._ui_agent_enabled():
            return None
        if not self.is_remote_enabled():
            return None
        if not self._ui_agent_runtime_available():
            return None

        ui_agent_root = self.agent_root / "UI Agent"
        loop = asyncio.get_running_loop()
        runtime_home = Path(tempfile.mkdtemp(prefix="ui-agent-runtime-"))
        output_root = runtime_home / "generated"

        async def emit_ui_usage_payload(payload: dict[str, Any]) -> None:
            if usage_event_callback is None:
                return
            await usage_event_callback(
                self._normalize_usage_metadata(
                    payload,
                    default_model=self._runtime_model_name("openai_sdk"),
                )
            )

        def forward_ui_usage_payload(payload: dict[str, Any]) -> None:
            if usage_event_callback is None or loop.is_closed():
                return
            asyncio.run_coroutine_threadsafe(
                emit_ui_usage_payload(payload),
                loop,
            )

        forward_ui_runtime_event = self._sync_runtime_event_emitter(
            loop=loop,
            runtime_event_callback=runtime_event_callback,
            agent_name="ui_agent",
            task_id=task_id,
        )

        cancel_event = threading.Event()
        completion_event = threading.Event()
        stdout_emitter = self._sync_status_emitter(
            loop=loop,
            agent_name="UI Agent",
            status_callback=status_callback,
            locale=locale,
            task_id=task_id,
        )
        stderr_emitter = self._sync_status_emitter(
            loop=loop,
            agent_name="UI Agent stderr",
            status_callback=status_callback,
            locale=locale,
            task_id=task_id,
            stream_kind="stderr",
        )

        def run_ui_agent() -> dict[str, Any]:
            completion_state = "stopped"
            try:
                return agent_bridge.run_ui_agent(
                    ui_agent_root=ui_agent_root,
                    runtime_home=runtime_home,
                    project_name=self._project_name_from_prompt(prompt),
                    use_case_text=use_case_text,
                    dialog_map_text=dialog_map_text,
                    api_methods=self._build_ui_agent_api_methods_payload(
                        artifacts=artifacts,
                        selected_modules=selected_modules,
                    ),
                    output_root=output_root,
                    python_bin=self._ui_agent_python_bin(),
                    api_key=self.api_key,
                    base_url=self.base_url,
                    model=self._runtime_model_name("openai_sdk"),
                    stdout_line_handler=stdout_emitter,
                    stderr_line_handler=stderr_emitter,
                    usage_callback=forward_ui_usage_payload,
                    runtime_event_callback=forward_ui_runtime_event,
                    cancel_event=cancel_event,
                )
            except asyncio.CancelledError:
                completion_state = "cancelled"
                raise
            except Exception:
                completion_state = "failed"
                raise
            finally:
                self._mark_running_agent_completion(
                    task_id=task_id,
                    completion_event=completion_event,
                    runtime_state=completion_state,
                )

        try:
            self._register_running_agent_runtime(
                task_id=task_id,
                agent_name="ui_agent",
                cancel_event=cancel_event,
                completion_event=completion_event,
                runtime_home=runtime_home,
                output_root=output_root,
            )
            runtime_result = await asyncio.wait_for(
                _run_in_agent_executor(run_ui_agent),
                timeout=self.ui_agent_timeout,
            )
        except asyncio.TimeoutError as exc:
            cancel_event.set()
            project_name = self._project_name_from_prompt(prompt)
            debug_bundle = self._persist_ui_agent_debug_bundle(
                project_name=project_name,
                runtime_home=runtime_home,
                output_root=output_root,
                reason="timeout",
                stage="ui_generation",
                timeout=self.ui_agent_timeout,
            )
            logger.exception(
                "UI Agent timed out after %.1fs. project=%s %s debug_bundle=%s",
                self.ui_agent_timeout,
                project_name,
                self._output_snapshot(output_root),
                str(debug_bundle) if debug_bundle is not None else "-",
            )
            _cleanup_path_if_configured(runtime_home)
            raise RuntimeError(f"UI Agent timed out after {int(self.ui_agent_timeout)}s during UI generation.") from exc
        except asyncio.CancelledError as exc:
            cancel_event.set()
            project_name = self._project_name_from_prompt(prompt)
            debug_bundle = self._persist_ui_agent_debug_bundle(
                project_name=project_name,
                runtime_home=runtime_home,
                output_root=output_root,
                reason="cancelled",
                stage="ui_generation",
                timeout=self.ui_agent_timeout,
            )
            if debug_bundle is not None:
                logger.error("UI Agent cancelled. project=%s debug_bundle=%s", project_name, str(debug_bundle))
            _cleanup_path_if_configured(runtime_home)
            raise
        except UIAgentRuntimeError as exc:
            cancel_event.set()
            project_name = self._project_name_from_prompt(prompt)
            debug_bundle = self._persist_ui_agent_debug_bundle(
                project_name=project_name,
                runtime_home=runtime_home,
                output_root=Path(exc.output_root) if exc.output_root else output_root,
                stdout_text=exc.stdout_text,
                stderr_text=exc.stderr_text,
                reason=exc.reason,
                stage=exc.stage,
                timeout=self.ui_agent_timeout,
                partial_files=exc.partial_files,
            )
            logger.exception(
                "UI Agent execution failed. project=%s reason=%s stage=%s partial_files=%s debug_bundle=%s %s",
                project_name,
                exc.reason,
                exc.stage,
                exc.partial_files,
                str(debug_bundle) if debug_bundle is not None else "-",
                self._output_snapshot(Path(exc.output_root) if exc.output_root else output_root),
            )
            reason_messages = {
                "invalid_page_description_json": "UI Agent failed because page_descriptions.json was not valid JSON.",
                "invalid_dar_json": "UI Agent failed because dar_model.json was not valid JSON.",
                "invalid_single_page_contract": "UI Agent failed because the generated page description did not satisfy the single-page UI contract.",
                "missing_required_code_blocks": "UI Agent failed because html/css/javascript code blocks were incomplete.",
                "runtime_exception": f"UI Agent failed due to a runtime exception: {exc}",
            }
            _cleanup_path_if_configured(runtime_home)
            raise RuntimeError(reason_messages.get(exc.reason, f"UI Agent failed: {exc}")) from exc
        except Exception as exc:
            cancel_event.set()
            project_name = self._project_name_from_prompt(prompt)
            debug_bundle = self._persist_ui_agent_debug_bundle(
                project_name=project_name,
                runtime_home=runtime_home,
                output_root=output_root,
                reason="runtime_exception",
                stage="ui_generation",
                timeout=self.ui_agent_timeout,
            )
            logger.exception(
                "UI Agent execution failed unexpectedly. project=%s debug_bundle=%s %s",
                project_name,
                str(debug_bundle) if debug_bundle is not None else "-",
                self._output_snapshot(output_root),
            )
            _cleanup_path_if_configured(runtime_home)
            raise RuntimeError(f"UI Agent failed due to a runtime exception: {exc}") from exc
        finally:
            self._unregister_running_agent_runtime(task_id)
        files = runtime_result.get("files") if isinstance(runtime_result, dict) else None
        usage = runtime_result.get("usage") if isinstance(runtime_result, dict) else None
        self._set_last_usage_metadata(usage, default_model=self._litellm_model_name())
        _cleanup_path_if_configured(runtime_home)
        return files or None

    async def _build_with_test_agent(
        self,
        *,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        artifacts: dict[str, Any],
        code_files: list[dict[str, Any]] | None = None,
        locale: str = "en",
        task_id: str | None = None,
        status_callback: StatusCallback | None = None,
        usage_event_callback: Any = None,
        runtime_event_callback: Any = None,
    ) -> list[dict[str, str]] | None:
        """Test Agent 的执行入口。"""
        if not self._test_agent_enabled():
            return None
        if not self.is_remote_enabled():
            return None
        if not self._test_agent_runtime_available():
            return None

        test_agent_root = self.agent_root / "TestAgent"
        loop = asyncio.get_running_loop()
        runtime_home = Path(tempfile.mkdtemp(prefix="test-agent-runtime-"))
        code_root = runtime_home / "generated-code"
        dataset_name = self._project_name_from_prompt(prompt)
        self._write_runtime_workspace_files(code_root, code_files or [])

        async def emit_test_usage_payload(payload: dict[str, Any]) -> None:
            if usage_event_callback is None:
                return
            await usage_event_callback(
                self._normalize_usage_metadata(
                    payload,
                    default_model=self._runtime_model_name("crewai"),
                )
            )

        def forward_test_usage_payload(payload: dict[str, Any]) -> None:
            if usage_event_callback is None or loop.is_closed():
                return
            asyncio.run_coroutine_threadsafe(
                emit_test_usage_payload(payload),
                loop,
            )

        forward_test_runtime_event = self._sync_runtime_event_emitter(
            loop=loop,
            runtime_event_callback=runtime_event_callback,
            agent_name="Test Agent",
            task_id=task_id,
        )

        cancel_event = threading.Event()
        completion_event = threading.Event()
        stdout_emitter = self._sync_status_emitter(
            loop=loop,
            agent_name="Test Agent",
            status_callback=status_callback,
            locale=locale,
            task_id=task_id,
        )
        stderr_emitter = self._sync_status_emitter(
            loop=loop,
            agent_name="Test Agent stderr",
            status_callback=status_callback,
            locale=locale,
            task_id=task_id,
            stream_kind="stderr",
        )

        def run_test_agent() -> dict[str, Any]:
            completion_state = "stopped"
            try:
                return agent_bridge.run_test_agent(
                    test_agent_root=test_agent_root,
                    runtime_home=runtime_home,
                    dataset_name=dataset_name,
                    srs_text=str(artifacts.get("prd") or ""),
                    class_diagram_text=str(artifacts.get("architecture") or ""),
                    sequence_diagram_text=str(artifacts.get("uml_sequence") or ""),
                    architecture_text=str(artifacts.get("architecture") or ""),
                    code_root=code_root,
                    python_bin=self._test_agent_python_bin(),
                    api_key=self.api_key,
                    base_url=self.base_url,
                    model=self._runtime_model_name("crewai"),
                    stdout_line_handler=stdout_emitter,
                    stderr_line_handler=stderr_emitter,
                    usage_callback=forward_test_usage_payload,
                    runtime_event_callback=forward_test_runtime_event,
                    cancel_event=cancel_event,
                )
            except asyncio.CancelledError:
                completion_state = "cancelled"
                raise
            except Exception:
                completion_state = "failed"
                raise
            finally:
                self._mark_running_agent_completion(
                    task_id=task_id,
                    completion_event=completion_event,
                    runtime_state=completion_state,
                )

        try:
            self._register_running_agent_runtime(
                task_id=task_id,
                agent_name="test_agent",
                cancel_event=cancel_event,
                completion_event=completion_event,
                runtime_home=runtime_home,
                output_root=runtime_home / "output",
            )
            runtime_result = await asyncio.wait_for(
                _run_in_agent_executor(run_test_agent),
                timeout=self.test_agent_timeout,
            )
        except asyncio.TimeoutError as exc:
            cancel_event.set()
            salvaged_files = self._salvage_test_agent_files_from_runtime_home(
                runtime_home=runtime_home,
                dataset_name=dataset_name,
            )
            if salvaged_files:
                logger.warning(
                    "Test Agent hit timeout after %.1fs, but required files already exist. Using salvaged outputs. %s",
                    self.test_agent_timeout,
                    self._output_snapshot(runtime_home / "output"),
                )
                _cleanup_path_if_configured(runtime_home)
                return salvaged_files
            debug_bundle = self._persist_agent_debug_bundle(
                agent_name="test-agent",
                output_root=runtime_home / "output",
                context={
                    "projectName": dataset_name,
                    "model": self._litellm_model_name(),
                    "reason": "timeout",
                    "stage": "test_generation",
                    "timeout": self.test_agent_timeout,
                },
                extra_paths={
                    "runtime-home": runtime_home,
                    "memory": runtime_home / "memory",
                },
            )
            logger.exception("Test Agent timed out after %.1fs.", self.test_agent_timeout)
            if debug_bundle is not None:
                logger.error("Test Agent debug bundle saved to %s", debug_bundle)
            _cleanup_path_if_configured(runtime_home)
            raise RuntimeError(f"Test Agent timed out after {int(self.test_agent_timeout)}s.") from exc
        except asyncio.CancelledError:
            cancel_event.set()
            debug_bundle = self._persist_agent_debug_bundle(
                agent_name="test-agent",
                output_root=runtime_home / "output",
                context={
                    "projectName": dataset_name,
                    "model": self._litellm_model_name(),
                    "reason": "cancelled",
                    "stage": "test_generation",
                },
                extra_paths={
                    "runtime-home": runtime_home,
                    "memory": runtime_home / "memory",
                },
            )
            if debug_bundle is not None:
                logger.error("Test Agent cancelled; debug bundle saved to %s", debug_bundle)
            _cleanup_path_if_configured(runtime_home)
            raise
        except Exception as exc:
            cancel_event.set()
            debug_bundle = self._persist_agent_debug_bundle(
                agent_name="test-agent",
                output_root=runtime_home / "output",
                context={
                    "projectName": dataset_name,
                    "model": self._litellm_model_name(),
                    "reason": "runtime_exception",
                    "stage": "test_generation",
                    "error": str(exc),
                },
                extra_paths={
                    "runtime-home": runtime_home,
                    "memory": runtime_home / "memory",
                },
            )
            logger.exception("Test Agent execution failed.")
            if debug_bundle is not None:
                logger.error("Test Agent debug bundle saved to %s", debug_bundle)
            _cleanup_path_if_configured(runtime_home)
            return None
        finally:
            self._unregister_running_agent_runtime(task_id)
        files = runtime_result.get("files") if isinstance(runtime_result, dict) else None
        usage = runtime_result.get("usage") if isinstance(runtime_result, dict) else None
        self._set_last_usage_metadata(usage, default_model=self._litellm_model_name())
        _cleanup_path_if_configured(runtime_home)
        return files or None

    def _requirements_agent_module_names(self) -> tuple[str, ...]:
        """列出 Requirements Agent 可加载的模块名称元组。"""
        return (
            "main",
            "StandardProcess",
            "NonStandardProcess",
            "BusinessRequirements",
            "MetaAnalysis",
            "RequirementAnalysis",
            "RequirementElicitation",
            "RequirementSpecification",
            "util",
            "util.runtime_env",
            "util.util",
            "util.DAG",
            "util.Artifacts",
            "util.validate_format",
            "util.user_case",
        )

    def _prepare_requirements_agent_runtime(
        self,
        *,
        description_text: str,
    ) -> dict[str, Any]:
        """
        统一准备需求 Agent 运行时要用到的目录和配置文件。

        之前这些准备逻辑都堆在执行函数里，读起来会像“一整坨启动脚本”。
        拆出来以后，真正的执行流程就只剩三件事：
        1. 准备运行上下文
        2. 调用需求 Agent 函数入口
        3. 收尾并整理结果
        """

        output_root = Path(tempfile.mkdtemp(prefix="reagent-output-"))
        description_path = output_root / "project_description.md"
        description_path.write_text(description_text, encoding="utf-8")

        requirements_root = self.agent_root / "Requirements Agent" / "reagent"
        runtime_home = requirements_root / ".runtime-home"
        runtime_home.mkdir(parents=True, exist_ok=True)

        tasks_config_path = self._requirements_agent_tasks_config_path(runtime_home)
        self._write_requirements_agent_runtime_tasks_config(tasks_config_path)

        return {
            "output_root": output_root,
            "description_path": description_path,
            "runtime_home": runtime_home,
            "tasks_config_path": tasks_config_path,
            "litellm_model": self._litellm_model_name(),
        }

    def _requirements_agent_stream_emitters(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        mode: str,
        locale: str,
        status_callback: StatusCallback | None,
        task_id: str | None = None,
    ) -> tuple[Callable[[str], None], Callable[[str], None]]:
        """把标准输出和标准错误都接入现有的日志与前端进度推送。"""

        status_emit = self._sync_status_emitter(
            loop=loop,
            agent_name="Requirements Agent",
            status_callback=status_callback,
            locale=locale,
            task_id=task_id,
        )
        last_console_log = {"value": ""}

        def emit_stdout_line(line: str) -> None:
            summarized = self._summarize_requirements_stream_line(line, mode=mode)
            if summarized and summarized != last_console_log["value"]:
                last_console_log["value"] = summarized
                terminal_logger.info(summarized)
            status_emit(line)

        def emit_stderr_line(line: str) -> None:
            self._log_agent_stream_line("Requirements Agent", "stderr", line)
            status_emit(line)

        return emit_stdout_line, emit_stderr_line

    def _requirements_agent_process_like_error(
        self,
        *,
        mode: str,
        timeout: float | None = None,
        exc: Exception | None = None,
    ) -> Exception:
        """
        现有上层流程仍然按“像子进程一样”的异常结构处理。

        这里保留这个兼容外壳，但收口在一个地方，避免执行主流程里到处拼
        CalledProcessError / TimeoutExpired。
        """

        command = ["requirements-agent", mode]
        if timeout is not None:
            timeout_error = subprocess.TimeoutExpired(
                cmd=command,
                timeout=timeout,
                output="",
                stderr="",
            )
            return timeout_error

        stdout_text = ""
        stderr_text = ""
        if isinstance(exc, RequirementsAgentBridgeExecutionError):
            stdout_text = exc.stdout_text
            stderr_text = exc.stderr_text
        return subprocess.CalledProcessError(
            returncode=1,
            cmd=command,
            output=stdout_text,
            stderr=stderr_text,
        )

    async def _run_requirements_agent_inprocess(
        self,
        *,
        mode: str,
        task_id: str | None = None,
        project_name: str,
        description_text: str,
        reference_materials: list[dict[str, Any]] | None = None,
        timeout: float,
        locale: str = "en",
        status_callback: StatusCallback | None = None,
        artifact_file_callback: ArtifactFileCallback | None = None,
        human_feedback_callback: HumanFeedbackRequestCallback | None = None,
        usage_event_callback: Any = None,
        runtime_event_callback: Any = None,
    ) -> dict[str, Any]:
        """Requirements Agent 的进程内执行（通过函数桥调用）。"""
        reference_materials = reference_materials or []
        runtime_context = self._prepare_requirements_agent_runtime(description_text=description_text)
        output_root = runtime_context["output_root"]
        runtime_home = runtime_context["runtime_home"]
        tasks_config_path = runtime_context["tasks_config_path"]
        litellm_model = runtime_context["litellm_model"]
        loop = asyncio.get_running_loop()
        cancel_event = threading.Event()
        completion_event = threading.Event()
        emit_stdout_line, emit_stderr_line = self._requirements_agent_stream_emitters(
            loop=loop,
            mode=mode,
            locale=locale,
            status_callback=status_callback,
            task_id=task_id,
        )
        emit_runtime_event = self._sync_runtime_event_emitter(
            loop=loop,
            runtime_event_callback=runtime_event_callback,
            agent_name="requirements_agent",
            task_id=task_id,
        )

        seeded_files: list[str] = []
        observed_output_signatures: dict[str, tuple[int, int]] = {}
        runtime_started_at = datetime.now(UTC)
        runtime_last_output_at = {"value": runtime_started_at}
        runtime_stdout_line_count = {"value": 0}
        runtime_stderr_line_count = {"value": 0}
        runtime_latest_output_file = {"value": None}

        def mark_runtime_output(*, latest_output_file: str | None = None) -> None:
            runtime_last_output_at["value"] = datetime.now(UTC)
            if latest_output_file:
                runtime_latest_output_file["value"] = latest_output_file

        def tracked_stdout_line(line: str) -> None:
            if str(line).strip():
                runtime_stdout_line_count["value"] += 1
                mark_runtime_output()
            emit_stdout_line(line)

        def tracked_stderr_line(line: str) -> None:
            if str(line).strip():
                runtime_stderr_line_count["value"] += 1
                mark_runtime_output()
            emit_stderr_line(line)

        async def emit_runtime_snapshot(*, state: str | None = None) -> None:
            """
            原因注释：
            这个函数从 poll_output_updates (async) 中调用，跑在 event loop 上。
            之前它是 sync def，内部用 run_coroutine_threadsafe + future.result(timeout=10)
            等待 event loop 执行回调——但 event loop 此刻正在执行自己，形成 DEADLOCK。
            改为 async def 后直接 await 回调，不再死锁。
            """
            if runtime_event_callback is None:
                return
            now = datetime.now(UTC)
            payload = {
                "runtimePid": None,
                "runtimeState": state or ("running" if not agent_task.done() else "exited"),
                "startedAt": runtime_started_at.isoformat(),
                "lastHeartbeatAt": now.isoformat(),
                "lastOutputAt": runtime_last_output_at["value"].isoformat(),
                "latestOutputFile": runtime_latest_output_file["value"],
                "outputDir": str(output_root),
                "outputFileCount": len(observed_output_signatures),
                "stdoutLineCount": runtime_stdout_line_count["value"],
                "stderrLineCount": runtime_stderr_line_count["value"],
                "secondsSinceLastOutput": max(0, int((now - runtime_last_output_at["value"]).total_seconds())),
                "elapsedSeconds": max(0, int((now - runtime_started_at).total_seconds())),
            }
            if task_id:
                self._update_running_agent_runtime(
                    task_id,
                    runtime_pid=payload.get("runtimePid"),
                    runtime_state=payload.get("runtimeState"),
                    latest_output_file=payload.get("latestOutputFile"),
                    output_root=payload.get("outputDir"),
                    last_runtime_snapshot=dict(payload),
                )
            if runtime_event_callback is not None:
                result = runtime_event_callback(payload)
                if inspect.isawaitable(result):
                    await result

        async def emit_output_updates() -> None:
            if artifact_file_callback is None:
                return
            for path in sorted(candidate for candidate in output_root.rglob("*") if candidate.is_file()):
                relative_name = path.relative_to(output_root).as_posix()
                try:
                    stats = path.stat()
                except FileNotFoundError:
                    continue
                signature = (int(stats.st_mtime_ns), int(stats.st_size))
                if observed_output_signatures.get(relative_name) == signature:
                    continue
                observed_output_signatures[relative_name] = signature
                mark_runtime_output(latest_output_file=relative_name)
                await artifact_file_callback(
                    {
                        "agentName": "requirements_agent",
                        "outputDir": str(output_root),
                        "fileName": relative_name,
                    }
                )

        async def poll_output_updates(stop_event: asyncio.Event) -> None:
            try:
                while not stop_event.is_set():
                    await emit_output_updates()
                    await emit_runtime_snapshot()
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        continue
                await emit_output_updates()
                await emit_runtime_snapshot(state="exited")
            except Exception:
                logger.debug("Requirements Agent live output polling failed.", exc_info=True)

        def emit_usage_payload(payload: dict[str, Any]) -> None:
            import sys as _sys
            if usage_event_callback is None or loop.is_closed():
                print(f"[emit_usage_payload] SKIP: callback={usage_event_callback is not None} loop_closed={loop.is_closed()}", file=_sys.__stderr__, flush=True)
                return
            normalized_payload = self._normalize_usage_metadata(
                payload,
                default_model=self._litellm_model_name(),
            )
            if normalized_payload is None:
                print(f"[emit_usage_payload] SKIP: normalized to None. raw={payload}", file=_sys.__stderr__, flush=True)
                return
            print(f"[emit_usage_payload] forwarding: {normalized_payload}", file=_sys.__stderr__, flush=True)
            # 原因注释：
            # 必须等待 future 完成，确保 streaming usage 先写入 DB，
            # 否则后续 _reconciled_stage_usage 对账时 _streaming_usage_snapshot
            # 读到空值，会把同一笔 usage 重复累加到全局统计。
            future = asyncio.run_coroutine_threadsafe(
                usage_event_callback(normalized_payload),
                loop,
            )
            try:
                future.result(timeout=30)
                print("[emit_usage_payload] OK: usage written to DB", file=_sys.__stderr__, flush=True)
            except Exception as exc:
                print(f"[emit_usage_payload] FAILED: {exc}", file=_sys.__stderr__, flush=True)

        data_path: str | None = None
        data_dir: Path | None = None
        if reference_materials:
            upload_ids = [m.get("id") for m in reference_materials if m.get("id")]
            if upload_ids:
                try:
                    from app.services.store import store
                    data_dir = Path(tempfile.mkdtemp(prefix="req_agent_data_"))
                    for upload_id in upload_ids:
                        content = await store.read_upload_content(upload_id)
                        if content:
                            uploads = await store.get_uploads([upload_id])
                            if uploads:
                                (data_dir / uploads[0].fileName).write_bytes(content)
                    data_path = str(data_dir)
                    logger.info("Requirements Agent data_path prepared: %s with %d files", data_dir, len(upload_ids))
                except Exception as exc:
                    logger.warning("Failed to prepare data_path from reference_materials: %s", exc)
                    data_path = None
                    data_dir = None

        def run_agent() -> None:
            completion_state = "stopped"
            prompt_input_provider = None

            # 当平台提供了 human_feedback_callback 时，创建注入式输入 provider，
            # 走进程内 bridge 以支持审阅反馈流程（business_scope / BRD / elicitation）。
            # 没有 feedback 回调时继续走子进程隔离模式。
            if task_id and human_feedback_callback is not None:
                try:
                    from app.agents.requirements_bridge import load_requirements_agent_prompt_input_bridge

                    prompt_bridge_module = load_requirements_agent_prompt_input_bridge()
                    provider = prompt_bridge_module.InjectedPromptInputProvider(
                        task_id=task_id,
                        output_files_resolver=lambda: self._requirements_feedback_output_files(output_root),
                        waiting_callback=lambda waiting_payload: self._publish_requirements_prompt_waiting(
                            task_id=task_id,
                            waiting_payload=waiting_payload,
                            output_root=output_root,
                            feedback_request_callback=human_feedback_callback,
                            loop=loop,
                        ),
                    )
                    self._create_requirements_prompt_session(task_id, provider=provider)
                    prompt_input_provider = provider
                except Exception:
                    logger.debug("Failed to set up feedback provider, falling back to subprocess mode.", exc_info=True)

            if prompt_input_provider is not None:
                logger.info(
                    "Requirements Agent starting (in-process, feedback enabled): mode=%s project=%s output=%s model=%s",
                    mode,
                    project_name,
                    output_root,
                    litellm_model,
                )
            else:
                logger.info(
                    "Requirements Agent starting (subprocess): mode=%s project=%s output=%s model=%s",
                    mode,
                    project_name,
                    output_root,
                    litellm_model,
                )

            try:
                try:
                    from app.agents.reagent_adapter import _patched_run_with_retry
                except Exception as _import_err:
                    _patched_run_with_retry = None
                    print(f"[orchestrator] WARN: _patched_run_with_retry import failed: {_import_err}", file=sys.__stderr__, flush=True)

                print(f"[orchestrator] mode={mode} prompt_input_provider={prompt_input_provider is not None} _patched_run_with_retry={_patched_run_with_retry is not None}", file=sys.__stderr__, flush=True)

                def _setup_logging() -> None:
                    try:
                        from app.agents.llm_debug import install_crewai_llm_debug_logging
                        install_crewai_llm_debug_logging()
                    except Exception:
                        pass

                if prompt_input_provider is not None:
                    from app.agents.requirements_bridge import run_requirements_agent as run_requirements_agent_inprocess

                    return run_requirements_agent_inprocess(
                        mode=mode,
                        project_name=project_name,
                        description_text=description_text,
                        output_root=output_root,
                        runtime_home=runtime_home,
                        tasks_config_path=tasks_config_path,
                        api_key=self.api_key,
                        base_url=self.base_url,
                        model=self._runtime_model_name("requirements_bridge"),
                        site_packages_dir=self._requirements_agent_site_packages_dir(),
                        stdout_line_handler=tracked_stdout_line,
                        stderr_line_handler=tracked_stderr_line,
                        prompt_input_provider=prompt_input_provider,
                        run_with_retry_override=_patched_run_with_retry,
                        setup_logging=_setup_logging,
                        usage_callback=emit_usage_payload,
                        cancel_event=cancel_event,
                        task_id=task_id,
                        srs_example_path="util/doc_template/document_example.md",
                        srs_template=None,
                        data_path=data_path,
                    )

                return agent_bridge.run_requirements_agent(
                    mode=mode,
                    project_name=project_name,
                    description_text=description_text,
                    output_root=output_root,
                    runtime_home=runtime_home,
                    tasks_config_path=tasks_config_path,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    model=self._runtime_model_name("requirements_bridge"),
                    agent_root=str(self.agent_root),
                    python_bin=self._requirements_agent_python_bin(),
                    site_packages_dir=self._requirements_agent_site_packages_dir(),
                    timeout=timeout,
                    stdout_line_handler=tracked_stdout_line,
                    stderr_line_handler=tracked_stderr_line,
                    usage_callback=emit_usage_payload,
                    run_with_retry_override=_patched_run_with_retry,
                    runtime_event_callback=emit_runtime_event,
                    cancel_event=cancel_event,
                    srs_example_path="util/doc_template/document_example.md",
                    srs_template=None,
                    data_path=data_path,
                )
            except asyncio.CancelledError:
                completion_state = "cancelled"
                raise
            except Exception:
                completion_state = "failed"
                raise
            finally:
                if prompt_input_provider is not None and task_id:
                    self._close_requirements_prompt_session(task_id)
                self._mark_running_agent_completion(
                    task_id=task_id,
                    completion_event=completion_event,
                    runtime_state=completion_state,
                )

        output_poll_stop = asyncio.Event()
        output_poll_task = asyncio.create_task(poll_output_updates(output_poll_stop))
        agent_task = asyncio.create_task(_run_in_agent_executor(run_agent))

        self._register_running_agent_runtime(
            task_id=task_id,
            agent_name="requirements_agent",
            cancel_event=cancel_event,
            completion_event=completion_event,
            runtime_home=runtime_home,
            output_root=output_root,
        )

        async def watch_for_cancel_signal() -> None:
            while not cancel_event.is_set():
                await asyncio.sleep(0.2)
            if task_id:
                self._close_requirements_prompt_session(task_id)

        cancel_watch_task = asyncio.create_task(watch_for_cancel_signal())
        try:
            runtime_result = await self._await_requirements_agent_result(
                agent_task,
                timeout=timeout,
                task_id=task_id,
            )
        except asyncio.TimeoutError as exc:
            cancel_event.set()
            if task_id:
                self._close_requirements_prompt_session(task_id)
            agent_task.cancel()
            timeout_error = self._requirements_agent_process_like_error(mode=mode, timeout=timeout)
            timeout_error.output_root = str(output_root)
            raise timeout_error from exc
        except asyncio.CancelledError:
            cancel_event.set()
            if task_id:
                self._close_requirements_prompt_session(task_id)
            raise
        except Exception as exc:
            cancel_event.set()
            if task_id:
                self._close_requirements_prompt_session(task_id)
            agent_task.cancel()
            process_error = self._requirements_agent_process_like_error(mode=mode, exc=exc)
            process_error.output_root = str(output_root)
            raise process_error from exc
        finally:
            cancel_watch_task.cancel()
            try:
                await cancel_watch_task
            except asyncio.CancelledError:
                pass
            output_poll_stop.set()
            await output_poll_task
            if task_id:
                self._close_requirements_prompt_session(task_id)
            self._unregister_running_agent_runtime(task_id)
            if data_dir and data_dir.exists():
                shutil.rmtree(data_dir, ignore_errors=True)

        return {
            "output_root": output_root,
            "stdout": str(runtime_result.get("stdout") or ""),
            "stderr": str(runtime_result.get("stderr") or ""),
            "tasks_config_path": runtime_result.get("tasks_config_path") or tasks_config_path,
            "model": runtime_result.get("model") or litellm_model,
            "seededFiles": runtime_result.get("seededFiles") if isinstance(runtime_result.get("seededFiles"), list) else seeded_files,
            "usage": self._normalize_usage_metadata(
                runtime_result.get("usage"),
                default_model=str(runtime_result.get("model") or litellm_model),
            ),
        }

    async def _analyze_with_requirements_agent(
        self,
        prompt: str,
        reference_materials: list[dict[str, Any]],
        locale: str = "en",
        status_callback: StatusCallback | None = None,
        usage_event_callback: Any = None,
    ) -> dict[str, Any] | None:
        """Requirements Agent 分析阶段的执行入口。"""
        if not self._requirements_agent_enabled():
            logger.warning("Requirements Agent analysis skipped because the agent is disabled.")
            return None
        if not self._requirements_agent_runtime_available():
            logger.warning(
                "Requirements Agent analysis skipped because the runtime is unavailable. python_bin=%s site_packages=%s",
                self._requirements_agent_python_bin(),
                self._requirements_agent_site_packages_dir(),
            )
            return None

        description_text = self._build_requirements_agent_description(prompt, reference_materials)
        project_name = self._project_name_from_prompt(prompt)
        output_root: Path | None = None
        stdout_text = ""
        stderr_text = ""
        runtime_meta: dict[str, Any] | None = None
        try:
            logger.info(
                "Requirements Agent analysis started: project=%s locale=%s references=%s",
                project_name,
                locale,
                len(reference_materials),
            )
            runtime_meta = await self._run_requirements_agent_inprocess(
                mode="analysis",
                project_name=project_name,
                description_text=description_text,
                reference_materials=reference_materials,
                timeout=self.analysis_agent_timeout,
                locale=locale,
                status_callback=status_callback,
                usage_event_callback=usage_event_callback,
            )
            output_root = Path(runtime_meta["output_root"])
            stdout_text = str(runtime_meta.get("stdout") or "")
            stderr_text = str(runtime_meta.get("stderr") or "")
            logger.info(
                "Requirements Agent analysis finished: project=%s %s stdout_chars=%s stderr_chars=%s",
                project_name,
                self._requirements_agent_output_snapshot(output_root),
                len(stdout_text),
                len(stderr_text),
            )
            self._set_last_usage_metadata(
                runtime_meta.get("usage"),
                default_model=str(runtime_meta.get("model") or self._litellm_model_name()),
            )
            result = self._read_requirements_agent_output(output_root, prompt=prompt)
            if result is None and self._has_requirements_agent_output(output_root):
                debug_bundle = self._persist_agent_debug_bundle(
                    agent_name="requirements-agent-analysis",
                    output_root=output_root,
                    stdout_text=stdout_text,
                    stderr_text=stderr_text,
                    context={
                        "mode": "analysis",
                        "projectName": project_name,
                        "prompt": prompt,
                        "model": str(runtime_meta.get("model") or self._litellm_model_name()),
                    },
                )
                if debug_bundle is not None:
                    logger.error(
                        "Requirements Agent output incomplete for project %s; debug bundle saved to %s. %s",
                        project_name,
                        debug_bundle,
                        self._requirements_agent_output_snapshot(output_root),
                    )
                raise RuntimeError("Requirements Agent output is incomplete: missing feature_tree.md")
            if result is None:
                logger.error(
                    "Requirements Agent returned no usable analysis output for project %s. %s stdout_preview=%s stderr_preview=%s",
                    project_name,
                    self._requirements_agent_output_snapshot(output_root),
                    _truncate_for_log(stdout_text),
                    _truncate_for_log(stderr_text),
                )
            return result
        except subprocess.TimeoutExpired as exc:
            stdout_text = self._decode_subprocess_stream(exc.stdout or exc.output)
            stderr_text = self._decode_subprocess_stream(exc.stderr)
            if output_root is None:
                output_root_value = getattr(exc, "output_root", None)
                if output_root_value:
                    output_root = Path(str(output_root_value))
            if output_root is not None and self._has_requirements_agent_output(output_root):
                logger.warning(
                    "Requirements Agent timed out; using partial output from %s. %s",
                    output_root,
                    self._requirements_agent_output_snapshot(output_root),
                )
                return self._read_requirements_agent_output(
                    output_root,
                    prompt=prompt,
                    status="partial_timeout",
                )
            stdout_modules = self._extract_requirements_agent_stdout_modules(stdout_text)
            if stdout_modules:
                logger.warning(
                    "Requirements Agent timed out after producing stdout modules; using stdout salvage path. stdout_preview=%s",
                    _truncate_for_log(stdout_text),
                )
                return self._read_requirements_agent_output(
                    output_root or Path(tempfile.mkdtemp(prefix="reagent-output-empty-")),
                    prompt=prompt,
                    status="partial_stdout",
                    stdout_modules=stdout_modules,
                )
            self._persist_agent_debug_bundle(
                agent_name="requirements-agent-analysis",
                output_root=output_root,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
                context={
                    "mode": "analysis",
                    "projectName": project_name,
                    "prompt": prompt,
                    "model": self._litellm_model_name(),
                    "error": "timeout",
                    "command": exc.cmd if isinstance(exc.cmd, list) else ["requirements-agent", "analysis"],
                },
            )
            logger.exception(
                "Requirements Agent timed out without usable output. project=%s %s stdout_preview=%s stderr_preview=%s",
                project_name,
                self._requirements_agent_output_snapshot(output_root),
                _truncate_for_log(stdout_text),
                _truncate_for_log(stderr_text),
            )
            return None
        except subprocess.CalledProcessError as exc:
            stdout_text = self._decode_subprocess_stream(exc.stdout)
            stderr_text = self._decode_subprocess_stream(exc.stderr)
            if output_root is None:
                output_root_value = getattr(exc, "output_root", None)
                if output_root_value:
                    output_root = Path(str(output_root_value))
            stdout_modules = self._extract_requirements_agent_stdout_modules(stdout_text)
            if stdout_modules:
                logger.warning(
                    "Requirements Agent exited non-zero after producing stdout modules; using stdout salvage path. stdout_preview=%s",
                    _truncate_for_log(stdout_text),
                )
                return self._read_requirements_agent_output(
                    output_root or Path(tempfile.mkdtemp(prefix="reagent-output-empty-")),
                    prompt=prompt,
                    status="partial_stdout",
                    stdout_modules=stdout_modules,
                )
            self._persist_agent_debug_bundle(
                agent_name="requirements-agent-analysis",
                output_root=output_root,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
                context={
                    "mode": "analysis",
                    "projectName": project_name,
                    "prompt": prompt,
                    "model": self._litellm_model_name(),
                    "error": "non_zero_exit",
                    "returncode": exc.returncode,
                    "command": exc.cmd if isinstance(exc.cmd, list) else ["requirements-agent", "analysis"],
                },
            )
            logger.exception(
                "Requirements Agent execution failed. project=%s %s stdout_preview=%s stderr_preview=%s",
                project_name,
                self._requirements_agent_output_snapshot(output_root),
                _truncate_for_log(stdout_text),
                _truncate_for_log(stderr_text),
            )
            return None
        except RuntimeError:
            raise
        except Exception:
            self._persist_agent_debug_bundle(
                agent_name="requirements-agent-analysis",
                output_root=output_root,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
                context={
                    "mode": "analysis",
                    "projectName": project_name,
                    "prompt": prompt,
                    "model": self._litellm_model_name(),
                },
            )
            logger.exception(
                "Requirements Agent execution failed with unexpected exception. project=%s %s stdout_preview=%s stderr_preview=%s",
                project_name,
                self._requirements_agent_output_snapshot(output_root),
                _truncate_for_log(stdout_text),
                _truncate_for_log(stderr_text),
            )
            return None

    async def _build_with_requirements_agent_artifacts(
        self,
        *,
        task_id: str | None = None,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        reference_materials: list[dict[str, Any]],
        existing_artifacts: list[dict[str, Any]],
        locale: str = "en",
        status_callback: StatusCallback | None = None,
        artifact_file_callback: ArtifactFileCallback | None = None,
        human_feedback_callback: HumanFeedbackRequestCallback | None = None,
        usage_event_callback: Any = None,
        runtime_event_callback: Any = None,
    ) -> dict[str, Any] | None:
        """Requirements Agent 完整生成阶段的执行入口。"""
        if not self._requirements_agent_enabled():
            return None
        if not self._requirements_agent_runtime_available():
            return None

        description_text = self._build_requirements_agent_generation_description(
            prompt=prompt,
            selected_modules=selected_modules,
            reference_materials=reference_materials,
            existing_artifacts=existing_artifacts,
        )
        project_name = self._project_name_from_prompt(prompt)
        output_root: Path | None = None
        stdout_text = ""
        stderr_text = ""
        try:
            runtime_meta = await self._run_requirements_agent_inprocess(
                mode="full",
                task_id=task_id,
                project_name=project_name,
                description_text=description_text,
                reference_materials=reference_materials,
                timeout=self.generation_agent_timeout,
                locale=locale,
                status_callback=status_callback,
                artifact_file_callback=artifact_file_callback,
                human_feedback_callback=human_feedback_callback,
                usage_event_callback=usage_event_callback,
                runtime_event_callback=runtime_event_callback,
            )
            output_root = Path(runtime_meta["output_root"])
            stdout_text = str(runtime_meta.get("stdout") or "")
            stderr_text = str(runtime_meta.get("stderr") or "")
            payload = self._read_requirements_agent_artifact_output(
                output_root,
                prompt=prompt,
                selected_modules=selected_modules,
                seeded_files=runtime_meta.get("seededFiles") if isinstance(runtime_meta.get("seededFiles"), list) else None,
            )
            if payload is None and self._has_requirements_agent_output(output_root):
                debug_bundle = self._persist_agent_debug_bundle(
                    agent_name="requirements-agent-artifacts",
                    output_root=output_root,
                    stdout_text=stdout_text,
                    stderr_text=stderr_text,
                    context={
                        "mode": "full",
                        "projectName": project_name,
                        "prompt": prompt,
                        "model": str(runtime_meta.get("model") or self._litellm_model_name()),
                        "error": "missing_required_output",
                        "requiredFiles": ["SRS.md"],
                    },
                )
                logger.error(
                    "Requirements Agent produced files but they are not usable yet. project=%s %s missing_required=SRS.md debug_bundle=%s stdout_preview=%s stderr_preview=%s",
                    project_name,
                    self._requirements_agent_output_snapshot(output_root),
                    str(debug_bundle) if debug_bundle is not None else "-",
                    _truncate_for_log(stdout_text),
                    _truncate_for_log(stderr_text),
                )
            if payload is not None:
                payload["usage"] = self._normalize_usage_metadata(
                    runtime_meta.get("usage"),
                    default_model=str(runtime_meta.get("model") or self._litellm_model_name()),
                )
            return payload
        except subprocess.TimeoutExpired as exc:
            stdout_text = self._decode_subprocess_stream(exc.stdout or exc.output)
            stderr_text = self._decode_subprocess_stream(exc.stderr)
            output_root_value = getattr(exc, "output_root", None)
            if output_root is None and output_root_value:
                output_root = Path(str(output_root_value))
            if output_root is not None and self._has_requirements_agent_output(output_root):
                debug_bundle = self._persist_agent_debug_bundle(
                    agent_name="requirements-agent-artifacts",
                    output_root=output_root,
                    stdout_text=stdout_text,
                    stderr_text=stderr_text,
                    context={
                        "mode": "full",
                        "projectName": project_name,
                        "prompt": prompt,
                        "model": self._litellm_model_name(),
                        "error": "timeout",
                        "requiredFiles": ["SRS.md"],
                    },
                )
                logger.warning(
                    "Requirements Agent artifact generation timed out; using partial output from %s. debug_bundle=%s retry_summary=%s stdout_preview=%s stderr_preview=%s",
                    output_root,
                    str(debug_bundle) if debug_bundle is not None else "-",
                    _extract_retry_summary(stderr_text) or "-",
                    _truncate_for_log(stdout_text),
                    _truncate_for_log(stderr_text),
                )
                payload = self._read_requirements_agent_artifact_output(
                    output_root,
                    prompt=prompt,
                    selected_modules=selected_modules,
                    status="partial_timeout",
                )
                if payload is None:
                    logger.error(
                        "Timed out Requirements Agent output is still unusable. project=%s %s missing_required=SRS.md debug_bundle=%s retry_summary=%s stdout_preview=%s stderr_preview=%s",
                        project_name,
                        self._requirements_agent_output_snapshot(output_root),
                        str(debug_bundle) if debug_bundle is not None else "-",
                        _extract_retry_summary(stderr_text) or "-",
                        _truncate_for_log(stdout_text),
                        _truncate_for_log(stderr_text),
                    )
                return payload
            self._persist_agent_debug_bundle(
                agent_name="requirements-agent-artifacts",
                output_root=output_root,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
                context={
                    "mode": "full",
                    "projectName": project_name,
                    "prompt": prompt,
                    "model": self._litellm_model_name(),
                    "error": "timeout",
                },
            )
            logger.exception(
                "Requirements Agent artifact generation timed out without usable output. project=%s %s retry_summary=%s stdout_preview=%s stderr_preview=%s",
                project_name,
                self._requirements_agent_output_snapshot(output_root),
                _extract_retry_summary(stderr_text) or "-",
                _truncate_for_log(stdout_text),
                _truncate_for_log(stderr_text),
            )
            return None
        except subprocess.CalledProcessError as exc:
            stdout_text = self._decode_subprocess_stream(exc.stdout)
            stderr_text = self._decode_subprocess_stream(exc.stderr)
            if output_root is None:
                output_root_value = getattr(exc, "output_root", None)
                if output_root_value:
                    output_root = Path(str(output_root_value))
            if output_root is not None and self._has_requirements_agent_output(output_root):
                debug_bundle = self._persist_agent_debug_bundle(
                    agent_name="requirements-agent-artifacts",
                    output_root=output_root,
                    stdout_text=stdout_text,
                    stderr_text=stderr_text,
                    context={
                        "mode": "full",
                        "projectName": project_name,
                        "prompt": prompt,
                        "model": self._litellm_model_name(),
                        "error": "non_zero_exit",
                        "requiredFiles": ["SRS.md"],
                        "returncode": exc.returncode,
                        "command": exc.cmd if isinstance(exc.cmd, list) else ["requirements-agent", "full"],
                    },
                )
                logger.warning(
                    "Requirements Agent artifact generation exited non-zero; using partial output from %s. debug_bundle=%s retry_summary=%s stdout_preview=%s stderr_preview=%s",
                    output_root,
                    str(debug_bundle) if debug_bundle is not None else "-",
                    _extract_retry_summary(stderr_text) or "-",
                    _truncate_for_log(stdout_text),
                    _truncate_for_log(stderr_text),
                )
                payload = self._read_requirements_agent_artifact_output(
                    output_root,
                    prompt=prompt,
                    selected_modules=selected_modules,
                    status="partial_error",
                )
                if payload is None:
                    logger.error(
                        "Non-zero Requirements Agent output is still unusable. project=%s %s missing_required=SRS.md debug_bundle=%s retry_summary=%s stdout_preview=%s stderr_preview=%s",
                        project_name,
                        self._requirements_agent_output_snapshot(output_root),
                        str(debug_bundle) if debug_bundle is not None else "-",
                        _extract_retry_summary(stderr_text) or "-",
                        _truncate_for_log(stdout_text),
                        _truncate_for_log(stderr_text),
                    )
                return payload
            self._persist_agent_debug_bundle(
                agent_name="requirements-agent-artifacts",
                output_root=output_root,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
                context={
                    "mode": "full",
                    "projectName": project_name,
                    "prompt": prompt,
                    "model": self._litellm_model_name(),
                    "error": "non_zero_exit",
                    "returncode": exc.returncode,
                    "command": exc.cmd if isinstance(exc.cmd, list) else ["requirements-agent", "full"],
                },
            )
            logger.exception(
                "Requirements Agent artifact generation failed without usable output. project=%s %s stdout_preview=%s stderr_preview=%s",
                project_name,
                self._requirements_agent_output_snapshot(output_root),
                _truncate_for_log(stdout_text),
                _truncate_for_log(stderr_text),
            )
            return None
        except Exception:
            self._persist_agent_debug_bundle(
                agent_name="requirements-agent-artifacts",
                output_root=output_root,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
                context={
                    "mode": "full",
                    "projectName": project_name,
                    "prompt": prompt,
                    "model": self._litellm_model_name(),
                    "error": "unexpected_exception",
                },
            )
            logger.exception(
                "Requirements Agent artifact generation failed. project=%s %s stdout_preview=%s stderr_preview=%s",
                project_name,
                self._requirements_agent_output_snapshot(output_root),
                _truncate_for_log(stdout_text),
                _truncate_for_log(stderr_text),
            )
            return None

    def _write_requirements_agent_runtime_tasks_config(self, output_path: Path) -> Path:
        """
        原因注释：
        直接使用 Agent 团队维护的 tasks.yaml 作为运行时配置。
        之前这里合并了 tasks_eng.yaml 和 _requirements_agent_backend_task_overrides()，
        把原始中文 prompt（带详细字段说明、类型约束、示例格式）覆盖成了简短的英文 prompt，
        导致 LLM 输出格式频繁不合规，use_case 等步骤反复重试 5 次仍然失败。
        """
        requirements_config_root = self.agent_root / "Requirements Agent" / "reagent" / "src" / "reagent" / "config"
        source_path = requirements_config_root / "tasks.yaml"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
        return output_path

    # _requirements_agent_backend_task_overrides 已删除。
    # 之前这个方法用硬编码的英文 prompt 覆盖 Agent 团队维护的 tasks.yaml 中文 prompt，
    # 导致 LLM 输出格式频繁不合规（use_case secondary_actor 输出为字符串而非列表、
    # alternative_flows 输出为 dict 而非 list 等），反复重试 5 次仍然失败。
    # 现在直接使用 Agent 原始的 tasks.yaml 配置。

    def _build_requirements_agent_description(self, prompt: str, reference_materials: list[dict[str, Any]]) -> str:
        """聚合项目描述和参考材料作为 Requirements Agent 分析阶段的输入。"""
        sections = [
            "# Project Request",
            prompt.strip() or "No prompt provided.",
            "",
            "## Reference Materials",
            self._reference_list(reference_materials),
            "",
        ]
        return "\n".join(sections).strip() + "\n"

    def _build_requirements_agent_generation_description(
        self,
        *,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        reference_materials: list[dict[str, Any]],
        existing_artifacts: list[dict[str, Any]],
    ) -> str:
        """聚合项目描述、模块、参考材料、已有制品作为 Requirements Agent 生成阶段的输入。"""
        sections = [
            "# Project Request",
            prompt.strip() or "No prompt provided.",
            "",
            "## Selected Modules",
            self._selected_module_list(selected_modules),
            "",
            "## Reference Materials",
            self._reference_list(reference_materials),
            "",
            "## Existing Artifacts",
            self._existing_artifacts_for_requirements_agent(existing_artifacts),
            "",
        ]
        return "\n".join(sections).strip() + "\n"

    def _existing_artifacts_for_requirements_agent(self, existing_artifacts: list[dict[str, Any]]) -> str:
        """将已有制品格式化为 Requirements Agent 可读的 Markdown 段落。"""
        if not existing_artifacts:
            return "- No existing artifacts."
        sections: list[str] = []
        for artifact in existing_artifacts[:6]:
            artifact_type = str(artifact.get("type") or "artifact").strip()
            title = str(artifact.get("title") or artifact_type).strip() or artifact_type
            content = str(artifact.get("content") or "").strip()
            if len(content) > 2000:
                content = content[:2000].rstrip() + "\n...[truncated]"
            if content:
                sections.append(f"### {title} ({artifact_type})\n{content}")
            else:
                sections.append(f"### {title} ({artifact_type})\nNo current content available.")
        return "\n\n".join(sections)

    def _has_requirements_agent_output(self, output_root: Path) -> bool:
        """检查 Requirements Agent 是否产出了必要文件。"""
        candidate_names = (
            "functional_requirements.md",
            "business_scope.md",
            "survey.md",
            "SRS.md",
            "feature_tree.md",
        )
        return any((output_root / name).exists() for name in candidate_names)

    def _requirements_agent_output_snapshot(self, output_root: Path | None) -> str:
        """生成 Requirements Agent 输出目录的摘要日志字符串。"""
        if output_root is None:
            return "output_root=<missing>"
        return self._output_snapshot(output_root)

    def _output_snapshot(self, output_root: Path) -> str:
        """生成输出目录的文件快照字符串，用于日志。"""
        if not output_root.exists():
            return f"output_root={output_root} files=<missing_directory>"

        entries: list[str] = []
        for path in sorted(candidate for candidate in output_root.rglob("*") if candidate.is_file()):
            relative_name = path.relative_to(output_root).as_posix()
            preview = ""
            if path.suffix.lower() in {".md", ".txt", ".json", ".yaml", ".yml", ".html", ".css", ".js"}:
                try:
                    preview = _truncate_for_log(path.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    preview = "<preview_unavailable>"
            if preview:
                entries.append(f"{relative_name}: {preview}")
            else:
                entries.append(relative_name)
        if not entries:
            return f"output_root={output_root} files=<empty>"
        return f"output_root={output_root} files=[{'; '.join(entries[:12])}]"

    def _ui_output_file_paths(self, files: list[dict[str, str]]) -> list[str]:
        """从文件列表中提取有效的 filePath 字段。"""
        return [
            str(item.get("filePath") or "").strip()
            for item in files
            if str(item.get("filePath") or "").strip()
        ]

    def _write_runtime_workspace_files(self, output_root: Path, files: list[dict[str, Any]]) -> None:
        """
        把平台当前工作区快照落到临时目录，交给下游 Agent 当真实输入目录使用。

        教学注释：
        有些 Agent 不是只看文档，还会去检索、写入、运行项目目录。
        所以这里要把数据库里的代码文件快照先还原成一个真实文件树。
        """

        output_root.mkdir(parents=True, exist_ok=True)
        for item in files:
            file_path = str(item.get("filePath") or "").strip()
            if not file_path:
                continue
            destination = output_root / file_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(str(item.get("content") or ""), encoding="utf-8")

    def _read_runtime_text_files(self, output_root: Path, *, prefix: str = "") -> list[dict[str, str]]:
        """读取目录下所有文本文件并返回路径-内容字典列表。"""
        files: list[dict[str, str]] = []
        if not output_root.exists():
            return files
        for path in sorted(candidate for candidate in output_root.rglob("*") if candidate.is_file()):
            relative_name = path.relative_to(output_root).as_posix()
            file_path = f"{prefix}/{relative_name}" if prefix else relative_name
            files.append(
                {
                    "filePath": file_path,
                    "content": path.read_text(encoding="utf-8"),
                }
            )
        return files

    # 接口注释：
    # 当 Test Agent 因超时没有正常返回时，这里尝试从临时运行目录里直接捞回已经生成好的文件。
    # 只要成功判定所需的 3 个文件已经齐了，平台就可以安全收尾，不必把这轮结果白白判成失败。
    def _salvage_test_agent_files_from_runtime_home(
        self,
        *,
        runtime_home: Path,
        dataset_name: str,
        grace_seconds: float = 2.0,
    ) -> list[dict[str, str]] | None:
        """从超时的 Test Agent 运行目录中尝试捞回已生成的文件。"""
        deadline = time.monotonic() + max(0.0, grace_seconds)
        while True:
            output_files = self._read_runtime_text_files(runtime_home / "output")
            memory_files = self._read_runtime_text_files(runtime_home / "memory", prefix="memory")
            files = [*output_files, *memory_files]
            try:
                return self._validate_test_output_files(files, dataset_name=dataset_name)
            except RuntimeError:
                if time.monotonic() >= deadline:
                    return None
                time.sleep(0.2)

    def _validate_ui_output_files(self, files: list[dict[str, str]]) -> list[dict[str, str]]:
        """校验 UI Agent 输出的必要文件是否齐全。"""
        file_paths = self._ui_output_file_paths(files)
        if not file_paths:
            raise RuntimeError("UI Agent did not return any generated UI files.")

        # 教学注释：
        # 这里不是要求 UI Agent 一次性产出“所有”辅助文件，
        # 但最少要把页面描述、DAR、页面主体、样式、脚本这些核心骨架凑齐。
        missing_core_files = [path for path in _UI_AGENT_REQUIRED_CORE_FILES if path not in file_paths]
        if missing_core_files:
            generated_preview = ", ".join(sorted(file_paths))
            missing_preview = ", ".join(missing_core_files)
            raise RuntimeError(
                "UI output is incomplete. "
                f"Missing core files: {missing_preview}. "
                f"Generated files: {generated_preview}."
            )
        return files

    def _validate_test_output_files(
        self,
        files: list[dict[str, str]],
        *,
        dataset_name: str,
    ) -> list[dict[str, str]]:
        """校验 Test Agent 输出的必要文件是否齐全。"""
        file_paths = self._ui_output_file_paths(files)
        if not file_paths:
            raise RuntimeError("Test Agent did not return any generated test files.")

        required_files = [
            template.format(dataset_name=dataset_name)
            for template in _TEST_AGENT_REQUIRED_FILES
        ]
        missing_required = [path for path in required_files if path not in file_paths]
        if missing_required:
            raise RuntimeError(
                "Test Agent output is incomplete. "
                f"Missing required files: {', '.join(missing_required)}. "
                f"Generated files: {', '.join(sorted(file_paths))}."
            )
        return files

    def _read_requirements_agent_output(
        self,
        output_root: Path,
        *,
        prompt: str,
        status: str = "completed",
        stdout_modules: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """从 Requirements Agent 输出目录读取分析结果。"""
        summary_sources = [
            output_root / "functional_requirements.md",
            output_root / "business_scope.md",
            output_root / "survey.md",
            output_root / "SRS.md",
        ]
        summary = ""
        for path in summary_sources:
            if path.exists():
                text = self._compact_text(path.read_text(encoding="utf-8"))
                if text:
                    summary = text[:800]
                    break

        feature_tree_path = output_root / "feature_tree.md"
        if feature_tree_path.exists():
            modules = self._parse_feature_tree_modules(feature_tree_path.read_text(encoding="utf-8"))
        else:
            modules = list(stdout_modules or [])
        if not modules:
            return None
        if not summary:
            summary = prompt.strip() or "Requirement analysis is complete. Please confirm the suggested feature modules."

        return {
            "summary": summary,
            "modules": modules,
            "_meta": {
                "source": "requirements_agent",
                "outputDir": str(output_root),
                "status": status,
            },
        }

    def _read_requirements_agent_artifact_output(
        self,
        output_root: Path,
        *,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        status: str = "completed",
        seeded_files: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """从 Requirements Agent 输出目录读取生成阶段的完整制品。"""
        return self._requirements_agent_artifact_payload_from_files(
            {
                "SRS.md": self._read_optional_text(output_root / "SRS.md"),
                "business_scope.md": self._read_optional_text(output_root / "business_scope.md"),
                "feature_tree.md": self._read_optional_text(output_root / "feature_tree.md"),
                "functional_requirements.md": self._read_optional_text(output_root / "functional_requirements.md"),
                "non_functional_requirements.md": self._read_optional_text(output_root / "non_functional_requirements.md"),
                "use_case.md": self._read_optional_text(output_root / "use_case.md"),
            },
            prompt=prompt,
            selected_modules=selected_modules,
            output_dir=str(output_root),
            status=status,
            seeded_files=seeded_files,
        )

    def _requirements_agent_artifact_payload_from_files(
        self,
        file_contents: dict[str, str],
        *,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        output_dir: str,
        status: str = "completed",
        seeded_files: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """
        接口注释：
        根据 Requirements Agent 关键源文件内容，组装平台要用的 PRD / UI / API 载荷。

        设计注释：
        这层故意做成“只吃文件内容，不关心来源”。
        这样同一套拼装逻辑既能服务本地目录读取，也能服务数据库恢复。
        """

        srs_document = str(file_contents.get("SRS.md") or "").strip()
        business_scope = str(file_contents.get("business_scope.md") or "").strip()
        feature_tree = str(file_contents.get("feature_tree.md") or "").strip()
        functional_requirements = str(file_contents.get("functional_requirements.md") or "").strip()
        non_functional_requirements = str(file_contents.get("non_functional_requirements.md") or "").strip()
        use_case_text = str(file_contents.get("use_case.md") or "").strip()

        if not srs_document:
            return None

        module_labels = self._requirements_agent_module_labels(feature_tree, selected_modules)
        use_cases = self._parse_requirements_agent_use_cases(use_case_text)
        return {
            "prd": srs_document,
            "prdSummary": self._requirements_agent_prd_from_outputs(
                prompt=prompt,
                selected_modules=selected_modules,
                business_scope=business_scope,
                feature_tree=feature_tree,
                functional_requirements=functional_requirements,
                non_functional_requirements=non_functional_requirements,
                use_cases=use_cases,
            ),
            "ui": self._requirements_agent_ui_from_outputs(
                module_labels=module_labels,
                use_cases=use_cases,
            ),
            "api_spec": self._requirements_agent_api_spec_from_outputs(
                module_labels=module_labels,
                use_cases=use_cases,
            ),
            "_meta": {
                "source": "requirements_agent",
                "outputDir": output_dir,
                "status": status,
                "seededFiles": list(seeded_files or []),
                "requiredFiles": ["SRS.md"],
                "sourceFilesByArtifact": {
                    "prd": [
                        path
                        for path, text in (
                            ("SRS.md", srs_document),
                            ("business_scope.md", business_scope),
                            ("feature_tree.md", feature_tree),
                            ("functional_requirements.md", functional_requirements),
                            ("non_functional_requirements.md", non_functional_requirements),
                            ("use_case.md", use_case_text),
                        )
                        if text
                    ],
                    "ui": [
                        path
                        for path, text in (
                            ("feature_tree.md", feature_tree),
                            ("use_case.md", use_case_text),
                        )
                        if text
                    ],
                    "api_spec": [
                        path
                        for path, text in (
                            ("feature_tree.md", feature_tree),
                            ("use_case.md", use_case_text),
                        )
                        if text
                    ],
                },
            },
        }

    def _read_optional_text(self, path: Path) -> str:
        """读取文本文件内容，文件不存在则返回空字符串。"""
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def _requirements_agent_module_labels(
        self,
        feature_tree: str,
        selected_modules: list[dict[str, Any]],
    ) -> list[str]:
        """从 feature_tree 或 selected_modules 提取模块英文标签列表。"""
        labels = [module["labelEn"] for module in self._parse_feature_tree_modules(feature_tree)] if feature_tree else []
        if labels:
            return labels[:6]
        return [
            str(module.get("labelEn") or module.get("label") or module.get("id") or "Core Module")
            for module in selected_modules
            if str(module.get("labelEn") or module.get("label") or module.get("id") or "").strip()
        ][:6]

    def _parse_requirements_agent_use_cases(self, use_case_text: str) -> list[dict[str, Any]]:
        """从 use_case.md 内容中解析用例列表。"""
        if not use_case_text.strip():
            return []
        payload_text = use_case_text.strip()
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            match = re.search(r"(\[\s*{.*}\s*\])", payload_text, re.DOTALL)
            if not match:
                return []
            try:
                payload = json.loads(match.group(1))
            except json.JSONDecodeError:
                return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _strip_markdown_title(self, value: str) -> str:
        """去掉 Markdown 文本开头的标题行。"""
        lines = value.strip().splitlines()
        while lines and lines[0].strip().startswith("#"):
            lines.pop(0)
            while lines and not lines[0].strip():
                lines.pop(0)
        return "\n".join(lines).strip()

    def _requirements_agent_prd_from_outputs(
        self,
        *,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        business_scope: str,
        feature_tree: str,
        functional_requirements: str,
        non_functional_requirements: str,
        use_cases: list[dict[str, Any]],
    ) -> str:
        """将 Requirements Agent 多份输出文件合成 PRD 摘要 Markdown。"""
        overview = self._strip_markdown_title(business_scope) or prompt.strip() or "Project requirement summary."
        functional_sections: list[str] = []
        cleaned_feature_tree = self._strip_markdown_title(feature_tree)
        if cleaned_feature_tree:
            functional_sections.extend(["### Feature Tree", cleaned_feature_tree])
        cleaned_functional_requirements = self._strip_markdown_title(functional_requirements)
        if cleaned_functional_requirements:
            functional_sections.extend(["", "### Functional Requirements", cleaned_functional_requirements])
        use_case_outline = self._requirements_agent_use_case_outline(use_cases)
        if use_case_outline:
            functional_sections.extend(["", "### Use Cases", use_case_outline])
        if not functional_sections:
            functional_sections.append(self._selected_module_list(selected_modules))

        non_functional = self._strip_markdown_title(non_functional_requirements)
        if not non_functional:
            non_functional = (
                "- Responsive web experience for desktop-first workflows.\n"
                "- Clear API boundaries between frontend and Python backend services.\n"
                "- Version-aware artifact review and traceability.\n"
            )

        sections = [
            "# Product Requirements Document",
            "",
            "## Overview",
            overview,
            "",
            "## Functional Scope",
            *functional_sections,
            "",
            "## Non-Functional Requirements",
            non_functional,
        ]
        return "\n".join(section for section in sections if section is not None).strip()

    def _requirements_agent_use_case_outline(self, use_cases: list[dict[str, Any]]) -> str:
        """将用例列表格式化为简短 Markdown 概要。"""
        lines: list[str] = []
        for use_case in use_cases[:8]:
            name = str(use_case.get("use_case_name") or "Use Case").strip()
            actor = str(use_case.get("primary_actor") or "").strip()
            description = str(use_case.get("use_case_description") or "").strip()
            suffix = f" ({actor})" if actor else ""
            summary = f": {description}" if description else ""
            lines.append(f"- **{name}**{suffix}{summary}")
        return "\n".join(lines)

    def _slugify_path_segment(self, value: str) -> str:
        """将字符串转为 URL 友好的 slug 格式。"""
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "module"

    def _requirements_agent_ui_from_outputs(
        self,
        *,
        module_labels: list[str],
        use_cases: list[dict[str, Any]],
    ) -> str:
        """从模块标签和用例生成 UI 页面描述 Markdown。"""
        if not module_labels and not use_cases:
            module_labels = ["Core Workspace"]

        lines = ["# UI Pages", "", "## Page Inventory"]
        for label in module_labels[:6]:
            route = f"/{self._slugify_path_segment(label)}"
            lines.append(f"- {label} Workspace (`{route}`)")
        if not module_labels:
            lines.append("- Core Workspace (`/`)")

        interaction_lines = []
        for use_case in use_cases[:6]:
            name = str(use_case.get("use_case_name") or "Use Case").strip()
            description = str(use_case.get("use_case_description") or "").strip()
            interaction_lines.append(f"- {name}: {description or 'Primary workflow interaction.'}")
        if interaction_lines:
            lines.extend(["", "## Primary Interactions", *interaction_lines])

        return "\n".join(lines).strip()

    def _requirements_agent_api_spec_from_outputs(
        self,
        *,
        module_labels: list[str],
        use_cases: list[dict[str, Any]],
    ) -> str:
        """从模块标签和用例生成 OpenAPI Spec 草稿。"""
        labels = module_labels[:4]
        if not labels:
            for use_case in use_cases[:4]:
                name = str(use_case.get("use_case_name") or "").strip()
                if name:
                    labels.append(name)
        if not labels:
            labels = ["core-module"]

        lines = [
            "openapi: 3.0.0",
            "info:",
            "  title: Requirements Agent API",
            "  version: 0.1.0",
            "paths:",
        ]
        for label in labels:
            slug = self._slugify_path_segment(label)
            title = label.strip() or "Module"
            lines.extend(
                [
                    f"  /api/{slug}:",
                    "    get:",
                    f"      summary: List {title} records",
                    "      responses:",
                    "        '200':",
                    "          description: Successful response",
                    "    post:",
                    f"      summary: Create a {title} record",
                    "      responses:",
                    "        '200':",
                    "          description: Successful response",
                ]
            )
        return "\n".join(lines).strip() + "\n"

    def _parse_feature_tree_modules(self, feature_tree_text: str) -> list[dict[str, Any]]:
        """从 feature_tree Markdown 文本中解析出模块列表。"""
        list_prefix_pattern = re.compile(r"^(?:[-*+]\s+|\d+(?:\.\d+)*\.?\s+)")
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")
        level_outline_pattern = re.compile(r"^L(?P<level>\d+)\s*[:.]\s*(?P<label>.+)$", re.IGNORECASE)
        numbered_outline_pattern = re.compile(r"^(?P<number>\d+(?:\.\d+)*\.?)(?:\s+)(?P<label>.+)$")

        def normalize_markdown_text(value: str) -> str:
            normalized = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
            normalized = re.sub(r"__(.*?)__", r"\1", normalized)
            return normalized.strip()

        def strip_tree_prefixes(value: str) -> str:
            label = value.strip()
            while True:
                next_label = list_prefix_pattern.sub("", label, count=1).strip()
                if next_label == label:
                    return label
                label = next_label

        def inferred_number_indent(value: str) -> int | None:
            candidate = list_prefix_pattern.sub("", value, count=1).strip()
            match = numbered_outline_pattern.match(candidate)
            if not match:
                return None
            number = match.group("number").rstrip(".")
            if not number:
                return None
            segment_count = len([part for part in number.split(".") if part])
            return max(segment_count - 1, 0) * 2

        heading_entries = [
            (len(match.group(1)), normalize_markdown_text(match.group(2)))
            for raw_line in feature_tree_text.splitlines()
            if (match := heading_pattern.match(raw_line.strip()))
            and not normalize_markdown_text(match.group(2)).lower().startswith("feature tree")
        ]
        heading_levels = [level for level, _label in heading_entries]
        base_heading_level = min(heading_levels) if heading_levels else None
        if (
            base_heading_level is not None
            and any(level > base_heading_level for level in heading_levels)
            and sum(1 for level in heading_levels if level == base_heading_level) == 1
        ):
            deeper_heading_levels = [level for level in heading_levels if level > base_heading_level]
            if deeper_heading_levels:
                base_heading_level = min(deeper_heading_levels)
        level_entries = [
            (int(match.group("level")), match.group("label").strip())
            for raw_line in feature_tree_text.splitlines()
            if (match := level_outline_pattern.match(raw_line.strip()))
            and match.group("label").strip()
        ]
        level_values = [level for level, _label in level_entries]
        base_outline_level: int | None = None
        if level_values:
            base_outline_level = min(level_values)
            if (
                base_outline_level == 1
                and any(level > 1 for level in level_values)
                and sum(1 for level in level_values if level == 1) == 1
            ):
                base_outline_level = 2

        normalized_lines: list[str] = []
        active_heading_indent_level: int | None = None
        for raw_line in feature_tree_text.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            normalized_stripped = normalize_markdown_text(stripped)
            if normalized_stripped.lower().startswith("feature tree"):
                continue
            level_match = level_outline_pattern.match(normalized_stripped)
            if level_match:
                level = int(level_match.group("level"))
                label = level_match.group("label").strip()
                if not label:
                    continue
                if base_outline_level is not None and level < base_outline_level:
                    continue
                indent_level = 0
                if base_outline_level is not None:
                    indent_level = max(level - base_outline_level, 0)
                normalized_lines.append(f"{'  ' * indent_level}- {label}")
                continue
            heading_match = heading_pattern.match(normalized_stripped)
            if heading_match:
                heading_text = heading_match.group(2).strip()
                label = strip_tree_prefixes(heading_text)
                label = re.sub(r"\s+", " ", label)
                if not label:
                    continue
                indent_level = max(len(heading_match.group(1)) - (base_heading_level or len(heading_match.group(1))), 0)
                if base_heading_level is not None and len(heading_match.group(1)) < base_heading_level:
                    active_heading_indent_level = None
                    continue
                normalized_lines.append(f"{'  ' * indent_level}- {label}")
                active_heading_indent_level = indent_level
                continue
            if not list_prefix_pattern.match(normalized_stripped):
                continue
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            inferred_indent = inferred_number_indent(normalized_stripped)
            if active_heading_indent_level is not None and indent == 0:
                indent = (active_heading_indent_level + 1) * 2
            elif inferred_indent is not None:
                indent = max(indent, inferred_indent)
            label = strip_tree_prefixes(normalized_stripped)
            normalized_lines.append(f"{' ' * indent}- {label}")

        modules: list[dict[str, Any]] = []
        current_children: list[str] = []
        current_module: dict[str, Any] | None = None

        def flush_current() -> None:
            nonlocal current_module, current_children
            if current_module is None:
                return
            if current_children and not current_module.get("description"):
                current_module["description"] = "; ".join(current_children[:3])
            modules.append(current_module)
            current_module = None
            current_children = []

        for raw_line in normalized_lines:
            if not raw_line.strip():
                continue
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            stripped = raw_line.strip()
            if not list_prefix_pattern.match(stripped):
                continue
            label = list_prefix_pattern.sub("", stripped, count=1).strip()
            label = re.sub(r"\s+", " ", label)
            if not label:
                continue
            if indent == 0:
                flush_current()
                current_module = {
                    "id": self._module_id_from_label(label, default_index=len(modules) + 1),
                    "label": label,
                    "labelEn": label,
                    "description": "",
                    "checked": True,
                }
            elif current_module is not None and len(current_children) < 3:
                current_children.append(label)
        flush_current()
        return modules[:6]

    def _decode_subprocess_stream(self, value: str | bytes | None) -> str:
        """将子进程输出的 bytes/str 安全解码为字符串。"""
        if isinstance(value, bytes):
            return value.decode("utf-8", "ignore")
        return value or ""

    def _persist_ui_agent_debug_bundle(
        self,
        *,
        project_name: str,
        runtime_home: Path,
        output_root: Path,
        stdout_text: str = "",
        stderr_text: str = "",
        reason: str,
        stage: str,
        timeout: float | None = None,
        partial_files: list[str] | None = None,
    ) -> Path | None:
        """保存 UI Agent 失败时的调试包。"""
        context: dict[str, Any] = {
            "projectName": project_name,
            "model": self._litellm_model_name(),
            "reason": reason,
            "stage": stage,
            "partialFiles": list(partial_files or []),
        }
        if timeout is not None:
            context["timeout"] = timeout

        bundle_root = self._persist_agent_debug_bundle(
            agent_name="ui-agent",
            output_root=output_root,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            context=context,
        )
        if bundle_root is None:
            return None

        inputs_root = bundle_root / "inputs"
        inputs_root.mkdir(parents=True, exist_ok=True)
        for file_name in ("use_case.md", "dialog_map.md", "api_methods.json"):
            source = runtime_home / file_name
            if source.exists():
                shutil.copy2(source, inputs_root / file_name)
        return bundle_root

    def _persist_agent_debug_bundle(
        self,
        *,
        agent_name: str,
        output_root: Path | None,
        stdout_text: str = "",
        stderr_text: str = "",
        context: dict[str, Any] | None = None,
        extra_paths: dict[str, Path | None] | None = None,
    ) -> Path | None:
        """保存 Agent 失败时的调试包（输出文件、日志、上下文）。"""
        try:
            debug_root = self.platform_root / "data" / "agent-debug" / agent_name
            debug_root.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
            bundle_root = debug_root / f"failure-{timestamp}"
            collision_index = 2
            while bundle_root.exists():
                bundle_root = debug_root / f"failure-{timestamp}-{collision_index:02d}"
                collision_index += 1
            bundle_root.mkdir(parents=True, exist_ok=False)
            if context:
                (bundle_root / "context.json").write_text(
                    json.dumps(context, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if stdout_text.strip():
                (bundle_root / "stdout.log").write_text(stdout_text, encoding="utf-8")
            if stderr_text.strip():
                (bundle_root / "stderr.log").write_text(stderr_text, encoding="utf-8")
            if output_root is not None and output_root.exists():
                copied_output_root = bundle_root / "outputs"
                copied_output_root.mkdir(parents=True, exist_ok=True)
                for child in output_root.iterdir():
                    destination = copied_output_root / child.name
                    if child.is_dir():
                        shutil.copytree(child, destination, dirs_exist_ok=True)
                    elif child.is_file():
                        shutil.copy2(child, destination)
            for label, source_root in (extra_paths or {}).items():
                if not label or source_root is None or not source_root.exists():
                    continue
                destination_root = bundle_root / label
                if source_root.is_dir():
                    shutil.copytree(source_root, destination_root, dirs_exist_ok=True)
                elif source_root.is_file():
                    destination_root.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_root, destination_root)
            return bundle_root
        except Exception:
            logger.warning("Failed to persist debug bundle for %s.", agent_name, exc_info=True)
            return None

    def _extract_requirements_agent_stdout_modules(self, stdout_text: str) -> list[dict[str, Any]]:
        """从 Requirements Agent 的 stdout 中提取模块列表（降级补救路径）。"""
        if not stdout_text.strip():
            return []
        bullet_lines: list[tuple[int, str]] = []
        in_final_answer = False
        for raw_line in stdout_text.splitlines():
            line = raw_line.strip("\n")
            if "Agent Final Answer" in line:
                in_final_answer = True
                continue
            if "Tracing Status" in line and in_final_answer:
                break
            if not in_final_answer:
                continue
            line = re.sub(r"^[│|]\s?", "", line)
            line = re.sub(r"\s*[│|]\s*$", "", line)
            if not line.strip():
                continue
            if "•" in line:
                prefix, marker, suffix = line.partition("•")
                cleaned = suffix.strip()
                cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
                bullet_lines.append((len(prefix), cleaned))
        if not bullet_lines:
            return []
        base_indent = min(indent for indent, _ in bullet_lines)
        normalized_lines = [f"{' ' * max(indent - base_indent, 0)}- {cleaned}" for indent, cleaned in bullet_lines]
        return self._parse_feature_tree_modules("\n".join(normalized_lines))

    def _module_id_from_label(self, label: str, *, default_index: int) -> str:
        """将模块标签转为小写连字符格式的 ID。"""
        normalized = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
        return normalized or f"module-{default_index}"

    def _requirements_agent_feature_tree_seed(self, selected_modules: list[dict[str, Any]]) -> str:
        """从 selected_modules 生成 feature_tree 种子 Markdown。"""
        lines = ["# Feature Tree", ""]
        normalized_modules = [
            {
                "label": str(module.get("labelEn") or module.get("label") or module.get("id") or "").strip(),
                "description": str(module.get("description") or "").strip(),
            }
            for module in selected_modules
            if str(module.get("labelEn") or module.get("label") or module.get("id") or "").strip()
        ]
        if not normalized_modules:
            normalized_modules = [
                {
                    "label": "Core Module",
                    "description": "Primary project workflow and user-facing capability.",
                }
            ]
        for index, module in enumerate(normalized_modules, start=1):
            lines.append(f"{index}. {module['label']}")
            description = module["description"]
            if not description:
                continue
            detail_parts = [
                part.strip(" -")
                for part in re.split(r"[;,\n]+", description)
                if part.strip(" -")
            ]
            if not detail_parts:
                continue
            for child_index, detail in enumerate(detail_parts[:3], start=1):
                lines.append(f"   {index}.{child_index} {detail}")
        return "\n".join(lines).strip() + "\n"

    def _compact_text(self, text: str) -> str:
        """将多行文本压缩为单行。"""
        return " ".join(text.split()).strip()

    def _read_usage_payload_file(self, usage_path: Path, *, default_model: str) -> dict[str, Any] | None:
        """
        从子进程写出的 usage 文件里读取并标准化 Usage。

        这样即使某个 Agent 还没有完全接成后端直接函数调用，
        我们也能先把真实 token 用量接回项目统计，不影响总账。
        """

        if not usage_path.exists():
            return None
        try:
            payload = json.loads(usage_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to read usage payload file: %s", usage_path, exc_info=True)
            return None
        return self._normalize_usage_metadata(payload, default_model=default_model)

    async def _build_with_architecture_agent(
        self,
        *,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        reference_materials: list[dict[str, Any]],
        existing_artifacts: list[dict[str, Any]],
        locale: str = "en",
        task_id: str | None = None,
        status_callback: StatusCallback | None = None,
        usage_event_callback: Any = None,
        runtime_event_callback: Any = None,
    ) -> dict[str, Any] | None:
        """Architecture Agent 的执行入口。"""
        # 原因注释：
        # 这三个守卫以前都是裸 return None，上层只会得到一句
        # "Architecture Agent did not return the architecture draft."，
        # 既没有调试包也没有日志，一个配置笔误就能变成完全无法排查的失败。
        # 所以每条跳过路径都必须自己说明是被哪个条件拦下的。
        if not self._architecture_agent_enabled():
            logger.warning(
                "Architecture Agent skipped because the agent is disabled. ISOFTDEVAGENTS_ENABLE_ARCH_AGENT=%s",
                os.getenv("ISOFTDEVAGENTS_ENABLE_ARCH_AGENT"),
            )
            return None
        architecture_root = self.agent_root / "Architecture Agent"
        architecture_entrypoint = architecture_root / "src" / "arch_agent" / "main.py"
        if not architecture_entrypoint.exists():
            logger.warning(
                "Architecture Agent skipped because its entrypoint is missing. path=%s",
                architecture_entrypoint,
            )
            return None
        if not self._architecture_agent_runtime_available():
            logger.warning(
                "Architecture Agent skipped because the runtime is unavailable. python_bin=%s",
                self._architecture_agent_python_bin(),
            )
            return None

        requirement_document = self._build_architecture_requirements_input(
            prompt=prompt,
            selected_modules=selected_modules,
            reference_materials=reference_materials,
            existing_artifacts=existing_artifacts,
        )
        project_name = self._project_name_from_prompt(prompt)
        runtime_home = architecture_root / ".runtime-home"
        runtime_home.mkdir(parents=True, exist_ok=True)
        litellm_model = self._litellm_model_name()
        architecture_python_bin = self._architecture_agent_python_bin()
        python_path_entries = [str(architecture_root / "src")]
        if self._architecture_agent_python_uses_parent_sitepackages():
            python_path_entries.append(site.getusersitepackages())

        loop = asyncio.get_running_loop()

        # 设计注释：
        # 架构 Agent 之前自己手写 stdout/stderr 转发，导致 registry 里看不到
        # stdout_preview / stderr_preview。统一走同一个发射器后，handoff 超时现场
        # 才能直接回答“它最后在输出什么”。
        emit_stdout_line = self._sync_status_emitter(
            loop=loop,
            agent_name="Architecture Agent",
            status_callback=status_callback,
            locale=locale,
            task_id=task_id,
        )
        emit_stderr_line = self._sync_status_emitter(
            loop=loop,
            agent_name="Architecture Agent stderr",
            status_callback=status_callback,
            locale=locale,
            task_id=task_id,
            stream_kind="stderr",
        )

        async def emit_architecture_usage_payload(payload: dict[str, Any]) -> None:
            if usage_event_callback is None:
                return
            await usage_event_callback(
                self._normalize_usage_metadata(
                    payload,
                    default_model=self._runtime_model_name("crewai"),
                )
            )

        def forward_architecture_usage_payload(payload: dict[str, Any]) -> None:
            if usage_event_callback is None or loop.is_closed():
                return
            asyncio.run_coroutine_threadsafe(
                emit_architecture_usage_payload(payload),
                loop,
            )

        forward_architecture_runtime_event = self._sync_runtime_event_emitter(
            loop=loop,
            runtime_event_callback=runtime_event_callback,
            agent_name="Architecture Agent",
            task_id=task_id,
        )

        cancel_event = threading.Event()
        completion_event = threading.Event()
        self._register_running_agent_runtime(
            task_id=task_id,
            agent_name="architecture_agent",
            cancel_event=cancel_event,
            completion_event=completion_event,
            runtime_home=runtime_home,
            output_root=self._architecture_agent_output_root(),
        )

        def run_architecture_agent() -> dict[str, Any]:
            completion_state = "stopped"
            try:
                return agent_bridge.run_architecture_agent(
                    architecture_root=architecture_root,
                    requirement_document=requirement_document,
                    project_name=project_name,
                    runtime_home=runtime_home,
                    python_bin=architecture_python_bin,
                    python_path_entries=python_path_entries,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    model=self._runtime_model_name("openai_sdk"),
                    timeout=self.architecture_agent_timeout,
                    stdout_line_handler=emit_stdout_line,
                    stderr_line_handler=emit_stderr_line,
                    usage_callback=forward_architecture_usage_payload,
                    runtime_event_callback=forward_architecture_runtime_event,
                    cancel_event=cancel_event,
                )
            except asyncio.CancelledError:
                completion_state = "cancelled"
                raise
            except Exception:
                completion_state = "failed"
                raise
            finally:
                self._mark_running_agent_completion(
                    task_id=task_id,
                    completion_event=completion_event,
                    runtime_state=completion_state,
                )

        try:
            runtime_result = await _run_in_agent_executor(run_architecture_agent)
        except subprocess.TimeoutExpired as exc:
            cancel_event.set()
            stdout_text = self._decode_subprocess_stream(exc.output)
            stderr_text = self._decode_subprocess_stream(exc.stderr)
            debug_bundle = self._persist_agent_debug_bundle(
                agent_name="architecture-agent",
                output_root=self._architecture_agent_output_root(),
                stdout_text=stdout_text,
                stderr_text=stderr_text,
                context={
                    "projectName": project_name,
                    "model": litellm_model,
                    "reason": "timeout",
                    "stage": "architecture_generation",
                    "timeout": self.architecture_agent_timeout,
                    "command": exc.cmd if isinstance(exc.cmd, list) else None,
                },
                extra_paths={
                    "runtime-home": runtime_home,
                },
            )
            logger.exception(
                "Architecture Agent timed out after %.1fs. project=%s stdout_preview=%s stderr_preview=%s debug_bundle=%s",
                self.architecture_agent_timeout,
                project_name,
                _truncate_for_log(stdout_text),
                _truncate_for_log(stderr_text),
                str(debug_bundle) if debug_bundle is not None else "-",
            )
            raise RuntimeError(
                f"Architecture Agent timed out after {int(self.architecture_agent_timeout)}s."
            ) from exc
        except asyncio.CancelledError as exc:
            cancel_event.set()
            debug_bundle = self._persist_agent_debug_bundle(
                agent_name="architecture-agent",
                output_root=self._architecture_agent_output_root(),
                context={
                    "projectName": project_name,
                    "model": litellm_model,
                    "reason": "cancelled",
                    "stage": "architecture_generation",
                },
                extra_paths={
                    "runtime-home": runtime_home,
                },
            )
            logger.error(
                "Architecture Agent cancelled during runtime. project=%s debug_bundle=%s",
                project_name,
                str(debug_bundle) if debug_bundle is not None else "-",
            )
            raise
        except Exception as exc:
            cancel_event.set()
            debug_bundle = self._persist_agent_debug_bundle(
                agent_name="architecture-agent",
                output_root=self._architecture_agent_output_root(),
                context={
                    "projectName": project_name,
                    "model": litellm_model,
                    "reason": "runtime_exception",
                    "stage": "architecture_generation",
                    "error": str(exc),
                },
                extra_paths={
                    "runtime-home": runtime_home,
                },
            )
            logger.exception(
                "Architecture Agent execution failed. project=%s debug_bundle=%s",
                project_name,
                str(debug_bundle) if debug_bundle is not None else "-",
            )
            return None
        finally:
            self._unregister_running_agent_runtime(task_id)

        output_dir_value = str(runtime_result.get("output_dir") or "").strip()
        if not output_dir_value:
            return None
        output_dir = Path(output_dir_value)
        payload = self._read_architecture_agent_output(output_dir)
        if payload is None:
            return None
        payload["usage"] = runtime_result.get("usage") or self._read_usage_payload_file(
            Path(str(runtime_result.get("usage_output_path") or "")),
            default_model=litellm_model,
        )
        return payload

    def _build_architecture_requirements_input(
        self,
        *,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        reference_materials: list[dict[str, Any]],
        existing_artifacts: list[dict[str, Any]],
    ) -> str:
        """聚合项目描述、模块、参考材料作为 Architecture Agent 的输入。"""
        sections = [
            "# Project Request",
            prompt.strip() or "No prompt provided.",
            "",
            "## Selected Modules",
            self._selected_module_list(selected_modules),
            "",
            "## Reference Materials",
            self._reference_list(reference_materials),
            "",
            "## Existing Artifacts",
            self._existing_artifacts_for_generation_prompt(existing_artifacts),
            "",
        ]
        return "\n".join(sections).strip() + "\n"

    def _project_name_from_prompt(self, prompt: str) -> str:
        """从用户 prompt 提取简短项目名。"""
        slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")
        if not slug:
            return "generated-project"
        parts = [part for part in slug.split("-") if part][:6]
        return "-".join(parts) or "generated-project"

    def _build_ui_agent_api_methods_payload(
        self,
        *,
        artifacts: dict[str, Any],
        selected_modules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        把 OpenAPI 草稿整理成 UI Agent 当前脚本真正使用的 api_methods.json 结构。

        UI Agent 现在不会直接读 OpenAPI YAML，
        所以后端桥梁要在这里做一次“结构翻译”，把接口列表转成它现有脚本能消费的格式。
        """

        module_ids = [
            re.sub(r"[^a-z0-9]+", "-", str(module.get("id") or module.get("labelEn") or module.get("label") or "").lower()).strip("-")
            for module in selected_modules
        ]
        payload: dict[str, Any] = {}
        try:
            api_spec_payload = yaml.safe_load(str(artifacts.get("api_spec") or "")) if str(artifacts.get("api_spec") or "").strip() else {}
        except Exception:
            api_spec_payload = {}
        paths = api_spec_payload.get("paths") if isinstance(api_spec_payload, dict) else None
        if isinstance(paths, dict):
            for route, methods in paths.items():
                if not isinstance(route, str) or not isinstance(methods, dict):
                    continue
                module_id = self._match_module_for_route(route, module_ids) or "ui-backend"
                service_name = module_id.replace("-", "_")
                service_entry = payload.setdefault(service_name, {"methods": {}})
                methods_entry = service_entry.setdefault("methods", {})
                for verb, operation in methods.items():
                    if not isinstance(operation, dict):
                        continue
                    raw_method_name = str(operation.get("operationId") or f"{verb}_{route}")
                    method_name = re.sub(r"[^a-z0-9_]+", "_", raw_method_name.lower()).strip("_") or "call_api"
                    methods_entry[method_name] = {
                        "summary": str(operation.get("summary") or operation.get("description") or "API operation"),
                        "http": {
                            "verb": str(verb).upper(),
                            "route": route,
                        },
                    }
        for module in selected_modules:
            module_id = re.sub(r"[^a-z0-9]+", "-", str(module.get("id") or module.get("labelEn") or module.get("label") or "").lower()).strip("-")
            if not module_id:
                continue
            payload.setdefault(module_id.replace("-", "_"), {"methods": {}})
        if payload:
            return payload
        return {"ui_backend": {"methods": {}}}

    def _build_coding_agent_project_manifest(
        self,
        *,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        artifacts: dict[str, Any],
    ) -> dict[str, Any]:
        """构造 Coding Agent 的项目文件结构清单（纯结构元数据，不含提示词）。"""
        # 这里不是在“后端自己生成代码”，而是在定义要交给真实 Code Agent 的文件合同。
        # Code Agent 会按这个 manifest 的文件树和优先级，逐个生成真实代码文件。
        module_specs = self._coding_agent_module_specs(
            prompt=prompt,
            selected_modules=selected_modules,
            api_spec=str(artifacts.get("api_spec") or ""),
        )
        backend_manifest: dict[str, Any] = {
            "run.py": {
                "priority": 12,
                "description": "Application entry point.",
                "source_ref": ["project.summary", "artifacts.architecture"],
                "depends_on": ["app/__init__.py"],
            },
            "app": {
                "__init__.py": {
                    "priority": 11,
                    "description": "Application initialization.",
                    "source_ref": ["project.summary", "artifacts.architecture"],
                    "depends_on": ["app/api/__init__.py", "app/config.py"],
                },
                "config.py": {
                    "priority": 1,
                    "description": "Configuration and constants.",
                    "source_ref": ["project.summary", "artifacts.architecture"],
                    "depends_on": [],
                },
                "api": {
                    "__init__.py": {
                        "priority": 10,
                        "description": "API router registration.",
                        "source_ref": ["project.summary", "artifacts.api_spec"],
                        "depends_on": [f"app/api/{spec['file_stem']}_api.py" for spec in module_specs],
                    },
                },
                "services": {
                    "__init__.py": {
                        "priority": 2,
                        "description": "Service layer.",
                        "source_ref": ["project.summary"],
                        "depends_on": [],
                    },
                },
                "repositories": {
                    "__init__.py": {
                        "priority": 2,
                        "description": "Data access layer.",
                        "source_ref": ["project.summary"],
                        "depends_on": [],
                    },
                },
                "models": {
                    "__init__.py": {
                        "priority": 2,
                        "description": "Data models.",
                        "source_ref": ["project.summary"],
                        "depends_on": [],
                    },
                },
            },
        }
        api_manifest = backend_manifest["app"]["api"]
        service_manifest = backend_manifest["app"]["services"]
        repository_manifest = backend_manifest["app"]["repositories"]
        model_manifest = backend_manifest["app"]["models"]

        for index, spec in enumerate(module_specs, start=1):
            api_manifest[f"{spec['file_stem']}_api.py"] = {
                "priority": 9 + index,
                "description": f"{spec['label']} API endpoints.",
                "source_ref": [spec["source_ref"]],
                "depends_on": [f"app/services/{spec['file_stem']}_service.py"],
            }
            service_manifest[f"{spec['file_stem']}_service.py"] = {
                "priority": 6 + index,
                "description": f"{spec['label']} business logic.",
                "source_ref": [spec["source_ref"]],
                "depends_on": [
                    f"app/repositories/{spec['file_stem']}_repository.py",
                    f"app/models/{spec['file_stem']}.py",
                ],
            }
            repository_manifest[f"{spec['file_stem']}_repository.py"] = {
                "priority": 4 + index,
                "description": f"{spec['label']} data access.",
                "source_ref": [spec["source_ref"]],
                "depends_on": [f"app/models/{spec['file_stem']}.py"],
            }
            model_manifest[f"{spec['file_stem']}.py"] = {
                "priority": 3 + index,
                "description": f"{spec['label']} data models.",
                "source_ref": [spec["source_ref"]],
                "depends_on": [],
            }

        return {"backend": backend_manifest}

    def _build_coding_agent_semantic_model(
        self,
        *,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        artifacts: dict[str, Any],
    ) -> dict[str, Any]:
        """构造 Coding Agent 的语义上下文（项目摘要、制品、模块操作）。"""
        # semantic_model 是给 Code Agent 的结构化上下文。
        # 它把需求、架构、接口、模块操作统一整理成一个稳定输入，避免 Agent 只靠长文本硬猜。
        module_specs = self._coding_agent_module_specs(
            prompt=prompt,
            selected_modules=selected_modules,
            api_spec=str(artifacts.get("api_spec") or ""),
        )
        backend_modules: dict[str, Any] = {}
        for spec in module_specs:
            backend_modules[spec["semantic_key"]] = {
                "name": spec["label"],
                "summary": spec["description"],
                "operations": spec["operations"],
                "routes": [operation["route"] for operation in spec["operations"]],
            }
        return {
            "project": {
                "summary": prompt,
                "selected_modules": [spec["label"] for spec in module_specs],
            },
            "artifacts": {
                "prd": str(artifacts.get("prd") or ""),
                "architecture": str(artifacts.get("architecture") or ""),
                "api_spec": str(artifacts.get("api_spec") or ""),
            },
            "backend": {
                "modules": backend_modules,
            },
        }

    def _coding_agent_module_specs(
        self,
        *,
        prompt: str,
        selected_modules: list[dict[str, Any]],
        api_spec: str,
    ) -> list[dict[str, Any]]:
        """从用户选择的模块和 API Spec 提取模块规格。"""
        operations_by_module = self._coding_agent_operations_by_module(api_spec, selected_modules)
        module_specs: list[dict[str, Any]] = []
        for index, module in enumerate(selected_modules or [{"id": "core-business-workflow", "labelEn": "Core Business Workflow"}], start=1):
            raw_id = str(module.get("id") or module.get("labelEn") or module.get("label") or f"module-{index}")
            label = str(module.get("labelEn") or module.get("label") or raw_id).strip() or f"Module {index}"
            module_slug = re.sub(r"[^a-z0-9]+", "-", raw_id.lower()).strip("-") or f"module-{index}"
            semantic_key = module_slug.replace("-", "_")
            operations = operations_by_module.get(module_slug) or []
            if not operations:
                operations = [
                    {
                        "verb": "GET",
                        "route": f"/api/{module_slug}",
                        "summary": f"List {label.lower()}.",
                    },
                    {
                        "verb": "POST",
                        "route": f"/api/{module_slug}",
                        "summary": f"Create or update {label.lower()}.",
                    },
                ]
            operation_summary = ", ".join(
                f"{operation['verb']} {operation['route']}" for operation in operations[:4]
            )
            module_specs.append(
                {
                    "id": module_slug,
                    "label": label,
                    "description": f"{label}",
                    "file_stem": module_slug.replace("-", "_"),
                    "semantic_key": semantic_key,
                    "source_ref": f"backend.modules.{semantic_key}",
                    "operations": operations,
                    "operation_summary": operation_summary,
                }
            )
        return module_specs

    def _coding_agent_operations_by_module(
        self,
        api_spec: str,
        selected_modules: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, str]]]:
        """从 OpenAPI Spec 按模块分组提取操作。"""
        grouped: dict[str, list[dict[str, str]]] = {}
        try:
            payload = yaml.safe_load(api_spec) if api_spec.strip() else {}
        except Exception:
            payload = {}
        paths = payload.get("paths") if isinstance(payload, dict) else None
        if not isinstance(paths, dict):
            return grouped

        module_ids = [
            re.sub(r"[^a-z0-9]+", "-", str(module.get("id") or module.get("labelEn") or module.get("label") or "").lower()).strip("-")
            for module in selected_modules
        ]
        for route, methods in paths.items():
            if not isinstance(route, str) or not isinstance(methods, dict):
                continue
            module_id = self._match_module_for_route(route, module_ids)
            if not module_id:
                continue
            module_operations = grouped.setdefault(module_id, [])
            for verb, operation in methods.items():
                if not isinstance(operation, dict):
                    continue
                module_operations.append(
                    {
                        "verb": str(verb).upper(),
                        "route": route,
                        "summary": str(operation.get("summary") or operation.get("operationId") or "API operation"),
                    }
                )
        return grouped

    def _match_module_for_route(self, route: str, module_ids: list[str]) -> str | None:
        """将 API 路由匹配到最相关的模块 ID。"""
        normalized_route = re.sub(r"[^a-z0-9/]+", "-", route.lower())
        for module_id in module_ids:
            if not module_id:
                continue
            if module_id in normalized_route:
                return module_id
        segments = [segment for segment in route.split("/") if segment and not segment.startswith("{")]
        if segments and module_ids:
            first_segment = re.sub(r"[^a-z0-9]+", "-", segments[0].lower()).strip("-")
            if first_segment in module_ids:
                return first_segment
            return module_ids[0]
        return module_ids[0] if module_ids else None

    def _find_newest_architecture_output_dir(
        self,
        *,
        output_root: Path,
        before: set[Path],
        project_name: str,
    ) -> Path | None:
        """在 Architecture Agent 输出根目录中找到最新产出的子目录。"""
        candidates = [path.resolve() for path in output_root.iterdir() if path.is_dir()]
        fresh = [path for path in candidates if path not in before]
        if fresh:
            return max(fresh, key=lambda path: path.stat().st_mtime)
        matching = [path for path in candidates if path.name.endswith(f"_{project_name}")]
        if matching:
            return max(matching, key=lambda path: path.stat().st_mtime)
        return None

    def _architecture_agent_payload_from_files(
        self,
        file_contents: dict[str, str],
        *,
        output_dir: str,
        status: str = "completed",
    ) -> dict[str, Any] | None:
        """
        从一组已经拿到手的架构文件内容里，重建平台后续阶段要用的 payload。

        接口注释：
        这个入口既给正常目录读取复用，也给“文件已经进数据库，但子进程还没返回”的恢复场景复用。
        这样平台只维护一套架构稿拼装规则，避免目录路径和数据库路径各写一份，后面越改越偏。
        """

        component_text = str(file_contents.get("component_design.json") or "").strip()
        class_raw = str(file_contents.get("class_design_raw.md") or "").strip()
        class_structured = str(file_contents.get("class_design_structured.json") or "").strip()
        analysis_text = str(file_contents.get("analysis_task_output.txt") or "").strip()

        if not component_text and not class_raw and not analysis_text:
            return None
        # 设计注释：
        # `analysis_task_output.txt` 只是架构 Agent 最早产出的分析草稿，
        # `component_design.json` 也只覆盖到了组件层。
        # 默认拼装路径必须看到真实架构设计文件，不能只靠分析草稿冒充完整结果。
        # 只有 `_read_architecture_agent_output` 的展示兜底会传入
        # `salvaged_analysis_output`，明确表示“这里只是给页面展示已有分析，不代表阶段完成”。
        if status != "salvaged_analysis_output" and (not component_text or not class_raw):
            return None
        # 设计注释：
        # 只有在“recovered_live_output”这条实时恢复链路里，才必须把三份核心架构文件看齐：
        # 1. component_design.json
        # 2. class_design_raw.md
        # 3. class_design_structured.json
        #
        # 原因注释：
        # 正常完成链路下，Architecture Agent 可能还会返回一个可以继续兜底展示的 payload；
        # 但实时恢复链路完全依赖已经落盘的原始文件，少任何一份都说明架构稿还只是半成品。
        # 如果这里放宽，前端就会出现“还缺 class_design_* 文件，但流程已经进入下一步确认”的假成功状态。
        if status == "recovered_live_output" and (not component_text or not class_raw or not class_structured):
            return None

        overview = "Generated by Architecture Agent."
        diagram = ""
        components_markdown = ""
        if component_text:
            payload = json.loads(component_text)
            overview = "Generated by Architecture Agent."
            components = payload.get("components")
            if isinstance(components, list) and components:
                component_lines = []
                for component in components:
                    if not isinstance(component, dict):
                        continue
                    name = str(component.get("name") or "Component").strip()
                    description = str(component.get("description") or "").strip()
                    if description:
                        component_lines.append(f"- **{name}**: {description}")
                    else:
                        component_lines.append(f"- **{name}**")
                if component_lines:
                    components_markdown = "\n".join(component_lines)
            diagram = str(payload.get("component_diagram") or "").strip()
        elif analysis_text:
            overview = analysis_text or overview

        sections = [
            "# Architecture",
            "",
            "## Overview",
            overview,
        ]
        if components_markdown:
            sections.extend(["", "## Components", components_markdown])
        if diagram:
            sections.extend(["", "## Diagram", "```mermaid", diagram, "```"])
        if class_raw:
            sections.extend(["", "## Module Design", class_raw])
        return {
            "architecture": "\n".join(sections).strip(),
            "_meta": {
                "source": "architecture_agent",
                "status": status,
                "outputDir": output_dir,
                "structuredClassDesignPath": f"{output_dir}/class_design_structured.json" if class_structured else None,
                "sourceFilesByArtifact": {
                    "architecture": [
                        file_name
                        for file_name, exists in (
                            ("component_design.json", bool(component_text)),
                            ("class_design_raw.md", bool(class_raw)),
                            ("class_design_structured.json", bool(class_structured)),
                            ("analysis_task_output.txt", bool(analysis_text) and not component_text and not class_raw),
                        )
                        if exists
                    ],
                },
            },
        }

    def _read_architecture_agent_output(self, output_dir: Path) -> dict[str, Any] | None:
        """从 Architecture Agent 输出目录读取架构制品。"""
        file_contents = {
            path.name: path.read_text(encoding="utf-8")
            for path in (
                output_dir / "component_design.json",
                output_dir / "class_design_raw.md",
                output_dir / "class_design_structured.json",
                output_dir / "analysis_task_output.txt",
            )
            if path.exists()
        }
        status = "completed"
        if (
            file_contents.get("analysis_task_output.txt")
            and not file_contents.get("component_design.json")
            and not file_contents.get("class_design_raw.md")
        ):
            # 原因注释：
            # 这里是“展示兜底”，不是“流程完成”。架构 Agent 超时或失败时，
            # 页面仍然可以把已写出的分析草稿给用户看，但不能因此进入人工确认。
            status = "salvaged_analysis_output"
        return self._architecture_agent_payload_from_files(
            file_contents,
            output_dir=str(output_dir),
            status=status,
        )

    def _game_prompt_module_catalog(self) -> list[dict[str, Any]]:
        """返回游戏类项目的预定义模块目录。"""
        return [
            {
                "id": "core-gameplay-mechanics",
                "label": "Core Gameplay Mechanics",
                "labelEn": "Core Gameplay Mechanics",
                "description": "Snake movement, collision rules, growth logic, and the main gameplay loop.",
            },
            {
                "id": "consumables-system",
                "label": "Consumables System",
                "labelEn": "Consumables System",
                "description": "Food spawning, placement validation, and item consumption handling.",
            },
            {
                "id": "game-state-management",
                "label": "Game State Management",
                "labelEn": "Game State Management",
                "description": "Start, running, paused, game-over, and restart state transitions.",
            },
            {
                "id": "rendering-engine",
                "label": "Rendering Engine",
                "labelEn": "Rendering Engine",
                "description": "Game board rendering, snake drawing, food rendering, and frame updates.",
            },
            {
                "id": "input-processing",
                "label": "Input Processing",
                "labelEn": "Input Processing",
                "description": "Keyboard input handling, direction changes, and invalid-turn protection.",
            },
            {
                "id": "scoring-progression",
                "label": "Scoring & Progression",
                "labelEn": "Scoring & Progression",
                "description": "Score tracking, speed progression, and optional leaderboard readiness.",
            },
        ]

    def _prompt_looks_like_game(self, prompt: str) -> bool:
        """判断用户 prompt 是否看起来像游戏类项目。"""
        lowered = prompt.lower()
        keywords = (
            "snake",
            "贪吃蛇",
            "game",
            "游戏",
            "arcade",
            "pygame",
            "canvas game",
        )
        return any(keyword in lowered for keyword in keywords)

    def _looks_like_generic_enterprise_module_set(self, modules: list[dict[str, Any]]) -> bool:
        """判断模块列表是否为通用企业模块的默认组合。"""
        if not modules:
            return False
        module_ids = {str(module.get("id") or "").strip() for module in modules}
        return module_ids.issubset({"user-system", "core-business-workflow", "admin-console"})

    def _looks_like_broken_document_module(self, module: dict[str, Any]) -> bool:
        """
        有些坏结果会把整篇业务范围文档塞进一个模块里。

        这种结果通常有两个明显特征：
        1. 模块标题本身像“业务范围文档”“说明书”
        2. description 不是一句描述，而是整段 Markdown 标题、表格、编号章节
        """

        label = self._compact_text(str(module.get("label") or module.get("labelEn") or ""))
        description = str(module.get("description") or "")
        if not label and not description:
            return False

        label_lower = label.lower()
        if any(keyword in label_lower for keyword in ("业务范围文档", "需求规格说明书", "business scope", "document")):
            return True

        normalized_description = description.strip()
        if len(normalized_description) < 80:
            return False
        return any(
            marker in normalized_description
            for marker in ("## ", "|", "### ", "1.业务目标", "1. Business Goal", "编号")
        )

    def _repair_analysis_modules_for_prompt(
        self,
        prompt: str,
        modules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """当分析结果模块为空时尝试从 prompt 推断。"""
        if not self._prompt_looks_like_game(prompt):
            return modules
        if any(self._looks_like_broken_document_module(module) for module in modules):
            return [{**module, "checked": True} for module in self._game_prompt_module_catalog()]
        if not self._looks_like_generic_enterprise_module_set(modules):
            return modules
        return [{**module, "checked": True} for module in self._game_prompt_module_catalog()]

    def _normalize_artifacts(
        self,
        *,
        prompt: str,
        payload: dict[str, Any],
        selected_modules: list[dict[str, Any]],
    ) -> dict[str, str]:
        """标准化各类制品的格式和必要段落。"""
        prd = self._normalize_prd(str(payload.get("prd") or "").strip(), prompt, selected_modules)
        ui = self._normalize_ui(payload.get("ui"), selected_modules)
        architecture = self._normalize_architecture(payload.get("architecture"))
        api_spec = self._normalize_api_spec(str(payload.get("api_spec") or "").strip())
        return {
            "prd": prd,
            "ui": ui,
            "architecture": architecture,
            "api_spec": api_spec,
        }

    def _normalize_prd(self, content: str, prompt: str, selected_modules: list[dict[str, Any]]) -> str:
        """标准化 PRD 文档格式，补齐缺失的必要段落。"""
        body = content.strip()
        if not body.startswith("# "):
            body = f"# Product Requirements Document\n\n{body}"
        elif not body.lower().startswith("# product requirements document"):
            body = f"# Product Requirements Document\n\n{body}"

        if "## Overview" not in body:
            overview_source = content.strip() or prompt.strip() or "Project requirement summary."
            body += f"\n\n## Overview\n{overview_source}"

        if "## Functional Scope" not in body:
            module_lines = self._selected_module_list(selected_modules)
            body += f"\n\n## Functional Scope\n{module_lines}"

        if "## Non-Functional Requirements" not in body:
            body += (
                "\n\n## Non-Functional Requirements\n"
                "- Responsive web experience for desktop-first workflows.\n"
                "- Clear API boundaries between frontend and Python backend services.\n"
                "- Basic auditability for project versions and generated artifacts.\n"
            )
        return body.strip()

    def _normalize_ui(self, value: Any, selected_modules: list[dict[str, Any]]) -> str:
        """标准化 UI 页面描述格式。"""
        if isinstance(value, dict) and isinstance(value.get("pages"), list):
            lines = [
                "# UI Pages",
                "",
                "## Page Inventory",
                "| Page | Route | Preview |",
                "| --- | --- | --- |",
            ]
            for page in value["pages"]:
                if not isinstance(page, dict):
                    continue
                name = str(page.get("name") or page.get("id") or "Page")
                route = str(page.get("route") or "/")
                preview = str(page.get("previewUrl") or "-")
                lines.append(f"| {name} | {route} | {preview} |")
            return "\n".join(lines).strip()

        body = str(value or "").strip()
        if not body.startswith("# UI Pages"):
            body = f"# UI Pages\n\n{body}"
        if "## Page Inventory" not in body:
            body += f"\n\n## Page Inventory\n{self._selected_module_list(selected_modules)}"
        return body.strip()

    def _normalize_architecture(self, value: Any) -> str:
        """标准化架构文档格式。"""
        if isinstance(value, dict):
            description = str(value.get("description") or "System architecture overview.").strip()
            mermaid_code = str(value.get("mermaidCode") or "").strip()
            sections = ["# Architecture", "", "## Overview", description]
            if mermaid_code:
                sections.extend(["", "## Diagram", "```mermaid", mermaid_code, "```"])
            return "\n".join(sections).strip()

        body = str(value or "").strip()
        if not body.startswith("# Architecture"):
            body = f"# Architecture\n\n{body}"
        if "## Overview" not in body:
            summary = str(value or "System architecture overview.").strip() or "System architecture overview."
            body += f"\n\n## Overview\n{summary}"
        return body.strip()

    def _normalize_api_spec(self, content: str) -> str:
        """标准化 OpenAPI Spec 格式，补齐缺失的必要字段。"""
        body = content.strip()
        if not body.startswith("openapi:"):
            body = f"openapi: 3.0.0\n{body}"
        if "\ninfo:" not in body:
            body = body.replace("openapi: 3.0.0", "openapi: 3.0.0\ninfo:\n  title: API Spec\n  version: 0.1.0", 1)
        if "\npaths:" not in body:
            body += "\npaths: {}\n"
        return body.strip() + "\n"

    def _selected_module_list(self, selected_modules: list[dict[str, Any]]) -> str:
        """将 selected_modules 格式化为 Markdown 列表。"""
        if not selected_modules:
            return "- No modules selected yet."
        lines: list[str] = []
        for module in selected_modules:
            label = str(module.get("labelEn") or module.get("label") or module.get("id") or "Core Module")
            lines.append(f"- {label}")
        return "\n".join(lines)

    def _reference_list(self, reference_materials: list[dict[str, Any]]) -> str:
        """将参考材料格式化为 Markdown 列表。"""
        if not reference_materials:
            return "- No external references provided."
        lines: list[str] = []
        for material in reference_materials:
            preview = material.get("contentPreview") or "No preview available."
            if str(material.get("summarySource") or "").strip() == "image_analysis":
                lines.append(f"- {material['fileName']} [Image summary for first-pass analysis]: {preview}")
                continue
            lines.append(f"- {material['fileName']}: {preview}")
        return "\n".join(lines)

    def _existing_artifacts_outline(self, existing_artifacts: list[dict[str, Any]]) -> str:
        """将已有制品格式化为简短 Markdown 大纲。"""
        if not existing_artifacts:
            return "- No existing artifacts."
        lines: list[str] = []
        for artifact in existing_artifacts:
            lines.append(f"- {artifact['type']}: {artifact['title']}")
        return "\n".join(lines)

    def _existing_artifacts_for_generation_prompt(self, existing_artifacts: list[dict[str, Any]]) -> str:
        """将已有制品格式化为生成阶段 prompt 的 Markdown 段落。"""
        if not existing_artifacts:
            return "- No existing artifacts."
        sections: list[str] = []
        for artifact in existing_artifacts[:6]:
            artifact_type = str(artifact.get("type") or "artifact").strip()
            title = str(artifact.get("title") or artifact_type).strip() or artifact_type
            content = str(artifact.get("content") or "").strip()
            if len(content) > 1200:
                content = content[:1200].rstrip() + "\n...[truncated]"
            if content:
                sections.append(f"### {title} ({artifact_type})\n{content}")
            else:
                sections.append(f"### {title} ({artifact_type})")
        return "\n\n".join(sections)


agent_orchestrator = AgentOrchestrator()
