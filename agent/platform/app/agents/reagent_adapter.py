from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any


def _read_usage_field(source: Any, *names: str) -> int:
    """
    接口注释：
    从不同形状的 usage 对象里读取 token 字段，并统一转成整数。

    设计注释：
    Requirements Agent 现在会碰到多种来源：
    - CrewAI 汇总对象
    - Crew 结果对象上的 `token_usage`
    - 某些网关或适配层给出的驼峰字段
    - 一些对象自带 `dict()` / `model_dump()`

    如果这里只认一种字段名，平台就会把真实已经发生的消耗误判成“未上报”。
    """

    payload = source
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    elif hasattr(payload, "dict"):
        payload = payload.dict()

    for name in names:
        value = None
        if isinstance(payload, dict):
            value = payload.get(name)
        else:
            value = getattr(payload, name, None)
        try:
            normalized = int(value or 0)
        except (TypeError, ValueError):
            normalized = 0
        if normalized > 0:
            return normalized
    return 0


def _normalize_usage_payload(usage: Any) -> dict[str, Any] | None:
    """
    把 Requirements Agent 拿到的 usage 统一成平台自己的字段形状。

    教学注释：
    平台后面只认 `inputTokens / outputTokens / totalTokens`。
    这里先把驼峰、下划线、以及 CrewAI 老字段都收口，
    后面的桥梁和统计层就不用再一层层猜字段名字。
    """

    if usage is None:
        return None

    input_tokens = _read_usage_field(
        usage,
        "prompt_tokens",
        "prompt_token_count",
        "input_tokens",
        "inputTokens",
    )
    output_tokens = _read_usage_field(
        usage,
        "completion_tokens",
        "candidates_token_count",
        "output_tokens",
        "outputTokens",
    )
    total_tokens = _read_usage_field(
        usage,
        "total_tokens",
        "totalTokens",
    )

    if total_tokens <= 0 and (input_tokens > 0 or output_tokens > 0):
        total_tokens = input_tokens + output_tokens
    if total_tokens <= 0 and input_tokens <= 0 and output_tokens <= 0:
        return None

    return {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
    }


def _normalize_output_text(result: Any) -> str:
    raw = getattr(result, "raw", None)
    text = raw if isinstance(raw, str) and raw.strip() else str(result or "").strip()
    normalized = text.strip()
    if normalized.startswith("```"):
        first_newline = normalized.find("\n")
        if first_newline != -1:
            normalized = normalized[first_newline + 1 :]
        if normalized.endswith("```"):
            normalized = normalized[:-3]
    return normalized.strip()


def _resolve_output_path(output_file: Any) -> Path:
    output_path = Path(str(output_file))
    if output_path.is_absolute():
        return output_path

    store_root = os.getenv("REAGENT_STORE_PATH", "").strip()
    if store_root:
        store_root_path = Path(store_root)
        if store_root_path.is_absolute():
            stripped_store_root = Path(str(store_root_path).lstrip("/"))
            prefix = output_path.parts[: len(stripped_store_root.parts)]
            if prefix == stripped_store_root.parts:
                return Path("/") / output_path

    return output_path


def _persist_task_outputs(crew: Any, result: Any) -> None:
    # 原因注释：
    # CrewAI 1.6.x 的 output_file_validation 会 strip 掉绝对路径的 leading '/'，
    # 导致 task.output_file 变成相对路径，CrewAI 内部写文件时写到了 CWD 下的
    # 错误位置。这里用 _resolve_output_path 恢复绝对路径，再做一次兜底写入。
    content = _normalize_output_text(result)
    if not content:
        return

    store_root = os.getenv("REAGENT_STORE_PATH", "").strip()

    for task in getattr(crew, "tasks", []) or []:
        output_file = getattr(task, "output_file", None)
        if not output_file:
            continue

        output_path = _resolve_output_path(output_file)

        # 防御：如果 _resolve_output_path 返回的仍是相对路径，
        # 用 REAGENT_STORE_PATH + 文件名拼出正确的绝对路径。
        if not output_path.is_absolute() and store_root:
            output_path = Path(store_root) / output_path.name

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists() and output_path.read_text(encoding="utf-8").strip():
            continue
        output_path.write_text(content, encoding="utf-8")


def _usage_payload_from_crew(crew: Any) -> dict[str, Any] | None:
    """
    从 Crew 实例里提取这一次执行真正消耗掉的 token 数。

    需求 Agent 里有很多小 Crew 分阶段运行。这里统一把它们每一次 kickoff
    的 usage 抓出来，后端就能把整个需求阶段的总用量累加到项目统计里。
    """

    metrics = None
    try:
        if hasattr(crew, "calculate_usage_metrics"):
            metrics = crew.calculate_usage_metrics()
    except Exception:
        metrics = getattr(crew, "usage_metrics", None)

    return _normalize_usage_payload(metrics)


def _usage_payload_from_result(result: Any) -> dict[str, Any] | None:
    """
    接口注释：
    有些 Crew 运行方式不会把 usage 正确汇总回 `crew.calculate_usage_metrics()`，
    但 `kickoff()` 返回结果本身会带 `token_usage` 或 `usage_metrics`。

    这里补这一层兼容，避免平台把真实已消耗的 token 误判成“未上报”。
    """

    if result is None:
        return None

    usage = getattr(result, "token_usage", None)
    if usage is None:
        usage = getattr(result, "usage_metrics", None)
    if usage is None:
        usage = getattr(result, "usage", None)
    if usage is None:
        return None

    return _normalize_usage_payload(usage)


def _write_usage_to_file(usage_payload: dict[str, Any]) -> None:
    """
    子进程运行时通过文件把 usage 数据传递给父进程。

    原因注释：
    subprocess 模式下 usage_callback 无法跨进程传递。
    每次 crew attempt（无论成功或失败）都会调用这个函数，
    所以这里用累加而不是覆盖，确保所有 attempt 的 token 消耗都被记录。
    """
    usage_output = os.getenv("ISOFTDEVAGENTS_USAGE_OUTPUT", "").strip()
    if not usage_output:
        return
    try:
        usage_path = Path(usage_output)
        existing: dict[str, Any] = {}
        if usage_path.exists():
            try:
                existing = json.loads(usage_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}
        merged = {
            "model": usage_payload.get("model") or existing.get("model") or "",
            "inputTokens": int(existing.get("inputTokens") or 0) + int(usage_payload.get("inputTokens") or 0),
            "outputTokens": int(existing.get("outputTokens") or 0) + int(usage_payload.get("outputTokens") or 0),
            "totalTokens": int(existing.get("totalTokens") or 0) + int(usage_payload.get("totalTokens") or 0),
        }
        usage_path.write_text(
            json.dumps(merged, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _patched_run_with_retry(
    crew_callable: Any,
    inputs: dict[str, Any],
    name: str,
    retries: int = 5,
    delay: int = 15,
    post_process_callable: Any = None,
    post_process_params: Any = None,
    usage_callback: Any = None,
    cancel_event: Any = None,
) -> Any:
    last_error: Exception | None = None

    def raise_if_cancelled() -> None:
        if cancel_event is not None and getattr(cancel_event, "is_set", None) and cancel_event.is_set():
            raise RuntimeError(f"[{name}] Cancelled before completing retry chain.")

    for attempt in range(1, retries + 1):
        crew = None
        result = None
        try:
            raise_if_cancelled()
            print(f"[{name}] Attempt {attempt}/{retries}")
            try:
                from app.agents.llm_debug import llm_debug_context
            except Exception:
                llm_debug_context = None  # type: ignore[assignment]

            if llm_debug_context is None:
                context_manager = None
            else:
                context_manager = llm_debug_context(
                    retry_name=name,
                    retry_attempt=attempt,
                    retry_max=retries,
                )
            crew_instance = crew_callable()
            crew = crew_instance.crew()
            if context_manager is None:
                result = crew.kickoff(inputs=inputs)
            else:
                with context_manager:
                    result = crew.kickoff(inputs=inputs)
            _persist_task_outputs(crew, result)
            print(f"[{name}] Success")

            if post_process_callable:
                post_process_result = (
                    post_process_callable(post_process_params)
                    if post_process_params is not None
                    else post_process_callable()
                )
                if post_process_result is not None:
                    return post_process_result

            return None
        except Exception as error:  # pragma: no cover - exercised through subprocess integration
            last_error = error
            print(f"[{name}] Failed attempt {attempt}: {error}")
            traceback.print_exc()
            if attempt < retries:
                slept = 0.0
                while slept < delay:
                    raise_if_cancelled()
                    sleep_slice = min(0.2, delay - slept)
                    time.sleep(sleep_slice)
                    slept += sleep_slice
            else:
                raise Exception(f"[{name}] Failed after {retries} retries: {last_error}") from error
        finally:
            import sys as _sys
            usage_payload = None
            if crew is not None:
                usage_payload = _usage_payload_from_crew(crew)
            if usage_payload is None:
                usage_payload = _usage_payload_from_result(result)
            if usage_payload is None and crew is not None:
                # 诊断：dump crew 上所有 usage 相关属性
                _diag_parts = []
                for _attr in ("usage_metrics", "_usage_metrics", "token_usage", "_token_usage", "_usage"):
                    _val = getattr(crew, _attr, "N/A")
                    if _val != "N/A":
                        _diag_parts.append(f"crew.{_attr}={_val}")
                if hasattr(crew, "calculate_usage_metrics"):
                    try:
                        _diag_parts.append(f"crew.calculate_usage_metrics()={crew.calculate_usage_metrics()}")
                    except Exception as _e:
                        _diag_parts.append(f"crew.calculate_usage_metrics() RAISED: {_e}")
                if result is not None:
                    for _attr in ("token_usage", "usage_metrics", "usage", "tokens_used"):
                        _val = getattr(result, _attr, "N/A")
                        if _val != "N/A":
                            _diag_parts.append(f"result.{_attr}={_val}")
                print(f"[{name}] usage: NONE. diag: {'; '.join(_diag_parts) or 'no usage attrs found'}", file=_sys.__stderr__, flush=True)
            if usage_payload is not None:
                print(f"[{name}] usage: {usage_payload}", file=_sys.__stderr__, flush=True)
                if usage_callback is not None:
                    usage_callback(usage_payload)
                _write_usage_to_file(usage_payload)

    return None


def main() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    reagent_root = repo_root / "agent" / "Requirements Agent" / "reagent"
    package_root = reagent_root / "src" / "reagent"
    src_root = reagent_root / "src"

    for candidate in (package_root, src_root, reagent_root):
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)

    try:
        from app.agents.llm_debug import install_crewai_llm_debug_logging
    except ImportError:
        from llm_debug import install_crewai_llm_debug_logging  # type: ignore

    install_crewai_llm_debug_logging()

    from util.runtime_env import load_runtime_env

    load_runtime_env(reagent_root)

    import util

    util.run_with_retry = _patched_run_with_retry

    import main as reagent_main

    reagent_main.main()


if __name__ == "__main__":
    main()
