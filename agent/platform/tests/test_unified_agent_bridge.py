import json
import os
import tempfile
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.unified_bridge import (
    UIAgentRuntimeError,
    UnifiedAgentBridge,
    _run_streaming_subprocess,
)


class UnifiedAgentBridgeTests(unittest.TestCase):
    def test_streaming_subprocess_runs_without_terminal_input(self) -> None:
        events: dict[str, object] = {}

        class FakePipe:
            def readline(self) -> str:
                return ""

            def close(self) -> None:
                return None

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = FakePipe()
                self.stderr = FakePipe()

            def wait(self, timeout: float | None = None) -> int:
                events["timeout"] = timeout
                return 0

        def fake_popen(*args: object, **kwargs: object) -> FakeProcess:
            events["stdin"] = kwargs.get("stdin")
            return FakeProcess()

        stdout_writer = unittest.mock.Mock()
        stdout_writer._chunks = []
        stderr_writer = unittest.mock.Mock()
        stderr_writer._chunks = []

        with patch("app.agents.unified_bridge.subprocess.Popen", side_effect=fake_popen):
            _run_streaming_subprocess(
                command=["python", "-c", "print('ok')"],
                cwd="/tmp",
                env={"PATH": "/usr/bin"},
                stdout_writer=stdout_writer,
                stderr_writer=stderr_writer,
                timeout=12,
            )

        self.assertIs(events["stdin"], subprocess.DEVNULL)
        self.assertEqual(events["timeout"], 2.0)
        stdout_writer.flush.assert_called_once()
        stderr_writer.flush.assert_called_once()

    def test_requirements_entry_delegates_to_subprocess(self) -> None:
        bridge = UnifiedAgentBridge()
        captured: dict[str, object] = {}

        def fake_streaming_subprocess(**kwargs: object) -> None:
            captured["command"] = kwargs["command"]
            result_path = Path(str(list(kwargs["command"])[-1]))
            result_path.write_text(json.dumps({"output_root": "/tmp/demo", "seededFiles": []}), encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_home = Path(temp_dir) / "home"
            output_root = Path(temp_dir) / "output"

            with patch(
                "app.agents.unified_bridge._run_streaming_subprocess",
                side_effect=fake_streaming_subprocess,
            ):
                result = bridge.run_requirements_agent(
                    mode="analysis",
                    project_name="demo",
                    description_text="build demo",
                    output_root=str(output_root),
                    runtime_home=str(runtime_home),
                    tasks_config_path=str(Path(temp_dir) / "tasks.yaml"),
                    agent_root="/tmp/agent",
                    python_bin="python3",
                    api_key="secret",
                    base_url="https://example.com/v1",
                    model="moonshot/kimi-k2.5",
                )

        self.assertIn("stdout", result)
        self.assertTrue(captured.get("command"))

    def test_test_entry_runs_real_test_agent_runtime_and_collects_files(self) -> None:
        bridge = UnifiedAgentBridge()

        def fake_streaming_subprocess(**kwargs: object) -> None:
            command = list(kwargs["command"])
            args_path = Path(command[-2])
            result_path = Path(command[-1])
            args = json.loads(args_path.read_text(encoding="utf-8"))
            output_root = Path(args["output_root"])
            memory_root = Path(args["memory_root"])
            output_root.mkdir(parents=True, exist_ok=True)
            memory_root.mkdir(parents=True, exist_ok=True)
            (output_root / f"{args['dataset_name']}_test_plan.md").write_text("# Test Plan\n", encoding="utf-8")
            (output_root / f"{args['dataset_name']}_testcase.md").write_text("# Test Cases\n", encoding="utf-8")
            (memory_root / "test_plan.json").write_text('{"modules": []}\n', encoding="utf-8")
            kwargs["stdout_writer"].write("Starting TestAgent Pipeline...\n")
            result_path.write_text(json.dumps({"usage": None}), encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_home = Path(temp_dir)
            with patch(
                "app.agents.unified_bridge._run_streaming_subprocess",
                side_effect=fake_streaming_subprocess,
            ):
                result = bridge.run_test_agent(
                    test_agent_root="/tmp/test-agent",
                    runtime_home=str(runtime_home),
                    dataset_name="demo-project",
                    srs_text="# SRS",
                    class_diagram_text="# Class Diagram",
                    sequence_diagram_text="# Sequence Diagram",
                    architecture_text="# Architecture",
                    code_root="/tmp/generated-code",
                    python_bin="python3",
                    api_key="secret",
                    base_url="https://example.com/v1",
                    model="openai/moonshot/kimi-k2.5",
                )

        file_paths = {item["filePath"] for item in result["files"]}
        self.assertIn("demo-project_test_plan.md", file_paths)
        self.assertIn("demo-project_testcase.md", file_paths)
        self.assertIn("memory/test_plan.json", file_paths)
        self.assertIn("Starting TestAgent Pipeline...", result["stdout"])

    def test_test_entry_forwards_runtime_usage_snapshots(self) -> None:
        bridge = UnifiedAgentBridge()

        def fake_streaming_subprocess(**kwargs: object) -> None:
            command = list(kwargs["command"])
            args_path = Path(command[-2])
            result_path = Path(command[-1])
            args = json.loads(args_path.read_text(encoding="utf-8"))
            output_root = Path(args["output_root"])
            memory_root = Path(args["memory_root"])
            output_root.mkdir(parents=True, exist_ok=True)
            memory_root.mkdir(parents=True, exist_ok=True)
            (output_root / f"{args['dataset_name']}_test_plan.md").write_text("# Test Plan\n", encoding="utf-8")
            (output_root / f"{args['dataset_name']}_testcase.md").write_text("# Test Cases\n", encoding="utf-8")
            (memory_root / "test_plan.json").write_text('{"modules": []}\n', encoding="utf-8")
            result_path.write_text(
                json.dumps(
                    {
                        "usage": {
                            "model": "openai/moonshot/kimi-k2.5",
                            "inputTokens": 18,
                            "outputTokens": 7,
                            "totalTokens": 25,
                        }
                    }
                ),
                encoding="utf-8",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_home = Path(temp_dir)
            with patch(
                "app.agents.unified_bridge._run_streaming_subprocess",
                side_effect=fake_streaming_subprocess,
            ):
                result = bridge.run_test_agent(
                    test_agent_root="/tmp/test-agent",
                    runtime_home=str(runtime_home),
                    dataset_name="demo-project",
                    srs_text="# SRS",
                    class_diagram_text="# Class Diagram",
                    sequence_diagram_text="# Sequence Diagram",
                    architecture_text="# Architecture",
                    code_root="/tmp/generated-code",
                    python_bin="python3",
                    api_key="secret",
                    base_url="https://example.com/v1",
                    model="openai/moonshot/kimi-k2.5",
                )

        self.assertIn("demo-project_test_plan.md", {item["filePath"] for item in result["files"]})
        self.assertEqual(result["usage"]["totalTokens"], 25)

    def test_test_entry_reports_runtime_heartbeat_with_latest_output_file(self) -> None:
        bridge = UnifiedAgentBridge()
        runtime_events: list[dict[str, object]] = []

        def fake_streaming_subprocess(**kwargs: object) -> None:
            heartbeat_callback = kwargs.get("heartbeat_callback")
            command = list(kwargs["command"])
            args_path = Path(command[-2])
            result_path = Path(command[-1])
            args = json.loads(args_path.read_text(encoding="utf-8"))
            output_root = Path(args["output_root"])
            memory_root = Path(args["memory_root"])
            output_root.mkdir(parents=True, exist_ok=True)
            memory_root.mkdir(parents=True, exist_ok=True)
            (memory_root / "test_plan.json").write_text('{"modules": []}\n', encoding="utf-8")
            (output_root / f"{args['dataset_name']}_test_plan.md").write_text("# Test Plan\n", encoding="utf-8")
            if heartbeat_callback is not None:
                heartbeat_callback({
                    "runtimePid": 12345,
                    "runtimeState": "running",
                    "startedAt": "2026-04-07T10:00:00+00:00",
                    "lastHeartbeatAt": "2026-04-07T10:00:10+00:00",
                    "lastOutputAt": "2026-04-07T10:00:08+00:00",
                    "stdoutLineCount": 0,
                    "stderrLineCount": 0,
                    "secondsSinceLastOutput": 2,
                    "elapsedSeconds": 10,
                })
            result_path.write_text(json.dumps({"usage": None}), encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_home = Path(temp_dir)
            with patch(
                "app.agents.unified_bridge._run_streaming_subprocess",
                side_effect=fake_streaming_subprocess,
            ):
                result = bridge.run_test_agent(
                    test_agent_root="/tmp/test-agent",
                    runtime_home=str(runtime_home),
                    dataset_name="demo-project",
                    srs_text="# SRS",
                    class_diagram_text="# Class Diagram",
                    sequence_diagram_text="# Sequence Diagram",
                    architecture_text="# Architecture",
                    code_root="/tmp/generated-code",
                    python_bin="python3",
                    api_key="secret",
                    base_url="https://example.com/v1",
                    model="openai/moonshot/kimi-k2.5",
                    runtime_event_callback=runtime_events.append,
                )

        self.assertIn("demo-project_test_plan.md", {item["filePath"] for item in result["files"]})
        self.assertTrue(runtime_events)
        has_output_file = any(
            bool(item.get("latestOutputFile"))
            for item in runtime_events
        )
        self.assertTrue(has_output_file)

    def test_test_entry_injects_allowed_runtime_write_roots(self) -> None:
        bridge = UnifiedAgentBridge()
        captured_env: dict[str, str] = {}

        def fake_streaming_subprocess(**kwargs: object) -> None:
            env = dict(kwargs["env"])
            captured_env.update(env)
            command = list(kwargs["command"])
            args_path = Path(command[-2])
            result_path = Path(command[-1])
            args = json.loads(args_path.read_text(encoding="utf-8"))
            output_root = Path(args["output_root"])
            memory_root = Path(args["memory_root"])
            output_root.mkdir(parents=True, exist_ok=True)
            memory_root.mkdir(parents=True, exist_ok=True)
            (output_root / "done.md").write_text("# done\n", encoding="utf-8")
            result_path.write_text(json.dumps({"usage": None}), encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_home = Path(temp_dir)
            code_root = runtime_home / "generated-code"
            with patch(
                "app.agents.unified_bridge._run_streaming_subprocess",
                side_effect=fake_streaming_subprocess,
            ):
                bridge.run_test_agent(
                    test_agent_root="/tmp/test-agent",
                    runtime_home=str(runtime_home),
                    dataset_name="demo-project",
                    srs_text="# SRS",
                    class_diagram_text="# Class Diagram",
                    sequence_diagram_text="# Sequence Diagram",
                    architecture_text="# Architecture",
                    code_root=str(code_root),
                    python_bin="python3",
                    api_key="secret",
                    base_url="https://example.com/v1",
                    model="openai/moonshot/kimi-k2.5",
                )

        observed_allowed_roots = captured_env.get("ISOFTDEVAGENTS_TEST_AGENT_ALLOWED_WRITE_ROOTS")
        self.assertIsNotNone(observed_allowed_roots)
        allowed_roots = set(str(item) for item in (observed_allowed_roots or "").split(os.pathsep) if item)
        self.assertEqual(
            allowed_roots,
            {
                str((runtime_home / "generated-code").resolve()),
                str((runtime_home / "output").resolve()),
                str((runtime_home / "memory").resolve()),
            },
        )

    def test_ui_entry_runs_real_ui_agent_runtime_and_collects_files(self) -> None:
        bridge = UnifiedAgentBridge()

        def fake_streaming_subprocess(**kwargs: object) -> None:
            command = list(kwargs["command"])
            result_path = Path(command[-1])
            output_dir = Path(command[-2])
            (output_dir / "app" / "css").mkdir(parents=True, exist_ok=True)
            (output_dir / "app" / "js").mkdir(parents=True, exist_ok=True)
            (output_dir / "page_descriptions.json").write_text('{"pages": []}\n', encoding="utf-8")
            (output_dir / "page_descriptions.md").write_text("# Page Descriptions\n", encoding="utf-8")
            (output_dir / "dar_model.json").write_text('{"dar_models": []}\n', encoding="utf-8")
            (output_dir / "dar_model.md").write_text("# DAR Model\n", encoding="utf-8")
            (output_dir / "app" / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
            (output_dir / "app" / "css" / "style.css").write_text("body {}\n", encoding="utf-8")
            (output_dir / "app" / "js" / "index.js").write_text("console.log('ui')\n", encoding="utf-8")
            (output_dir / "app" / "js" / "api.js").write_text("export const api = {};\n", encoding="utf-8")
            kwargs["stdout_writer"].write("UI Agent stage: page descriptions\n")
            kwargs["stdout_writer"].write("UI Agent stage: ui design\n")
            result_path.write_text(
                json.dumps({"usage": {"inputTokens": 21, "outputTokens": 9, "totalTokens": 30}}),
                encoding="utf-8",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_home = Path(temp_dir) / "runtime"
            output_root = Path(temp_dir) / "generated"
            with patch(
                "app.agents.unified_bridge._run_streaming_subprocess",
                side_effect=fake_streaming_subprocess,
            ):
                result = bridge.run_ui_agent(
                    ui_agent_root="/tmp/ui-agent",
                    runtime_home=str(runtime_home),
                    project_name="demo-project",
                    use_case_text="# Use Case",
                    dialog_map_text="# Dialog Map",
                    api_methods={"user_service": {"methods": {}}},
                    output_root=str(output_root),
                    python_bin="python3",
                    api_key="secret",
                    base_url="https://example.com/v1",
                    model="openai/moonshot/kimi-k2.5",
                )

        file_paths = {item["filePath"] for item in result["files"]}
        self.assertIn("page_descriptions.json", file_paths)
        self.assertIn("dar_model.md", file_paths)
        self.assertIn("app/index.html", file_paths)
        self.assertEqual(result["usage"]["totalTokens"], 30)
        self.assertIn("UI Agent stage: page descriptions", result["stdout"])

    def test_ui_entry_reports_error_on_subprocess_failure(self) -> None:
        bridge = UnifiedAgentBridge()

        def fake_streaming_subprocess(**kwargs: object) -> None:
            kwargs["stderr_writer"].write("json.decoder.JSONDecodeError: Expecting value: line 1 column 1\n")
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["python3", "-c", "..."],
                output="",
                stderr="json.decoder error",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_home = Path(temp_dir) / "runtime"
            output_root = Path(temp_dir) / "generated"
            with patch(
                "app.agents.unified_bridge._run_streaming_subprocess",
                side_effect=fake_streaming_subprocess,
            ):
                with self.assertRaises(UIAgentRuntimeError) as raised:
                    bridge.run_ui_agent(
                        ui_agent_root="/tmp/ui-agent",
                        runtime_home=str(runtime_home),
                        project_name="demo-project",
                        use_case_text="# Use Case",
                        dialog_map_text="# Dialog Map",
                        api_methods={"user_service": {"methods": {}}},
                        output_root=str(output_root),
                        python_bin="python3",
                        api_key="secret",
                        base_url="https://example.com/v1",
                        model="openai/moonshot/kimi-k2.5",
                    )

        self.assertEqual(raised.exception.reason, "invalid_page_description_json")

    def test_ui_entry_reports_missing_required_code_blocks_with_partial_outputs(self) -> None:
        bridge = UnifiedAgentBridge()

        def fake_streaming_subprocess(**kwargs: object) -> None:
            command = list(kwargs["command"])
            output_dir = Path(command[-2])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "page_descriptions.json").write_text('{"pages": [{"page_id": "home"}]}\n', encoding="utf-8")
            kwargs["stderr_writer"].write("RuntimeError: UI Agent did not return all required code blocks.\n")
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["python3", "-c", "..."],
                output="",
                stderr="UI Agent did not return all required code blocks",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_home = Path(temp_dir) / "runtime"
            output_root = Path(temp_dir) / "generated"
            with patch(
                "app.agents.unified_bridge._run_streaming_subprocess",
                side_effect=fake_streaming_subprocess,
            ):
                with self.assertRaises(UIAgentRuntimeError) as raised:
                    bridge.run_ui_agent(
                        ui_agent_root="/tmp/ui-agent",
                        runtime_home=str(runtime_home),
                        project_name="demo-project",
                        use_case_text="# Use Case",
                        dialog_map_text="# Dialog Map",
                        api_methods={"user_service": {"methods": {}}},
                        output_root=str(output_root),
                        python_bin="python3",
                        api_key="secret",
                        base_url="https://example.com/v1",
                        model="openai/moonshot/kimi-k2.5",
                    )

        self.assertEqual(raised.exception.reason, "missing_required_code_blocks")
        self.assertIn("page_descriptions.json", raised.exception.partial_files)

    def test_architecture_entry_runs_with_architecture_python_and_collects_result(self) -> None:
        bridge = UnifiedAgentBridge()
        architecture_root = Path("/tmp/arch-agent")
        runtime_home = Path("/tmp/arch-runtime")
        output_root = architecture_root / "data" / "output"
        output_dir = output_root / "20260402_1200_demo-project"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "analysis_task_output.txt").write_text("architecture analysis", encoding="utf-8")

        def fake_run_streaming_subprocess(**kwargs: object) -> None:
            command = list(kwargs["command"])
            self.assertEqual(command[0], "/tmp/arch-agent/.venv/bin/python")
            result_path = Path(command[-1])
            result_path.write_text(json.dumps({"usage": {"totalTokens": 12}}), encoding="utf-8")

        with patch(
            "app.agents.unified_bridge._run_streaming_subprocess",
            side_effect=fake_run_streaming_subprocess,
        ):
            with unittest.mock.patch.dict("os.environ", {}, clear=False):
                result = bridge.run_architecture_agent(
                    architecture_root=str(architecture_root),
                    requirement_document="# Requirements",
                    project_name="demo-project",
                    runtime_home=str(runtime_home),
                    python_bin="/tmp/arch-agent/.venv/bin/python",
                    python_path_entries=["/tmp/arch-agent/src"],
                    api_key="secret",
                    base_url="https://example.com/v1",
                    model="moonshot/kimi-k2.5",
                )

        self.assertIn("output_dir", result)
        self.assertEqual(result["usage"]["totalTokens"], 12)

    def test_architecture_entry_emits_usage_snapshots_from_usage_file(self) -> None:
        bridge = UnifiedAgentBridge()
        architecture_root = Path("/tmp/arch-agent")
        runtime_home = Path("/tmp/arch-runtime-usage")
        output_root = architecture_root / "data" / "output"
        output_dir = output_root / "20260402_1200_demo-project"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "analysis_task_output.txt").write_text("architecture analysis", encoding="utf-8")
        usage_events: list[dict[str, object]] = []

        def fake_run_streaming_subprocess(**kwargs: object) -> None:
            command = list(kwargs["command"])
            result_path = Path(command[-1])
            env = kwargs["env"]
            usage_path = Path(str(env["ISOFTDEVAGENTS_USAGE_OUTPUT"]))
            usage_path.write_text(
                json.dumps({"model": "moonshot/kimi-k2.5", "inputTokens": 20, "outputTokens": 10, "totalTokens": 30}),
                encoding="utf-8",
            )
            kwargs["stdout_writer"].write("architecture step\n")
            result_path.write_text(json.dumps({"usage": {"totalTokens": 30}}), encoding="utf-8")

        with patch(
            "app.agents.unified_bridge._run_streaming_subprocess",
            side_effect=fake_run_streaming_subprocess,
        ):
            result = bridge.run_architecture_agent(
                architecture_root=str(architecture_root),
                requirement_document="# Requirements",
                project_name="demo-project",
                runtime_home=str(runtime_home),
                python_bin="/tmp/arch-agent/.venv/bin/python",
                python_path_entries=["/tmp/arch-agent/src"],
                api_key="secret",
                base_url="https://example.com/v1",
                model="moonshot/kimi-k2.5",
                usage_callback=usage_events.append,
            )

        self.assertEqual(result["usage"]["totalTokens"], 30)
        self.assertTrue(usage_events)
        self.assertEqual(usage_events[-1]["totalTokens"], 30)

    def test_architecture_entry_emits_runtime_snapshots_with_latest_output_file(self) -> None:
        bridge = UnifiedAgentBridge()
        architecture_root = Path("/tmp/arch-agent-runtime")
        runtime_home = Path("/tmp/arch-runtime-monitor")
        output_root = architecture_root / "data" / "output"
        output_dir = output_root / "20260407_1801_demo-project"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "analysis_task_output.txt").write_text("architecture analysis", encoding="utf-8")
        runtime_events: list[dict[str, object]] = []

        def fake_run_streaming_subprocess(**kwargs: object) -> None:
            heartbeat_callback = kwargs["heartbeat_callback"]
            heartbeat_callback(
                {
                    "runtimePid": 43210,
                    "runtimeState": "running",
                    "startedAt": "2026-04-07T10:00:00+00:00",
                    "lastHeartbeatAt": "2026-04-07T10:00:10+00:00",
                    "lastOutputAt": "2026-04-07T10:00:08+00:00",
                    "stdoutLineCount": 0,
                    "stderrLineCount": 0,
                    "secondsSinceLastOutput": 2,
                    "elapsedSeconds": 10,
                }
            )
            result_path = Path(list(kwargs["command"])[-1])
            result_path.write_text(json.dumps({"usage": {"totalTokens": 12}}), encoding="utf-8")

        with patch(
            "app.agents.unified_bridge._run_streaming_subprocess",
            side_effect=fake_run_streaming_subprocess,
        ):
            bridge.run_architecture_agent(
                architecture_root=str(architecture_root),
                requirement_document="# Requirements",
                project_name="demo-project",
                runtime_home=str(runtime_home),
                python_bin="/tmp/arch-agent/.venv/bin/python",
                python_path_entries=["/tmp/arch-agent/src"],
                api_key="secret",
                base_url="https://example.com/v1",
                model="moonshot/kimi-k2.5",
                runtime_event_callback=runtime_events.append,
            )

        self.assertTrue(runtime_events)
        self.assertEqual(runtime_events[-1]["runtimePid"], 43210)
        self.assertEqual(runtime_events[-1]["latestOutputFile"], "analysis_task_output.txt")
        self.assertEqual(Path(str(runtime_events[-1]["outputDir"])).resolve(), output_dir.resolve())

    def test_architecture_entry_forces_noninteractive_observability_env(self) -> None:
        bridge = UnifiedAgentBridge()
        architecture_root = Path("/tmp/arch-agent-env")
        runtime_home = Path("/tmp/arch-runtime-env")
        output_root = architecture_root / "data" / "output"
        output_dir = output_root / "20260402_1200_demo-project"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "analysis_task_output.txt").write_text("architecture analysis", encoding="utf-8")
        captured_env: dict[str, str] = {}

        def fake_run_streaming_subprocess(**kwargs: object) -> None:
            env = dict(kwargs["env"])
            captured_env.update(env)
            result_path = Path(list(kwargs["command"])[-1])
            result_path.write_text(json.dumps({"usage": {"totalTokens": 12}}), encoding="utf-8")

        with patch(
            "app.agents.unified_bridge._run_streaming_subprocess",
            side_effect=fake_run_streaming_subprocess,
        ):
            bridge.run_architecture_agent(
                architecture_root=str(architecture_root),
                requirement_document="# Requirements",
                project_name="demo-project",
                runtime_home=str(runtime_home),
                python_bin="/tmp/arch-agent/.venv/bin/python",
                python_path_entries=["/tmp/arch-agent/src"],
                api_key="secret",
                base_url="https://example.com/v1",
                model="moonshot/kimi-k2.5",
            )

        self.assertEqual(captured_env["CREWAI_TRACING_ENABLED"], "false")
        self.assertEqual(captured_env["OTEL_SDK_DISABLED"], "true")
        self.assertEqual(captured_env["CREWAI_DISABLE_TELEMETRY"], "true")
        self.assertEqual(captured_env["CREWAI_DISABLE_TRACKING"], "true")
        self.assertEqual(captured_env["OPENAI_API_KEY"], "secret")
        self.assertEqual(captured_env["OPENAI_BASE_URL"], "https://example.com/v1")
        self.assertEqual(captured_env["OPENAI_MODEL"], "moonshot/kimi-k2.5")
        self.assertEqual(captured_env["ISOFTDEVAGENTS_LLM_API_KEY"], "secret")
        self.assertEqual(captured_env["ISOFTDEVAGENTS_LLM_BASE_URL"], "https://example.com/v1")
        self.assertEqual(captured_env["ISOFTDEVAGENTS_LLM_MODEL"], "moonshot/kimi-k2.5")

    def test_code_entry_runs_real_code_agent_app_and_collects_files(self) -> None:
        bridge = UnifiedAgentBridge()

        class FakeCodeAgentApp:
            def __init__(self, *, paths: dict[str, str]) -> None:
                self.paths = paths
                self.codegen_agent = object()

            def run(self, *, mode: str = "full") -> None:
                output_root = Path(self.paths["software"])
                (output_root / "backend").mkdir(parents=True, exist_ok=True)
                (output_root / "backend" / "run.py").write_text("print('generated')\n", encoding="utf-8")
                print("Code generation pipeline started")

        class FakeCodeRuntime:
            CodeAgentApp = FakeCodeAgentApp

        with patch(
            "app.agents.unified_bridge.load_code_agent_runtime_module",
            return_value=FakeCodeRuntime,
        ):
            result = bridge.run_code_agent(
                code_agent_root="/tmp/code-agent",
                runtime_home="/tmp/code-runtime",
                project_manifest={"backend": {"run.py": {"priority": 1}}},
                semantic_model={"project": {"summary": "demo"}},
                srs_text="# SRS",
                architecture_text="# Architecture",
                api_spec_text="openapi: 3.0.0",
                output_root="/tmp/code-runtime/generated",
                api_key="secret",
                base_url="https://example.com/v1",
                model="openai/moonshot/kimi-k2.5",
            )

        self.assertEqual(result["files"][0]["filePath"], "backend/run.py")
        self.assertIn("Code generation pipeline started", result["stdout"])

    def test_code_entry_emits_usage_snapshots_during_runtime(self) -> None:
        bridge = UnifiedAgentBridge()
        usage_events: list[dict[str, object]] = []

        class FakeSummary:
            prompt_tokens = 12
            completion_tokens = 8
            total_tokens = 20

        class FakeTokenProcess:
            def get_summary(self) -> FakeSummary:
                return FakeSummary()

        class FakeCodeAgentApp:
            def __init__(self, *, paths: dict[str, str]) -> None:
                self.paths = paths
                self.codegen_agent = type("CodegenAgent", (), {"_token_process": FakeTokenProcess()})()

            def run(self, *, mode: str = "full") -> None:
                output_root = Path(self.paths["software"])
                (output_root / "backend").mkdir(parents=True, exist_ok=True)
                (output_root / "backend" / "run.py").write_text("print('generated')\n", encoding="utf-8")
                print("Code generation pipeline started")

        class FakeCodeRuntime:
            CodeAgentApp = FakeCodeAgentApp

        with patch(
            "app.agents.unified_bridge.load_code_agent_runtime_module",
            return_value=FakeCodeRuntime,
        ):
            result = bridge.run_code_agent(
                code_agent_root="/tmp/code-agent",
                runtime_home="/tmp/code-runtime",
                project_manifest={"backend": {"run.py": {"priority": 1}}},
                semantic_model={"project": {"summary": "demo"}},
                srs_text="# SRS",
                architecture_text="# Architecture",
                api_spec_text="openapi: 3.0.0",
                output_root="/tmp/code-runtime/generated",
                api_key="secret",
                base_url="https://example.com/v1",
                model="openai/moonshot/kimi-k2.5",
                usage_callback=usage_events.append,
            )

        self.assertEqual(result["usage"]["totalTokens"], 20)
        self.assertTrue(usage_events)
        self.assertEqual(usage_events[-1]["totalTokens"], 20)

    def test_code_entry_runs_with_dedicated_python_subprocess(self) -> None:
        bridge = UnifiedAgentBridge()
        captured: dict[str, object] = {}

        with tempfile.TemporaryDirectory() as temp_dir:
            python_bin = Path(temp_dir) / "code-agent-python"
            python_bin.write_text("#!/bin/sh\n", encoding="utf-8")

            def fake_streaming_subprocess(**kwargs: object) -> None:
                command = kwargs["command"]
                assert isinstance(command, list)
                captured["command"] = command
                result_path = Path(str(command[-1]))
                output_root = Path(str(command[-2]))
                (output_root / "backend").mkdir(parents=True, exist_ok=True)
                (output_root / "backend" / "run.py").write_text("print('generated')\n", encoding="utf-8")
                result_path.write_text(
                    json.dumps(
                        {
                            "files": [
                                {
                                    "filePath": "backend/run.py",
                                    "content": "print('generated')\n",
                                }
                            ],
                            "usage": {
                                "model": "openai/moonshot/kimi-k2.5",
                                "inputTokens": 12,
                                "outputTokens": 8,
                                "totalTokens": 20,
                            },
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

            with patch("app.agents.unified_bridge._run_streaming_subprocess", side_effect=fake_streaming_subprocess):
                result = bridge.run_code_agent(
                    code_agent_root="/tmp/code-agent",
                    runtime_home="/tmp/code-runtime",
                    python_bin=str(python_bin),
                    project_manifest={"backend": {"run.py": {"priority": 1}}},
                    semantic_model={"project": {"summary": "demo"}},
                    srs_text="# SRS",
                    architecture_text="# Architecture",
                    api_spec_text="openapi: 3.0.0",
                    output_root="/tmp/code-runtime/generated",
                    api_key="secret",
                    base_url="https://example.com/v1",
                    model="openai/moonshot/kimi-k2.5",
                )

        self.assertEqual(captured["command"][0], str(python_bin))
        self.assertEqual(result["files"][0]["filePath"], "backend/run.py")
        self.assertEqual(result["usage"]["totalTokens"], 20)
