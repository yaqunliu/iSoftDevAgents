from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, UTC
import threading
from typing import Any, Callable

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.key_binding import KeyBindings
except ModuleNotFoundError:
    PromptSession = None
    KeyBindings = None
    create_pipe_input = None


@dataclass
class PendingPromptState:
    """
    描述当前这一次等待中的输入请求。

    这里故意把等待中的关键信息收口成一个结构，
    这样平台侧要上报什么、本地调试时要看什么，都有统一来源，
    不需要再到处拼临时字典。
    """

    task_id: str | None
    prompt_text: str
    checkpoint: str | None
    output_files: list[str]
    is_waiting: bool
    submitted_text: str | None
    created_at: str


class PromptInputProvider(ABC):
    """
    统一的人类输入接口。

    Requirements Agent 的业务代码只认这一个接口，
    不再关心输入到底来自真实终端，还是来自平台后端注入。
    """

    @abstractmethod
    def read_multiline(self, prompt_text: str = "请输入反馈：", checkpoint: str | None = None) -> str:
        raise NotImplementedError


def _ensure_prompt_toolkit_available() -> None:
    if PromptSession is None or KeyBindings is None:
        raise ModuleNotFoundError("prompt_toolkit is required for interactive multiline input.")


def _build_terminal_key_bindings() -> Any:
    _ensure_prompt_toolkit_available()
    kb = KeyBindings()

    @kb.add("enter")
    def _(event):
        buffer = event.app.current_buffer
        text = buffer.text

        # 本地终端模式继续保留“双空行提交”。
        # 这样可以兼容 Requirements Agent 原本的多行输入习惯。
        if text.endswith("\n\n"):
            buffer.validate_and_handle()
        else:
            buffer.insert_text("\n")

    return kb


def _build_injected_key_bindings() -> Any:
    _ensure_prompt_toolkit_available()
    kb = KeyBindings()

    @kb.add("c-y")
    def _(event):
        # 平台注入模式不模拟“双回车”，而是走一个内部专用提交键。
        # 这样多行文本可以原样注入，提交动作也不会依赖不同终端的回车行为。
        event.app.current_buffer.validate_and_handle()

    return kb


class TerminalPromptInputProvider(PromptInputProvider):
    """
    本地终端输入实现。

    这个实现专门服务“直接在本机终端运行 Requirements Agent”的场景。
    平台模式不要混进来，避免把两种交互方式搅在一起。
    """

    def read_multiline(self, prompt_text: str = "请输入反馈：", checkpoint: str | None = None) -> str:
        del checkpoint
        _ensure_prompt_toolkit_available()
        session = PromptSession(
            key_bindings=_build_terminal_key_bindings(),
            multiline=True,
        )
        return session.prompt(prompt_text)


class InjectedPromptInputProvider(PromptInputProvider):
    """
    平台注入输入实现。

    这里让 Agent 线程继续真的阻塞在 PromptSession.prompt() 上，
    只是把输入源换成 PipeInput。
    当前端提交反馈时，后端再把文本送进这个输入流里。
    """

    def __init__(
        self,
        *,
        task_id: str | None = None,
        output_files_resolver: Callable[[], list[str]] | None = None,
        waiting_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.task_id = task_id
        self._output_files_resolver = output_files_resolver
        self._waiting_callback = waiting_callback
        self._lock = threading.Lock()
        self._pending_state: PendingPromptState | None = None
        self._pipe_input = None
        self._pipe_input_context = None
        self._closed = False

    def _resolve_output_files(self) -> list[str]:
        if self._output_files_resolver is None:
            return []
        resolved = self._output_files_resolver()
        return [str(item) for item in resolved or []]

    def _build_waiting_payload(self, *, prompt_text: str, checkpoint: str | None) -> dict[str, Any]:
        output_files = self._resolve_output_files()
        return {
            "taskId": self.task_id,
            "promptText": prompt_text.strip(),
            "checkpoint": checkpoint,
            "outputFiles": output_files,
        }

    def read_multiline(self, prompt_text: str = "请输入反馈：", checkpoint: str | None = None) -> str:
        _ensure_prompt_toolkit_available()
        if create_pipe_input is None:
            raise ModuleNotFoundError("prompt_toolkit pipe input is required for injected prompt input.")

        with self._lock:
            if self._closed:
                return "exit"
            if self._pipe_input is not None:
                raise RuntimeError("Another injected prompt is already waiting for input.")

        payload = self._build_waiting_payload(prompt_text=prompt_text, checkpoint=checkpoint)
        pipe_input_context = create_pipe_input()
        pipe_input = pipe_input_context.__enter__()
        session = PromptSession(
            input=pipe_input,
            key_bindings=_build_injected_key_bindings(),
            multiline=True,
        )

        with self._lock:
            if self._closed:
                pipe_input.close()
                pipe_input_context.__exit__(None, None, None)
                return "exit"
            self._pipe_input_context = pipe_input_context
            self._pipe_input = pipe_input
            self._pending_state = PendingPromptState(
                task_id=self.task_id,
                prompt_text=payload["promptText"],
                checkpoint=checkpoint,
                output_files=list(payload["outputFiles"]),
                is_waiting=True,
                submitted_text=None,
                created_at=datetime.now(UTC).isoformat(),
            )

        if self._waiting_callback is not None:
            self._waiting_callback(payload)

        try:
            return session.prompt(prompt_text)
        except (EOFError, KeyboardInterrupt):
            return "exit"
        finally:
            with self._lock:
                if self._pending_state is not None:
                    self._pending_state.is_waiting = False
                self._pipe_input = None
                self._pipe_input_context = None
            try:
                pipe_input.close()
            except Exception:
                pass
            pipe_input_context.__exit__(None, None, None)

    def inject_text(self, text: str) -> bool:
        normalized = str(text or "").strip() or "no"
        with self._lock:
            if self._closed or self._pending_state is None or not self._pending_state.is_waiting:
                return False
            if self._pending_state.submitted_text is not None:
                return False
            pipe_input = self._pipe_input
            self._pending_state.submitted_text = normalized

        if pipe_input is None:
            with self._lock:
                if self._pending_state is not None and self._pending_state.submitted_text == normalized:
                    self._pending_state.submitted_text = None
            return False

        try:
            pipe_input.send_text(normalized)
            pipe_input.send_bytes(b"\x19")
            return True
        except Exception:
            with self._lock:
                if self._pending_state is not None and self._pending_state.submitted_text == normalized:
                    self._pending_state.submitted_text = None
            return False

    def close(self) -> None:
        with self._lock:
            self._closed = True
            pipe_input = self._pipe_input
        if pipe_input is not None:
            try:
                pipe_input.close()
            except Exception:
                pass


_PROMPT_INPUT_PROVIDER_LOCAL = threading.local()


def set_prompt_input_provider(provider: PromptInputProvider | None) -> None:
    """
    给当前线程注册输入 provider。

    需求 Agent 现在是在后端线程里运行的，所以这里必须按线程隔离，
    避免多个并发任务互相串输入源。
    """

    _PROMPT_INPUT_PROVIDER_LOCAL.current = provider


def get_prompt_input_provider() -> PromptInputProvider | None:
    return getattr(_PROMPT_INPUT_PROVIDER_LOCAL, "current", None)


def clear_prompt_input_provider() -> None:
    if hasattr(_PROMPT_INPUT_PROVIDER_LOCAL, "current"):
        delattr(_PROMPT_INPUT_PROVIDER_LOCAL, "current")
