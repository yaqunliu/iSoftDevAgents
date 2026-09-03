import asyncio
import json
import io
import os
import site
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from types import ModuleType
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import yaml

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.orchestrator import AgentOrchestrator, _extract_retry_summary, _truncate_for_log
from app.config import load_local_env_files
from app.main import app
from app.services import workflow
from app.services.store import SQLiteStore


def _requirements_runtime_result(
    output_root: Path,
    *,
    stdout: str = "",
    stderr: str = "",
    model: str = "openai/moonshot/kimi-k2.5",
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "output_root": output_root,
        "stdout": stdout,
        "stderr": stderr,
        "model": model,
        "tasks_config_path": output_root / "tasks.backend.runtime.yaml",
        "usage": usage,
    }


def _usage_payload(
    *,
    model: str = "openai/moonshot/kimi-k2.5",
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    cost_amount: float = 0.0,
) -> dict[str, Any]:
    return {
        "model": model,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
        "costAmount": cost_amount,
    }


class AgentOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    def test_truncate_for_log_keeps_both_start_and_end_for_long_text(self) -> None:
        long_text = "Attempt 1/5 " + ("middle " * 80) + "Failed after 5 retries: Field 'secondary_actor' must be of type list."

        preview = _truncate_for_log(long_text, limit=120)

        self.assertIn("Attempt 1/5", preview)
        self.assertIn("Failed after 5 retries", preview)
        self.assertIn("...[truncated]...", preview)

    def test_extract_retry_summary_reads_final_retry_error(self) -> None:
        stderr_text = (
            "Traceback...\n"
            "Exception: [UserCaseCrew] Failed after 5 retries: "
            "Use case format error: Field 'secondary_actor' in use case at index 1 must be of type list.\n"
        )

        self.assertEqual(
            _extract_retry_summary(stderr_text),
            "[UserCaseCrew] Failed after 5 retries: Use case format error: "
            "Field 'secondary_actor' in use case at index 1 must be of type list.",
        )

    async def test_requirements_feedback_bridge_injects_feedback_into_waiting_prompt(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )
        requests: list[dict[str, Any]] = []
        result: dict[str, str] = {}

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "business_scope.md").write_text("# Business Scope\n\nDraft\n", encoding="utf-8")

            async def feedback_callback(payload: dict[str, Any]) -> None:
                requests.append(payload)

            runtime_context = {
                "output_root": output_root,
                "runtime_home": output_root / ".runtime-home",
                "tasks_config_path": output_root / "tasks.backend.runtime.yaml",
                "litellm_model": "openai/moonshot/kimi-k2.5",
            }

            def fake_run_requirements_agent(**kwargs: Any) -> dict[str, Any]:
                provider = kwargs["prompt_input_provider"]
                result["feedback"] = provider.read_multiline(
                    prompt_text="请查看现有的business_scope.md文档并告诉我有哪些需要改进的地方：",
                    checkpoint="business_scope_review",
                )
                return _requirements_runtime_result(output_root, stdout="ok")

            with patch.object(
                orchestrator,
                "_prepare_requirements_agent_runtime",
                return_value=runtime_context,
            ), patch(
                "app.agents.requirements_bridge.run_requirements_agent",
                side_effect=fake_run_requirements_agent,
            ):
                runner = asyncio.create_task(
                    orchestrator._run_requirements_agent_inprocess(
                        mode="full",
                        task_id="task-feedback",
                        project_name="demo-project",
                        description_text="demo-description",
                        timeout=5,
                        human_feedback_callback=feedback_callback,
                    )
                )
                started_waiting_at = time.monotonic()
                while not requests and (time.monotonic() - started_waiting_at) < 1.5:
                    await asyncio.sleep(0.05)

                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0]["taskId"], "task-feedback")
                self.assertEqual(
                    requests[0]["promptText"],
                    "请查看现有的business_scope.md文档并告诉我有哪些需要改进的地方：",
                )
                self.assertEqual(requests[0]["outputFiles"], ["business_scope.md"])
                self.assertEqual(requests[0]["checkpoint"], "business_scope_review")

                self.assertTrue(orchestrator.submit_requirements_feedback("task-feedback", "请补充验收范围和成功标准"))
                await asyncio.wait_for(runner, timeout=2)

        self.assertEqual(result["feedback"], "请补充验收范围和成功标准")

    async def test_requirements_feedback_wait_time_does_not_consume_runtime_timeout(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            runtime_context = {
                "output_root": output_root,
                "runtime_home": output_root / ".runtime-home",
                "tasks_config_path": output_root / "tasks.backend.runtime.yaml",
                "litellm_model": "openai/moonshot/kimi-k2.5",
            }

            async def feedback_callback(payload: dict[str, Any]) -> None:
                return None

            def fake_run_requirements_agent(**kwargs: Any) -> dict[str, Any]:
                provider = kwargs["prompt_input_provider"]
                answer = provider.read_multiline(
                    prompt_text="请查看现有的BRD.md文档并告诉我有哪些需要改进的地方：",
                    checkpoint="brd_review",
                )
                self.assertEqual(answer, "no")
                # 设计注释：
                # 这里故意在用户反馈之后再睡一小段时间，用来模拟“恢复执行后的真实收尾工作”。
                # 如果 orchestrator 把前面的等待用户时间也算进总超时，这个测试就会错误超时。
                threading.Event().wait(0.05)
                return _requirements_runtime_result(output_root, stdout="ok")

            with patch.object(
                orchestrator,
                "_prepare_requirements_agent_runtime",
                return_value=runtime_context,
            ), patch(
                "app.agents.requirements_bridge.run_requirements_agent",
                side_effect=fake_run_requirements_agent,
            ):
                runner = asyncio.create_task(
                    orchestrator._run_requirements_agent_inprocess(
                        mode="full",
                        task_id="task-timeout-budget",
                        project_name="demo-project",
                        description_text="demo-description",
                        timeout=0.2,
                        human_feedback_callback=feedback_callback,
                    )
                )

                # 教学注释：
                # 故意让任务在“等待用户反馈”的状态里停留得比 timeout 更久。
                # 修复前这里会把整段等待时间也算进去，导致恢复后立刻超时。
                await asyncio.sleep(0.3)
                self.assertTrue(orchestrator.submit_requirements_feedback("task-timeout-budget", "no"))
                result = await asyncio.wait_for(runner, timeout=2)

        self.assertEqual(result["stdout"], "ok")

    async def test_requirements_agent_stops_when_running_task_is_cancelled_while_waiting_for_feedback(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )
        waiting_payloads: list[dict[str, Any]] = []
        result: dict[str, Any] = {}

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            runtime_context = {
                "output_root": output_root,
                "runtime_home": output_root / ".runtime-home",
                "tasks_config_path": output_root / "tasks.backend.runtime.yaml",
                "litellm_model": "openai/moonshot/kimi-k2.5",
            }

            async def feedback_callback(payload: dict[str, Any]) -> None:
                waiting_payloads.append(payload)

            def fake_run_requirements_agent(**kwargs: Any) -> dict[str, Any]:
                result["cancel_event_passed"] = kwargs["cancel_event"] is not None
                provider = kwargs["prompt_input_provider"]
                result["feedback"] = provider.read_multiline(
                    prompt_text="请查看现有的BRD.md文档并告诉我有哪些需要改进的地方：",
                    checkpoint="brd_review",
                )
                return _requirements_runtime_result(output_root, stdout="cancelled-cleanly")

            with patch.object(
                orchestrator,
                "_prepare_requirements_agent_runtime",
                return_value=runtime_context,
            ), patch(
                "app.agents.requirements_bridge.run_requirements_agent",
                side_effect=fake_run_requirements_agent,
            ):
                runner = asyncio.create_task(
                    orchestrator._run_requirements_agent_inprocess(
                        mode="full",
                        task_id="task-cancelled-feedback",
                        project_name="demo-project",
                        description_text="demo-description",
                        timeout=5,
                        human_feedback_callback=feedback_callback,
                    )
                )
                started_waiting_at = time.monotonic()
                while not waiting_payloads and (time.monotonic() - started_waiting_at) < 1.5:
                    await asyncio.sleep(0.05)

                self.assertTrue(waiting_payloads)
                self.assertTrue(workflow.cancel_running_task_sync("task-cancelled-feedback"))
                response = await asyncio.wait_for(runner, timeout=2)

        self.assertTrue(result["cancel_event_passed"])
        self.assertEqual(result["feedback"], "exit")
        self.assertEqual(response["stdout"], "cancelled-cleanly")

    def test_load_local_env_files_strips_matching_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env.local").write_text(
                'ISOFTDEVAGENTS_REAGENT_PYTHON_BIN="/tmp/reagent/bin/python"\n'
                "ISOFTDEVAGENTS_ARCH_AGENT_PYTHON_BIN='/tmp/arch/bin/python'\n"
                'ISOFTDEVAGENTS_CODING_AGENT_SITE_PACKAGES="/tmp/coding/site-packages"\n',
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                load_local_env_files(root)

                self.assertEqual(os.environ["ISOFTDEVAGENTS_REAGENT_PYTHON_BIN"], "/tmp/reagent/bin/python")
                self.assertEqual(os.environ["ISOFTDEVAGENTS_ARCH_AGENT_PYTHON_BIN"], "/tmp/arch/bin/python")
                self.assertEqual(os.environ["ISOFTDEVAGENTS_CODING_AGENT_SITE_PACKAGES"], "/tmp/coding/site-packages")

    def test_load_local_env_files_prefers_os_environ_then_env_local_then_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env").write_text(
                "ISOFTDEVAGENTS_LLM_BASE_URL=https://env.example/v1\nISOFTDEVAGENTS_LLM_MODEL=env-model\n",
                encoding="utf-8",
            )
            (root / ".env.local").write_text(
                "ISOFTDEVAGENTS_LLM_BASE_URL=https://local.example/v1\nISOFTDEVAGENTS_LLM_API_KEY=local-key\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"ISOFTDEVAGENTS_LLM_MODEL": "real-env-model"}, clear=True):
                load_local_env_files(root)

                self.assertEqual(os.environ["ISOFTDEVAGENTS_LLM_MODEL"], "real-env-model")
                self.assertEqual(os.environ["ISOFTDEVAGENTS_LLM_BASE_URL"], "https://local.example/v1")
                self.assertEqual(os.environ["ISOFTDEVAGENTS_LLM_API_KEY"], "local-key")

    def test_requirements_agent_python_bin_auto_detects_repo_virtualenv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            reagent_python = repo_root / "agent" / "Requirements Agent" / "reagent" / ".venv" / "bin" / "python"
            reagent_python.parent.mkdir(parents=True, exist_ok=True)
            reagent_python.write_text("", encoding="utf-8")

            orchestrator = AgentOrchestrator()
            orchestrator.repo_root = repo_root
            orchestrator.agent_root = repo_root / "agent"

            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(orchestrator._requirements_agent_python_bin(), str(reagent_python))

    def test_architecture_agent_python_bin_auto_detects_repo_virtualenv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            arch_python = repo_root / "agent" / "Architecture Agent" / ".venv" / "bin" / "python"
            arch_python.parent.mkdir(parents=True, exist_ok=True)
            arch_python.write_text("", encoding="utf-8")

            orchestrator = AgentOrchestrator()
            orchestrator.repo_root = repo_root
            orchestrator.agent_root = repo_root / "agent"

            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(orchestrator._architecture_agent_python_bin(), str(arch_python))

    def test_coding_agent_site_packages_dir_auto_detects_repo_virtualenv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            coding_site_packages = (
                repo_root
                / "agent"
                / "Coding Agent"
                / ".venv"
                / "lib"
                / "python3.11"
                / "site-packages"
            )
            coding_site_packages.mkdir(parents=True, exist_ok=True)

            orchestrator = AgentOrchestrator()
            orchestrator.repo_root = repo_root
            orchestrator.agent_root = repo_root / "agent"

            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(orchestrator._coding_agent_site_packages_dir(), str(coding_site_packages))

    def test_coding_agent_python_bin_auto_detects_repo_virtualenv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            coding_python = repo_root / "agent" / "Coding Agent" / ".venv" / "bin" / "python"
            coding_python.parent.mkdir(parents=True, exist_ok=True)
            coding_python.write_text("", encoding="utf-8")

            orchestrator = AgentOrchestrator()
            orchestrator.repo_root = repo_root
            orchestrator.agent_root = repo_root / "agent"

            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(orchestrator._coding_agent_python_bin(), str(coding_python))

    def test_agent_runtime_paths_strip_quoted_env_values(self) -> None:
        orchestrator = AgentOrchestrator()

        with patch.dict(
            os.environ,
            {
                "ISOFTDEVAGENTS_REAGENT_PYTHON_BIN": f'"{sys.executable}"',
                "ISOFTDEVAGENTS_ARCH_AGENT_PYTHON_BIN": "'/tmp/arch/bin/python'",
                "ISOFTDEVAGENTS_CODING_AGENT_PYTHON_BIN": '"/tmp/coding/bin/python"',
                "ISOFTDEVAGENTS_CODING_AGENT_SITE_PACKAGES": '"/tmp/coding/site-packages"',
            },
            clear=True,
        ):
            self.assertEqual(orchestrator._requirements_agent_python_bin(), sys.executable)
            self.assertEqual(orchestrator._architecture_agent_python_bin(), "/tmp/arch/bin/python")
            with patch("app.agents.orchestrator.Path.exists", return_value=True):
                self.assertEqual(orchestrator._coding_agent_python_bin(), "/tmp/coding/bin/python")
            self.assertEqual(orchestrator._coding_agent_site_packages_dir(), "/tmp/coding/site-packages")

    def test_requirements_agent_runtime_diagnostics_reports_bridge_mode_and_runtime_fields(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch.object(
            orchestrator, "_requirements_agent_runtime_available", return_value=True
        ), patch.object(orchestrator, "_requirements_agent_python_bin", return_value=sys.executable), patch.object(
            orchestrator, "_requirements_agent_site_packages_dir", return_value=None
        ):
            diagnostics = orchestrator.requirements_agent_runtime_diagnostics()

        self.assertEqual(diagnostics["bridge_mode"], "inprocess_function_bridge")
        self.assertTrue(diagnostics["enabled"])
        self.assertTrue(diagnostics["runtime_available"])
        self.assertEqual(diagnostics["python_bin"], sys.executable)

    def test_requirements_stream_summary_keeps_task_and_file_progress_only(self) -> None:
        orchestrator = AgentOrchestrator()

        self.assertEqual(
            orchestrator._summarize_requirements_stream_line("Name: business_scope_task", mode="full"),
            "[Requirements Agent task] business_scope_task",
        )
        self.assertEqual(
            orchestrator._summarize_requirements_stream_line("[FeatureTreeDev] Attempt 1/3", mode="analysis"),
            "[Requirements Agent file] feature_tree.md",
        )
        self.assertEqual(
            orchestrator._summarize_requirements_stream_line("请查看现有的business_scope.md文档并告诉我有哪些需要改进的地方：", mode="full"),
            "[Requirements Agent waiting_for_feedback] file=business_scope.md",
        )
        self.assertEqual(
            orchestrator._summarize_requirements_stream_line("[UserIntroductionDev] Failed attempt 5: Expected user_intro too short.", mode="full"),
            "[Requirements Agent error] step=UserIntroductionDev attempt=5 message=Expected user_intro too short.",
        )
        self.assertIsNone(
            orchestrator._summarize_requirements_stream_line("You are Software manager", mode="analysis"),
        )
        self.assertIsNone(
            orchestrator._summarize_requirements_stream_line("Name: Search", mode="analysis"),
        )
        self.assertIsNone(
            orchestrator._summarize_requirements_stream_line("[SurveyCrew] Attempt 1/3", mode="analysis"),
        )
        self.assertEqual(
            orchestrator._summarize_requirements_stream_line("[SurveyCrew] Attempt 1/3", mode="full"),
            "[Requirements Agent file] survey.md",
        )
        self.assertIsNone(
            orchestrator._summarize_requirements_stream_line("You are Software manager", mode="analysis"),
        )

    def test_requirements_agent_python_bin_falls_back_when_explicit_path_is_missing(self) -> None:
        orchestrator = AgentOrchestrator()

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            orchestrator.repo_root = repo_root
            orchestrator.agent_root = repo_root / "agent"

            with patch.dict(
                os.environ,
                {
                    "ISOFTDEVAGENTS_REAGENT_PYTHON_BIN": "/tmp/does-not-exist/python",
                },
                clear=True,
            ):
                self.assertEqual(orchestrator._requirements_agent_python_bin(), "python3")

    def test_requirements_agent_runtime_available_can_fall_back_to_parent_python_when_explicit_path_is_missing(self) -> None:
        orchestrator = AgentOrchestrator()

        with patch.dict(
            os.environ,
            {
                "ISOFTDEVAGENTS_REAGENT_PYTHON_BIN": "/tmp/does-not-exist/python",
            },
            clear=True,
        ), patch("app.agents.orchestrator.subprocess.run") as mocked_run:
            mocked_run.return_value = subprocess.CompletedProcess(args=["python3"], returncode=0)
            self.assertTrue(orchestrator._requirements_agent_runtime_available())

    def test_agent_timeouts_default_to_short_analysis_and_long_generation_windows(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            orchestrator = AgentOrchestrator(timeout=90.0)

        self.assertEqual(orchestrator.timeout, 90.0)
        self.assertEqual(orchestrator.analysis_agent_timeout, 3600.0)
        self.assertEqual(orchestrator.generation_agent_timeout, 3600.0)

    def test_agent_timeouts_support_specific_env_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ISOFTDEVAGENTS_AGENT_TIMEOUT": "420",
                "ISOFTDEVAGENTS_ANALYSIS_AGENT_TIMEOUT": "360",
                "ISOFTDEVAGENTS_GENERATION_AGENT_TIMEOUT": "1200",
            },
            clear=True,
        ):
            orchestrator = AgentOrchestrator(timeout=90.0)

        self.assertEqual(orchestrator.analysis_agent_timeout, 360.0)
        self.assertEqual(orchestrator.generation_agent_timeout, 1200.0)

    def test_agent_timeouts_default_ui_architecture_and_coding_to_generation_timeout(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            orchestrator = AgentOrchestrator(timeout=90.0)

        self.assertEqual(orchestrator.architecture_agent_timeout, 3600.0)
        self.assertEqual(orchestrator.ui_agent_timeout, 3600.0)
        self.assertEqual(orchestrator.coding_agent_timeout, 3600.0)
        self.assertEqual(orchestrator.test_agent_timeout, 3600.0)

    def test_agent_timeouts_support_per_agent_generation_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ISOFTDEVAGENTS_GENERATION_AGENT_TIMEOUT": "2400",
                "ISOFTDEVAGENTS_UI_AGENT_TIMEOUT": "1800",
                "ISOFTDEVAGENTS_ARCHITECTURE_AGENT_TIMEOUT": "2700",
            },
            clear=True,
        ):
            orchestrator = AgentOrchestrator(timeout=90.0)

        self.assertEqual(orchestrator.generation_agent_timeout, 2400.0)
        self.assertEqual(orchestrator.architecture_agent_timeout, 2700.0)
        self.assertEqual(orchestrator.ui_agent_timeout, 1800.0)
        self.assertEqual(orchestrator.coding_agent_timeout, 2400.0)
        self.assertEqual(orchestrator.test_agent_timeout, 2400.0)

    def test_agent_timeouts_support_test_agent_override(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ISOFTDEVAGENTS_GENERATION_AGENT_TIMEOUT": "2400",
                "ISOFTDEVAGENTS_TEST_AGENT_TIMEOUT": "3000",
            },
            clear=True,
        ):
            orchestrator = AgentOrchestrator(timeout=90.0)

        self.assertEqual(orchestrator.generation_agent_timeout, 2400.0)
        self.assertEqual(orchestrator.test_agent_timeout, 3000.0)

    def test_agent_debug_stdio_flag_defaults_to_disabled(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            orchestrator = AgentOrchestrator(timeout=90.0)

        self.assertFalse(orchestrator.debug_agent_stdio)

    def test_agent_debug_stdio_flag_can_be_enabled_from_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ISOFTDEVAGENTS_AGENT_DEBUG_STDIO": "true",
            },
            clear=True,
        ):
            orchestrator = AgentOrchestrator(timeout=90.0)

        self.assertTrue(orchestrator.debug_agent_stdio)

    def test_runtime_model_name_uses_runtime_specific_adaptation(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="gpt-5.4",
        )

        self.assertEqual(orchestrator._runtime_model_name("crewai"), "openai/gpt-5.4")
        self.assertEqual(orchestrator._runtime_model_name("openai_sdk"), "gpt-5.4")

    def test_runtime_model_name_strips_known_provider_prefix_for_openai_sdk(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="openai/gpt-5.4",
        )

        self.assertEqual(orchestrator._runtime_model_name("openai_sdk"), "gpt-5.4")
        self.assertEqual(orchestrator._runtime_model_name("crewai"), "openai/gpt-5.4")

    async def test_run_requirements_agent_inprocess_uses_backend_bridge(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        def fake_run_requirements_agent(**kwargs: Any) -> dict[str, Any]:
            self.assertEqual(kwargs["model"], "openai/moonshot/kimi-k2.5")
            output_root = Path(kwargs["output_root"])
            (output_root / "feature_tree.md").write_text("# Feature Tree\n- Workspace\n", encoding="utf-8")
            return _requirements_runtime_result(output_root, stdout="ok")

        with patch("app.agents.orchestrator.agent_bridge.run_requirements_agent", side_effect=fake_run_requirements_agent) as mocked_run:
            result = await orchestrator._run_requirements_agent_inprocess(
                mode="analysis",
                project_name="demo-project",
                description_text="demo-description",
                timeout=5,
            )

        mocked_run.assert_called_once()
        self.assertEqual(result["stdout"], "ok")
        self.assertTrue(Path(result["output_root"]).exists())

    async def test_run_requirements_agent_inprocess_preserves_bridge_error_output(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        from app.agents.requirements_bridge import RequirementsAgentBridgeExecutionError

        with patch(
            "app.agents.orchestrator.agent_bridge.run_requirements_agent",
            side_effect=RequirementsAgentBridgeExecutionError(
                "analysis crashed early",
                stdout_text="early stdout",
                stderr_text="early stderr",
            ),
        ):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                await orchestrator._run_requirements_agent_inprocess(
                    mode="analysis",
                    project_name="demo-project",
                    description_text="demo-description",
                    timeout=5,
                )

        self.assertEqual(raised.exception.stdout, "early stdout")
        self.assertEqual(raised.exception.stderr, "early stderr")

    def test_log_agent_stream_line_writes_prefixed_terminal_log_when_enabled(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ISOFTDEVAGENTS_AGENT_DEBUG_STDIO": "1",
            },
            clear=True,
        ):
            orchestrator = AgentOrchestrator(timeout=90.0)

        with patch("app.agents.orchestrator.terminal_logger.info") as mocked_info:
            orchestrator._log_agent_stream_line("Requirements Agent", "stdout", "hello world\n")

        mocked_info.assert_called_once_with("[Requirements Agent stdout] hello world")

    def test_persist_agent_debug_bundle_uses_timestamp_directory_names(self) -> None:
        orchestrator = AgentOrchestrator()

        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator.platform_root = Path(temp_dir)

            bundle_root = orchestrator._persist_agent_debug_bundle(
                agent_name="requirements-agent-analysis",
                output_root=None,
                stdout_text="debug output",
            )

            self.assertIsNotNone(bundle_root)
            assert bundle_root is not None
            self.assertRegex(bundle_root.name, r"^failure-\d{8}-\d{6}-\d{6}(?:-\d{2})?$")
            self.assertTrue((bundle_root / "stdout.log").exists())

    def test_write_requirements_agent_runtime_tasks_config_replaces_legacy_competitive_analysis_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "tasks.runtime.yaml"
            orchestrator = AgentOrchestrator()

            orchestrator._write_requirements_agent_runtime_tasks_config(output_path)

            config = yaml.safe_load(output_path.read_text(encoding="utf-8")) or {}
            context_diagram_task = config["draft_context_diagram_task"]["description"]
            brd_task = config["business_requirements_document_task"]["description"]

            self.assertIn("{survey}", context_diagram_task)
            self.assertNotIn("{competitive_analysis}", context_diagram_task)
            self.assertIn("{reference}", brd_task)
            self.assertNotIn("{competitive_analysis}", brd_task)

    def test_write_requirements_agent_runtime_tasks_config_replaces_user_introduction_brd_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "tasks.runtime.yaml"
            orchestrator = AgentOrchestrator()

            orchestrator._write_requirements_agent_runtime_tasks_config(output_path)

            config = yaml.safe_load(output_path.read_text(encoding="utf-8")) or {}
            user_introduction_task = config["user_introduction_draft_task"]["description"]

            self.assertIn("{reference}", user_introduction_task)
            self.assertNotIn("{BRD}", user_introduction_task)

    def test_requirements_agent_runtime_tasks_config_path_avoids_agent_default_runtime_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = AgentOrchestrator()

            output_path = orchestrator._requirements_agent_tasks_config_path(Path(temp_dir))

            self.assertEqual(output_path.name, "tasks.backend.runtime.yaml")
            self.assertNotEqual(output_path.name, "tasks.runtime.yaml")

    async def test_analyze_prompt_leaves_usage_unreported_for_agent_only_execution(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_analyze_with_requirements_agent",
            AsyncMock(
                return_value={
                    "summary": "Requirements analysis summary",
                    "modules": [
                        {
                            "id": "user-system",
                            "label": "User System",
                            "labelEn": "User System",
                            "description": "User auth",
                            "checked": True,
                        }
                    ],
                }
            ),
        ):
            result = await orchestrator.analyze_prompt("Build a CRM")

        self.assertEqual(result["summary"], "Requirements analysis summary")
        self.assertIsNone(orchestrator.consume_last_usage_metadata())

    async def test_analyze_prompt_prefers_requirements_agent_adapter(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_analyze_with_requirements_agent",
            AsyncMock(
                return_value={
                    "summary": "Requirements agent summary",
                    "modules": [
                        {
                            "id": "customer-management",
                            "label": "Customer Management",
                            "labelEn": "Customer Management",
                            "description": "Manage customers",
                            "checked": True,
                        }
                    ],
                }
            ),
        ) as mocked_requirements_agent:
            result = await orchestrator.analyze_prompt("Build a CRM")

        mocked_requirements_agent.assert_awaited_once()
        self.assertEqual(result["summary"], "Requirements agent summary")
        self.assertEqual(result["_meta"]["source"], "requirements_agent")

    async def test_requirements_agent_analysis_runs_inprocess_without_subprocess(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "feature_tree.md").write_text("# Feature Tree\n\n1. Core Gameplay", encoding="utf-8")

            with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), \
                patch.object(orchestrator, "_requirements_agent_runtime_available", return_value=True), \
                patch.object(
                    orchestrator,
                    "_run_requirements_agent_inprocess",
                    return_value={"output_root": output_root, "stdout": "[FeatureTreeDev] Success\n", "stderr": ""},
                ) as mocked_runtime, \
                patch("app.agents.orchestrator.subprocess.run") as mocked_subprocess:
                result = await orchestrator._analyze_with_requirements_agent("Build a snake game", [])

        mocked_runtime.assert_called_once()
        mocked_subprocess.assert_not_called()
        self.assertIsNotNone(result)
        self.assertEqual(result["_meta"]["outputDir"], str(output_root))

    async def test_requirements_agent_full_generation_runs_inprocess_without_subprocess(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "feature_tree.md").write_text("# Feature Tree\n\n1. Core Gameplay", encoding="utf-8")
            (output_root / "business_scope.md").write_text("# Business Scope\n\nGame scope", encoding="utf-8")
            (output_root / "functional_requirements.md").write_text("# Functional Requirements\n\n- Move snake", encoding="utf-8")
            (output_root / "non_functional_requirements.md").write_text("# Non Functional Requirements\n\n- Smooth play", encoding="utf-8")
            (output_root / "use_case.md").write_text("# Use Case\n\n## Play Game", encoding="utf-8")
            (output_root / "SRS.md").write_text("# SRS\n\n## Scope\nSnake game scope\n", encoding="utf-8")

            with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), \
                patch.object(orchestrator, "_requirements_agent_runtime_available", return_value=True), \
                patch.object(
                    orchestrator,
                    "_run_requirements_agent_inprocess",
                    return_value={"output_root": output_root, "stdout": "[FRCrew] Success\n", "stderr": ""},
                ) as mocked_runtime, \
                patch("app.agents.orchestrator.subprocess.run") as mocked_subprocess:
                result = await orchestrator._build_with_requirements_agent_artifacts(
                    prompt="Build a snake game",
                    selected_modules=[{"label": "Gameplay", "labelEn": "Gameplay"}],
                    reference_materials=[],
                    existing_artifacts=[],
                )

        mocked_runtime.assert_called_once()
        mocked_subprocess.assert_not_called()
        self.assertIsNotNone(result)
        self.assertEqual(result["_meta"]["outputDir"], str(output_root))

    async def test_analyze_prompt_repairs_generic_enterprise_modules_for_snake_game_prompt(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_analyze_with_requirements_agent",
            AsyncMock(
                return_value={
                    "summary": "Requirement analysis is complete. Please confirm the suggested feature modules.",
                    "modules": [
                        {
                            "id": "user-system",
                            "label": "User System",
                            "labelEn": "User System",
                            "description": "User registration, sign-in, and access control.",
                            "checked": True,
                        },
                        {
                            "id": "core-business-workflow",
                            "label": "Core Business Workflow",
                            "labelEn": "Core Business Workflow",
                            "description": "The main domain workflow that moves the business process from input to completion.",
                            "checked": True,
                        },
                        {
                            "id": "admin-console",
                            "label": "Admin Console",
                            "labelEn": "Admin Console",
                            "description": "Centralized project, data, and configuration management.",
                            "checked": True,
                        },
                    ],
                }
            ),
        ):
            result = await orchestrator.analyze_prompt("开发一个贪吃蛇项目")

        module_ids = [module["id"] for module in result["modules"]]
        self.assertIn("core-gameplay-mechanics", module_ids)
        self.assertIn("game-state-management", module_ids)
        self.assertNotIn("user-system", module_ids)

    async def test_analyze_prompt_repairs_broken_business_scope_module_for_game_prompt(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_analyze_with_requirements_agent",
            AsyncMock(
                return_value={
                    "summary": "需求分析已完成，请确认建议的功能模块。",
                    "modules": [
                        {
                            "id": "sokoban-scope",
                            "label": "推箱子游戏系统（1-2个关卡）业务范围文档",
                            "labelEn": "推箱子游戏系统（1-2个关卡）业务范围文档",
                            "description": "## 1.业务目标 | | 编号 | 业务目标 | 衡量方式 | 目标值 |",
                            "checked": True,
                        }
                    ],
                }
            ),
        ):
            result = await orchestrator.analyze_prompt("开发一个推箱子游戏")

        module_ids = [module["id"] for module in result["modules"]]
        self.assertIn("core-gameplay-mechanics", module_ids)
        self.assertIn("game-state-management", module_ids)
        self.assertNotIn("sokoban-scope", module_ids)

    async def test_analyze_with_requirements_agent_reads_feature_tree_output(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "feature_tree.md").write_text(
                "- Customer Management\n"
                "  - Customer Profiles\n"
                "- Workflow Automation\n"
                "  - Approval Rules\n"
                "- Reporting Analytics\n"
                "  - KPI Dashboards\n",
                encoding="utf-8",
            )
            (output_root / "functional_requirements.md").write_text(
                "# Functional Requirements\n\n"
                "The platform manages customers, routes approvals, and exposes dashboards.\n",
                encoding="utf-8",
            )
            with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch(
                "app.agents.orchestrator.importlib.util.find_spec",
                return_value=object(),
            ), patch.object(
                orchestrator,
                "_run_requirements_agent_inprocess",
                AsyncMock(return_value=_requirements_runtime_result(output_root)),
            ):
                result = await orchestrator._analyze_with_requirements_agent("Build a CRM", [])

        assert result is not None
        self.assertEqual(result["modules"][0]["id"], "customer-management")
        self.assertEqual(result["modules"][1]["id"], "workflow-automation")
        self.assertIn("routes approvals", result["summary"])
        self.assertEqual(result["_meta"]["source"], "requirements_agent")

    async def test_analyze_with_requirements_agent_sets_usage_metadata_from_runtime(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "feature_tree.md").write_text("- Customer Management\n", encoding="utf-8")
            (output_root / "functional_requirements.md").write_text(
                "# Functional Requirements\n\nCustomer records are managed.\n",
                encoding="utf-8",
            )
            with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch(
                "app.agents.orchestrator.importlib.util.find_spec",
                return_value=object(),
            ), patch.object(
                orchestrator,
                "_run_requirements_agent_inprocess",
                AsyncMock(
                    return_value=_requirements_runtime_result(
                        output_root,
                        usage=_usage_payload(input_tokens=120, output_tokens=45, total_tokens=165),
                    )
                ),
            ):
                result = await orchestrator._analyze_with_requirements_agent("Build a CRM", [])

        assert result is not None
        usage = orchestrator.consume_last_usage_metadata()
        self.assertIsNotNone(usage)
        assert usage is not None
        self.assertEqual(usage["inputTokens"], 120)
        self.assertEqual(usage["outputTokens"], 45)
        self.assertEqual(usage["totalTokens"], 165)
        self.assertEqual(usage["model"], "openai/moonshot/kimi-k2.5")

    def test_parse_feature_tree_modules_supports_numbered_outline(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        modules = orchestrator._parse_feature_tree_modules(
            "1. Core Gameplay Engine\n"
            "   1.1 Snake Entity Management\n"
            "      1.1.1 Directional Movement\n"
            "2. Game State Management\n"
            "   2.1 State Machine\n"
            "      2.1.1 Active Play State\n"
            "3. User Interface (UI)\n"
            "   3.1 Main Menu\n"
            "      3.1.1 Start Game Button\n"
        )

        self.assertEqual(
            [module["labelEn"] for module in modules],
            [
                "Core Gameplay Engine",
                "Game State Management",
                "User Interface (UI)",
            ],
        )
        self.assertIn("Snake Entity Management", modules[0]["description"])
        self.assertEqual(modules[0]["id"], "core-gameplay-engine")

    def test_parse_feature_tree_modules_supports_markdown_heading_outline(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        modules = orchestrator._parse_feature_tree_modules(
            "## Feature Tree: Snake Game\n\n"
            "### 1. Core Gameplay Mechanics\n"
            "   1.1 Snake Movement Engine\n"
            "      1.1.1 Directional Control Processing\n\n"
            "### 2. User Interface & Visualization\n"
            "   2.1 Game Board Rendering\n"
            "      2.1.1 Grid Canvas Setup\n"
        )

        self.assertEqual(
            [module["labelEn"] for module in modules],
            [
                "Core Gameplay Mechanics",
                "User Interface & Visualization",
            ],
        )
        self.assertIn("Snake Movement Engine", modules[0]["description"])

    def test_parse_feature_tree_modules_supports_plain_markdown_heading_outline(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        modules = orchestrator._parse_feature_tree_modules(
            "# Feature Tree: Sokoban Game\n\n"
            "## Game System\n"
            "### Core Game Engine\n"
            "- Level Rendering\n"
            "- Player Movement Control\n"
            "### Level Management\n"
            "- Level Loader\n"
            "- Win Condition Verifier\n"
        )

        self.assertEqual(
            [module["labelEn"] for module in modules],
            [
                "Core Game Engine",
                "Level Management",
            ],
        )
        self.assertIn("Level Rendering", modules[0]["description"])

    def test_parse_feature_tree_modules_supports_l1_l2_l3_outline(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        modules = orchestrator._parse_feature_tree_modules(
            "Feature Tree for gomoku-web-game\n\n"
            "L1: Gomoku Web Game System\n"
            "  L2: Game Board Module\n"
            "    L3: 15x15 grid rendering with clickable cells\n"
            "    L3: Board state data structure (piece positions)\n"
            "  L2: Turn Management Module\n"
            "    L3: Alternating turn logic (Black -> White -> Black)\n"
            "    L3: Turn indicator display\n"
            "  L2: Win Detection Module\n"
            "    L3: Horizontal 5-in-a-row check\n"
            "    L3: Vertical 5-in-a-row check\n"
        )

        self.assertEqual(
            [module["labelEn"] for module in modules],
            [
                "Game Board Module",
                "Turn Management Module",
                "Win Detection Module",
            ],
        )
        self.assertIn("15x15 grid rendering with clickable cells", modules[0]["description"])
        self.assertEqual(modules[0]["id"], "game-board-module")

    def test_parse_feature_tree_modules_supports_l1_l2_l3_dot_outline(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        modules = orchestrator._parse_feature_tree_modules(
            "Feature Tree: Gomoku\n\n"
            "L1. Game Core\n"
            "  L2. Board Management\n"
            "    L3. Grid rendering and display\n"
            "    L3. Stone placement mechanism\n"
            "  L2. Game Rules Engine\n"
            "    L3. Win condition detection\n"
            "    L3. Turn alternation management\n"
        )

        self.assertEqual(
            [module["labelEn"] for module in modules],
            [
                "Board Management",
                "Game Rules Engine",
            ],
        )
        self.assertIn("Grid rendering and display", modules[0]["description"])

    def test_parse_feature_tree_modules_supports_bold_numbered_outline(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        modules = orchestrator._parse_feature_tree_modules(
            "**Feature Tree: Snake Game (贪吃蛇游戏)**\n\n"
            "**1. Game Core**\n"
            "- **1.1 Snake Movement**\n"
            "  - 1.1.1 Direction Control (up, down, left, right)\n"
            "  - 1.1.2 Movement Speed (tick-based timing)\n"
            "- **1.2 Food System**\n"
            "  - 1.2.1 Food Spawning\n"
            "  - 1.2.2 Collision Detection (snake head vs food)\n"
        )

        self.assertEqual(
            [module["labelEn"] for module in modules],
            [
                "Game Core",
            ],
        )
        self.assertIn("Snake Movement", modules[0]["description"])

    def test_requirements_agent_output_snapshot_lists_generated_files(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "business_scope.md").write_text("# Business Scope\n\nSnake game scope.\n", encoding="utf-8")
            (output_root / "nested").mkdir()
            (output_root / "nested" / "notes.txt").write_text("draft notes", encoding="utf-8")

            snapshot = orchestrator._requirements_agent_output_snapshot(output_root)

        self.assertIn("business_scope.md", snapshot)
        self.assertIn("nested/notes.txt", snapshot)

    async def test_analyze_with_requirements_agent_runs_analysis_only_mode(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "feature_tree.md").write_text(
                "- Customer Management\n"
                "  - Lifecycle Tracking\n",
                encoding="utf-8",
            )
            (output_root / "business_scope.md").write_text(
                "# Business Scope\n\nA CRM system for customer lifecycle tracking.\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"ISOFTDEVAGENTS_REAGENT_PYTHON_BIN": sys.executable}, clear=False):
                with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch(
                    "app.agents.orchestrator.importlib.util.find_spec",
                    return_value=object(),
                ), patch.object(
                    orchestrator,
                    "_run_requirements_agent_inprocess",
                    AsyncMock(return_value=_requirements_runtime_result(output_root)),
                ) as mocked_runtime:
                    result = await orchestrator._analyze_with_requirements_agent("Build a CRM", [])

        assert result is not None
        mocked_runtime.assert_awaited_once()
        self.assertEqual(mocked_runtime.await_args.kwargs["mode"], "analysis")
        self.assertEqual(mocked_runtime.await_args.kwargs["project_name"], "build-a-crm")
        self.assertEqual(mocked_runtime.await_args.kwargs["timeout"], orchestrator.analysis_agent_timeout)

    async def test_analyze_with_requirements_agent_accepts_l1_l2_l3_feature_tree_output(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "feature_tree.md").write_text(
                "Feature Tree for gomoku-web-game\n\n"
                "L1: Gomoku Web Game System\n"
                "  L2: Game Board Module\n"
                "    L3: 15x15 grid rendering with clickable cells\n"
                "    L3: Board state data structure (piece positions)\n"
                "  L2: Turn Management Module\n"
                "    L3: Alternating turn logic (Black -> White -> Black)\n"
                "    L3: Turn indicator display\n",
                encoding="utf-8",
            )
            with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch(
                "app.agents.orchestrator.importlib.util.find_spec",
                return_value=object(),
            ), patch.object(
                orchestrator,
                "_run_requirements_agent_inprocess",
                AsyncMock(return_value=_requirements_runtime_result(output_root)),
            ):
                result = await orchestrator._analyze_with_requirements_agent("Build a Gomoku game", [])

        assert result is not None
        self.assertEqual(
            [module["labelEn"] for module in result["modules"]],
            ["Game Board Module", "Turn Management Module"],
        )

    async def test_analyze_with_requirements_agent_uses_custom_python_even_when_backend_env_lacks_crewai(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "feature_tree.md").write_text(
                "- Customer Management\n"
                "  - Profiles\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"ISOFTDEVAGENTS_REAGENT_PYTHON_BIN": sys.executable}, clear=False):
                with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch(
                    "app.agents.orchestrator.importlib.util.find_spec",
                    return_value=None,
                ), patch.object(
                    orchestrator,
                    "_run_requirements_agent_inprocess",
                    AsyncMock(return_value=_requirements_runtime_result(output_root)),
                ):
                    result = await orchestrator._analyze_with_requirements_agent("Build a CRM", [])

        assert result is not None
        self.assertEqual(result["modules"][0]["id"], "customer-management")

    async def test_analyze_with_requirements_agent_passes_normalized_model_to_runtime(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "feature_tree.md").write_text("- Customer Management\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "ISOFTDEVAGENTS_REAGENT_PYTHON_BIN": sys.executable,
                    "ISOFTDEVAGENTS_LLM_MODEL": "moonshot/kimi-k2.5",
                    "OPENAI_MODEL": "moonshot/kimi-k2.5",
                },
                clear=False,
            ):
                with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch.object(
                    orchestrator,
                    "_run_requirements_agent_inprocess",
                    AsyncMock(
                        return_value=_requirements_runtime_result(
                            output_root,
                            model="openai/moonshot/kimi-k2.5",
                        )
                    ),
                ) as mocked_runtime:
                    result = await orchestrator._analyze_with_requirements_agent("Build a CRM", [])

        assert result is not None
        self.assertEqual(mocked_runtime.await_args.kwargs["mode"], "analysis")

    async def test_analyze_with_requirements_agent_raises_diagnostic_error_when_feature_tree_is_missing(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "business_scope.md").write_text(
                "# Business Scope\n\nA CRM system for customer lifecycle tracking and approval workflows.\n",
                encoding="utf-8",
            )
            with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch(
                "app.agents.orchestrator.importlib.util.find_spec",
                return_value=object(),
            ), patch.object(
                orchestrator,
                "_run_requirements_agent_inprocess",
                AsyncMock(return_value=_requirements_runtime_result(output_root)),
            ), patch.object(
                orchestrator,
                "_persist_agent_debug_bundle",
                return_value=Path("/tmp/reagent-debug"),
            ) as mocked_debug_bundle:
                with self.assertRaisesRegex(RuntimeError, "missing feature_tree\\.md"):
                    await orchestrator._analyze_with_requirements_agent("Build a CRM", [])

        mocked_debug_bundle.assert_called_once()

    async def test_analyze_with_requirements_agent_logs_launch_context(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "feature_tree.md").write_text("- Customer Management\n", encoding="utf-8")
            (output_root / "functional_requirements.md").write_text(
                "# Functional Requirements\n\nCustomer records are managed.\n",
                encoding="utf-8",
            )
            with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch(
                "app.agents.orchestrator.importlib.util.find_spec",
                return_value=object(),
            ), patch.object(
                orchestrator,
                "_run_requirements_agent_inprocess",
                AsyncMock(return_value=_requirements_runtime_result(output_root)),
            ), patch("app.agents.orchestrator.logger") as mocked_logger:
                result = await orchestrator._analyze_with_requirements_agent("Build a CRM", [])

        assert result is not None
        self.assertGreaterEqual(mocked_logger.info.call_count, 2)
        self.assertTrue(any("analysis started" in str(call.args[0]) for call in mocked_logger.info.call_args_list))
        self.assertTrue(any("analysis finished" in str(call.args[0]) for call in mocked_logger.info.call_args_list))

    def test_requirements_agent_is_enabled_by_default_outside_tests(self) -> None:
        orchestrator = AgentOrchestrator()

        with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"unittest": None}, clear=False):
            sys.modules.pop("unittest", None)
            self.assertTrue(orchestrator._requirements_agent_enabled())

    async def test_analyze_with_requirements_agent_sets_english_task_config_by_default(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "feature_tree.md").write_text(
                "- Customer Management\n"
                "  - Lifecycle Tracking\n",
                encoding="utf-8",
            )
            (output_root / "functional_requirements.md").write_text(
                "# Functional Requirements\n\nEnglish default task config check.\n",
                encoding="utf-8",
            )
            with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch(
                "app.agents.orchestrator.importlib.util.find_spec",
                return_value=object(),
            ), patch.object(
                orchestrator,
                "_run_requirements_agent_inprocess",
                AsyncMock(return_value=_requirements_runtime_result(output_root)),
            ) as mocked_runtime:
                result = await orchestrator._analyze_with_requirements_agent("Build a CRM", [])

        assert result is not None
        self.assertEqual(mocked_runtime.await_args.kwargs["mode"], "analysis")

    async def test_analyze_with_requirements_agent_uses_partial_output_after_timeout(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "feature_tree.md").write_text(
                "- Customer Management\n"
                "  - Profiles\n"
                "- Workflow Automation\n"
                "  - Approval Rules\n",
                encoding="utf-8",
            )
            (output_root / "functional_requirements.md").write_text(
                "# Functional Requirements\n\nThe platform manages customers and approval workflows.\n",
                encoding="utf-8",
            )
            timeout_error = subprocess.TimeoutExpired(cmd=["requirements-agent", "analysis"], timeout=45.0)
            timeout_error.output_root = str(output_root)
            with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch(
                "app.agents.orchestrator.importlib.util.find_spec",
                return_value=object(),
            ), patch.object(
                orchestrator,
                "_run_requirements_agent_inprocess",
                AsyncMock(side_effect=timeout_error),
            ):
                result = await orchestrator._analyze_with_requirements_agent("Build a CRM", [])

        assert result is not None
        self.assertEqual(result["modules"][0]["id"], "customer-management")
        self.assertEqual(result["_meta"]["status"], "partial_timeout")

    async def test_analyze_with_requirements_agent_salvages_feature_tree_from_stdout_when_file_is_missing(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        stdout = (
            "[FeatureTreeDev] Attempt 1/5\n"
            "╭─────────────────────────────── ✅ Agent Final Answer ────────────────────────────╮\n"
            "│  • **Customer Management**                                                   │\n"
            "│    • Contact Profiles                                                        │\n"
            "│    • Account Timeline                                                        │\n"
            "│  • **Workflow Automation**                                                   │\n"
            "│    • Approval Rules                                                          │\n"
            "│    • SLA Notifications                                                       │\n"
            "╰──────────────────────────────────────────────────────────────────────────────╯\n"
            "╭─────────────────────────────── Tracing Status ───────────────────────────────╮\n"
            "│  • Set tracing=True in your Crew/Flow code                                   │\n"
            "╰──────────────────────────────────────────────────────────────────────────────╯\n"
        )

        with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch(
            "app.agents.orchestrator.importlib.util.find_spec",
            return_value=object(),
        ), patch.object(
            orchestrator,
            "_run_requirements_agent_inprocess",
            AsyncMock(
                side_effect=subprocess.TimeoutExpired(
                    cmd=["requirements-agent", "analysis"],
                    timeout=90.0,
                    output=stdout,
                    stderr="",
                )
            ),
        ):
            result = await orchestrator._analyze_with_requirements_agent("Build a CRM", [])

        assert result is not None
        self.assertEqual(result["modules"][0]["id"], "customer-management")
        self.assertEqual(result["modules"][1]["id"], "workflow-automation")
        self.assertEqual(result["_meta"]["status"], "partial_stdout")

    async def test_analyze_with_requirements_agent_passes_status_callback_to_inprocess_runtime(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )
        streamed: list[str] = []

        async def status_callback(line: str) -> None:
            streamed.append(line)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "feature_tree.md").write_text("- Customer Management\n", encoding="utf-8")
            (output_root / "functional_requirements.md").write_text(
                "# Functional Requirements\n\nCustomer records are managed.\n",
                encoding="utf-8",
            )
            with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch(
                "app.agents.orchestrator.importlib.util.find_spec",
                return_value=object(),
            ), patch.object(
                orchestrator,
                "_run_requirements_agent_inprocess",
                AsyncMock(return_value=_requirements_runtime_result(output_root)),
            ) as mocked_runtime:
                result = await orchestrator._analyze_with_requirements_agent("Build a CRM", [], status_callback=status_callback)

        assert result is not None
        self.assertEqual(streamed, [])
        self.assertIs(mocked_runtime.await_args.kwargs["status_callback"], status_callback)

    def test_curate_status_line_filters_requirements_agent_boilerplate_for_english(self) -> None:
        orchestrator = AgentOrchestrator()

        curated = orchestrator._curate_status_line(
            "Previous output: User feedback: 本轮没有人类意见",
            locale="en",
        )

        self.assertIsNone(curated)

    def test_curate_status_line_filters_requirements_agent_boilerplate_for_chinese(self) -> None:
        orchestrator = AgentOrchestrator()

        curated = orchestrator._curate_status_line(
            "Previous output: User feedback: 本轮没有人类意见",
            locale="zh",
        )

        self.assertIsNone(curated)

    def test_curate_status_line_filters_crewai_trace_enable_hint(self) -> None:
        orchestrator = AgentOrchestrator()

        curated = orchestrator._curate_status_line("Run: crewai traces enable", locale="en")

        self.assertIsNone(curated)

    def test_curate_status_line_filters_crewai_tracing_env_hint(self) -> None:
        orchestrator = AgentOrchestrator()

        curated = orchestrator._curate_status_line(
            "Set CREWAI_TRACING_ENABLED=true in your project's .env file │",
            locale="en",
        )

        self.assertIsNone(curated)

    def test_curate_status_line_filters_missing_reference_boilerplate(self) -> None:
        orchestrator = AgentOrchestrator()

        curated = orchestrator._curate_status_line(
            "No external references provided. │",
            locale="en",
        )

        self.assertIsNone(curated)

    def test_curate_status_line_filters_prompt_template_scaffolding(self) -> None:
        orchestrator = AgentOrchestrator()

        curated = orchestrator._curate_status_line(
            "Previous output: User feedback: 本轮没有人类意见 │",
            locale="zh",
        )

        self.assertIsNone(curated)

    def test_curate_status_line_filters_mermaid_content_lines(self) -> None:
        orchestrator = AgentOrchestrator()

        curated = orchestrator._curate_status_line(
            "SYS -->|Board State Descriptions| AT │",
            locale="en",
        )

        self.assertIsNone(curated)

    def test_curate_status_line_filters_prompt_section_headings(self) -> None:
        orchestrator = AgentOrchestrator()

        curated = orchestrator._curate_status_line(
            "Reference Materials",
            locale="en",
        )

        self.assertIsNone(curated)

    def test_build_requirements_agent_description_marks_image_analysis_references(self) -> None:
        orchestrator = AgentOrchestrator()

        description = orchestrator._build_requirements_agent_description(
            "Build a CRM workspace",
            [
                {
                    "fileName": "screen.png",
                    "contentPreview": "[Image Summary]\n主题：CRM 首页\n可见文字：Sales Dashboard",
                    "summarySource": "image_analysis",
                },
                {
                    "fileName": "brief.md",
                    "contentPreview": "Markdown reference content",
                },
            ],
        )

        self.assertIn("screen.png [Image summary for first-pass analysis]", description)
        self.assertIn("brief.md: Markdown reference content", description)

    def test_requirements_agent_runtime_tasks_config_prefers_english_overrides(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "tasks.runtime.yaml"
            orchestrator._write_requirements_agent_runtime_tasks_config(output_path)
            config = yaml.safe_load(output_path.read_text(encoding="utf-8"))

        survey_description = config["survey_task"]["description"]
        business_scope_description = config["business_scope_task"]["description"]
        use_case_description = config["use_case_draft_task"]["description"]

        self.assertIn("Analyze existing software products", survey_description)
        self.assertIn("Write a business scope document", business_scope_description)
        self.assertIn("Write a set of use cases", use_case_description)
        self.assertNotIn("针对目标产品", survey_description)
        self.assertNotIn("你的任务是", business_scope_description)
        self.assertNotIn("你需要根据给定的", use_case_description)

    async def test_analyze_prompt_requires_requirements_agent_output(self) -> None:
        orchestrator = AgentOrchestrator()

        with patch.object(
            orchestrator,
            "_analyze_with_requirements_agent",
            new=AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "Requirements Agent"):
                await orchestrator.analyze_prompt(
                    "Build a CRM platform for sales teams with customer lifecycle tracking, approval workflows, and analytics dashboards."
                )

    async def test_build_artifacts_requires_requirements_agent_outputs(self) -> None:
        orchestrator = AgentOrchestrator()

        with patch.object(
            orchestrator,
            "_build_with_requirements_agent_artifacts",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orchestrator,
            "_build_with_architecture_agent",
            new=AsyncMock(
                return_value={
                    "architecture": "# Architecture\n\n## Overview\nGenerated by architecture agent.\n",
                    "_meta": {"source": "architecture_agent", "status": "completed"},
                }
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "Requirements Agent"):
                await orchestrator.build_artifacts(
                    prompt="Build a CRM",
                    selected_modules=[{"label": "User System", "labelEn": "User System"}],
                )

    async def test_build_artifacts_requires_architecture_agent_outputs(self) -> None:
        orchestrator = AgentOrchestrator()

        with patch.object(
            orchestrator,
            "_build_with_requirements_agent_artifacts",
            new=AsyncMock(
                return_value={
                    "prd": "# Product Requirements Document\n\n## Overview\nRequirements agent PRD.\n",
                    "ui": "# UI Pages\n\n## Page Inventory\n- Requirements Agent Workspace\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: Requirements Agent API\npaths: {}\n",
                    "_meta": {"source": "requirements_agent", "status": "completed"},
                }
            ),
        ), patch.object(
            orchestrator,
            "_build_with_architecture_agent",
            new=AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "Architecture Agent"):
                await orchestrator.build_artifacts(
                    prompt="Build a CRM",
                    selected_modules=[{"label": "User System", "labelEn": "User System"}],
                )

    async def test_build_artifacts_prefers_architecture_agent_output(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_build_with_architecture_agent",
            AsyncMock(
                return_value={
                    "architecture": "# Architecture\n\n## Overview\nGenerated by architecture agent.\n\n## Diagram\n```mermaid\ngraph TD\nA[Web]-->B[FastAPI]\n```",
                    "_meta": {
                        "source": "architecture_agent",
                        "outputDir": "/tmp/fake-architecture-output",
                    },
                }
            ),
        ) as mocked_architecture_agent, patch.object(
            orchestrator,
            "_build_with_requirements_agent_artifacts",
            AsyncMock(
                return_value={
                    "prd": "# Product Requirements Document\n\n## Overview\nCRM workspace\n",
                    "ui": "# UI Pages\n\n## Page Inventory\n- Dashboard\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                    "_meta": {
                        "source": "requirements_agent",
                        "status": "completed",
                    },
                }
            ),
        ):
            result = await orchestrator.build_artifacts(
                prompt="Build a CRM",
                selected_modules=[{"label": "User System", "labelEn": "User System"}],
            )

        mocked_architecture_agent.assert_awaited_once()
        self.assertIn("Generated by architecture agent.", result["architecture"])
        self.assertEqual(result["_meta"]["architecture"]["source"], "architecture_agent")

    async def test_build_requirements_drafts_sets_usage_metadata(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_build_with_requirements_agent_artifacts",
            AsyncMock(
                return_value={
                    "prd": "# Product Requirements Document\n\n## Overview\nRequirements agent PRD.\n",
                    "ui": "# UI Pages\n\n## Page Inventory\n- Workspace\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: Requirements Agent API\npaths: {}\n",
                    "usage": _usage_payload(input_tokens=210, output_tokens=90, total_tokens=300),
                    "_meta": {"source": "requirements_agent", "status": "completed"},
                }
            ),
        ):
            result = await orchestrator.build_requirements_drafts(
                prompt="Build a CRM",
                selected_modules=[{"label": "Customer Management", "labelEn": "Customer Management"}],
            )

        self.assertIn("Requirements agent PRD", result["prd"])
        usage = orchestrator.consume_last_usage_metadata()
        self.assertIsNotNone(usage)
        assert usage is not None
        self.assertEqual(usage["totalTokens"], 300)
        self.assertEqual(usage["inputTokens"], 210)
        self.assertEqual(usage["outputTokens"], 90)

    def test_read_requirements_agent_artifact_output_requires_srs_document(self) -> None:
        orchestrator = AgentOrchestrator()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "business_scope.md").write_text("# Business Scope\n\nDraft\n", encoding="utf-8")
            (output_root / "feature_tree.md").write_text("# Feature Tree\n\n- Gameplay\n", encoding="utf-8")

            result = orchestrator._read_requirements_agent_artifact_output(
                output_root,
                prompt="开发一个推箱子游戏",
                selected_modules=[{"label": "Core", "labelEn": "Core"}],
            )

        self.assertIsNone(result)

    def test_read_requirements_agent_artifact_output_uses_real_srs_as_prd(self) -> None:
        orchestrator = AgentOrchestrator()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "SRS.md").write_text("# SRS\n\n## 1. Scope\n真实需求规格说明书\n", encoding="utf-8")
            (output_root / "feature_tree.md").write_text("# Feature Tree\n\n- Gameplay\n", encoding="utf-8")
            (output_root / "use_case.md").write_text("[]", encoding="utf-8")

            result = orchestrator._read_requirements_agent_artifact_output(
                output_root,
                prompt="开发一个推箱子游戏",
                selected_modules=[{"label": "Core", "labelEn": "Core"}],
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("真实需求规格说明书", result["prd"])
        self.assertIn("SRS.md", result["_meta"]["sourceFilesByArtifact"]["prd"])

    async def test_build_architecture_draft_sets_usage_metadata(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_build_with_architecture_agent",
            AsyncMock(
                return_value={
                    "architecture": "# Architecture\n\n## Overview\nArchitecture output.\n",
                    "usage": _usage_payload(input_tokens=80, output_tokens=20, total_tokens=100),
                    "_meta": {"source": "architecture_agent", "status": "completed"},
                }
            ),
        ):
            result = await orchestrator.build_architecture_draft(
                prompt="Build a CRM",
                selected_modules=[{"label": "Customer Management", "labelEn": "Customer Management"}],
            )

        self.assertIn("Architecture output", result["architecture"])
        usage = orchestrator.consume_last_usage_metadata()
        self.assertIsNotNone(usage)
        assert usage is not None
        self.assertEqual(usage["totalTokens"], 100)
        self.assertEqual(usage["inputTokens"], 80)
        self.assertEqual(usage["outputTokens"], 20)

    async def test_build_artifacts_merges_requirements_and_architecture_usage_metadata(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_build_with_requirements_agent_artifacts",
            AsyncMock(
                return_value={
                    "prd": "# Product Requirements Document\n\n## Overview\nRequirements output.\n",
                    "ui": "# UI Pages\n\n## Page Inventory\n- Dashboard\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: Requirements Agent API\npaths: {}\n",
                    "usage": _usage_payload(input_tokens=100, output_tokens=40, total_tokens=140),
                    "_meta": {"source": "requirements_agent", "status": "completed"},
                }
            ),
        ), patch.object(
            orchestrator,
            "_build_with_architecture_agent",
            AsyncMock(
                return_value={
                    "architecture": "# Architecture\n\n## Overview\nArchitecture output.\n",
                    "usage": _usage_payload(input_tokens=60, output_tokens=10, total_tokens=70),
                    "_meta": {"source": "architecture_agent", "status": "completed"},
                }
            ),
        ):
            result = await orchestrator.build_artifacts(
                prompt="Build a CRM",
                selected_modules=[{"label": "Customer Management", "labelEn": "Customer Management"}],
            )

        self.assertIn("Requirements output", result["prd"])
        self.assertIn("Architecture output", result["architecture"])
        usage = orchestrator.consume_last_usage_metadata()
        self.assertIsNotNone(usage)
        assert usage is not None
        self.assertEqual(usage["inputTokens"], 160)
        self.assertEqual(usage["outputTokens"], 50)
        self.assertEqual(usage["totalTokens"], 210)

    async def test_build_artifacts_prefers_requirements_agent_prd_when_available(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_build_with_requirements_agent_artifacts",
            AsyncMock(
                return_value={
                    "prd": "# Product Requirements Document\n\n## Overview\nRequirements agent PRD.\n",
                    "ui": "# UI Pages\n\n## Page Inventory\n- Requirements Agent Workspace\n",
                    "api_spec": (
                        "openapi: 3.0.0\n"
                        "info:\n"
                        "  title: Requirements Agent API\n"
                        "  version: 0.1.0\n"
                        "paths: {}\n"
                    ),
                    "_meta": {
                        "source": "requirements_agent",
                        "status": "completed",
                    },
                }
            ),
        ) as mocked_requirements_agent, patch.object(
            orchestrator,
            "_build_with_architecture_agent",
            AsyncMock(
                return_value={
                    "architecture": "# Architecture\n\n## Overview\nArchitecture agent output.\n",
                    "_meta": {
                        "source": "architecture_agent",
                        "status": "completed",
                    },
                }
            ),
        ):
            result = await orchestrator.build_artifacts(
                prompt="Build a CRM",
                selected_modules=[{"label": "User System", "labelEn": "User System"}],
            )

        mocked_requirements_agent.assert_awaited_once()
        self.assertIn("Requirements agent PRD.", result["prd"])
        self.assertNotIn("Remote PRD should not win.", result["prd"])
        self.assertEqual(result["_meta"]["requirements"]["source"], "requirements_agent")

    async def test_build_code_files_returns_only_real_coding_agent_files(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_build_with_coding_agent",
            AsyncMock(
                return_value=[
                    {
                        "filePath": "backend/run.py",
                        "content": "from app import create_app\n\napp = create_app()\n",
                    },
                    {
                        "filePath": "backend/app/api/user_system_api.py",
                        "content": "from fastapi import APIRouter\n",
                    },
                ]
            ),
        ):
            result = await orchestrator.build_code_files(
                prompt="Build a CRM",
                selected_modules=[{"id": "user-system", "labelEn": "User System"}],
                artifacts={
                    "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                    "ui": "# UI Pages\n\n## Page Inventory\n- Dashboard\n",
                    "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                },
            )

        file_paths = {item["filePath"] for item in result}
        self.assertEqual(
            file_paths,
            {
                "backend/run.py",
                "backend/app/api/user_system_api.py",
            },
        )
        self.assertNotIn("docs/PRD.md", file_paths)
        self.assertNotIn("ui/index.html", file_paths)
        self.assertNotIn("src/user-system/index.ts", file_paths)

    async def test_build_code_files_sets_usage_metadata_from_coding_agent_output(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_build_with_coding_agent",
            AsyncMock(
                return_value={
                    "files": [
                        {
                            "filePath": "backend/app/api/customer_management_api.py",
                            "content": "from fastapi import APIRouter\n",
                        }
                    ],
                    "usage": _usage_payload(input_tokens=330, output_tokens=120, total_tokens=450),
                }
            ),
        ):
            result = await orchestrator.build_code_files(
                prompt="Build a CRM",
                selected_modules=[{"id": "customer-management", "labelEn": "Customer Management"}],
                artifacts={
                    "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                    "ui": "# UI Pages\n\n## Page Inventory\n- Dashboard\n",
                    "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                },
            )

        self.assertEqual(result[0]["filePath"], "backend/app/api/customer_management_api.py")
        usage = orchestrator.consume_last_usage_metadata()
        self.assertIsNotNone(usage)
        assert usage is not None
        self.assertEqual(usage["inputTokens"], 330)
        self.assertEqual(usage["outputTokens"], 120)
        self.assertEqual(usage["totalTokens"], 450)

    async def test_build_code_files_requires_coding_agent_output(self) -> None:
        orchestrator = AgentOrchestrator()

        with patch.object(
            orchestrator,
            "_build_with_coding_agent",
            AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "Coding Agent"):
                await orchestrator.build_code_files(
                    prompt="Build a CRM",
                    selected_modules=[{"id": "user-system", "labelEn": "User System"}],
                    artifacts={
                        "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                        "ui": "# UI Pages\n\n## Page Inventory\n- Dashboard\n",
                        "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                        "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                    },
                )

    async def test_build_ui_files_returns_only_real_ui_agent_files(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_build_with_ui_agent",
            AsyncMock(
                return_value=[
                    {
                        "filePath": "page_descriptions.json",
                        "content": '{"pages": []}\n',
                    },
                    {
                        "filePath": "dar_model.json",
                        "content": '{"dar_models": []}\n',
                    },
                    {
                        "filePath": "app/index.html",
                        "content": "<!doctype html>\n",
                    },
                    {
                        "filePath": "app/css/style.css",
                        "content": "body {}\n",
                    },
                    {
                        "filePath": "app/js/index.js",
                        "content": "console.log('ui')\n",
                    },
                ]
            ),
        ):
            result = await orchestrator.build_ui_files(
                prompt="Build a CRM",
                selected_modules=[{"id": "dashboard", "labelEn": "Dashboard"}],
                artifacts={
                    "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                    "ui": "# UI Pages\n\n## Page Inventory\n- Dashboard\n",
                    "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                },
                use_case_text="# Use Case",
                dialog_map_text="# Dialog Map",
            )

        self.assertEqual(
            {item["filePath"] for item in result},
            {
                "page_descriptions.json",
                "dar_model.json",
                "app/index.html",
                "app/css/style.css",
                "app/js/index.js",
            },
        )

    async def test_build_ui_files_requires_ui_agent_output(self) -> None:
        orchestrator = AgentOrchestrator()

        with patch.object(
            orchestrator,
            "_build_with_ui_agent",
            AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "UI Agent"):
                await orchestrator.build_ui_files(
                    prompt="Build a CRM",
                    selected_modules=[{"id": "dashboard", "labelEn": "Dashboard"}],
                    artifacts={
                        "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                        "ui": "# UI Pages\n\n## Page Inventory\n- Dashboard\n",
                        "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                        "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                    },
                    use_case_text="# Use Case",
                    dialog_map_text="# Dialog Map",
                )

    async def test_build_ui_files_reports_incomplete_output_with_generated_file_names(self) -> None:
        orchestrator = AgentOrchestrator()

        with patch.object(
            orchestrator,
            "_build_with_ui_agent",
            AsyncMock(
                return_value=[
                    {
                        "filePath": "page_descriptions.json",
                        "content": '{"pages": []}\n',
                    },
                    {
                        "filePath": "page_descriptions.md",
                        "content": "# Page Descriptions\n",
                    },
                ]
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "UI output is incomplete"):
                await orchestrator.build_ui_files(
                    prompt="Build a CRM",
                    selected_modules=[{"id": "dashboard", "labelEn": "Dashboard"}],
                    artifacts={
                        "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                        "ui": "# UI Pages\n\n## Page Inventory\n- Dashboard\n",
                        "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                        "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                    },
                    use_case_text="# Use Case",
                    dialog_map_text="# Dialog Map",
                )

    async def test_build_test_files_returns_only_real_test_agent_files(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_build_with_test_agent",
            AsyncMock(
                return_value=[
                    {
                        "filePath": "build-a-crm_test_plan.md",
                        "content": "# Test Plan\n",
                    },
                    {
                        "filePath": "memory/test_plan.json",
                        "content": '{"modules": []}\n',
                    },
                    {
                        "filePath": "build-a-crm_testcase.md",
                        "content": "# Test Cases\n",
                    },
                ]
            ),
        ):
            result = await orchestrator.build_test_files(
                prompt="Build a CRM",
                selected_modules=[{"id": "dashboard", "labelEn": "Dashboard"}],
                artifacts={
                    "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                    "ui": "# UI Pages\n\n## Page Inventory\n- Dashboard\n",
                    "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                },
            )

        self.assertEqual(
            {item["filePath"] for item in result},
            {
                "build-a-crm_test_plan.md",
                "memory/test_plan.json",
                "build-a-crm_testcase.md",
            },
        )

    async def test_build_test_files_requires_test_agent_output(self) -> None:
        orchestrator = AgentOrchestrator()

        with patch.object(
            orchestrator,
            "_build_with_test_agent",
            AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "Test Agent"):
                await orchestrator.build_test_files(
                    prompt="Build a CRM",
                    selected_modules=[{"id": "dashboard", "labelEn": "Dashboard"}],
                    artifacts={
                        "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                        "ui": "# UI Pages\n\n## Page Inventory\n- Dashboard\n",
                        "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                        "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                    },
                )

    async def test_build_with_test_agent_uses_unified_bridge_runtime(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        def fake_run_test_agent(**kwargs: Any) -> dict[str, Any]:
            self.assertEqual(kwargs["dataset_name"], "build-a-crm")
            self.assertEqual(kwargs["model"], "openai/moonshot/kimi-k2.5")
            self.assertIn("Product Requirements Document", kwargs["srs_text"])
            self.assertIn("Architecture", kwargs["architecture_text"])
            self.assertTrue(str(kwargs["code_root"]).endswith("/generated-code"))
            return {
                "files": [
                    {
                        "filePath": "build-a-crm_test_plan.md",
                        "content": "# Test Plan\n",
                    }
                ],
                "usage": {"inputTokens": 11, "outputTokens": 7, "totalTokens": 18, "model": "openai/moonshot/kimi-k2.5"},
            }

        with patch.object(orchestrator, "_test_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_test_agent_runtime_available",
            return_value=True,
        ), patch("app.agents.orchestrator.agent_bridge.run_test_agent", side_effect=fake_run_test_agent):
            result = await orchestrator._build_with_test_agent(
                prompt="Build a CRM",
                selected_modules=[{"id": "dashboard", "labelEn": "Dashboard"}],
                artifacts={
                    "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                    "ui": "# UI Pages\n\n## Page Inventory\n- Dashboard\n",
                    "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                },
            )

        assert result is not None
        self.assertEqual(result[0]["filePath"], "build-a-crm_test_plan.md")
        usage = orchestrator.consume_last_usage_metadata()
        self.assertEqual(usage["totalTokens"], 18)

    async def test_build_with_test_agent_forwards_async_runtime_events_back_to_main_loop(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )
        runtime_events: list[dict[str, Any]] = []

        async def runtime_event_callback(payload: dict[str, Any]) -> None:
            runtime_events.append(payload)

        def fake_run_test_agent(**kwargs: Any) -> dict[str, Any]:
            runtime_callback = kwargs.get("runtime_event_callback")
            assert callable(runtime_callback)
            runtime_callback(
                {
                    "runtimeState": "running",
                    "latestOutputFile": "build-a-crm_test_plan.md",
                    "outputDir": "/tmp/test-agent-output",
                }
            )
            return {
                "files": [
                    {
                        "filePath": "build-a-crm_test_plan.md",
                        "content": "# Test Plan\n",
                    }
                ],
                "usage": {"inputTokens": 11, "outputTokens": 7, "totalTokens": 18, "model": "openai/moonshot/kimi-k2.5"},
            }

        with patch.object(orchestrator, "_test_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_test_agent_runtime_available",
            return_value=True,
        ), patch("app.agents.orchestrator.agent_bridge.run_test_agent", side_effect=fake_run_test_agent):
            result = await orchestrator._build_with_test_agent(
                prompt="Build a CRM",
                selected_modules=[{"id": "dashboard", "labelEn": "Dashboard"}],
                artifacts={
                    "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                    "ui": "# UI Pages\n\n## Page Inventory\n- Dashboard\n",
                    "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                },
                runtime_event_callback=runtime_event_callback,
            )

        assert result is not None
        self.assertEqual([item["latestOutputFile"] for item in runtime_events], ["build-a-crm_test_plan.md"])

    async def test_build_with_test_agent_salvages_completed_files_after_timeout(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )
        orchestrator.test_agent_timeout = 0.01

        def fake_run_test_agent(**kwargs: Any) -> dict[str, Any]:
            runtime_home = Path(str(kwargs["runtime_home"]))
            output_root = runtime_home / "output"
            memory_root = runtime_home / "memory"
            output_root.mkdir(parents=True, exist_ok=True)
            memory_root.mkdir(parents=True, exist_ok=True)
            (memory_root / "test_plan.json").write_text('{"modules": []}\n', encoding="utf-8")
            (output_root / "build-a-crm_test_plan.md").write_text("# Test Plan\n", encoding="utf-8")
            (output_root / "build-a-crm_testcase.md").write_text("# Test Cases\n", encoding="utf-8")
            time.sleep(0.05)
            return {"files": []}

        with patch.object(orchestrator, "_test_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_test_agent_runtime_available",
            return_value=True,
        ), patch("app.agents.orchestrator.agent_bridge.run_test_agent", side_effect=fake_run_test_agent):
            result = await orchestrator._build_with_test_agent(
                prompt="Build a CRM",
                selected_modules=[{"id": "dashboard", "labelEn": "Dashboard"}],
                artifacts={
                    "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                    "ui": "# UI Pages\n\n## Page Inventory\n- Dashboard\n",
                    "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                },
            )

        assert result is not None
        self.assertEqual(
            {item["filePath"] for item in result},
            {
                "memory/test_plan.json",
                "build-a-crm_test_plan.md",
                "build-a-crm_testcase.md",
            },
        )

    async def test_build_with_ui_agent_uses_unified_bridge_runtime(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        def fake_run_ui_agent(**kwargs: Any) -> dict[str, Any]:
            self.assertEqual(kwargs["project_name"], "build-a-crm")
            self.assertEqual(kwargs["model"], "moonshot/kimi-k2.5")
            self.assertIn("Use Case", kwargs["use_case_text"])
            self.assertIn("Dialog Map", kwargs["dialog_map_text"])
            self.assertIn("dashboard", kwargs["api_methods"])
            return {
                "files": [
                    {
                        "filePath": "app/index.html",
                        "content": "<!doctype html>\n",
                    }
                ],
                "usage": {"inputTokens": 16, "outputTokens": 10, "totalTokens": 26, "model": "openai/moonshot/kimi-k2.5"},
            }

        with patch.object(orchestrator, "_ui_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_ui_agent_runtime_available",
            return_value=True,
        ), patch("app.agents.orchestrator.agent_bridge.run_ui_agent", side_effect=fake_run_ui_agent):
            result = await orchestrator._build_with_ui_agent(
                prompt="Build a CRM",
                selected_modules=[{"id": "dashboard", "labelEn": "Dashboard"}],
                artifacts={
                    "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                    "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths:\n  /dashboard:\n    get:\n      operationId: listDashboard\n",
                },
                use_case_text="# Use Case",
                dialog_map_text="# Dialog Map",
            )

        assert result is not None
        self.assertEqual(result[0]["filePath"], "app/index.html")
        usage = orchestrator.consume_last_usage_metadata()
        self.assertEqual(usage["totalTokens"], 26)

    async def test_build_with_ui_agent_honors_ui_agent_timeout(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )
        orchestrator.ui_agent_timeout = 12.0

        async def fake_to_thread(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "files": [
                    {
                        "filePath": "app/index.html",
                        "content": "<!doctype html>\n",
                    }
                ]
            }

        async def fake_wait_for(awaitable: Any, timeout: float) -> Any:
            self.assertEqual(timeout, 12.0)
            return await awaitable

        with patch.object(orchestrator, "_ui_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_ui_agent_runtime_available",
            return_value=True,
        ), patch("app.agents.orchestrator.asyncio.to_thread", side_effect=fake_to_thread), patch(
            "app.agents.orchestrator.asyncio.wait_for",
            side_effect=fake_wait_for,
        ):
            result = await orchestrator._build_with_ui_agent(
                prompt="Build a CRM",
                selected_modules=[{"id": "dashboard", "labelEn": "Dashboard"}],
                artifacts={
                    "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                    "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths:\n  /dashboard:\n    get:\n      operationId: listDashboard\n",
                },
                use_case_text="# Use Case",
                dialog_map_text="# Dialog Map",
            )

        assert result is not None
        self.assertEqual(result[0]["filePath"], "app/index.html")

    async def test_build_with_ui_agent_cancellation_persists_debug_and_unregisters(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        def fake_run_ui_agent(**kwargs: Any) -> dict[str, Any]:
            self.assertTrue(kwargs["cancel_event"] is not None)
            raise asyncio.CancelledError()

        with patch.object(orchestrator, "_ui_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_ui_agent_runtime_available",
            return_value=True,
        ), patch(
            "app.agents.orchestrator.agent_bridge.run_ui_agent",
            side_effect=fake_run_ui_agent,
        ), patch.object(
            orchestrator,
            "_persist_ui_agent_debug_bundle",
            return_value=Path("/tmp/agent-debug/ui-agent/failure-cancelled"),
        ) as persist_debug_bundle:
            with self.assertRaises(asyncio.CancelledError):
                await orchestrator._build_with_ui_agent(
                    prompt="Build a CRM",
                    selected_modules=[{"id": "dashboard", "labelEn": "Dashboard"}],
                    artifacts={
                        "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                        "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                        "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths:\n  /dashboard:\n    get:\n      operationId: listDashboard\n",
                    },
                    use_case_text="# Use Case",
                    dialog_map_text="# Dialog Map",
                    task_id="task-ui-cancelled",
                )

        persist_debug_bundle.assert_called_once()
        self.assertEqual(persist_debug_bundle.call_args.kwargs["reason"], "cancelled")
        self.assertEqual(
            workflow.wait_for_running_task_stop("task-ui-cancelled", timeout_seconds=0.01)["stop_reason"],
            "not_registered",
        )

    async def test_build_with_coding_agent_uses_unified_bridge_runtime(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        def fake_run_code_agent(**kwargs: Any) -> dict[str, Any]:
            self.assertEqual(kwargs["model"], "openai/moonshot/kimi-k2.5")
            self.assertEqual(kwargs["python_bin"], "/tmp/coding-agent/.venv/bin/python")
            self.assertIn("backend", kwargs["project_manifest"])
            self.assertIn("project", kwargs["semantic_model"])
            self.assertIn("CRM", kwargs["srs_text"])
            return {
                "files": [
                    {
                        "filePath": "backend/run.py",
                        "content": "from app import create_app\n",
                    }
                ],
                "usage": {"inputTokens": 12, "outputTokens": 8, "totalTokens": 20, "model": "openai/moonshot/kimi-k2.5"},
            }

        with patch.object(orchestrator, "_coding_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_coding_agent_runtime_available",
            return_value=True,
        ), patch.object(
            orchestrator,
            "_coding_agent_python_bin",
            return_value="/tmp/coding-agent/.venv/bin/python",
        ), patch("app.agents.orchestrator.agent_bridge.run_code_agent", side_effect=fake_run_code_agent):
            result = await orchestrator._build_with_coding_agent(
                prompt="Build a CRM",
                selected_modules=[{"id": "workflow-automation", "labelEn": "Workflow Automation"}],
                artifacts={
                    "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                    "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                },
            )

        assert result is not None
        self.assertEqual(result[0]["filePath"], "backend/run.py")
        usage = orchestrator.consume_last_usage_metadata()
        self.assertEqual(usage["totalTokens"], 20)

    async def test_build_with_coding_agent_streams_printed_status_callback_lines(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )
        streamed: list[str] = []

        async def status_callback(line: str) -> None:
            streamed.append(line)

        def fake_run_code_agent(**kwargs: Any) -> dict[str, Any]:
            stdout_handler = kwargs.get("stdout_line_handler")
            if callable(stdout_handler):
                stdout_handler("Code generation pipeline started")
                stdout_handler("Generating backend/run.py")
            return {
                "files": [
                    {
                        "filePath": "backend/run.py",
                        "content": "from app import create_app\n",
                    }
                ]
            }

        with patch.object(orchestrator, "_coding_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_coding_agent_runtime_available",
            return_value=True,
        ), patch.object(
            orchestrator,
            "_coding_agent_python_bin",
            return_value="/tmp/coding-agent/.venv/bin/python",
        ), patch("app.agents.orchestrator.agent_bridge.run_code_agent", side_effect=fake_run_code_agent):
            result = await orchestrator._build_with_coding_agent(
                prompt="Build a CRM",
                selected_modules=[{"id": "workflow-automation", "labelEn": "Workflow Automation"}],
                artifacts={
                    "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                    "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                },
                status_callback=status_callback,
            )

        assert result is not None
        self.assertTrue(any("Coding Agent" in line and "Code generation pipeline started" in line for line in streamed))
        self.assertTrue(any("Coding Agent" in line and "Generating backend/run.py" in line for line in streamed))

    async def test_build_with_coding_agent_removes_runtime_directory_after_success_when_zero_residual_enabled(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )
        observed_runtime_home: dict[str, Path] = {}

        def fake_run_code_agent(**kwargs: Any) -> dict[str, Any]:
            runtime_home = Path(str(kwargs["runtime_home"]))
            observed_runtime_home["path"] = runtime_home
            runtime_home.mkdir(parents=True, exist_ok=True)
            (runtime_home / "marker.txt").write_text("runtime marker", encoding="utf-8")
            return {
                "files": [
                    {
                        "filePath": "backend/run.py",
                        "content": "from app import create_app\n",
                    }
                ],
                "usage": {"inputTokens": 12, "outputTokens": 8, "totalTokens": 20, "model": "openai/moonshot/kimi-k2.5"},
            }

        with patch.dict(os.environ, {"ISOFTDEVAGENTS_DELETE_LOCAL_FILES_AFTER_PERSIST": "1"}, clear=False), patch.object(
            orchestrator, "_coding_agent_enabled", return_value=True
        ), patch.object(
            orchestrator,
            "_coding_agent_runtime_available",
            return_value=True,
        ), patch.object(
            orchestrator,
            "_coding_agent_python_bin",
            return_value="/tmp/coding-agent/.venv/bin/python",
        ), patch("app.agents.orchestrator.agent_bridge.run_code_agent", side_effect=fake_run_code_agent):
            result = await orchestrator._build_with_coding_agent(
                prompt="Build a CRM",
                selected_modules=[{"id": "workflow-automation", "labelEn": "Workflow Automation"}],
                artifacts={
                    "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                    "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                },
            )

        assert result is not None
        self.assertIn("path", observed_runtime_home)
        self.assertFalse(observed_runtime_home["path"].exists())

    async def test_build_with_coding_agent_persists_debug_bundle_when_timeout_happens(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        async def fake_wait_for(_awaitable: Any, timeout: float) -> Any:
            self.assertEqual(timeout, orchestrator.coding_agent_timeout)
            if hasattr(_awaitable, "close"):
                _awaitable.close()
            raise asyncio.TimeoutError()

        with patch.object(orchestrator, "_coding_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_coding_agent_runtime_available",
            return_value=True,
        ), patch.object(
            orchestrator,
            "_coding_agent_python_bin",
            return_value="/tmp/coding-agent/.venv/bin/python",
        ), patch(
            "app.agents.orchestrator.asyncio.to_thread",
            side_effect=lambda *args, **kwargs: asyncio.sleep(3600),
        ), patch("app.agents.orchestrator.asyncio.wait_for", side_effect=fake_wait_for), patch.object(
            orchestrator,
            "_persist_agent_debug_bundle",
            return_value=Path("/tmp/agent-debug/coding-agent/failure-test"),
        ) as persist_debug_bundle:
            with self.assertRaises(RuntimeError):
                await orchestrator._build_with_coding_agent(
                    prompt="Build a CRM",
                    selected_modules=[{"id": "workflow-automation", "labelEn": "Workflow Automation"}],
                    artifacts={
                        "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                        "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                        "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                    },
                )

        persist_debug_bundle.assert_called_once()
        self.assertEqual(persist_debug_bundle.call_args.kwargs["agent_name"], "coding-agent")

    async def test_build_with_coding_agent_cancellation_persists_debug_and_unregisters(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        def fake_run_code_agent(**kwargs: Any) -> dict[str, Any]:
            self.assertTrue(kwargs["cancel_event"] is not None)
            raise asyncio.CancelledError()

        with patch.object(orchestrator, "_coding_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_coding_agent_runtime_available",
            return_value=True,
        ), patch.object(
            orchestrator,
            "_coding_agent_python_bin",
            return_value="/tmp/coding-agent/.venv/bin/python",
        ), patch(
            "app.agents.orchestrator.agent_bridge.run_code_agent",
            side_effect=fake_run_code_agent,
        ), patch.object(
            orchestrator,
            "_persist_agent_debug_bundle",
            return_value=Path("/tmp/agent-debug/coding-agent/failure-cancelled"),
        ) as persist_debug_bundle:
            with self.assertRaises(asyncio.CancelledError):
                await orchestrator._build_with_coding_agent(
                    prompt="Build a CRM",
                    selected_modules=[{"id": "workflow-automation", "labelEn": "Workflow Automation"}],
                    artifacts={
                        "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                        "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                        "api_spec": "openapi: 3.0.0\ninfo:\n  title: CRM API\npaths: {}\n",
                    },
                    task_id="task-coding-cancelled",
                )

        persist_debug_bundle.assert_called_once()
        self.assertEqual(persist_debug_bundle.call_args.kwargs["agent_name"], "coding-agent")
        self.assertEqual(persist_debug_bundle.call_args.kwargs["context"]["reason"], "cancelled")
        self.assertEqual(
            workflow.wait_for_running_task_stop("task-coding-cancelled", timeout_seconds=0.01)["stop_reason"],
            "not_registered",
        )

    async def test_build_with_test_agent_persists_debug_bundle_when_timeout_has_no_salvage(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        async def fake_wait_for(_awaitable: Any, timeout: float) -> Any:
            self.assertEqual(timeout, orchestrator.test_agent_timeout)
            if hasattr(_awaitable, "close"):
                _awaitable.close()
            raise asyncio.TimeoutError()

        with patch.object(orchestrator, "_test_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_test_agent_runtime_available",
            return_value=True,
        ), patch(
            "app.agents.orchestrator.asyncio.to_thread",
            side_effect=lambda *args, **kwargs: asyncio.sleep(3600),
        ), patch("app.agents.orchestrator.asyncio.wait_for", side_effect=fake_wait_for), patch.object(
            orchestrator,
            "_salvage_test_agent_files_from_runtime_home",
            return_value=None,
        ), patch.object(
            orchestrator,
            "_persist_agent_debug_bundle",
            return_value=Path("/tmp/agent-debug/test-agent/failure-test"),
        ) as persist_debug_bundle:
            with self.assertRaises(RuntimeError):
                await orchestrator._build_with_test_agent(
                    prompt="Build a CRM",
                    selected_modules=[{"id": "workflow-automation", "labelEn": "Workflow Automation"}],
                    artifacts={
                        "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                        "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                    },
                )

        persist_debug_bundle.assert_called_once()
        self.assertEqual(persist_debug_bundle.call_args.kwargs["agent_name"], "test-agent")

    async def test_build_with_test_agent_cancellation_persists_debug_and_unregisters(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        def fake_run_test_agent(**kwargs: Any) -> dict[str, Any]:
            self.assertTrue(kwargs["cancel_event"] is not None)
            raise asyncio.CancelledError()

        with patch.object(orchestrator, "_test_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_test_agent_runtime_available",
            return_value=True,
        ), patch(
            "app.agents.orchestrator.agent_bridge.run_test_agent",
            side_effect=fake_run_test_agent,
        ), patch.object(
            orchestrator,
            "_persist_agent_debug_bundle",
            return_value=Path("/tmp/agent-debug/test-agent/failure-cancelled"),
        ) as persist_debug_bundle:
            with self.assertRaises(asyncio.CancelledError):
                await orchestrator._build_with_test_agent(
                    prompt="Build a CRM",
                    selected_modules=[{"id": "workflow-automation", "labelEn": "Workflow Automation"}],
                    artifacts={
                        "prd": "# Product Requirements Document\n\n## Overview\nCRM\n",
                        "architecture": "# Architecture\n\n## Overview\nFastAPI backend\n",
                    },
                    task_id="task-test-cancelled",
                )

        persist_debug_bundle.assert_called_once()
        self.assertEqual(persist_debug_bundle.call_args.kwargs["agent_name"], "test-agent")
        self.assertEqual(persist_debug_bundle.call_args.kwargs["context"]["reason"], "cancelled")
        self.assertEqual(
            workflow.wait_for_running_task_stop("task-test-cancelled", timeout_seconds=0.01)["stop_reason"],
            "not_registered",
        )

    async def test_build_with_requirements_agent_artifacts_runs_full_mode_and_reads_outputs(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "business_scope.md").write_text(
                "# Business Scope\n\nThe platform supports customer lifecycle management and approvals.\n",
                encoding="utf-8",
            )
            (output_root / "feature_tree.md").write_text(
                "- Customer Management\n"
                "  - Profiles\n"
                "- Workflow Automation\n"
                "  - Approval Rules\n",
                encoding="utf-8",
            )
            (output_root / "functional_requirements.md").write_text(
                "# Functional Requirements\n\n- Maintain customer records.\n- Route approval requests.\n",
                encoding="utf-8",
            )
            (output_root / "non_functional_requirements.md").write_text(
                "# Non-Functional Requirements\n\n- Responsive web UI.\n- Python backend APIs.\n",
                encoding="utf-8",
            )
            (output_root / "use_case.md").write_text(
                json.dumps(
                    [
                        {
                            "use_case_name": "Manage Customers",
                            "primary_actor": "Operations Manager",
                            "secondary_actor": "",
                            "use_case_description": "Create and update customer profiles.",
                            "preconditions": ["User is signed in"],
                            "postconditions": ["Customer profile is stored"],
                            "main_flow": ["Open customer workspace", "Save profile"],
                            "alternative_flows": [],
                            "exception_flows": [],
                            "priority": "high",
                            "business_rules": [],
                            "assumptions": [],
                            "other_constraints": [],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (output_root / "SRS.md").write_text(
                "# SRS\n\n## Scope\nThe platform supports customer lifecycle management and approvals.\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"ISOFTDEVAGENTS_REAGENT_PYTHON_BIN": sys.executable}, clear=False):
                with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch(
                    "app.agents.orchestrator.importlib.util.find_spec",
                    return_value=object(),
                ), patch.object(
                    orchestrator,
                    "_run_requirements_agent_inprocess",
                    AsyncMock(return_value=_requirements_runtime_result(output_root)),
                ) as mocked_runtime:
                    result = await orchestrator._build_with_requirements_agent_artifacts(
                        prompt="Build a CRM",
                        selected_modules=[{"label": "Customer Management", "labelEn": "Customer Management"}],
                        reference_materials=[],
                        existing_artifacts=[],
                    )

        assert result is not None
        self.assertEqual(mocked_runtime.await_args.kwargs["mode"], "full")
        self.assertEqual(mocked_runtime.await_args.kwargs["project_name"], "build-a-crm")
        self.assertIn("customer lifecycle management", result["prd"])
        self.assertIn("Customer Management Workspace", result["ui"])
        self.assertIn("/api/customer-management", result["api_spec"])

    async def test_build_with_requirements_agent_artifacts_persists_debug_bundle_for_partial_non_zero_output(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "business_scope.md").write_text(
                "# Business Scope\n\nOnly the first draft step completed.\n",
                encoding="utf-8",
            )
            exc = subprocess.CalledProcessError(
                1,
                ["requirements-agent", "full"],
                output="stdout before crash",
                stderr="stderr before crash",
            )
            exc.output_root = str(output_root)

            with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch.object(
                orchestrator,
                "_requirements_agent_runtime_available",
                return_value=True,
            ), patch.object(
                orchestrator,
                "_run_requirements_agent_inprocess",
                AsyncMock(side_effect=exc),
            ), patch.object(
                orchestrator,
                "_persist_agent_debug_bundle",
                return_value=Path("/tmp/reagent-debug"),
            ) as mocked_debug_bundle, patch("app.agents.orchestrator.logger") as mocked_logger:
                result = await orchestrator._build_with_requirements_agent_artifacts(
                    prompt="Build a CRM",
                    selected_modules=[{"label": "Customer Management", "labelEn": "Customer Management"}],
                    reference_materials=[],
                    existing_artifacts=[],
                )

        self.assertIsNone(result)
        mocked_debug_bundle.assert_called_once()
        self.assertEqual(mocked_debug_bundle.call_args.kwargs["stdout_text"], "stdout before crash")
        self.assertEqual(mocked_debug_bundle.call_args.kwargs["stderr_text"], "stderr before crash")
        self.assertTrue(
            any("stdout_preview=%s stderr_preview=%s" in str(call.args[0]) for call in mocked_logger.error.call_args_list)
        )

    async def test_build_requirements_drafts_raises_helpful_message_when_required_outputs_are_missing(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_build_with_requirements_agent_artifacts",
            AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "missing SRS\\.md"):
                await orchestrator.build_requirements_drafts(
                    prompt="Build a CRM",
                    selected_modules=[{"label": "Customer Management", "labelEn": "Customer Management"}],
                )

    async def test_build_with_architecture_agent_uses_unified_bridge_and_reads_output_dir(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )
        streamed: list[str] = []
        output_dir = Path(tempfile.mkdtemp(prefix="arch-agent-output-"))
        (output_dir / "analysis_task_output.txt").write_text("Architecture analysis", encoding="utf-8")

        async def status_callback(line: str) -> None:
            streamed.append(line)

        def fake_run_architecture_agent(**kwargs: Any) -> dict[str, Any]:
            self.assertEqual(kwargs["model"], "moonshot/kimi-k2.5")
            stdout_handler = kwargs.get("stdout_line_handler")
            if callable(stdout_handler):
                stdout_handler("Analyzing architecture constraints")
                stdout_handler("Generating service topology")
            return {
                "output_dir": str(output_dir),
                "usage": {"totalTokens": 12, "inputTokens": 8, "outputTokens": 4},
            }

        with patch.object(orchestrator, "_architecture_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_architecture_agent_runtime_available",
            return_value=True,
        ), patch.object(
            orchestrator,
            "_read_architecture_agent_output",
            return_value={"architecture": "# Architecture\n\nGenerated\n"},
        ), patch("app.agents.orchestrator.agent_bridge.run_architecture_agent", side_effect=fake_run_architecture_agent):
            result = await orchestrator._build_with_architecture_agent(
                prompt="Build a CRM",
                selected_modules=[{"label": "User System", "labelEn": "User System"}],
                reference_materials=[],
                existing_artifacts=[],
                status_callback=status_callback,
            )

        assert result is not None
        self.assertTrue(any("Architecture Agent" in line and "Analyzing architecture constraints" in line for line in streamed))
        self.assertTrue(any("Architecture Agent" in line and "Generating service topology" in line for line in streamed))
        self.assertEqual(result["usage"]["totalTokens"], 12)

    async def test_build_with_architecture_agent_strips_openai_prefix_for_openai_sdk_runtime(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="openai/gpt-5.4",
        )
        output_dir = Path(tempfile.mkdtemp(prefix="arch-agent-output-"))
        (output_dir / "analysis_task_output.txt").write_text("Architecture analysis", encoding="utf-8")

        def fake_run_architecture_agent(**kwargs: Any) -> dict[str, Any]:
            self.assertEqual(kwargs["model"], "gpt-5.4")
            return {"output_dir": str(output_dir)}

        with patch.object(orchestrator, "_architecture_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_architecture_agent_runtime_available",
            return_value=True,
        ), patch.object(
            orchestrator,
            "_read_architecture_agent_output",
            return_value={"architecture": "# Architecture\n\nGenerated\n"},
        ), patch("app.agents.orchestrator.agent_bridge.run_architecture_agent", side_effect=fake_run_architecture_agent):
            result = await orchestrator._build_with_architecture_agent(
                prompt="Build a CRM",
                selected_modules=[{"label": "User System", "labelEn": "User System"}],
                reference_materials=[],
                existing_artifacts=[],
            )

        assert result is not None

    def test_architecture_agent_payload_from_files_requires_real_architecture_files(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        payload = orchestrator._architecture_agent_payload_from_files(
            {
                "analysis_task_output.txt": "Architecture analysis only",
            },
            output_dir="/tmp/architecture-output",
        )

        self.assertIsNone(payload)

    def test_architecture_agent_payload_from_files_requires_class_design_before_recovery(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        payload = orchestrator._architecture_agent_payload_from_files(
            {
                "component_design.json": json.dumps(
                    {
                        "component_diagram": "graph TD\nA-->B",
                        "components": [],
                    },
                    ensure_ascii=False,
                ),
                "analysis_task_output.txt": "Architecture analysis",
            },
            output_dir="/tmp/architecture-output",
            status="recovered_live_output",
        )

        self.assertIsNone(payload)

    def test_architecture_agent_payload_from_files_requires_structured_class_design_before_recovery(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        payload = orchestrator._architecture_agent_payload_from_files(
            {
                "component_design.json": json.dumps(
                    {
                        "component_diagram": "graph TD\nA-->B",
                        "components": [],
                    },
                    ensure_ascii=False,
                ),
                "class_design_raw.md": "# Class Design\n\n- GameService",
                "analysis_task_output.txt": "Architecture analysis",
            },
            output_dir="/tmp/architecture-output",
            status="recovered_live_output",
        )

        self.assertIsNone(payload)

    async def test_build_with_architecture_agent_forwards_async_runtime_events_back_to_main_loop(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )
        output_dir = Path(tempfile.mkdtemp(prefix="arch-agent-output-"))
        (output_dir / "analysis_task_output.txt").write_text("Architecture analysis", encoding="utf-8")
        runtime_events: list[dict[str, Any]] = []

        async def runtime_event_callback(payload: dict[str, Any]) -> None:
            runtime_events.append(payload)

        def fake_run_architecture_agent(**kwargs: Any) -> dict[str, Any]:
            runtime_callback = kwargs.get("runtime_event_callback")
            assert callable(runtime_callback)
            runtime_callback(
                {
                    "runtimePid": 43210,
                    "runtimeState": "running",
                    "latestOutputFile": "analysis_task_output.txt",
                    "outputDir": str(output_dir),
                }
            )
            return {
                "output_dir": str(output_dir),
                "usage": {"totalTokens": 12, "inputTokens": 8, "outputTokens": 4},
            }

        with patch.object(orchestrator, "_architecture_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_read_architecture_agent_output",
            return_value={"architecture": "# Architecture\n\nGenerated\n"},
        ), patch("app.agents.orchestrator.agent_bridge.run_architecture_agent", side_effect=fake_run_architecture_agent):
            result = await orchestrator._build_with_architecture_agent(
                prompt="Build a CRM",
                selected_modules=[{"label": "User System", "labelEn": "User System"}],
                reference_materials=[],
                existing_artifacts=[],
                runtime_event_callback=runtime_event_callback,
            )

        assert result is not None
        self.assertEqual([item["latestOutputFile"] for item in runtime_events], ["analysis_task_output.txt"])

    async def test_build_with_architecture_agent_updates_registry_from_stream_output(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )
        output_dir = Path(tempfile.mkdtemp(prefix="arch-agent-output-"))
        (output_dir / "analysis_task_output.txt").write_text("Architecture analysis", encoding="utf-8")
        registry_updates: list[dict[str, Any]] = []

        def fake_update_running_task(task_id: str, **updates: Any) -> None:
            registry_updates.append({"task_id": task_id, **updates})

        def fake_run_architecture_agent(**kwargs: Any) -> dict[str, Any]:
            stdout_handler = kwargs.get("stdout_line_handler")
            stderr_handler = kwargs.get("stderr_line_handler")
            assert callable(stdout_handler)
            assert callable(stderr_handler)
            stdout_handler("Generating analysis_task_output.txt")
            stderr_handler("Architecture warning line")
            return {"output_dir": str(output_dir)}

        with patch.object(orchestrator, "_architecture_agent_enabled", return_value=True), patch.object(
            orchestrator,
            "_read_architecture_agent_output",
            return_value={"architecture": "# Architecture\n\nGenerated\n"},
        ), patch("app.agents.orchestrator.agent_bridge.run_architecture_agent", side_effect=fake_run_architecture_agent), patch(
            "app.services.workflow.update_running_task",
            side_effect=fake_update_running_task,
        ):
            result = await orchestrator._build_with_architecture_agent(
                prompt="Build a CRM",
                selected_modules=[{"label": "User System", "labelEn": "User System"}],
                reference_materials=[],
                existing_artifacts=[],
                task_id="task-architecture-stream-registry",
            )

        assert result is not None
        self.assertTrue(
            any(update.get("stdout_preview") == "Generating analysis_task_output.txt" for update in registry_updates)
        )
        self.assertTrue(any(update.get("stderr_preview") == "Architecture warning line" for update in registry_updates))
        self.assertEqual(
            workflow.wait_for_running_task_stop("task-architecture-stream-registry", timeout_seconds=0.01)["stop_reason"],
            "not_registered",
        )

    async def test_build_with_architecture_agent_cancellation_persists_debug_and_unregisters(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        def fake_run_architecture_agent(**kwargs: Any) -> dict[str, Any]:
            self.assertTrue(kwargs["cancel_event"] is not None)
            raise asyncio.CancelledError()

        with patch.object(orchestrator, "_architecture_agent_enabled", return_value=True), patch(
            "app.agents.orchestrator.agent_bridge.run_architecture_agent",
            side_effect=fake_run_architecture_agent,
        ), patch.object(
            orchestrator,
            "_persist_agent_debug_bundle",
            return_value=Path("/tmp/agent-debug/architecture-agent/failure-cancelled"),
        ) as persist_debug_bundle:
            with self.assertRaises(asyncio.CancelledError):
                await orchestrator._build_with_architecture_agent(
                    prompt="Build a CRM",
                    selected_modules=[{"label": "User System", "labelEn": "User System"}],
                    reference_materials=[],
                    existing_artifacts=[],
                    task_id="task-architecture-cancelled",
                )

        persist_debug_bundle.assert_called_once()
        self.assertEqual(persist_debug_bundle.call_args.kwargs["agent_name"], "architecture-agent")
        self.assertEqual(persist_debug_bundle.call_args.kwargs["context"]["reason"], "cancelled")
        self.assertEqual(
            workflow.wait_for_running_task_stop("task-architecture-cancelled", timeout_seconds=0.01)["stop_reason"],
            "not_registered",
        )

    async def test_build_with_architecture_agent_persists_debug_bundle_when_timeout_happens(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        timeout_error = subprocess.TimeoutExpired(
            cmd=["python3", "arch-agent"],
            timeout=orchestrator.architecture_agent_timeout,
            output="arch stdout",
            stderr="arch stderr",
        )

        with patch.object(orchestrator, "_architecture_agent_enabled", return_value=True), patch(
            "app.agents.orchestrator.agent_bridge.run_architecture_agent",
            side_effect=timeout_error,
        ), patch.object(
            orchestrator,
            "_persist_agent_debug_bundle",
            return_value=Path("/tmp/agent-debug/architecture-agent/failure-test"),
        ) as persist_debug_bundle:
            with self.assertRaises(RuntimeError):
                await orchestrator._build_with_architecture_agent(
                    prompt="Build a CRM",
                    selected_modules=[{"label": "User System", "labelEn": "User System"}],
                    reference_materials=[],
                    existing_artifacts=[],
                )

        persist_debug_bundle.assert_called_once()
        self.assertEqual(persist_debug_bundle.call_args.kwargs["agent_name"], "architecture-agent")

    async def test_build_artifacts_emits_architecture_handoff_status(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )
        streamed: list[str] = []

        async def status_callback(line: str) -> None:
            streamed.append(line)

        with patch.object(
            orchestrator,
            "_build_with_requirements_agent_artifacts",
            AsyncMock(
                return_value={
                    "prd": "# PRD",
                    "ui": "# UI",
                    "api_spec": "openapi: 3.0.0\npaths: {}\n",
                    "_meta": {},
                }
            ),
        ), patch.object(
            orchestrator,
            "_build_with_architecture_agent",
            AsyncMock(return_value={"architecture": "# Architecture", "_meta": {}}),
        ):
            result = await orchestrator.build_artifacts(
                prompt="Build a snake game",
                selected_modules=[{"label": "Gameplay", "labelEn": "Gameplay"}],
                status_callback=status_callback,
            )

        assert result is not None
        self.assertTrue(any(line == "Architecture Agent: Generating analysis_task_output.txt." for line in streamed))

    def test_read_architecture_agent_output_salvages_analysis_output_when_design_files_are_missing(self) -> None:
        orchestrator = AgentOrchestrator()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "analysis_task_output.txt").write_text(
                "Architecture analysis summary.\n\n- Web frontend\n- FastAPI backend\n- SQLite storage\n",
                encoding="utf-8",
            )

            result = orchestrator._read_architecture_agent_output(output_dir)

        assert result is not None
        self.assertIn("Architecture analysis summary.", result["architecture"])
        self.assertEqual(
            result["_meta"]["sourceFilesByArtifact"]["architecture"],
            ["analysis_task_output.txt"],
        )

    async def test_build_with_requirements_agent_artifacts_includes_existing_artifact_content_in_description(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        seen_description = ""
        output_root = Path(tempfile.mkdtemp(prefix="reagent-existing-artifact-"))

        async def fake_runtime(**kwargs):
            nonlocal seen_description
            seen_description = kwargs["description_text"]
            (output_root / "business_scope.md").write_text(
                "# Business Scope\n\nUpdated scope for the modified CRM.\n",
                encoding="utf-8",
            )
            (output_root / "SRS.md").write_text(
                "# SRS\n\n## Scope\nUpdated scope for the modified CRM.\n",
                encoding="utf-8",
            )
            return _requirements_runtime_result(output_root)

        with patch.dict(os.environ, {"ISOFTDEVAGENTS_REAGENT_PYTHON_BIN": sys.executable}, clear=False):
            with patch.object(orchestrator, "_requirements_agent_enabled", return_value=True), patch(
                "app.agents.orchestrator.importlib.util.find_spec",
                return_value=object(),
            ), patch.object(
                orchestrator,
                "_run_requirements_agent_inprocess",
                AsyncMock(side_effect=fake_runtime),
            ):
                result = await orchestrator._build_with_requirements_agent_artifacts(
                    prompt="Update login to phone number sign-in",
                    selected_modules=[{"label": "User System", "labelEn": "User System"}],
                    reference_materials=[],
                    existing_artifacts=[
                        {
                            "type": "prd",
                            "title": "PRD Draft",
                            "content": "# Product Requirements Document\n\n## Overview\nCurrent login uses email and password.\n",
                        }
                    ],
                )

        assert result is not None
        self.assertIn("Update login to phone number sign-in", seen_description)
        self.assertIn("Current login uses email and password.", seen_description)
        self.assertIn("## Existing Artifacts", seen_description)

    async def test_build_artifacts_normalizes_agent_payloads(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_build_with_requirements_agent_artifacts",
            AsyncMock(
                return_value={
                    "prd": "Overview: CRM dashboard for sales teams.",
                    "ui": {
                        "pages": [
                            {
                                "id": "home",
                                "name": "Dashboard",
                                "route": "/",
                                "previewUrl": "/ui/dashboard.html",
                            }
                        ]
                    },
                    "architecture": {
                        "mermaidCode": "graph TD\n  A[Web] --> B[API]",
                        "description": "System context",
                    },
                    "api_spec": "info:\n  title: CRM API\npaths:\n  /users:\n    get:\n      summary: List users\n",
                    "_meta": {"source": "requirements_agent", "status": "completed"},
                }
            ),
        ), patch.object(
            orchestrator,
            "_build_with_architecture_agent",
            AsyncMock(
                return_value={
                    "architecture": {
                        "mermaidCode": "graph TD\n  A[Web] --> B[API]",
                        "description": "System context",
                    },
                    "_meta": {"source": "architecture_agent", "status": "completed"},
                }
            ),
        ):
            result = await orchestrator.build_artifacts(
                prompt="Build a CRM",
                selected_modules=[{"label": "User System", "labelEn": "User System"}],
            )

        self.assertTrue(result["prd"].startswith("# Product Requirements Document"))
        self.assertIn("## Overview", result["prd"])
        self.assertIn("CRM dashboard for sales teams", result["prd"])
        self.assertIn("# UI Pages", result["ui"])
        self.assertIn("| Dashboard | / |", result["ui"])
        self.assertIn("# Architecture", result["architecture"])
        self.assertIn("```mermaid", result["architecture"])
        self.assertTrue(result["api_spec"].startswith("openapi: 3.0.0"))
        self.assertIn("summary: List users", result["api_spec"])

    async def test_build_artifacts_adds_missing_prd_sections(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_build_with_requirements_agent_artifacts",
            AsyncMock(
                return_value={
                    "prd": "# Product Requirements Document\n\nA lightweight internal operations dashboard.",
                    "ui": "# UI Pages\n\n## Page Inventory\n- Dashboard\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: Ops API\npaths: {}\n",
                    "_meta": {"source": "requirements_agent", "status": "completed"},
                }
            ),
        ), patch.object(
            orchestrator,
            "_build_with_architecture_agent",
            AsyncMock(
                return_value={
                    "architecture": "# Architecture\n\n## Overview\nInternal dashboard stack.\n",
                    "_meta": {"source": "architecture_agent", "status": "completed"},
                }
            ),
        ):
            result = await orchestrator.build_artifacts(
                prompt="Build an ops dashboard",
                selected_modules=[{"label": "Admin Console", "labelEn": "Admin Console"}],
            )

        self.assertIn("## Overview", result["prd"])
        self.assertIn("## Functional Scope", result["prd"])
        self.assertIn("## Non-Functional Requirements", result["prd"])

    async def test_build_artifacts_uses_agent_outputs_without_template_fallbacks(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )

        with patch.object(
            orchestrator,
            "_build_with_requirements_agent_artifacts",
            AsyncMock(
                return_value={
                    "prd": "## Overview\nCRM dashboard.\n\n## Functional Scope\n- Pipeline",
                    "ui": "## Page Inventory\n- Dashboard\n\n## Primary Interactions\n- Drag and drop",
                    "api_spec": "info:\n  title: CRM API\npaths:\n  /pipeline:\n    get:\n      summary: List pipeline\n",
                    "_meta": {"source": "requirements_agent", "status": "completed"},
                }
            ),
        ), patch.object(
            orchestrator,
            "_build_with_architecture_agent",
            AsyncMock(
                return_value={
                    "architecture": "## Service Boundaries\n- Web Client\n- Backend API",
                    "_meta": {"source": "architecture_agent", "status": "completed"},
                }
            ),
        ):
            result = await orchestrator.build_artifacts(
                prompt="Build a CRM",
                selected_modules=[{"label": "User System", "labelEn": "User System"}],
            )

        self.assertIn("CRM dashboard.", result["prd"])
        self.assertIn("# UI Pages", result["ui"])
        self.assertIn("Dashboard", result["ui"])
        self.assertIn("# Architecture", result["architecture"])
        self.assertTrue(result["api_spec"].startswith("openapi:"))

    def test_configured_model_name_prefers_external_model(self) -> None:
        orchestrator = AgentOrchestrator(
            base_url="https://api.modelverse.cn/v1",
            api_key="secret",
            model="moonshot/kimi-k2.5",
        )
        self.assertEqual(orchestrator.get_model_name(), "moonshot/kimi-k2.5")


class WorkflowStatisticsModelTests(unittest.TestCase):
    def _default_analysis_payload(self) -> dict[str, Any]:
        return {
            "summary": "Requirements Agent completed the feature analysis.",
            "modules": [
                {
                    "id": "user-system",
                    "label": "User System",
                    "labelEn": "User System",
                    "description": "User auth",
                    "checked": True,
                }
            ],
            "_meta": {
                "source": "requirements_agent",
                "status": "completed",
            },
        }

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(db_path=str(Path(self.temp_dir.name) / "test.db"))

        patchers = [
            patch("app.main.store", self.store),
            patch("app.services.workflow.store", self.store),
            patch("app.main.agent_orchestrator.get_model_name", return_value="moonshot/kimi-k2.5"),
            patch("app.services.workflow.agent_orchestrator.get_model_name", return_value="moonshot/kimi-k2.5"),
            patch(
                "app.services.workflow.agent_orchestrator.analyze_prompt",
                new=AsyncMock(side_effect=lambda *args, **kwargs: self._default_analysis_payload()),
            ),
            patch("app.services.workflow.agent_orchestrator.consume_last_usage_metadata", return_value=None),
        ]
        self._patchers = patchers
        for patcher in patchers:
            patcher.start()

        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        for patcher in reversed(self._patchers):
            patcher.stop()
        self.store._connection.close()
        self.temp_dir.cleanup()

    def test_statistics_response_uses_configured_model_name(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Stats Model Project", "description": "Testing configured model"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build an analytics workspace", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)

        statistics_response = self.client.get(f"/api/projects/{project_id}/statistics")
        self.assertEqual(statistics_response.status_code, 200)
        self.assertEqual(statistics_response.json()["model"], "moonshot/kimi-k2.5")

    def test_statistics_response_uses_remote_usage_metadata(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Stats Usage Project", "description": "Testing remote usage"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        with patch(
            "app.services.workflow.agent_orchestrator.analyze_prompt",
            AsyncMock(
                return_value={
                    "summary": "Remote analysis summary",
                    "modules": [
                        {
                            "id": "user-system",
                            "label": "User System",
                            "labelEn": "User System",
                            "description": "User auth",
                            "checked": True,
                        }
                    ],
                }
            ),
        ), patch(
            "app.services.workflow.agent_orchestrator.consume_last_usage_metadata",
            return_value={
                "model": "moonshot/kimi-k2.5",
                "inputTokens": 321,
                "outputTokens": 654,
                "totalTokens": 975,
            },
        ):
            generate_response = self.client.post(
                f"/api/projects/{project_id}/generate",
                json={"prompt": "Build an analytics workspace", "uploadedFiles": []},
            )

        self.assertEqual(generate_response.status_code, 200)

        statistics_response = self.client.get(f"/api/projects/{project_id}/statistics")
        self.assertEqual(statistics_response.status_code, 200)
        payload = statistics_response.json()
        self.assertEqual(payload["tokens"]["input"], 321)
        self.assertEqual(payload["tokens"]["output"], 654)
        self.assertEqual(payload["tokens"]["total"], 975)
        self.assertEqual(payload["model"], "moonshot/kimi-k2.5")

    def test_generate_flow_exposes_analysis_source_in_confirmation_payload(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Analysis Source Project", "description": "Testing analysis source metadata"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        with patch(
            "app.services.workflow.agent_orchestrator.analyze_prompt",
            AsyncMock(
                return_value={
                    "summary": "Requirements summary",
                    "modules": [
                        {
                            "id": "customer-management",
                            "label": "Customer Management",
                            "labelEn": "Customer Management",
                            "description": "Manage accounts and contacts.",
                            "checked": True,
                        }
                    ],
                    "_meta": {
                        "source": "requirements_agent",
                        "status": "completed",
                    },
                }
            ),
        ):
            generate_response = self.client.post(
                f"/api/projects/{project_id}/generate",
                json={"prompt": "Build a CRM platform", "uploadedFiles": []},
            )

        self.assertEqual(generate_response.status_code, 200)

        current_task_response = self.client.get(f"/api/projects/{project_id}/task/current")
        self.assertEqual(current_task_response.status_code, 200)
        confirmation = current_task_response.json()["confirmationData"]
        self.assertEqual(confirmation["analysisSource"], "requirements_agent")
        self.assertNotIn("analysisReason", confirmation)
        self.assertEqual(confirmation["options"][0]["id"], "customer-management")


if __name__ == "__main__":
    unittest.main()
