from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.llm_debug import (
    _LiteLLMUsageTrackingCallback,
    _current_debug_context,
    _debug_summary_parts,
    _emit_debug_text,
    _normalize_litellm_callback_usage_payload,
    _normalize_openai_response_usage,
    _normalize_crewai_usage_payload,
    _resolve_debug_log_path,
    _render_messages,
    _render_response,
    llm_debug_context,
)


def test_render_messages_formats_chat_roles() -> None:
    rendered = _render_messages(
        [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "build a snake game"},
        ],
        limit=1000,
    )

    assert "[system]" in rendered
    assert "system prompt" in rendered
    assert "[user]" in rendered
    assert "build a snake game" in rendered


def test_render_response_truncates_large_output() -> None:
    rendered = _render_response("x" * 20, limit=10)

    assert rendered.startswith("x" * 10)
    assert "[truncated]" in rendered


def test_normalize_crewai_usage_payload_supports_camel_case_usage_fields() -> None:
    normalized, reported_total_tokens = _normalize_crewai_usage_payload(
        {
            "inputTokens": 120,
            "outputTokens": 45,
            "totalTokens": 165,
            "cachedPromptTokens": 12,
        }
    )

    assert normalized["prompt_tokens"] == 120
    assert normalized["input_tokens"] == 120
    assert normalized["completion_tokens"] == 45
    assert normalized["output_tokens"] == 45
    assert normalized["cached_prompt_tokens"] == 12
    assert normalized["cached_tokens"] == 12
    assert reported_total_tokens == 165


def test_normalize_crewai_usage_payload_keeps_unknown_shapes_safe() -> None:
    normalized, reported_total_tokens = _normalize_crewai_usage_payload(SimpleNamespace(totalTokens=30))

    assert normalized == {}
    assert reported_total_tokens == 0


def test_normalize_litellm_callback_usage_payload_supports_nested_camel_case_usage() -> None:
    normalized = _normalize_litellm_callback_usage_payload(
        {
            "usage": {
                "inputTokens": 91,
                "outputTokens": 27,
                "totalTokens": 118,
            }
        }
    )

    assert normalized["prompt_tokens"] == 91
    assert normalized["completion_tokens"] == 27
    assert normalized["total_tokens"] == 118


def test_normalize_litellm_callback_usage_payload_supports_usage_object() -> None:
    usage_object = SimpleNamespace(
        prompt_tokens=1014,
        completion_tokens=231,
        total_tokens=1245,
    )

    normalized = _normalize_litellm_callback_usage_payload({"usage": usage_object})

    assert normalized["prompt_tokens"] == 1014
    assert normalized["completion_tokens"] == 231
    assert normalized["total_tokens"] == 1245


def test_litellm_usage_tracking_callback_writes_usage_back_to_llm_token_counter() -> None:
    captured_usage = []

    class _FakeLLM:
        def _track_token_usage_internal(self, usage_data):
            captured_usage.append(dict(usage_data))

    callback = _LiteLLMUsageTrackingCallback(_FakeLLM())
    callback.log_success_event(
        kwargs={},
        response_obj={
            "usage": {
                "inputTokens": 44,
                "outputTokens": 16,
                "totalTokens": 60,
            }
        },
        start_time=0,
        end_time=0,
    )

    assert captured_usage == [
        {
            "inputTokens": 44,
            "outputTokens": 16,
            "totalTokens": 60,
            "prompt_tokens": 44,
            "input_tokens": 44,
            "completion_tokens": 16,
            "output_tokens": 16,
            "total_tokens": 60,
            "cached_tokens": 0,
            "cached_prompt_tokens": 0,
        }
    ]


def test_normalize_openai_response_usage_supports_camel_case_gateway_usage() -> None:
    normalized = _normalize_openai_response_usage(
        {
            "inputTokens": 73,
            "outputTokens": 19,
            "totalTokens": 92,
            "cachedPromptTokens": 7,
        }
    )

    assert normalized == {
        "prompt_tokens": 73,
        "completion_tokens": 19,
        "total_tokens": 92,
        "cached_prompt_tokens": 7,
    }


def test_normalize_openai_response_usage_supports_usage_object() -> None:
    normalized = _normalize_openai_response_usage(
        SimpleNamespace(
            prompt_tokens=73,
            completion_tokens=19,
            total_tokens=92,
            cached_prompt_tokens=7,
        )
    )

    assert normalized == {
        "prompt_tokens": 73,
        "completion_tokens": 19,
        "total_tokens": 92,
        "cached_prompt_tokens": 7,
    }


def test_resolve_debug_log_path_uses_default_platform_log_file_when_file_logging_enabled() -> None:
    with patch.dict(os.environ, {"ISOFTDEVAGENTS_AGENT_DEBUG_LLM_LOG_TO_FILE": "1"}, clear=False):
        resolved = _resolve_debug_log_path()

    assert resolved is not None
    assert resolved.name == "llm-debug.log"
    assert resolved.parent.name == "log"


def test_emit_debug_text_appends_to_debug_log_file() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        log_path = Path(temp_dir) / "llm-debug.log"
        with patch.dict(
            os.environ,
            {
                "ISOFTDEVAGENTS_AGENT_DEBUG_LLM_LOG_FILE": str(log_path),
            },
            clear=False,
        ):
            _emit_debug_text("first line")
            _emit_debug_text("second line")

        content = log_path.read_text(encoding="utf-8")

    assert "first line" in content
    assert "second line" in content


def test_emit_debug_text_does_not_print_to_console_by_default() -> None:
    with patch("builtins.print") as print_mock:
        with patch.dict(
            os.environ,
            {
                "ISOFTDEVAGENTS_AGENT_DEBUG_LLM_LOG_TO_CONSOLE": "0",
                "ISOFTDEVAGENTS_AGENT_DEBUG_LLM_LOG_TO_FILE": "0",
            },
            clear=False,
        ):
            _emit_debug_text("console should stay quiet")

    print_mock.assert_not_called()


def test_emit_debug_text_prints_to_console_when_explicitly_enabled() -> None:
    with patch("builtins.print") as print_mock:
        with patch.dict(
            os.environ,
            {
                "ISOFTDEVAGENTS_AGENT_DEBUG_LLM_LOG_TO_CONSOLE": "1",
                "ISOFTDEVAGENTS_AGENT_DEBUG_LLM_LOG_TO_FILE": "0",
            },
            clear=False,
        ):
            _emit_debug_text("console output enabled")

    print_mock.assert_called_once_with("console output enabled")


def test_resolve_debug_log_path_returns_none_when_zero_residual_cleanup_is_enabled() -> None:
    with patch.dict(
        os.environ,
        {
            "ISOFTDEVAGENTS_AGENT_DEBUG_LLM_LOG_TO_FILE": "1",
            "ISOFTDEVAGENTS_DELETE_LOCAL_FILES_AFTER_PERSIST": "1",
        },
        clear=False,
    ):
        resolved = _resolve_debug_log_path()

    assert resolved is None


def test_llm_debug_context_sets_and_restores_thread_local_labels() -> None:
    assert _current_debug_context() == {}

    with llm_debug_context(task_id="task-1", phase="requirements_drafts_started", agent_name="requirements_agent"):
        assert _current_debug_context()["task_id"] == "task-1"
        assert _current_debug_context()["phase"] == "requirements_drafts_started"
        assert _current_debug_context()["agent_name"] == "requirements_agent"

        with llm_debug_context(retry_name="SRS Chapter 3", retry_attempt=2, retry_max=5):
            assert _current_debug_context()["retry_name"] == "SRS Chapter 3"
            assert _current_debug_context()["retry_attempt"] == 2
            assert _current_debug_context()["retry_max"] == 5
            assert _current_debug_context()["task_id"] == "task-1"

        assert "retry_name" not in _current_debug_context()
        assert _current_debug_context()["task_id"] == "task-1"

    assert _current_debug_context() == {}


def test_debug_summary_parts_include_task_phase_agent_and_crew_labels() -> None:
    parts = _debug_summary_parts(
        debug_context={
            "task_id": "task-41",
            "phase": "architecture_generation_started",
            "agent_name": "architecture_agent",
            "retry_name": "module_design",
            "retry_attempt": 2,
            "retry_max": 5,
            "output_file": "class_design_raw.md",
        },
        from_agent=SimpleNamespace(role="Architecture Agent"),
        from_task=SimpleNamespace(name="module_design_task"),
    )

    assert "task_id=task-41" in parts
    assert "phase=architecture_generation_started" in parts
    assert "agent_name=architecture_agent" in parts
    assert "output_file=class_design_raw.md" in parts
    assert "retry_name=module_design" in parts
    assert "retry_attempt=2" in parts
    assert "retry_max=5" in parts
    assert "crew_agent=Architecture Agent" in parts
    assert "crew_task=module_design_task" in parts
