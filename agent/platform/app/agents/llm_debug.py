from __future__ import annotations

import itertools
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.config import delete_local_files_after_persist_enabled

_PATCH_LOCK = threading.Lock()
_CALL_COUNTER = itertools.count(1)
_PATCHED = False
_USAGE_TRACKING_PATCHED = False
_FILE_WRITE_LOCK = threading.Lock()
_DEBUG_CONTEXT_LOCAL = threading.local()


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _clip_text(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit], True


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def _resolve_debug_log_path() -> Path | None:
    """
    接口注释：
    解析 LLM 调试日志文件路径。

    设计注释：
    调试开关打开后，开发者通常希望既能在终端看到内容，
    也能在任务结束后回头翻完整日志。
    这里允许显式指定日志文件路径；如果没指定，但打开了“写文件”开关，
    就落到平台目录下的默认日志文件。
    """

    if delete_local_files_after_persist_enabled():
        return None

    configured = str(os.getenv("ISOFTDEVAGENTS_AGENT_DEBUG_LLM_LOG_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    if _env_flag("ISOFTDEVAGENTS_AGENT_DEBUG_LLM_LOG_TO_FILE", default=False):
        return Path(__file__).resolve().parents[2] / "log" / "llm-debug.log"
    return None


def _debug_console_enabled() -> bool:
    """
    接口注释：
    判断 LLM 调试日志是否允许直接写到当前后端控制台。

    设计注释：
    本地开发时打开 LLM 输入输出日志后，单次请求可能会打印非常长的 prompt 和模型响应。
    如果这些内容持续写进启动 uvicorn 的终端，终端缓冲区一旦堵住，就会把整个后端请求链路一起拖停。
    所以这里把“写文件”和“写控制台”拆开：默认保留文件日志，控制台必须显式开启。
    """

    return _env_flag("ISOFTDEVAGENTS_AGENT_DEBUG_LLM_LOG_TO_CONSOLE", default=False)


def _emit_debug_text(text: str) -> None:
    if _debug_console_enabled():
        print(text)

    log_path = _resolve_debug_log_path()
    if log_path is None:
        return

    with _FILE_WRITE_LOCK:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")


def _current_debug_context() -> dict[str, Any]:
    current = getattr(_DEBUG_CONTEXT_LOCAL, "current", None)
    return dict(current or {})


@contextmanager
def llm_debug_context(**values: Any):
    """
    给当前线程里的 LLM 调试日志附加上下文标签。

    接口注释：
    这里专门服务“同一个日志文件里混了多个 Agent、多轮重试”的排查场景。
    只要外层在进入某条 Agent 链路前挂上 task_id / phase / retry，
    后面的每一次 LLM 调用就都会自动带上这些标签。
    """

    previous = _current_debug_context()
    merged = dict(previous)
    for key, value in values.items():
        if value is None:
            continue
        merged[key] = value
    _DEBUG_CONTEXT_LOCAL.current = merged
    try:
        yield
    finally:
        if previous:
            _DEBUG_CONTEXT_LOCAL.current = previous
        elif hasattr(_DEBUG_CONTEXT_LOCAL, "current"):
            delattr(_DEBUG_CONTEXT_LOCAL, "current")


def _int_like(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _read_usage_value(source: Any, *names: str) -> Any:
    """
    接口注释：
    从 usage 容器里读取字段，既支持字典，也支持带属性的对象。

    教学注释：
    这层专门用来兼容 LiteLLM / OpenAI SDK 一些对象型 usage。
    它们看起来像字典里的内容，但真实类型可能是 `Usage(...)`，
    只能通过属性访问，不能直接 `get("prompt_tokens")`。
    """

    for name in names:
        value = None
        if isinstance(source, dict):
            value = source.get(name)
        else:
            value = getattr(source, name, None)
        if value is not None:
            return value
    return None


def _normalize_crewai_usage_payload(usage_data: Any) -> tuple[dict[str, Any], int]:
    """
    接口注释：
    把不同风格的 usage 字段统一成 CrewAI 自己能识别的结构。

    原因注释：
    我们当前接的部分网关会返回 `inputTokens/outputTokens/totalTokens`
    这种驼峰命名，但 CrewAI 1.6 内部只会读取
    `prompt_tokens/completion_tokens/input_tokens/output_tokens`。
    如果不在这里兜底，模型虽然真实消耗了 token，
    CrewAI 的内部累计器仍然会一直记成 0。
    """
    payload = usage_data
    if hasattr(payload, "model_dump"):
        try:
            dumped = payload.model_dump()
            if isinstance(dumped, dict):
                payload = dumped
        except Exception:
            pass
    elif hasattr(payload, "dict"):
        try:
            dumped = payload.dict()
            if isinstance(dumped, dict):
                payload = dumped
        except Exception:
            pass

    prompt_tokens = _int_like(
        _read_usage_value(
            payload,
            "prompt_tokens",
            "prompt_token_count",
            "input_tokens",
            "inputTokens",
        )
    )
    completion_tokens = _int_like(
        _read_usage_value(
            payload,
            "completion_tokens",
            "candidates_token_count",
            "output_tokens",
            "outputTokens",
        )
    )
    cached_prompt_tokens = _int_like(
        _read_usage_value(
            payload,
            "cached_tokens",
            "cached_prompt_tokens",
            "cachedPromptTokens",
        )
    )
    total_tokens = _int_like(
        _read_usage_value(
            payload,
            "total_tokens",
            "totalTokens",
        )
    )

    if prompt_tokens <= 0 and completion_tokens <= 0 and cached_prompt_tokens <= 0:
        return {}, 0

    normalized = dict(payload) if isinstance(payload, dict) else {}

    normalized["prompt_tokens"] = prompt_tokens
    normalized["input_tokens"] = prompt_tokens
    normalized["completion_tokens"] = completion_tokens
    normalized["output_tokens"] = completion_tokens
    normalized["total_tokens"] = total_tokens
    normalized["cached_tokens"] = cached_prompt_tokens
    normalized["cached_prompt_tokens"] = cached_prompt_tokens

    return normalized, total_tokens


def _normalize_litellm_callback_usage_payload(response_obj: Any) -> dict[str, Any]:
    """
    接口注释：
    从 LiteLLM 成功回调给出的 `response_obj` 里抽出 usage，并统一成 CrewAI 可识别的字段。

    设计注释：
    CrewAI 走 LiteLLM 的非流式路径时，很多模型不会主动把 usage 写进
    `self._token_usage`，而是只把 `response_obj["usage"]` 交给 callback。
    如果我们不在这里把 callback 里的 usage 再喂回 `_track_token_usage_internal`，
    Requirements Agent 分析阶段虽然真实调用成功，平台看到的 token 仍然会是 0。
    """

    if not isinstance(response_obj, dict):
        return {}
    usage_payload = response_obj.get("usage")
    normalized_usage_payload, _ = _normalize_crewai_usage_payload(usage_payload)
    return normalized_usage_payload


def _normalize_openai_response_usage(usage_payload: Any) -> dict[str, Any]:
    """
    接口注释：
    把 OpenAI SDK 响应对象上的 `usage` 统一成 provider 能继续累计的字段。

    原因注释：
    当前这条网关返回的 usage 不是标准 `prompt_tokens/completion_tokens`，
    而是 `inputTokens/outputTokens/totalTokens`。
    CrewAI 自带的 OpenAI provider 只认前一种，所以会把真实 token 全部算成 0。
    """

    normalized_usage_payload, reported_total_tokens = _normalize_crewai_usage_payload(usage_payload)
    if not normalized_usage_payload:
        return {"total_tokens": 0}

    return {
        "prompt_tokens": _int_like(normalized_usage_payload.get("prompt_tokens")),
        "completion_tokens": _int_like(normalized_usage_payload.get("completion_tokens")),
        "total_tokens": _int_like(normalized_usage_payload.get("total_tokens") or reported_total_tokens),
        "cached_prompt_tokens": _int_like(normalized_usage_payload.get("cached_prompt_tokens")),
    }


class _LiteLLMUsageTrackingCallback:
    """
    教学注释：
    这是一个只给 CrewAI 内部用的 callback。

    它不负责业务逻辑，只做一件事：
    当 LiteLLM 成功返回时，把 `response_obj["usage"]` 再写回当前 LLM 实例的
    `_token_usage` 累计器。这样后面的 `calculate_usage_metrics()` 才能看到真实 token。
    """

    __isoft_usage_tracker__ = True

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def log_success_event(
        self,
        *,
        kwargs: Any,
        response_obj: Any,
        start_time: Any,
        end_time: Any,
    ) -> None:
        del kwargs, start_time, end_time
        normalized_usage_payload = _normalize_litellm_callback_usage_payload(response_obj)
        if not normalized_usage_payload:
            return
        self._llm._track_token_usage_internal(normalized_usage_payload)


def _install_crewai_usage_tracking_patch() -> None:
    global _USAGE_TRACKING_PATCHED
    if _USAGE_TRACKING_PATCHED:
        return

    from crewai.llm import LLM

    original_track_token_usage_internal = LLM._track_token_usage_internal
    original_call = LLM.call

    from crewai.llms.providers.openai.completion import OpenAICompletion

    original_extract_openai_token_usage = OpenAICompletion._extract_openai_token_usage

    def patched_track_token_usage_internal(self, usage_data: Any) -> None:
        normalized_usage_data, reported_total_tokens = _normalize_crewai_usage_payload(usage_data)
        original_track_token_usage_internal(self, normalized_usage_data)

        accounted_total_tokens = _int_like(normalized_usage_data.get("prompt_tokens")) + _int_like(
            normalized_usage_data.get("completion_tokens")
        )
        remaining_total_tokens = reported_total_tokens - accounted_total_tokens
        if remaining_total_tokens > 0:
            self._token_usage["total_tokens"] += remaining_total_tokens

    def patched_call(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> Any:
        patched_callbacks = callbacks
        if getattr(self, "is_litellm", False):
            callback_list = list(callbacks or [])
            has_usage_tracker = any(
                getattr(callback, "__isoft_usage_tracker__", False)
                for callback in callback_list
            )
            if not has_usage_tracker:
                callback_list.append(_LiteLLMUsageTrackingCallback(self))
            patched_callbacks = callback_list

        return original_call(
            self,
            messages,
            tools=tools,
            callbacks=patched_callbacks,
            available_functions=available_functions,
            from_task=from_task,
            from_agent=from_agent,
            response_model=response_model,
        )

    def patched_extract_openai_token_usage(self, response: Any) -> dict[str, Any]:
        extracted_usage_payload = original_extract_openai_token_usage(self, response)
        if int(extracted_usage_payload.get("total_tokens") or 0) > 0:
            return extracted_usage_payload
        usage_payload = getattr(response, "usage", None)
        return _normalize_openai_response_usage(usage_payload)

    LLM._track_token_usage_internal = patched_track_token_usage_internal  # type: ignore[assignment]
    LLM.call = patched_call  # type: ignore[assignment]
    OpenAICompletion._extract_openai_token_usage = patched_extract_openai_token_usage  # type: ignore[assignment]
    _USAGE_TRACKING_PATCHED = True


def _render_messages(messages: Any, *, limit: int) -> str:
    if isinstance(messages, str):
        clipped, truncated = _clip_text(messages, limit)
        suffix = "\n[truncated]" if truncated else ""
        return f"[user]\n{clipped}{suffix}"

    if not isinstance(messages, list):
        rendered = _safe_json(messages)
        clipped, truncated = _clip_text(rendered, limit)
        suffix = "\n[truncated]" if truncated else ""
        return f"[unknown]\n{clipped}{suffix}"

    rendered_parts: list[str] = []
    remaining = limit
    truncated = False
    for message in messages:
        if not isinstance(message, dict):
            chunk = _safe_json(message)
            role = "unknown"
        else:
            role = str(message.get("role") or "unknown")
            content = message.get("content")
            if isinstance(content, str):
                chunk = content
            else:
                chunk = _safe_json(content)
        block = f"[{role}]\n{chunk}"
        if len(block) > remaining:
            block = block[: max(0, remaining)]
            truncated = True
        rendered_parts.append(block)
        remaining -= len(block)
        if remaining <= 0:
            break
    text = "\n\n".join(rendered_parts)
    if truncated:
        text += "\n\n[truncated]"
    return text


def _render_response(response: Any, *, limit: int) -> str:
    if isinstance(response, str):
        clipped, truncated = _clip_text(response, limit)
        return clipped + ("\n[truncated]" if truncated else "")
    rendered = _safe_json(response)
    clipped, truncated = _clip_text(rendered, limit)
    return clipped + ("\n[truncated]" if truncated else "")


def _debug_summary_parts(
    *,
    debug_context: dict[str, Any],
    from_agent: Any = None,
    from_task: Any = None,
) -> list[str]:
    """
    生成一行可读的 LLM 调试摘要字段。

    接口注释：
    目标不是替代完整输入输出，而是让开发者只看单行摘要就知道：
    - 这是哪个平台任务
    - 当前处在哪个阶段
    - 属于哪个 Agent
    - 是哪一个 Crew 任务 / 哪一轮重试
    """

    parts: list[str] = []
    for field in (
        "task_id",
        "phase",
        "agent_name",
        "project_name",
        "output_file",
        "retry_name",
        "retry_attempt",
        "retry_max",
    ):
        value = debug_context.get(field)
        if value is None or value == "":
            continue
        parts.append(f"{field}={value}")

    agent_label = getattr(from_agent, "role", None) or getattr(from_agent, "name", None) or from_agent
    if agent_label:
        parts.append(f"crew_agent={agent_label}")

    task_label = getattr(from_task, "description", None) or getattr(from_task, "name", None) or from_task
    if task_label:
        clipped_task_label, truncated = _clip_text(str(task_label), 240)
        if truncated:
            clipped_task_label += "..."
        parts.append(f"crew_task={clipped_task_label}")

    return parts


def install_crewai_llm_debug_logging() -> None:
    global _PATCHED
    with _PATCH_LOCK:
        _install_crewai_usage_tracking_patch()
    if not _env_flag("ISOFTDEVAGENTS_AGENT_DEBUG_LLM_IO", default=False):
        return
    with _PATCH_LOCK:
        if _PATCHED:
            return
        from crewai.llm import LLM

        original_call = LLM.call

        def logged_call(
            self,
            messages: Any,
            tools: Any = None,
            callbacks: Any = None,
            available_functions: Any = None,
            from_task: Any = None,
            from_agent: Any = None,
            response_model: Any = None,
        ) -> Any:
            call_id = next(_CALL_COUNTER)
            input_limit = int(os.getenv("ISOFTDEVAGENTS_AGENT_DEBUG_LLM_INPUT_LIMIT") or "12000")
            output_limit = int(os.getenv("ISOFTDEVAGENTS_AGENT_DEBUG_LLM_OUTPUT_LIMIT") or "12000")
            debug_context = _current_debug_context()
            summary_parts = _debug_summary_parts(
                debug_context=debug_context,
                from_agent=from_agent,
                from_task=from_task,
            )
            summary_line = " | ".join(summary_parts)
            _emit_debug_text(f"[LLM DEBUG {call_id}] model={getattr(self, 'model', 'unknown')}")
            if summary_line:
                _emit_debug_text(f"[LLM DEBUG {call_id}] context={summary_line}")
            _emit_debug_text(f"[LLM DEBUG {call_id}] INPUT BEGIN")
            _emit_debug_text(_render_messages(messages, limit=input_limit))
            if summary_line:
                _emit_debug_text(f"[LLM DEBUG {call_id}] INPUT END context={summary_line}")
            else:
                _emit_debug_text(f"[LLM DEBUG {call_id}] INPUT END")
            try:
                response = original_call(
                    self,
                    messages,
                    tools=tools,
                    callbacks=callbacks,
                    available_functions=available_functions,
                    from_task=from_task,
                    from_agent=from_agent,
                    response_model=response_model,
                )
            except Exception as exc:
                if summary_line:
                    _emit_debug_text(f"[LLM DEBUG {call_id}] ERROR {exc} context={summary_line}")
                else:
                    _emit_debug_text(f"[LLM DEBUG {call_id}] ERROR {exc}")
                raise
            if summary_line:
                _emit_debug_text(f"[LLM DEBUG {call_id}] OUTPUT BEGIN context={summary_line}")
            else:
                _emit_debug_text(f"[LLM DEBUG {call_id}] OUTPUT BEGIN")
            _emit_debug_text(_render_response(response, limit=output_limit))
            if summary_line:
                _emit_debug_text(f"[LLM DEBUG {call_id}] OUTPUT END context={summary_line}")
            else:
                _emit_debug_text(f"[LLM DEBUG {call_id}] OUTPUT END")
            return response

        LLM.call = logged_call  # type: ignore[assignment]
        _PATCHED = True


__all__ = [
    "install_crewai_llm_debug_logging",
    "llm_debug_context",
]
