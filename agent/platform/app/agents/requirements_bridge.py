from __future__ import annotations

import importlib.util
import io
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


class RequirementsAgentBridgeExecutionError(RuntimeError):
    """桥梁层异常，保留已收集的标准输出和标准错误，方便后端继续往上报。"""

    def __init__(self, message: str, *, stdout_text: str = "", stderr_text: str = "") -> None:
        super().__init__(message)
        self.stdout_text = stdout_text
        self.stderr_text = stderr_text


class _CapturingLineWriter(io.TextIOBase):
    """把 Agent 的标准输出按行拆开，方便后端实时显示状态。"""

    def __init__(
        self,
        *,
        chunks: list[str],
        on_line: Callable[[str], None] | None = None,
    ) -> None:
        self._chunks = chunks
        self._on_line = on_line
        self._buffer = ""

    def write(self, text: str | bytes) -> int:
        """
        接口注释：
        Requirements Agent 的底层依赖并不总是老老实实写 `str`，
        有些路径会把 `bytes` 直接塞进 stdout/stderr。
        这里统一转成文本，避免桥梁层在收尾拼接时再次炸掉。
        """
        if not text:
            return 0
        normalized_text = _normalize_stream_chunk(text)
        self._chunks.append(normalized_text)
        self._buffer += normalized_text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if self._on_line is not None:
                self._on_line(line)
        return len(normalized_text)

    def flush(self) -> None:
        if self._buffer and self._on_line is not None:
            self._on_line(self._buffer)
        self._buffer = ""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _normalize_stream_chunk(chunk: str | bytes | Any) -> str:
    """
    设计注释：
    需求 Agent 当前是多层桥接结构，最底层库既可能写文本，也可能写字节。
    后端如果在每个调用点都临时判断一次，很快又会散乱失控。
    所以这里集中做一次“流内容标准化”，把所有收集路径都压到同一规则上。
    """

    if isinstance(chunk, str):
        return chunk
    if isinstance(chunk, bytes):
        return chunk.decode("utf-8", errors="replace")
    return str(chunk)


def _join_stream_chunks(chunks: list[str | bytes | Any]) -> str:
    """
    教学注释：
    这里不是多余的二次防线。
    就算写入器已经做了标准化，历史数据或者别的调用方仍可能直接改动 `chunks`。
    收尾阶段再统一整理一次，可以把“最后一步又因为脏数据崩掉”的风险压下去。
    """

    return "".join(_normalize_stream_chunk(chunk) for chunk in chunks)


def _requirements_runtime_bridge_path() -> Path:
    return _repo_root() / "agent" / "Requirements Agent" / "reagent" / "src" / "reagent" / "runtime_bridge.py"


def _requirements_prompt_input_bridge_path() -> Path:
    return _repo_root() / "agent" / "Requirements Agent" / "reagent" / "util" / "prompt_input_bridge.py"


def load_requirements_agent_runtime_bridge() -> ModuleType:
    """按文件路径加载需求 Agent 的新函数桥梁。"""

    module_path = _requirements_runtime_bridge_path()
    if not module_path.exists():
        raise FileNotFoundError(f"Requirements Agent runtime bridge not found: {module_path}")

    module_name = "isoftdevagents_requirements_runtime_bridge"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load Requirements Agent runtime bridge: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_requirements_agent_prompt_input_bridge() -> ModuleType:
    """
    加载 Requirements Agent 的输入桥梁模块。

    平台侧也需要创建 InjectedPromptInputProvider，
    但 Requirements Agent 目录不在后端默认 import 路径里，
    所以这里继续走按文件路径加载的方式。
    """

    module_path = _requirements_prompt_input_bridge_path()
    if not module_path.exists():
        raise FileNotFoundError(f"Requirements Agent prompt input bridge not found: {module_path}")

    module_name = "isoftdevagents_requirements_prompt_input_bridge"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load Requirements Agent prompt input bridge: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_runtime_entrypoint(runtime_bridge: ModuleType, mode: str) -> Callable[..., dict[str, Any]]:
    """
    把 mode 映射到需求 Agent 的真实函数入口。

    这样桥梁层只保留一个分发点，后面如果再加 mode，
    也只需要改这里，而不是到处写 if/elif。
    """

    entrypoint_name_by_mode = {
        "analysis": "run_requirements_agent_analysis",
        "full": "run_requirements_agent_full",
    }
    if mode not in entrypoint_name_by_mode:
        raise ValueError(f"Unsupported Requirements Agent mode: {mode}")
    return getattr(runtime_bridge, entrypoint_name_by_mode[mode])


def run_requirements_agent(
    *,
    mode: str,
    project_name: str,
    description_text: str,
    output_root: str | Path,
    runtime_home: str | Path,
    tasks_config_path: str | Path | None,
    api_key: str,
    base_url: str,
    model: str,
    site_packages_dir: str | None = None,
    stdout_line_handler: Callable[[str], None] | None = None,
    stderr_line_handler: Callable[[str], None] | None = None,
    prompt_input_provider: Any = None,
    run_with_retry_override: Any = None,
    setup_logging: Callable[[], None] | None = None,
    task_id: str | None = None,
    srs_example_path: str | None = "util/doc_template/document_example.md",
    srs_template: str | None = None,
    data_path: str | None = None,
    usage_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """
    后端专用的需求 Agent 调用桥梁。

    这一层只做两件事：
    1. 加载需求 Agent 自己提供的函数入口
    2. 负责把标准输出和标准错误收集起来，继续交给后端现有的状态系统
    """

    runtime_bridge = load_requirements_agent_runtime_bridge()
    stdout_chunks: list[str | bytes] = []
    stderr_chunks: list[str | bytes] = []
    stdout_writer = _CapturingLineWriter(chunks=stdout_chunks, on_line=stdout_line_handler)
    stderr_writer = _CapturingLineWriter(chunks=stderr_chunks, on_line=stderr_line_handler)

    common_kwargs = {
        "project_name": project_name,
        "description_text": description_text,
        "runtime_home": runtime_home,
        "output_root": output_root,
        "tasks_config_path": tasks_config_path,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "site_packages_dir": site_packages_dir,
        "stdout_writer": stdout_writer,
        "stderr_writer": stderr_writer,
        "run_with_retry_override": run_with_retry_override,
        "prompt_input_provider": prompt_input_provider,
        "task_id": task_id,
        "usage_callback": usage_callback,
        "setup_logging": setup_logging,
        "cancel_event": cancel_event,
    }

    try:
        runtime_entrypoint = _resolve_runtime_entrypoint(runtime_bridge, mode)
        extra_kwargs: dict[str, Any] = {}
        if mode == "full":
            extra_kwargs = {
                "srs_example_path": srs_example_path,
                "srs_template": srs_template,
                "data_path": data_path,
            }
        result = runtime_entrypoint(**common_kwargs, **extra_kwargs)
    except Exception as exc:
        stdout_writer.flush()
        stderr_writer.flush()
        traceback_text = traceback.format_exc()
        stderr_text = _join_stream_chunks(stderr_chunks)
        if traceback_text.strip():
            if stderr_text and not stderr_text.endswith("\n"):
                stderr_text += "\n"
            stderr_text += traceback_text
        raise RequirementsAgentBridgeExecutionError(
            str(exc),
            stdout_text=_join_stream_chunks(stdout_chunks),
            stderr_text=stderr_text,
        ) from exc
    finally:
        stdout_writer.flush()
        stderr_writer.flush()

    payload = dict(result or {})
    payload.setdefault("output_root", str(output_root))
    payload.setdefault("tasks_config_path", str(tasks_config_path) if tasks_config_path else None)
    payload.setdefault("model", model)
    payload.setdefault("seededFiles", [])
    payload["stdout"] = _join_stream_chunks(stdout_chunks)
    payload["stderr"] = _join_stream_chunks(stderr_chunks)
    return payload
