from __future__ import annotations

import asyncio
import importlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import UTC, datetime
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any


class _CapturingLineWriter(io.TextIOBase):
    """把函数桥里的 stdout / stderr 按行切开，继续往后端状态流里传。"""

    def __init__(self, *, chunks: list[str], on_line: Any = None) -> None:
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


_PROCESS_RUNTIME_LOCK = threading.Lock()

_NONINTERACTIVE_OBSERVABILITY_ENV = {
    "CREWAI_TRACING_ENABLED": "false",
    "OTEL_SDK_DISABLED": "true",
    "CREWAI_DISABLE_TELEMETRY": "true",
    "CREWAI_DISABLE_TRACKING": "true",
    # 原因注释：
    # CrewAI 1.6.x 在子进程里因为 HOME 是临时目录，每次都认为是 "first execution"，
    # 会弹出交互式 tracing 提示并等待 20 秒。设置 CREWAI_TESTING=true 跳过该提示。
    "CREWAI_TESTING": "true",
}
_NONINTERACTIVE_STDIN_TEXT = "n\n" * 8
_PROCESS_RUNTIME_POLL_SECONDS = 2.0


class UIAgentRuntimeError(RuntimeError):
    """
    UI Agent 运行失败时使用的统一异常。

    接口注释：
    orchestrator 只需要抓这个异常，就能知道：
    - 失败属于哪个阶段
    - 是哪一类错误
    - 当前已经落盘了哪些部分文件
    - stdout / stderr 有没有线索
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        stage: str,
        stdout_text: str = "",
        stderr_text: str = "",
        output_root: str | None = None,
        partial_files: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.stage = stage
        self.stdout_text = stdout_text
        self.stderr_text = stderr_text
        self.output_root = output_root
        self.partial_files = list(partial_files or [])


def _architecture_runtime_module_path(architecture_root: str | Path) -> Path:
    root = Path(architecture_root)
    return root / "src" / "arch_agent" / "main.py"


def _find_architecture_site_packages_dir(architecture_root: str | Path) -> str | None:
    root = Path(architecture_root)
    lib_root = root / ".venv" / "lib"
    if not lib_root.exists():
        return None
    for candidate in sorted(lib_root.glob("python*/site-packages")):
        if candidate.exists():
            return str(candidate)
    return None


def load_architecture_agent_runtime_module(architecture_root: str | Path) -> ModuleType:
    """
    按文件路径加载 Architecture Agent 的真实函数入口。

    这里专门走文件加载，而不是普通 import，
    因为我们要明确控制导入路径，避免后端环境里找错模块。
    """

    module_path = _architecture_runtime_module_path(architecture_root)
    if not module_path.exists():
        raise FileNotFoundError(f"Architecture Agent runtime module not found: {module_path}")

    module_name = "isoftdevagents_architecture_runtime_bridge"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load Architecture Agent runtime module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _find_newest_architecture_output_dir(
    *,
    output_root: Path,
    before: set[Path],
    project_name: str,
) -> Path | None:
    candidates = [path.resolve() for path in output_root.iterdir() if path.is_dir()]
    if not candidates:
        return None
    fresh = [path for path in candidates if path not in before]
    if fresh:
        return max(fresh, key=lambda path: path.stat().st_mtime)
    matching = [path for path in candidates if path.name.endswith(f"_{project_name}")]
    if matching:
        return max(matching, key=lambda path: path.stat().st_mtime)
    return None


def _architecture_agent_runner_script() -> str:
    """
    在 Architecture Agent 自己的 Python 解释器里执行真实函数入口。

    这里不用 `main.py` 命令行入口，而是明确加载模块后调用
    `run_architecture_agent(...)` 函数，继续遵守“桥梁层走函数入口”的设计。
    """

    return """
import importlib.util
import json
import os
import sys
from pathlib import Path

module_path = Path(sys.argv[1])
source_root = sys.argv[2]
requirements_path = sys.argv[3]
project_name = sys.argv[4]
result_path = Path(sys.argv[5])

if source_root:
    sys.path.insert(0, source_root)

# 安装 LLM debug logging + CrewAI usage tracking patch
# 原因：Architecture Agent 使用 CrewAI，如果不 patch _track_token_usage_internal，
# crew.calculate_usage_metrics() / _token_process.get_summary() 会返回全零。
platform_root = str(Path(module_path).resolve().parents[3] / "platform")
if platform_root not in sys.path:
    sys.path.insert(0, platform_root)
try:
    from app.agents.llm_debug import install_crewai_llm_debug_logging
    install_crewai_llm_debug_logging()
    print("[ArchAgent subprocess] LLM debug logging installed", flush=True)
except Exception as e:
    print(f"[ArchAgent subprocess] LLM debug logging skipped: {e}", flush=True)

spec = importlib.util.spec_from_file_location("isoftdevagents_architecture_runtime_bridge_subprocess", module_path)
if spec is None or spec.loader is None:
    raise ImportError(f"Unable to load Architecture Agent runtime module: {module_path}")

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = module.run_architecture_agent(
    requirements_path=requirements_path,
    project_name=project_name,
) or {}
result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
""".strip()


def _code_agent_runner_script() -> str:
    """
    在 Code Agent 自己的 Python 解释器里执行真实代码生成入口。

    原因注释：
    Code Agent 的依赖里包含 `numpy` 这类带二进制扩展的包。
    如果继续把它的 site-packages 塞进平台自己的 Python 进程，
    很容易出现“3.11 编出来的扩展，被 3.12 解释器加载”的崩溃。
    所以这里改成和架构 Agent 一样，明确用它自己的 `.venv/bin/python` 单独运行。
    """

    return """
import importlib.util
import json
import os
import sys
from pathlib import Path

module_path = Path(sys.argv[1])
source_root = sys.argv[2]
project_path = sys.argv[3]
semantic_model_path = sys.argv[4]
srs_path = sys.argv[5]
architecture_path = sys.argv[6]
api_spec_path = sys.argv[7]
memory_path = sys.argv[8]
output_root = Path(sys.argv[9])
result_path = Path(sys.argv[10])

if source_root:
    sys.path.insert(0, source_root)

# 安装 CrewAI usage tracking patch
platform_root = str(Path(module_path).resolve().parents[3] / "platform")
if platform_root not in sys.path:
    sys.path.insert(0, platform_root)
try:
    from app.agents.llm_debug import install_crewai_llm_debug_logging
    install_crewai_llm_debug_logging()
except Exception:
    pass

spec = importlib.util.spec_from_file_location("isoftdevagents_coding_runtime_bridge_subprocess", module_path)
if spec is None or spec.loader is None:
    raise ImportError(f"Unable to load Code Agent runtime module: {module_path}")

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
app = module.CodeAgentApp(
    paths={
        "project": project_path,
        "semantic_model": semantic_model_path,
        "memory": memory_path,
        "software": str(output_root),
        "srs": srs_path,
        "av": architecture_path,
        "add": api_spec_path,
    }
)
app.run(mode="full")

files = []
if output_root.exists():
    for path in sorted(output_root.rglob("*")):
        if not path.is_file():
            continue
        files.append(
            {
                "filePath": path.relative_to(output_root).as_posix(),
                "content": path.read_text(encoding="utf-8"),
            }
        )

usage = None
token_process = getattr(getattr(app, "codegen_agent", None), "_token_process", None)
if token_process is not None and hasattr(token_process, "get_summary"):
    summary = token_process.get_summary()
    input_tokens = int(getattr(summary, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(summary, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(summary, "total_tokens", 0) or 0)
    if total_tokens <= 0 and (input_tokens > 0 or output_tokens > 0):
        total_tokens = input_tokens + output_tokens
    if total_tokens > 0 or input_tokens > 0 or output_tokens > 0:
        usage = {
            "model": str(getattr(getattr(app, "codegen_agent", None), "llm", None).model) if getattr(getattr(app, "codegen_agent", None), "llm", None) is not None else "",
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": total_tokens,
        }

result_path.write_text(
    json.dumps(
        {
            "files": files,
            "usage": usage,
            "output_root": str(output_root),
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
""".strip()


def _run_streaming_subprocess(
    *,
    command: list[str],
    cwd: str | Path,
    env: dict[str, str],
    stdout_writer: _CapturingLineWriter,
    stderr_writer: _CapturingLineWriter,
    timeout: float | None = None,
    heartbeat_callback: Any = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """
    用子进程运行真实 Agent，同时把 stdout / stderr 按行继续推回后端。

    这里单独抽出来，是为了让桥梁层逻辑更清楚，也方便后续别的 Agent 复用。
    支持通过 cancel_event 取消正在运行的进程。
    """

    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    started_at = datetime.now(UTC)
    output_state = {
        "last_output_at": started_at,
        "stdout_line_count": 0,
        "stderr_line_count": 0,
    }
    output_state_lock = threading.Lock()

    def forward(pipe: Any, writer: _CapturingLineWriter) -> None:
        if pipe is None:
            return
        try:
            for line in iter(pipe.readline, ""):
                with output_state_lock:
                    output_state["last_output_at"] = datetime.now(UTC)
                    if writer is stdout_writer:
                        output_state["stdout_line_count"] += 1
                    else:
                        output_state["stderr_line_count"] += 1
                writer.write(line)
        finally:
            pipe.close()

    stdout_thread = threading.Thread(target=forward, args=(process.stdout, stdout_writer), daemon=True)
    stderr_thread = threading.Thread(target=forward, args=(process.stderr, stderr_writer), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    wait_started = datetime.now(UTC)
    heartbeat_interval_seconds = min(_PROCESS_RUNTIME_POLL_SECONDS, timeout) if timeout is not None else _PROCESS_RUNTIME_POLL_SECONDS
    if heartbeat_interval_seconds <= 0:
        heartbeat_interval_seconds = _PROCESS_RUNTIME_POLL_SECONDS

    def emit_heartbeat() -> None:
        if heartbeat_callback is None:
            return
        now = datetime.now(UTC)
        with output_state_lock:
            last_output_at = output_state["last_output_at"]
            stdout_line_count = int(output_state["stdout_line_count"])
            stderr_line_count = int(output_state["stderr_line_count"])
        heartbeat_callback(
            {
                "runtimePid": process.pid,
                "runtimeState": "running" if process.poll() is None else "exited",
                "startedAt": started_at.isoformat(),
                "lastHeartbeatAt": now.isoformat(),
                "lastOutputAt": last_output_at.isoformat(),
                "stdoutLineCount": stdout_line_count,
                "stderrLineCount": stderr_line_count,
                "secondsSinceLastOutput": max(0, int((now - last_output_at).total_seconds())),
                "elapsedSeconds": max(0, int((now - wait_started).total_seconds())),
            }
        )

    try:
        cancelled = False
        while True:
            try:
                return_code = process.wait(timeout=heartbeat_interval_seconds)
                break
            except subprocess.TimeoutExpired:
                emit_heartbeat()
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    process.terminate()
                    try:
                        process.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    break
                if timeout is None:
                    continue
                elapsed_seconds = (datetime.now(UTC) - wait_started).total_seconds()
                if elapsed_seconds < timeout:
                    continue
                process.kill()
                stdout_thread.join()
                stderr_thread.join()
                stdout_writer.flush()
                stderr_writer.flush()
                raise subprocess.TimeoutExpired(
                    cmd=command,
                    timeout=timeout,
                    output="".join(stdout_writer._chunks),
                    stderr="".join(stderr_writer._chunks),
                )
    except subprocess.TimeoutExpired as exc:
        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=timeout if timeout is not None else exc.timeout,
            output="".join(stdout_writer._chunks),
            stderr="".join(stderr_writer._chunks),
        ) from exc

    stdout_thread.join()
    stderr_thread.join()
    stdout_writer.flush()
    stderr_writer.flush()
    emit_heartbeat()

    if cancelled:
        raise asyncio.CancelledError(f"Task cancelled via cancel_event")

    if return_code != 0:
        raise subprocess.CalledProcessError(
            returncode=return_code,
            cmd=command,
            output="".join(stdout_writer._chunks),
            stderr="".join(stderr_writer._chunks),
        )


def _read_json_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _noninteractive_observability_env() -> dict[str, str]:
    """
    统一返回非交互运行时的观测配置。

    接口注释：
    平台接管 Agent 以后，不应该再让子 Agent 自己去打开 tracing、
    遥测导出或者命令行确认流程。
    这里把这些环境变量集中起来，后续所有 Agent 共用同一套默认值。
    """

    return dict(_NONINTERACTIVE_OBSERVABILITY_ENV)


def _read_output_files(output_root: Path) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    if not output_root.exists():
        return files
    for path in sorted(output_root.rglob("*")):
        if not path.is_file():
            continue
        files.append(
            {
                "filePath": path.relative_to(output_root).as_posix(),
                "content": path.read_text(encoding="utf-8"),
            }
        )
    return files


def _latest_output_file_snapshot(output_dir: Path | None) -> dict[str, Any]:
    """
    返回当前输出目录里最近一次被写入的文件快照。

    教学注释：
    架构 Agent 很多阶段只会往输出目录写文件，不一定会继续打印 stdout。
    所以平台不能只盯着终端输出，还要看目录里最近被修改的文件是谁。
    """

    if output_dir is None or not output_dir.exists():
        return {}

    files = [path for path in output_dir.rglob("*") if path.is_file()]
    if not files:
        return {
            "outputDir": str(output_dir),
            "outputFileCount": 0,
        }

    latest_file = max(files, key=lambda path: path.stat().st_mtime)
    return {
        "outputDir": str(output_dir),
        "outputFileCount": len(files),
        "latestOutputFile": latest_file.relative_to(output_dir).as_posix(),
        "latestOutputAt": datetime.fromtimestamp(latest_file.stat().st_mtime, tz=UTC).isoformat(),
    }


def _latest_named_output_snapshot(output_dirs: list[tuple[str, Path | None]]) -> dict[str, Any]:
    """
    接口注释：
    把多个输出目录合并成一个“最近文件快照”。

    设计注释：
    Test Agent 的有效产物分散在 `output/` 和 `memory/` 两个目录里。
    如果只盯一个目录，前端就会经常显示 `Recent file: None`，
    明明 `memory/test_plan.json` 已经写出来了，却像完全没动静一样。
    """

    latest_path: Path | None = None
    latest_prefix = ""
    latest_mtime = 0.0
    output_file_count = 0
    output_dirs_present: list[str] = []

    for prefix, output_dir in output_dirs:
        if output_dir is None or not output_dir.exists():
            continue
        output_dirs_present.append(str(output_dir))
        files = [path for path in output_dir.rglob("*") if path.is_file()]
        output_file_count += len(files)
        for path in files:
            mtime = path.stat().st_mtime
            if latest_path is None or mtime >= latest_mtime:
                latest_path = path
                latest_prefix = prefix
                latest_mtime = mtime

    if latest_path is None:
        return {
            "outputDir": ", ".join(output_dirs_present),
            "outputFileCount": output_file_count,
        }

    latest_output_file = latest_path.name
    if latest_prefix:
        latest_output_file = f"{latest_prefix}/{latest_path.name}"

    return {
        "outputDir": ", ".join(output_dirs_present),
        "outputFileCount": output_file_count,
        "latestOutputFile": latest_output_file,
        "latestOutputAt": datetime.fromtimestamp(latest_mtime, tz=UTC).isoformat(),
    }


def _code_agent_runtime_module_path(code_agent_root: str | Path) -> Path:
    root = Path(code_agent_root)
    return root / "app.py"


def _ui_agent_runtime_module_path(ui_agent_root: str | Path) -> Path:
    root = Path(ui_agent_root)
    return root / "ui_runtime_bridge.py"


def _test_agent_runtime_module_path(test_agent_root: str | Path) -> Path:
    root = Path(test_agent_root)
    return root / "agent.py"


def _find_code_agent_site_packages_dir(code_agent_root: str | Path) -> str | None:
    root = Path(code_agent_root).parent
    lib_root = root / ".venv" / "lib"
    if not lib_root.exists():
        return None
    for candidate in sorted(lib_root.glob("python*/site-packages")):
        if candidate.exists():
            return str(candidate)
    return None


def _find_ui_agent_site_packages_dir(ui_agent_root: str | Path) -> str | None:
    root = Path(ui_agent_root)
    lib_root = root / ".venv" / "lib"
    if not lib_root.exists():
        return None
    for candidate in sorted(lib_root.glob("python*/site-packages")):
        if candidate.exists():
            return str(candidate)
    return None


def _find_test_agent_site_packages_dir(test_agent_root: str | Path) -> str | None:
    root = Path(test_agent_root)
    lib_root = root / ".venv" / "lib"
    if not lib_root.exists():
        return None
    for candidate in sorted(lib_root.glob("python*/site-packages")):
        if candidate.exists():
            return str(candidate)
    return None


def _snapshot_modules(prefixes: tuple[str, ...]) -> dict[str, ModuleType]:
    saved: dict[str, ModuleType] = {}
    for name, module in list(sys.modules.items()):
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes):
            if isinstance(module, ModuleType):
                saved[name] = module
    return saved


def _clear_modules(prefixes: tuple[str, ...]) -> None:
    for name in list(sys.modules.keys()):
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes):
            sys.modules.pop(name, None)


def _restore_modules(prefixes: tuple[str, ...], saved: dict[str, ModuleType]) -> None:
    _clear_modules(prefixes)
    sys.modules.update(saved)


def _read_usage_payload_if_exists(path: str | Path) -> dict[str, Any] | None:
    usage_path = Path(path)
    if not usage_path.exists():
        return None
    try:
        payload = json.loads(usage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _token_process_usage_payload(token_process: Any, *, model: str) -> dict[str, Any] | None:
    if token_process is None or not hasattr(token_process, "get_summary"):
        return None
    summary = token_process.get_summary()
    input_tokens = int(getattr(summary, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(summary, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(summary, "total_tokens", 0) or 0)
    if total_tokens <= 0 and (input_tokens > 0 or output_tokens > 0):
        total_tokens = input_tokens + output_tokens
    if total_tokens <= 0 and input_tokens <= 0 and output_tokens <= 0:
        return None
    return {
        "model": model,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
    }


def load_code_agent_runtime_module(code_agent_root: str | Path) -> ModuleType:
    module_path = _code_agent_runtime_module_path(code_agent_root)
    if not module_path.exists():
        raise FileNotFoundError(f"Code Agent runtime module not found: {module_path}")

    module_name = "isoftdevagents_coding_runtime_app"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load Code Agent runtime module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_ui_agent_runtime_module(ui_agent_root: str | Path) -> ModuleType:
    module_path = _ui_agent_runtime_module_path(ui_agent_root)
    if not module_path.exists():
        raise FileNotFoundError(f"UI Agent runtime module not found: {module_path}")

    module_name = "isoftdevagents_ui_runtime_bridge"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load UI Agent runtime module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_test_agent_runtime_module(test_agent_root: str | Path) -> ModuleType:
    module_path = _test_agent_runtime_module_path(test_agent_root)
    if not module_path.exists():
        raise FileNotFoundError(f"Test Agent runtime module not found: {module_path}")

    module_name = "isoftdevagents_test_runtime_bridge"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load Test Agent runtime module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _requirements_agent_runner_script() -> str:
    """
    在 Requirements Agent 自己的 Python 解释器里执行真实函数入口。

    原因注释：
    Requirements Agent 的 _prepared_runtime 会修改 os.environ、sys.modules、
    os.chdir 等进程级全局状态。多项目并发运行时互相覆盖导致间歇性失败。
    改成独立子进程后，每个任务拥有隔离的环境，彻底消除共享状态问题。
    """

    return """
import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path

print("[ReqAgent subprocess] Starting...", flush=True)

runtime_bridge_path = Path(sys.argv[1])
source_root = sys.argv[2]
package_root = sys.argv[3]
reagent_root = sys.argv[4]
args_json_path = Path(sys.argv[5])
result_json_path = Path(sys.argv[6])

for p in (package_root, source_root, reagent_root):
    if p and p not in sys.path:
        sys.path.insert(0, p)

# 安装 LLM debug logging（如果平台可用）
# runtime_bridge_path = .../agent/Requirements Agent/reagent/src/reagent/runtime_bridge.py
# parents[4] = .../agent, 所以 platform 在 parents[4] / "platform"
platform_root = str(Path(runtime_bridge_path).resolve().parents[4] / "platform")
if platform_root not in sys.path:
    sys.path.insert(0, platform_root)
try:
    from app.agents.llm_debug import install_crewai_llm_debug_logging
    install_crewai_llm_debug_logging()
    print("[ReqAgent subprocess] LLM debug logging installed", flush=True)
except Exception as e:
    print(f"[ReqAgent subprocess] LLM debug logging skipped: {e}", flush=True)

# 安装 _patched_run_with_retry
try:
    from app.agents.reagent_adapter import _patched_run_with_retry
    run_with_retry_override = _patched_run_with_retry
    print("[ReqAgent subprocess] reagent_adapter loaded", flush=True)
except Exception as e:
    run_with_retry_override = None
    print(f"[ReqAgent subprocess] reagent_adapter skipped: {e}", flush=True)

print(f"[ReqAgent subprocess] Loading runtime bridge: {runtime_bridge_path}", flush=True)
spec = importlib.util.spec_from_file_location(
    "isoftdevagents_requirements_runtime_bridge_subprocess",
    runtime_bridge_path,
)
if spec is None or spec.loader is None:
    raise ImportError(f"Unable to load Requirements Agent runtime bridge: {runtime_bridge_path}")

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print("[ReqAgent subprocess] Runtime bridge loaded", flush=True)

args = json.loads(args_json_path.read_text(encoding="utf-8"))
mode = args["mode"]
print(f"[ReqAgent subprocess] mode={mode} project={args['project_name']} model={os.environ.get('OPENAI_MODEL','?')}", flush=True)

common_kwargs = {
    "project_name": args["project_name"],
    "description_text": args["description_text"],
    "runtime_home": args["runtime_home"],
    "output_root": args["output_root"],
    "tasks_config_path": args.get("tasks_config_path"),
    "api_key": os.environ.get("OPENAI_API_KEY", ""),
    "base_url": os.environ.get("OPENAI_BASE_URL", ""),
    "model": os.environ.get("OPENAI_MODEL", ""),
    "site_packages_dir": args.get("site_packages_dir"),
    "run_with_retry_override": run_with_retry_override,
}

try:
    if mode == "analysis":
        print("[ReqAgent subprocess] Calling run_requirements_agent_analysis...", flush=True)
        result = module.run_requirements_agent_analysis(**common_kwargs) or {}
    elif mode == "full":
        extra_kwargs = {
            "srs_example_path": args.get("srs_example_path"),
            "srs_template": args.get("srs_template"),
            "data_path": args.get("data_path"),
        }
        print("[ReqAgent subprocess] Calling run_requirements_agent_full...", flush=True)
        result = module.run_requirements_agent_full(**common_kwargs, **extra_kwargs) or {}
    else:
        raise ValueError(f"Unsupported mode: {mode}")
    print(f"[ReqAgent subprocess] Completed. Result keys: {list(result.keys())}", flush=True)
except Exception as e:
    print(f"[ReqAgent subprocess] FAILED: {e}", flush=True)
    traceback.print_exc()
    raise

result_json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("[ReqAgent subprocess] Result written. Exiting.", flush=True)
""".strip()


def _requirements_runtime_bridge_module_path(agent_root: Path) -> Path:
    return agent_root / "Requirements Agent" / "reagent" / "src" / "reagent" / "runtime_bridge.py"


class RequirementsAgentEntry:
    """
    Requirements Agent 统一桥梁入口。

    原因注释：
    改为 subprocess 执行，和 Architecture Agent / Code Agent 模式对齐。
    每个 Requirements Agent 任务运行在独立子进程中，拥有隔离的环境变量、
    模块缓存和工作目录，彻底消除多项目并发时的共享状态问题。
    """

    def run(
        self,
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
        agent_root: str | Path,
        python_bin: str,
        site_packages_dir: str | None = None,
        timeout: float | None = None,
        stdout_line_handler: Any = None,
        stderr_line_handler: Any = None,
        usage_callback: Any = None,
        runtime_event_callback: Any = None,
        cancel_event: Any = None,
        srs_example_path: str | None = None,
        srs_template: str | None = None,
        data_path: str | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        agent_root_path = Path(agent_root)
        runtime_home_path = Path(runtime_home)
        output_root_path = Path(output_root)
        runtime_home_path.mkdir(parents=True, exist_ok=True)
        (runtime_home_path / "crewai-storage").mkdir(parents=True, exist_ok=True)
        output_root_path.mkdir(parents=True, exist_ok=True)

        reagent_root = agent_root_path / "Requirements Agent" / "reagent"
        source_root = reagent_root / "src"
        package_root = source_root / "reagent"
        runtime_bridge_path = _requirements_runtime_bridge_module_path(agent_root_path)

        usage_output_path = runtime_home_path / "requirements-agent.usage.json"
        result_output_path = runtime_home_path / "requirements-agent.result.json"
        args_json_path = runtime_home_path / "requirements-agent.args.json"
        usage_output_path.unlink(missing_ok=True)
        result_output_path.unlink(missing_ok=True)

        args_payload = {
            "mode": mode,
            "project_name": project_name,
            "description_text": description_text,
            "output_root": str(output_root_path),
            "runtime_home": str(runtime_home_path),
            "tasks_config_path": str(tasks_config_path) if tasks_config_path else None,
            "site_packages_dir": site_packages_dir,
            "srs_example_path": srs_example_path,
            "srs_template": srs_template,
            "data_path": data_path,
        }
        args_json_path.write_text(json.dumps(args_payload, ensure_ascii=False), encoding="utf-8")

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        req_last_usage_mtime = {"value": 0.0}

        def tracked_stdout_line(line: str) -> None:
            if stdout_line_handler is not None:
                stdout_line_handler(line)
            # 和 Architecture Agent 对齐：每收到一行 stdout 时检查 usage 文件
            # 是否有更新，有就立即回调，让前端实时显示 token 消耗。
            if usage_callback is not None and usage_output_path.exists():
                try:
                    mtime = usage_output_path.stat().st_mtime
                except OSError:
                    return
                if mtime > req_last_usage_mtime["value"]:
                    req_last_usage_mtime["value"] = mtime
                    payload = _read_usage_payload_if_exists(usage_output_path)
                    if payload is not None:
                        usage_callback(payload)

        stdout_writer = _CapturingLineWriter(chunks=stdout_chunks, on_line=tracked_stdout_line)
        stderr_writer = _CapturingLineWriter(chunks=stderr_chunks, on_line=stderr_line_handler)

        def tracked_runtime_event(payload: dict[str, Any]) -> None:
            if runtime_event_callback is None:
                return
            runtime_event_callback(payload)

        platform_root = Path(__file__).resolve().parents[2]
        python_path_entries = [str(source_root), str(package_root), str(reagent_root), str(platform_root)]
        if site_packages_dir:
            python_path_entries.append(site_packages_dir)

        env_overrides: dict[str, str] = {
            **_noninteractive_observability_env(),
            "HOME": str(runtime_home_path),
            "CREWAI_STORAGE_DIR": str(runtime_home_path / "crewai-storage"),
            "REAGENT_STORE_PATH": str(output_root_path),
            "ISOFTDEVAGENTS_REAGENT_NONINTERACTIVE": "1",
            "ISOFTDEVAGENTS_REAGENT_ENABLE_WEB_TOOLS": "0",
            "OPENAI_API_KEY": api_key,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_MODEL": model,
            "ISOFTDEVAGENTS_LLM_API_KEY": api_key,
            "ISOFTDEVAGENTS_LLM_BASE_URL": base_url,
            "ISOFTDEVAGENTS_LLM_MODEL": model,
            "ISOFTDEVAGENTS_USAGE_OUTPUT": str(usage_output_path),
        }
        if tasks_config_path:
            env_overrides["ISOFTDEVAGENTS_REAGENT_TASKS_CONFIG"] = str(tasks_config_path)

        # 继承 LLM debug 相关的环境变量，确保子进程也能写调试日志
        for key in (
            "ISOFTDEVAGENTS_AGENT_DEBUG_LLM_IO",
            "ISOFTDEVAGENTS_AGENT_DEBUG_LLM_LOG_TO_FILE",
            "ISOFTDEVAGENTS_AGENT_DEBUG_LLM_LOG_FILE",
            "ISOFTDEVAGENTS_AGENT_DEBUG_LLM_INPUT_LIMIT",
            "ISOFTDEVAGENTS_AGENT_DEBUG_LLM_OUTPUT_LIMIT",
            "ISOFTDEVAGENTS_AGENT_DEBUG_LLM_LOG_TO_CONSOLE",
            "SERPER_API_KEY",
        ):
            value = os.environ.get(key)
            if value is not None:
                env_overrides[key] = value

        child_env = os.environ.copy()
        child_env.update({k: v for k, v in env_overrides.items() if v})
        if python_path_entries:
            child_env["PYTHONPATH"] = os.pathsep.join(
                [*python_path_entries, child_env.get("PYTHONPATH", "")]
            ).strip(os.pathsep)

        command = [
            python_bin,
            "-c",
            _requirements_agent_runner_script(),
            str(runtime_bridge_path),
            str(source_root),
            str(package_root),
            str(reagent_root),
            str(args_json_path),
            str(result_output_path),
        ]

        try:
            _run_streaming_subprocess(
                command=command,
                cwd=reagent_root,
                env=child_env,
                stdout_writer=stdout_writer,
                stderr_writer=stderr_writer,
                timeout=timeout,
                heartbeat_callback=tracked_runtime_event,
                cancel_event=cancel_event,
            )
        finally:
            stdout_writer.flush()
            stderr_writer.flush()
            args_json_path.unlink(missing_ok=True)

        payload = _read_json_payload(result_output_path)
        if usage_callback is not None and usage_output_path.exists():
            try:
                final_mtime = usage_output_path.stat().st_mtime
            except OSError:
                final_mtime = 0.0
            if final_mtime > req_last_usage_mtime["value"]:
                final_usage_payload = _read_usage_payload_if_exists(usage_output_path)
                if final_usage_payload is not None:
                    usage_callback(final_usage_payload)

        payload.setdefault("output_root", str(output_root_path))
        payload.setdefault("tasks_config_path", str(tasks_config_path) if tasks_config_path else None)
        payload.setdefault("model", model)
        payload.setdefault("seededFiles", [])
        payload["stdout"] = "".join(stdout_chunks)
        payload["stderr"] = "".join(stderr_chunks)
        return payload


class ArchitectureAgentEntry:
    """
    Architecture Agent 统一桥梁入口。

    这里直接接 Architecture Agent 自己提供的 `run_architecture_agent(...)` 函数，
    不再让 orchestrator 自己拼 subprocess 命令。
    """

    def run(
        self,
        *,
        architecture_root: str | Path,
        requirement_document: str,
        project_name: str,
        runtime_home: str | Path,
        python_bin: str,
        python_path_entries: list[str] | None = None,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float | None = None,
        stdout_line_handler: Any = None,
        stderr_line_handler: Any = None,
        usage_callback: Any = None,
        runtime_event_callback: Any = None,
        cancel_event: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        architecture_root_path = Path(architecture_root)
        runtime_home_path = Path(runtime_home)
        runtime_home_path.mkdir(parents=True, exist_ok=True)
        output_root = architecture_root_path / "data" / "output"
        output_root.mkdir(parents=True, exist_ok=True)
        before = {path.resolve() for path in output_root.iterdir() if path.is_dir()}
        usage_output_path = runtime_home_path / "architecture-agent.usage.json"
        result_output_path = runtime_home_path / "architecture-agent.result.json"
        usage_output_path.unlink(missing_ok=True)
        result_output_path.unlink(missing_ok=True)

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        arch_last_usage_mtime = {"value": 0.0}

        def tracked_stdout_line(line: str) -> None:
            if stdout_line_handler is not None:
                stdout_line_handler(line)
            if usage_callback is not None and usage_output_path.exists():
                try:
                    mtime = usage_output_path.stat().st_mtime
                except OSError:
                    return
                if mtime > arch_last_usage_mtime["value"]:
                    arch_last_usage_mtime["value"] = mtime
                    payload = _read_usage_payload_if_exists(usage_output_path)
                    if payload is not None:
                        usage_callback(payload)

        stdout_writer = _CapturingLineWriter(chunks=stdout_chunks, on_line=tracked_stdout_line)
        stderr_writer = _CapturingLineWriter(chunks=stderr_chunks, on_line=stderr_line_handler)

        def tracked_runtime_event(payload: dict[str, Any]) -> None:
            if runtime_event_callback is None:
                return
            output_dir = _find_newest_architecture_output_dir(
                output_root=output_root,
                before=before,
                project_name=project_name,
            )
            runtime_event_callback(
                {
                    **payload,
                    **_latest_output_file_snapshot(output_dir),
                }
            )

        python_path = [str(architecture_root_path / "src"), *list(python_path_entries or [])]

        env_overrides = {
            **_noninteractive_observability_env(),
            "MODEL": model,
            "BASE_URL": base_url,
            "OPENAI_API_KEY": api_key,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_MODEL": model,
            "ISOFTDEVAGENTS_LLM_API_KEY": api_key,
            "ISOFTDEVAGENTS_LLM_BASE_URL": base_url,
            "ISOFTDEVAGENTS_LLM_MODEL": model,
            "ISOFTDEVAGENTS_USAGE_OUTPUT": str(usage_output_path),
            "HOME": str(runtime_home_path),
            "CREWAI_STORAGE_DIR": str(runtime_home_path / "crewai-storage"),
        }

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
            handle.write(requirement_document)
            requirement_path = Path(handle.name)

        try:
            with _PROCESS_RUNTIME_LOCK:
                child_env = os.environ.copy()
                child_env.update({key: value for key, value in env_overrides.items() if value})
                if python_path:
                    child_env["PYTHONPATH"] = os.pathsep.join([*python_path, child_env.get("PYTHONPATH", "")]).strip(os.pathsep)
                command = [
                    python_bin,
                    "-c",
                    _architecture_agent_runner_script(),
                    str(_architecture_runtime_module_path(architecture_root_path)),
                    str(architecture_root_path / "src"),
                    str(requirement_path),
                    project_name,
                    str(result_output_path),
                ]
                _run_streaming_subprocess(
                    command=command,
                    cwd=architecture_root_path,
                    env=child_env,
                    stdout_writer=stdout_writer,
                    stderr_writer=stderr_writer,
                    timeout=timeout,
                    heartbeat_callback=tracked_runtime_event,
                    cancel_event=cancel_event,
                )
        finally:
            requirement_path.unlink(missing_ok=True)
            stdout_writer.flush()
            stderr_writer.flush()

        output_dir = _find_newest_architecture_output_dir(
            output_root=output_root,
            before=before,
            project_name=project_name,
        )
        payload = _read_json_payload(result_output_path)
        # 最终 usage: 优先从 usage 文件读（实时轮询可能已经读过一部分），
        # 如果文件不存在或没更新，从 result JSON 的 usage 字段 fallback。
        final_usage_reported = False
        if usage_callback is not None and usage_output_path.exists():
            try:
                final_mtime = usage_output_path.stat().st_mtime
            except OSError:
                final_mtime = 0.0
            if final_mtime > arch_last_usage_mtime["value"]:
                final_usage_payload = _read_usage_payload_if_exists(usage_output_path)
                if final_usage_payload is not None:
                    usage_callback(final_usage_payload)
                    final_usage_reported = True
        if not final_usage_reported and usage_callback is not None:
            result_usage = payload.get("usage") if isinstance(payload, dict) else None
            if isinstance(result_usage, dict) and int(result_usage.get("totalTokens") or 0) > 0:
                usage_callback(result_usage)
        payload["output_dir"] = str(output_dir) if output_dir is not None else None
        payload["usage_output_path"] = str(usage_output_path)
        payload["stdout"] = "".join(stdout_chunks)
        payload["stderr"] = "".join(stderr_chunks)
        return payload


class CodeAgentEntry:
    """
    Code Agent 统一桥梁入口。

    这里直接运行 CodeAgentApp，不再让 orchestrator 先造一层假代码 scaffold。
    后端只准备真实输入文件，然后把结果完整接回平台。
    """

    def run(
        self,
        *,
        code_agent_root: str | Path,
        runtime_home: str | Path,
        python_bin: str | None = None,
        project_manifest: dict[str, Any],
        semantic_model: dict[str, Any],
        srs_text: str,
        architecture_text: str,
        api_spec_text: str,
        output_root: str | Path,
        api_key: str,
        base_url: str,
        model: str,
        stdout_line_handler: Any = None,
        stderr_line_handler: Any = None,
        usage_callback: Any = None,
        runtime_event_callback: Any = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        code_agent_root_path = Path(code_agent_root)
        runtime_home_path = Path(runtime_home)
        runtime_home_path.mkdir(parents=True, exist_ok=True)
        output_root_path = Path(output_root)
        output_root_path.mkdir(parents=True, exist_ok=True)

        manifest_path = runtime_home_path / "project_manifest.json"
        semantic_model_path = runtime_home_path / "semantic_model.json"
        srs_path = runtime_home_path / "srs.md"
        architecture_path = runtime_home_path / "architecture.md"
        api_spec_path = runtime_home_path / "api_spec.yaml"
        memory_path = runtime_home_path / "working_memory.json"

        manifest_path.write_text(json.dumps(project_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        semantic_model_path.write_text(json.dumps(semantic_model, ensure_ascii=False, indent=2), encoding="utf-8")
        srs_path.write_text(srs_text, encoding="utf-8")
        architecture_path.write_text(architecture_text, encoding="utf-8")
        api_spec_path.write_text(api_spec_text, encoding="utf-8")

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        runtime_app_holder: dict[str, Any] = {}
        result_output_path = runtime_home_path / "code-agent.result.json"
        result_output_path.unlink(missing_ok=True)

        def emit_usage_snapshot() -> None:
            if usage_callback is None:
                return
            runtime_app = runtime_app_holder.get("app")
            token_process = getattr(getattr(runtime_app, "codegen_agent", None), "_token_process", None)
            payload = _token_process_usage_payload(token_process, model=model)
            if payload is not None:
                usage_callback(payload)

        def tracked_coding_runtime_event(payload: dict[str, Any]) -> None:
            if runtime_event_callback is None:
                return
            snapshot = _latest_output_file_snapshot(output_root_path)
            runtime_event_callback({**payload, **snapshot})

        def tracked_stdout_line(line: str) -> None:
            if stdout_line_handler is not None:
                stdout_line_handler(line)
            emit_usage_snapshot()

        stdout_writer = _CapturingLineWriter(chunks=stdout_chunks, on_line=tracked_stdout_line)
        stderr_writer = _CapturingLineWriter(chunks=stderr_chunks, on_line=stderr_line_handler)

        paths = {
            "project": str(manifest_path),
            "semantic_model": str(semantic_model_path),
            "memory": str(memory_path),
            "software": str(output_root_path),
            "srs": str(srs_path),
            "av": str(architecture_path),
            "add": str(api_spec_path),
        }

        env_overrides = {
            **_noninteractive_observability_env(),
            "HOME": str(runtime_home_path),
            "CREWAI_STORAGE_DIR": str(runtime_home_path / "crewai-storage"),
            "OPENAI_API_KEY": api_key,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_MODEL": model,
            "ISOFTDEVAGENTS_LLM_API_KEY": api_key,
            "ISOFTDEVAGENTS_LLM_BASE_URL": base_url,
            "ISOFTDEVAGENTS_LLM_MODEL": model,
        }

        managed_module_prefixes = ("agents", "config", "generators", "loaders")
        code_agent_site_packages = _find_code_agent_site_packages_dir(code_agent_root_path)
        effective_python_bin = str(python_bin or "").strip()
        if effective_python_bin and Path(effective_python_bin).exists():
            child_env = os.environ.copy()
            child_env.update({key: value for key, value in env_overrides.items() if value})
            command = [
                effective_python_bin,
                "-c",
                _code_agent_runner_script(),
                str(_code_agent_runtime_module_path(code_agent_root_path)),
                str(code_agent_root_path),
                str(manifest_path),
                str(semantic_model_path),
                str(srs_path),
                str(architecture_path),
                str(api_spec_path),
                str(memory_path),
                str(output_root_path),
                str(result_output_path),
            ]
            _run_streaming_subprocess(
                command=command,
                cwd=code_agent_root_path,
                env=child_env,
                stdout_writer=stdout_writer,
                stderr_writer=stderr_writer,
                heartbeat_callback=tracked_coding_runtime_event,
                cancel_event=cancel_event,
            )
            payload = _read_json_payload(result_output_path)
            usage = payload.get("usage") if isinstance(payload, dict) else None
            if usage is not None and usage_callback is not None:
                usage_callback(usage)
            return {
                "files": payload.get("files") if isinstance(payload, dict) else [],
                "usage": usage,
                "stdout": "".join(stdout_chunks),
                "stderr": "".join(stderr_chunks),
                "output_root": str(output_root_path),
            }

        try:
            with _PROCESS_RUNTIME_LOCK:
                original_env = os.environ.copy()
                original_sys_path = list(sys.path)
                saved_modules = _snapshot_modules(managed_module_prefixes)
                original_stdin = sys.stdin
                try:
                    _clear_modules(managed_module_prefixes)
                    os.environ.update({key: value for key, value in env_overrides.items() if value})
                    sys.path.insert(0, str(code_agent_root_path))
                    if code_agent_site_packages and code_agent_site_packages not in sys.path:
                        sys.path.insert(1, code_agent_site_packages)
                    runtime_module = load_code_agent_runtime_module(code_agent_root_path)
                    runtime_app = runtime_module.CodeAgentApp(paths=paths)
                    runtime_app_holder["app"] = runtime_app
                    # 真实 Code Agent 运行时会询问是否继续某些交互步骤。
                    # 这里先给出默认的 "n"，保证后端集成调用不会卡死在终端输入上。
                    sys.stdin = io.StringIO(_NONINTERACTIVE_STDIN_TEXT)
                    with redirect_stdout(stdout_writer), redirect_stderr(stderr_writer):
                        runtime_app.run(mode="full")
                    usage = _token_process_usage_payload(
                        getattr(getattr(runtime_app, "codegen_agent", None), "_token_process", None),
                        model=model,
                    )
                    if usage is not None and usage_callback is not None:
                        usage_callback(usage)
                finally:
                    sys.stdin = original_stdin
                    os.environ.clear()
                    os.environ.update(original_env)
                    sys.path[:] = original_sys_path
                    _restore_modules(managed_module_prefixes, saved_modules)
        finally:
            stdout_writer.flush()
            stderr_writer.flush()

        files: list[dict[str, str]] = []
        for path in sorted(output_root_path.rglob("*")):
            if not path.is_file():
                continue
            files.append(
                {
                    "filePath": path.relative_to(output_root_path).as_posix(),
                    "content": path.read_text(encoding="utf-8"),
                }
            )

        return {
            "files": files,
            "usage": usage,
            "stdout": "".join(stdout_chunks),
            "stderr": "".join(stderr_chunks),
            "output_root": str(output_root_path),
        }


def _ui_agent_runner_script() -> str:
    """
    在 UI Agent 自己的 Python 解释器里执行真实 UI 生成流程。

    原因注释：
    UI Agent 以前 in-process 运行时需要 _PROCESS_RUNTIME_LOCK 保护全局状态。
    改成独立子进程后自然隔离，多项目可以并发执行 UI 生成。
    """

    return """
import importlib.util
import json
import sys
from pathlib import Path

module_path = Path(sys.argv[1])
source_root = sys.argv[2]
project_name = sys.argv[3]
use_case_path = sys.argv[4]
dialog_map_path = sys.argv[5]
api_methods_path = sys.argv[6]
output_dir = sys.argv[7]
result_json_path = Path(sys.argv[8])

if source_root and source_root not in sys.path:
    sys.path.insert(0, source_root)

# 安装 CrewAI usage tracking patch
platform_root = str(Path(module_path).resolve().parents[1] / "platform")
if platform_root not in sys.path:
    sys.path.insert(0, platform_root)
try:
    from app.agents.llm_debug import install_crewai_llm_debug_logging
    install_crewai_llm_debug_logging()
except Exception:
    pass

spec = importlib.util.spec_from_file_location("isoftdevagents_ui_runtime_bridge_subprocess", module_path)
if spec is None or spec.loader is None:
    raise ImportError(f"Unable to load UI Agent runtime module: {module_path}")

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

result = module.run_ui_agent(
    project_name=project_name,
    use_case_path=use_case_path,
    dialog_map_path=dialog_map_path,
    api_methods_path=api_methods_path,
    output_dir=output_dir,
) or {}

result_json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
""".strip()


class UIAgentEntry:
    """
    UI Agent 统一桥梁入口。

    原因注释：
    改为 subprocess 执行，每个 UI Agent 任务运行在独立子进程中，
    拥有隔离的环境变量和模块缓存，消除并发共享状态问题。
    """

    def run(
        self,
        *,
        ui_agent_root: str | Path,
        runtime_home: str | Path,
        project_name: str,
        use_case_text: str,
        dialog_map_text: str,
        api_methods: dict[str, Any],
        output_root: str | Path,
        python_bin: str,
        api_key: str,
        base_url: str,
        model: str,
        stdout_line_handler: Any = None,
        stderr_line_handler: Any = None,
        usage_callback: Any = None,
        runtime_event_callback: Any = None,
        cancel_event: threading.Event | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        ui_agent_root_path = Path(ui_agent_root)
        runtime_home_path = Path(runtime_home)
        runtime_home_path.mkdir(parents=True, exist_ok=True)
        output_root_path = Path(output_root)
        output_root_path.mkdir(parents=True, exist_ok=True)

        use_case_path = runtime_home_path / "use_case.md"
        dialog_map_path = runtime_home_path / "dialog_map.md"
        api_methods_path = runtime_home_path / "api_methods.json"
        use_case_path.write_text(use_case_text, encoding="utf-8")
        dialog_map_path.write_text(dialog_map_text, encoding="utf-8")
        api_methods_path.write_text(json.dumps(api_methods, ensure_ascii=False, indent=2), encoding="utf-8")

        result_output_path = runtime_home_path / "ui-agent.result.json"
        result_output_path.unlink(missing_ok=True)

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        stdout_writer = _CapturingLineWriter(chunks=stdout_chunks, on_line=stdout_line_handler)
        stderr_writer = _CapturingLineWriter(chunks=stderr_chunks, on_line=stderr_line_handler)

        def tracked_runtime_event(payload: dict[str, Any]) -> None:
            if runtime_event_callback is None:
                return
            snapshot = _latest_output_file_snapshot(output_root_path)
            runtime_event_callback({**payload, **snapshot})

        env_overrides: dict[str, str] = {
            **_noninteractive_observability_env(),
            "HOME": str(runtime_home_path),
            "OPENAI_API_KEY": api_key,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_MODEL": model,
            "ISOFTDEVAGENTS_LLM_API_KEY": api_key,
            "ISOFTDEVAGENTS_LLM_BASE_URL": base_url,
            "ISOFTDEVAGENTS_LLM_MODEL": model,
        }
        ui_agent_site_packages = _find_ui_agent_site_packages_dir(ui_agent_root_path)

        python_path_entries = [str(ui_agent_root_path)]
        if ui_agent_site_packages:
            python_path_entries.append(ui_agent_site_packages)

        child_env = os.environ.copy()
        child_env.update({k: v for k, v in env_overrides.items() if v})
        child_env["PYTHONPATH"] = os.pathsep.join(
            [*python_path_entries, child_env.get("PYTHONPATH", "")]
        ).strip(os.pathsep)

        module_path = _ui_agent_runtime_module_path(ui_agent_root_path)
        command = [
            python_bin,
            "-c",
            _ui_agent_runner_script(),
            str(module_path),
            str(ui_agent_root_path),
            project_name,
            str(use_case_path),
            str(dialog_map_path),
            str(api_methods_path),
            str(output_root_path),
            str(result_output_path),
        ]

        try:
            _run_streaming_subprocess(
                command=command,
                cwd=ui_agent_root_path,
                env=child_env,
                stdout_writer=stdout_writer,
                stderr_writer=stderr_writer,
                heartbeat_callback=tracked_runtime_event,
                cancel_event=cancel_event,
            )
        except subprocess.CalledProcessError as exc:
            stdout_writer.flush()
            stderr_writer.flush()
            stderr_text = "".join(stderr_chunks)
            partial_files = _read_output_files(output_root_path)
            partial_file_names = [item["filePath"] for item in partial_files]
            reason = "runtime_exception"
            lowered = stderr_text.lower()
            if "single-page ui must" in lowered or "single-page ui requires" in lowered or "must contain exactly one page" in lowered:
                reason = "invalid_single_page_contract"
            elif "ui agent did not return all required code blocks" in lowered:
                reason = "missing_required_code_blocks"
            elif "jsondecode" in lowered or "json.decoder" in lowered:
                reason = "invalid_page_description_json"
            raise UIAgentRuntimeError(
                str(exc),
                reason=reason,
                stage="subprocess",
                stdout_text="".join(stdout_chunks),
                stderr_text=stderr_text,
                output_root=str(output_root_path),
                partial_files=partial_file_names,
            ) from exc
        finally:
            stdout_writer.flush()
            stderr_writer.flush()

        payload = _read_json_payload(result_output_path)
        files = _read_output_files(output_root_path)
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if usage is not None and usage_callback is not None:
            usage_callback(usage)

        return {
            "files": files,
            "usage": usage,
            "stdout": "".join(stdout_chunks),
            "stderr": "".join(stderr_chunks),
            "output_root": str(output_root_path),
        }


def _test_agent_runner_script() -> str:
    """
    在 Test Agent 自己的 Python 解释器里执行真实测试生成流程。

    原因注释：
    Test Agent 以前 in-process 运行时需要 _PROCESS_RUNTIME_LOCK 保护全局状态。
    改成独立子进程后自然隔离，多项目可以并发执行测试生成。
    """

    return """
import importlib.util
import json
import os
import sys
from pathlib import Path

module_path = Path(sys.argv[1])
source_root = sys.argv[2]
args_json_path = Path(sys.argv[3])
result_json_path = Path(sys.argv[4])

if source_root and source_root not in sys.path:
    sys.path.insert(0, source_root)

# 安装 CrewAI usage tracking patch
platform_root = str(Path(module_path).resolve().parents[1] / "platform")
if platform_root not in sys.path:
    sys.path.insert(0, platform_root)
try:
    from app.agents.llm_debug import install_crewai_llm_debug_logging
    install_crewai_llm_debug_logging()
except Exception:
    pass

args = json.loads(args_json_path.read_text(encoding="utf-8"))

# 注入 config.config 模块的 LLM 设置
try:
    import config.config as config_module
    config_payload = getattr(config_module, "config", None)
    if isinstance(config_payload, dict):
        llm_settings = config_payload.setdefault("llm", {})
        if isinstance(llm_settings, dict):
            llm_settings["api_key"] = os.environ.get("OPENAI_API_KEY", "")
            llm_settings["base_url"] = os.environ.get("OPENAI_BASE_URL", "")
            llm_settings["model"] = os.environ.get("OPENAI_MODEL", "")
        dataset_settings = config_payload.setdefault("dataset", {})
        if isinstance(dataset_settings, dict):
            dataset_settings["root_path"] = args["dataset_root"]
except Exception:
    pass

spec = importlib.util.spec_from_file_location("isoftdevagents_test_agent_subprocess", module_path)
if spec is None or spec.loader is None:
    raise ImportError(f"Unable to load Test Agent runtime module: {module_path}")

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

import inspect
runtime_app_kwargs = {
    "dataset_name": args["dataset_name"],
    "dataset_root": Path(args["dataset_root"]),
    "output_root": Path(args["output_root"]),
    "memory_root": Path(args["memory_root"]),
}
init_sig = inspect.signature(module.TestAgentApp.__init__)
if "usage_callback" in init_sig.parameters:
    usage_payloads = []
    runtime_app_kwargs["usage_callback"] = lambda p: usage_payloads.append(p)

runtime_app = module.TestAgentApp(**runtime_app_kwargs)
runtime_app.run()

usage = None
summary = getattr(runtime_app, "usage_summary", None)
if isinstance(summary, dict):
    usage = summary

result = {"usage": usage}
result_json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
""".strip()


class TestAgentEntry:
    """
    Test Agent 统一桥梁入口。

    原因注释：
    改为 subprocess 执行，每个 Test Agent 任务运行在独立子进程中，
    拥有隔离的环境变量和模块缓存，消除并发共享状态问题。
    """

    def run(
        self,
        *,
        test_agent_root: str | Path,
        runtime_home: str | Path,
        dataset_name: str,
        srs_text: str,
        class_diagram_text: str,
        sequence_diagram_text: str,
        architecture_text: str,
        code_root: str | Path,
        python_bin: str,
        api_key: str,
        base_url: str,
        model: str,
        stdout_line_handler: Any = None,
        stderr_line_handler: Any = None,
        usage_callback: Any = None,
        runtime_event_callback: Any = None,
        cancel_event: threading.Event | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        test_agent_root_path = Path(test_agent_root)
        runtime_home_path = Path(runtime_home)
        runtime_home_path.mkdir(parents=True, exist_ok=True)

        dataset_root = runtime_home_path / "datasets"
        dataset_dir = dataset_root / dataset_name
        output_root = runtime_home_path / "output"
        memory_root = runtime_home_path / "memory"
        code_root_path = Path(code_root)
        code_root_path.mkdir(parents=True, exist_ok=True)
        dataset_dir.mkdir(parents=True, exist_ok=True)
        output_root.mkdir(parents=True, exist_ok=True)
        memory_root.mkdir(parents=True, exist_ok=True)

        srs_path = dataset_dir / "SRS.md"
        class_diagram_path = dataset_dir / "uml_class.md"
        sequence_diagram_path = dataset_dir / "uml_sequence.md"
        architecture_path = dataset_dir / "architecture_design.md"
        srs_path.write_text(srs_text, encoding="utf-8")
        class_diagram_path.write_text(class_diagram_text, encoding="utf-8")
        sequence_diagram_path.write_text(sequence_diagram_text, encoding="utf-8")
        architecture_path.write_text(architecture_text, encoding="utf-8")
        (dataset_dir / "config.json").write_text(
            json.dumps(
                {
                    "srs": srs_path.name,
                    "uml_class": class_diagram_path.name,
                    "uml_sequence": sequence_diagram_path.name,
                    "architecture_design": architecture_path.name,
                    "sut_root": str(code_root_path),
                    "language": "python",
                    "conda_env": sys.executable,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        result_output_path = runtime_home_path / "test-agent.result.json"
        args_json_path = runtime_home_path / "test-agent.args.json"
        result_output_path.unlink(missing_ok=True)

        args_payload = {
            "dataset_name": dataset_name,
            "dataset_root": str(dataset_root),
            "output_root": str(output_root),
            "memory_root": str(memory_root),
        }
        args_json_path.write_text(json.dumps(args_payload, ensure_ascii=False), encoding="utf-8")

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        stdout_writer = _CapturingLineWriter(chunks=stdout_chunks, on_line=stdout_line_handler)
        stderr_writer = _CapturingLineWriter(chunks=stderr_chunks, on_line=stderr_line_handler)

        def tracked_runtime_event(payload: dict[str, Any]) -> None:
            if runtime_event_callback is None:
                return
            snapshot = _latest_named_output_snapshot(
                [
                    ("", output_root),
                    ("memory", memory_root),
                ]
            )
            runtime_event_callback({**payload, **snapshot})

        env_overrides: dict[str, str] = {
            **_noninteractive_observability_env(),
            "HOME": str(runtime_home_path),
            "CREWAI_STORAGE_DIR": str(runtime_home_path / "crewai-storage"),
            "OPENAI_API_KEY": api_key,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_MODEL": model,
            "ISOFTDEVAGENTS_LLM_API_KEY": api_key,
            "ISOFTDEVAGENTS_LLM_BASE_URL": base_url,
            "ISOFTDEVAGENTS_LLM_MODEL": model,
            "ISOFTDEVAGENTS_TEST_AGENT_ALLOWED_WRITE_ROOTS": os.pathsep.join(
                [
                    str(code_root_path.resolve()),
                    str(output_root.resolve()),
                    str(memory_root.resolve()),
                ]
            ),
        }
        test_agent_site_packages = _find_test_agent_site_packages_dir(test_agent_root_path)

        python_path_entries = [str(test_agent_root_path)]
        if test_agent_site_packages:
            python_path_entries.append(test_agent_site_packages)

        child_env = os.environ.copy()
        child_env.update({k: v for k, v in env_overrides.items() if v})
        child_env["PYTHONPATH"] = os.pathsep.join(
            [*python_path_entries, child_env.get("PYTHONPATH", "")]
        ).strip(os.pathsep)

        module_path = _test_agent_runtime_module_path(test_agent_root_path)
        command = [
            python_bin,
            "-c",
            _test_agent_runner_script(),
            str(module_path),
            str(test_agent_root_path),
            str(args_json_path),
            str(result_output_path),
        ]

        try:
            _run_streaming_subprocess(
                command=command,
                cwd=test_agent_root_path,
                env=child_env,
                stdout_writer=stdout_writer,
                stderr_writer=stderr_writer,
                heartbeat_callback=tracked_runtime_event,
                cancel_event=cancel_event,
            )
        finally:
            stdout_writer.flush()
            stderr_writer.flush()
            args_json_path.unlink(missing_ok=True)

        payload = _read_json_payload(result_output_path)

        files = _read_output_files(output_root)
        for item in _read_output_files(memory_root):
            files.append(
                {
                    "filePath": f"memory/{item['filePath']}",
                    "content": item["content"],
                }
            )

        usage = payload.get("usage") if isinstance(payload, dict) else None
        if usage is not None and usage_callback is not None:
            usage_callback(usage)

        return {
            "files": files,
            "usage": usage,
            "stdout": "".join(stdout_chunks),
            "stderr": "".join(stderr_chunks),
            "output_root": str(output_root),
            "memory_root": str(memory_root),
        }


class UnifiedAgentBridge:
    """
    后端统一 Agent 桥梁。

    设计目标很直接：
    - 后端以后只依赖这个桥梁对象
    - 每个 Agent 都有独立入口
    - 先让 Requirements 真实可用
    - 其它 Agent 还没接好之前，明确抛未实现，而不是继续走假逻辑
    """

    def __init__(self) -> None:
        self.requirements = RequirementsAgentEntry()
        self.architecture = ArchitectureAgentEntry()
        self.code = CodeAgentEntry()
        self.ui = UIAgentEntry()
        self.test = TestAgentEntry()

    def run_requirements_agent(self, **kwargs: Any) -> dict[str, Any]:
        return self.requirements.run(**kwargs)

    def run_architecture_agent(self, **kwargs: Any) -> dict[str, Any]:
        return self.architecture.run(**kwargs)

    def run_code_agent(self, **kwargs: Any) -> dict[str, Any]:
        return self.code.run(**kwargs)

    def run_ui_agent(self, **kwargs: Any) -> dict[str, Any]:
        return self.ui.run(**kwargs)

    def run_test_agent(self, **kwargs: Any) -> dict[str, Any]:
        return self.test.run(**kwargs)


agent_bridge = UnifiedAgentBridge()
