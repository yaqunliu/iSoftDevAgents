import importlib.util
import traceback
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import Mock, patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents import requirements_bridge


class RequirementsAgentBridgeTests(unittest.TestCase):
    @staticmethod
    def _load_runtime_bridge_module():
        repo_root = Path(__file__).resolve().parents[3]
        module_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "src" / "reagent" / "runtime_bridge.py"
        module_name = "reagent_runtime_bridge_test"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module_name, module

    @staticmethod
    def _load_prompt_input_bridge_module():
        repo_root = Path(__file__).resolve().parents[3]
        module_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "util" / "prompt_input_bridge.py"
        module_name = "reagent_prompt_input_bridge_test"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module_name, module

    @staticmethod
    def _load_validate_format_module():
        repo_root = Path(__file__).resolve().parents[3]
        module_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "util" / "validate_format.py"
        module_name = "reagent_validate_format_test"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module_name, module

    def test_backend_bridge_calls_agent_runtime_function(self) -> None:
        fake_runtime = SimpleNamespace(
            run_requirements_agent_full=Mock(return_value={"seededFiles": ["feature_tree.md"]}),
        )

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.agents.requirements_bridge.load_requirements_agent_runtime_bridge",
            return_value=fake_runtime,
        ):
            result = requirements_bridge.run_requirements_agent(
                mode="full",
                project_name="demo-project",
                description_text="demo-description",
                output_root=Path(temp_dir) / "output",
                runtime_home=Path(temp_dir) / "runtime-home",
                tasks_config_path=Path(temp_dir) / "tasks.yaml",
                api_key="secret",
                base_url="https://example.test/v1",
                model="openai/demo-model",
            )

        fake_runtime.run_requirements_agent_full.assert_called_once()
        self.assertEqual(result["seededFiles"], ["feature_tree.md"])
        self.assertIn("stdout", result)
        self.assertIn("stderr", result)

    def test_backend_bridge_forwards_prompt_input_provider_to_runtime(self) -> None:
        fake_provider = object()
        captured_kwargs: dict[str, object] = {}

        def fake_run_requirements_agent_full(**kwargs):
            captured_kwargs.update(kwargs)
            return {"seededFiles": []}

        fake_runtime = SimpleNamespace(run_requirements_agent_full=fake_run_requirements_agent_full)

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.agents.requirements_bridge.load_requirements_agent_runtime_bridge",
            return_value=fake_runtime,
        ):
            requirements_bridge.run_requirements_agent(
                mode="full",
                project_name="demo-project",
                description_text="demo-description",
                output_root=Path(temp_dir) / "output",
                runtime_home=Path(temp_dir) / "runtime-home",
                tasks_config_path=Path(temp_dir) / "tasks.yaml",
                api_key="secret",
                base_url="https://example.test/v1",
                model="openai/demo-model",
                prompt_input_provider=fake_provider,
            )

        self.assertIs(captured_kwargs["prompt_input_provider"], fake_provider)

    def test_backend_bridge_forwards_cancel_event_to_runtime(self) -> None:
        captured_kwargs: dict[str, object] = {}
        cancel_event = threading.Event()

        def fake_run_requirements_agent_full(**kwargs):
            captured_kwargs.update(kwargs)
            return {"seededFiles": []}

        fake_runtime = SimpleNamespace(run_requirements_agent_full=fake_run_requirements_agent_full)

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.agents.requirements_bridge.load_requirements_agent_runtime_bridge",
            return_value=fake_runtime,
        ):
            requirements_bridge.run_requirements_agent(
                mode="full",
                project_name="demo-project",
                description_text="demo-description",
                output_root=Path(temp_dir) / "output",
                runtime_home=Path(temp_dir) / "runtime-home",
                tasks_config_path=Path(temp_dir) / "tasks.yaml",
                api_key="secret",
                base_url="https://example.test/v1",
                model="openai/demo-model",
                cancel_event=cancel_event,
            )

        self.assertIs(captured_kwargs["cancel_event"], cancel_event)

    def test_use_case_normalizer_wraps_single_secondary_actor_string(self) -> None:
        module_name, validate_format_module = self._load_validate_format_module()
        try:
            normalize_use_case_payload = getattr(validate_format_module, "normalize_use_case_payload")
            validate_use_case_format = getattr(validate_format_module, "validate_use_case_format")

            normalized_payload = normalize_use_case_payload(
                [
                    {
                        "use_case_name": "Submit Move",
                        "primary_actor": "Player",
                        "secondary_actor": "Referee Service",
                        "use_case_description": "Player submits a move to the game service.",
                        "trigger": "Player clicks confirm move.",
                        "preconditions": ["Game is running"],
                        "postconditions": ["Move is stored"],
                        "main_flow": ["Player submits move", "System validates move"],
                        "alternative_flows": [],
                        "exception_flows": [],
                        "priority": "High",
                        "business_rules": ["Move must target an empty cell"],
                        "assumptions": ["Board state is already loaded"],
                        "other_constraints": ["Response must stay under 500ms"],
                    }
                ]
            )
        finally:
            sys.modules.pop(module_name, None)

        self.assertEqual(normalized_payload[0]["secondary_actor"], ["Referee Service"])
        self.assertEqual(validate_use_case_format(normalized_payload), (True, "OK"))

    def test_backend_bridge_forwards_setup_logging_to_runtime(self) -> None:
        captured_kwargs: dict[str, object] = {}

        def fake_setup_logging() -> None:
            return None

        def fake_run_requirements_agent_full(**kwargs):
            captured_kwargs.update(kwargs)
            return {"seededFiles": []}

        fake_runtime = SimpleNamespace(run_requirements_agent_full=fake_run_requirements_agent_full)

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.agents.requirements_bridge.load_requirements_agent_runtime_bridge",
            return_value=fake_runtime,
        ):
            requirements_bridge.run_requirements_agent(
                mode="full",
                project_name="demo-project",
                description_text="demo-description",
                output_root=Path(temp_dir) / "output",
                runtime_home=Path(temp_dir) / "runtime-home",
                tasks_config_path=Path(temp_dir) / "tasks.yaml",
                api_key="secret",
                base_url="https://example.test/v1",
                model="openai/demo-model",
                setup_logging=fake_setup_logging,
            )

        self.assertIs(captured_kwargs["setup_logging"], fake_setup_logging)

    def test_requirements_agent_main_delegates_to_bridge_cli(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        main_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "src" / "reagent" / "main.py"
        module_name = "reagent_main_bridge_test"
        spec = importlib.util.spec_from_file_location(module_name, main_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        try:
            with patch.object(module, "run_cli", return_value={"ok": True}) as mocked_run_cli:
                result = module.main(["--description_file", "demo.md"])
        finally:
            sys.modules.pop(module_name, None)

        mocked_run_cli.assert_called_once_with(["--description_file", "demo.md"])
        self.assertEqual(result, {"ok": True})

    def test_backend_bridge_preserves_captured_output_when_runtime_raises(self) -> None:
        class _BridgeCrash(Exception):
            pass

        def fail_full(**kwargs):
            kwargs["stdout_writer"].write("bridge stdout before crash\n")
            raise _BridgeCrash("bridge exploded")

        fake_runtime = SimpleNamespace(run_requirements_agent_full=fail_full)

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.agents.requirements_bridge.load_requirements_agent_runtime_bridge",
            return_value=fake_runtime,
        ):
            with self.assertRaises(requirements_bridge.RequirementsAgentBridgeExecutionError) as raised:
                requirements_bridge.run_requirements_agent(
                    mode="full",
                    project_name="demo-project",
                    description_text="demo-description",
                    output_root=Path(temp_dir) / "output",
                    runtime_home=Path(temp_dir) / "runtime-home",
                    tasks_config_path=Path(temp_dir) / "tasks.yaml",
                    api_key="secret",
                    base_url="https://example.test/v1",
                    model="openai/demo-model",
                )

        self.assertIn("bridge exploded", str(raised.exception))
        self.assertIn("bridge stdout before crash", raised.exception.stdout_text)

    def test_backend_bridge_appends_traceback_to_stderr_when_runtime_raises(self) -> None:
        class _BridgeCrash(Exception):
            pass

        def fail_full(**kwargs):
            kwargs["stderr_writer"].write("bridge stderr before crash\n")
            raise _BridgeCrash("bridge exploded")

        fake_runtime = SimpleNamespace(run_requirements_agent_full=fail_full)

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.agents.requirements_bridge.load_requirements_agent_runtime_bridge",
            return_value=fake_runtime,
        ):
            with self.assertRaises(requirements_bridge.RequirementsAgentBridgeExecutionError) as raised:
                requirements_bridge.run_requirements_agent(
                    mode="full",
                    project_name="demo-project",
                    description_text="demo-description",
                    output_root=Path(temp_dir) / "output",
                    runtime_home=Path(temp_dir) / "runtime-home",
                    tasks_config_path=Path(temp_dir) / "tasks.yaml",
                    api_key="secret",
                    base_url="https://example.test/v1",
                    model="openai/demo-model",
                )

        self.assertIn("bridge stderr before crash", raised.exception.stderr_text)
        self.assertIn("Traceback", raised.exception.stderr_text)
        self.assertIn("_BridgeCrash: bridge exploded", raised.exception.stderr_text)

    def test_backend_bridge_normalizes_mixed_stdout_and_stderr_chunks(self) -> None:
        def fake_run_requirements_agent_full(**kwargs):
            kwargs["stdout_writer"].write("stdout-text-1\n")
            kwargs["stdout_writer"].write(b"stdout-bytes-2\n")
            kwargs["stderr_writer"].write("stderr-text-1\n")
            kwargs["stderr_writer"].write(b"stderr-bytes-2\n")
            return {"seededFiles": []}

        fake_runtime = SimpleNamespace(run_requirements_agent_full=fake_run_requirements_agent_full)

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.agents.requirements_bridge.load_requirements_agent_runtime_bridge",
            return_value=fake_runtime,
        ):
            result = requirements_bridge.run_requirements_agent(
                mode="full",
                project_name="demo-project",
                description_text="demo-description",
                output_root=Path(temp_dir) / "output",
                runtime_home=Path(temp_dir) / "runtime-home",
                tasks_config_path=Path(temp_dir) / "tasks.yaml",
                api_key="secret",
                base_url="https://example.test/v1",
                model="openai/demo-model",
            )

        self.assertEqual(result["stdout"], "stdout-text-1\nstdout-bytes-2\n")
        self.assertEqual(result["stderr"], "stderr-text-1\nstderr-bytes-2\n")

    def test_runtime_bridge_analysis_falls_back_to_feature_tree_run_when_prompt_analysis_is_missing(self) -> None:
        module_name, runtime_bridge = self._load_runtime_bridge_module()
        try:
            fake_standard_process = SimpleNamespace()
            feature_tree_run_instance = Mock()
            feature_tree_run_class = Mock(return_value=feature_tree_run_instance)
            fake_business_requirements = ModuleType("BusinessRequirements")
            fake_business_requirements.FeatureTreeRun = feature_tree_run_class

            class _PreparedRuntime:
                def __enter__(self_inner):
                    return {
                        "StandardProcess": fake_standard_process,
                        "util": object(),
                        "model": "openai/demo-model",
                        "output_root": Path("/tmp/runtime-output"),
                        "tasks_config_path": None,
                    }

                def __exit__(self_inner, exc_type, exc, tb):
                    return False

            with patch.object(runtime_bridge, "_prepared_runtime", return_value=_PreparedRuntime()), patch.dict(
                sys.modules,
                {"BusinessRequirements": fake_business_requirements},
            ):
                result = runtime_bridge.run_requirements_agent_analysis(
                    project_name="demo-project",
                    description_text="设计一个推箱子游戏",
                    runtime_home="/tmp/runtime-home",
                    output_root="/tmp/runtime-output",
                    tasks_config_path=None,
                    api_key="secret",
                    base_url="https://example.test/v1",
                    model="demo-model",
                )

            feature_tree_run_class.assert_called_once_with(
                project_name="demo-project",
                Description="设计一个推箱子游戏",
            )
            feature_tree_run_instance.run.assert_called_once_with(
                "本轮没有人类意见",
                {"all": ""},
                "设计一个推箱子游戏",
            )
            self.assertEqual(result["output_root"], "/tmp/runtime-output")
        finally:
            sys.modules.pop(module_name, None)

    def test_runtime_bridge_applies_run_with_retry_override_to_preloaded_requirement_modules(self) -> None:
        module_name, runtime_bridge = self._load_runtime_bridge_module()
        try:
            original_run_with_retry = object()
            override_run_with_retry = object()

            fake_util = ModuleType("util")
            fake_util.run_with_retry = original_run_with_retry

            fake_standard_process = ModuleType("StandardProcess")
            fake_standard_process.run_with_retry = original_run_with_retry

            fake_business_requirements = ModuleType("BusinessRequirements")
            fake_business_requirements.run_with_retry = original_run_with_retry

            fake_requirement_analysis = ModuleType("RequirementAnalysis")
            fake_requirement_analysis.run_with_retry = original_run_with_retry

            fake_requirement_elicitation = ModuleType("RequirementElicitation")
            fake_requirement_elicitation.run_with_retry = original_run_with_retry

            fake_non_standard_process = ModuleType("NonStandardProcess")
            fake_non_standard_process.run_with_retry = original_run_with_retry

            with patch.dict(
                sys.modules,
                {
                    "util": fake_util,
                    "StandardProcess": fake_standard_process,
                    "BusinessRequirements": fake_business_requirements,
                    "RequirementAnalysis": fake_requirement_analysis,
                    "RequirementElicitation": fake_requirement_elicitation,
                    "NonStandardProcess": fake_non_standard_process,
                },
                clear=False,
            ):
                runtime_bridge._apply_run_with_retry_override(
                    run_with_retry_override=override_run_with_retry,
                    util_module=fake_util,
                    standard_process_module=fake_standard_process,
                )

            self.assertIs(fake_util.run_with_retry, override_run_with_retry)
            self.assertIs(fake_standard_process.run_with_retry, override_run_with_retry)
            self.assertIs(fake_business_requirements.run_with_retry, override_run_with_retry)
            self.assertIs(fake_requirement_analysis.run_with_retry, override_run_with_retry)
            self.assertIs(fake_requirement_elicitation.run_with_retry, override_run_with_retry)
            self.assertIs(fake_non_standard_process.run_with_retry, override_run_with_retry)
        finally:
            sys.modules.pop(module_name, None)

    def test_runtime_bridge_calls_setup_logging_after_site_packages_are_added(self) -> None:
        module_name, runtime_bridge = self._load_runtime_bridge_module()
        try:
            observed = {"site_packages_visible": False, "called": False}

            def fake_setup_logging() -> None:
                observed["called"] = True
                observed["site_packages_visible"] = "/tmp/reagent-site-packages" in sys.path

            def fake_load_runtime_env(_root) -> None:
                return None

            def fake_apply_runtime_observability_defaults(force: bool = False) -> None:
                return None

            fake_runtime_env = ModuleType("util.runtime_env")
            fake_runtime_env.load_runtime_env = fake_load_runtime_env
            fake_runtime_env.apply_runtime_observability_defaults = fake_apply_runtime_observability_defaults

            fake_prompt_bridge = ModuleType("util.prompt_input_bridge")
            fake_prompt_bridge.set_prompt_input_provider = lambda provider: None
            fake_prompt_bridge.clear_prompt_input_provider = lambda: None
            fake_prompt_bridge.get_prompt_input_provider = lambda: None

            class _FakeTerminalPromptInputProvider:
                def read_multiline(self, prompt_text: str, checkpoint: str | None = None) -> str:
                    return "no"

            fake_prompt_bridge.TerminalPromptInputProvider = _FakeTerminalPromptInputProvider

            fake_util = ModuleType("util")
            fake_standard_process = ModuleType("StandardProcess")

            with patch.object(runtime_bridge.site, "addsitedir", side_effect=lambda path: sys.path.insert(0, path)), patch.dict(
                sys.modules,
                {
                    "util.runtime_env": fake_runtime_env,
                    "util.prompt_input_bridge": fake_prompt_bridge,
                    "util": fake_util,
                    "StandardProcess": fake_standard_process,
                },
            ):
                with runtime_bridge._prepared_runtime(
                    runtime_home="/tmp/runtime-home",
                    output_root="/tmp/runtime-output",
                    tasks_config_path=None,
                    api_key="secret",
                    base_url="https://example.test/v1",
                    model="openai/demo-model",
                    site_packages_dir="/tmp/reagent-site-packages",
                    stdin_text="no\n",
                    setup_logging=fake_setup_logging,
                ):
                    pass

            self.assertTrue(observed["called"])
            self.assertTrue(observed["site_packages_visible"])
        finally:
            sys.modules.pop(module_name, None)

    def test_runtime_bridge_full_mode_does_not_import_requirement_extraction_without_data_path(self) -> None:
        module_name, runtime_bridge = self._load_runtime_bridge_module()
        try:
            fake_standard_process = SimpleNamespace(
                StandardProcessrun=Mock(return_value=(object(), object(), object(), {}, [])),
            )
            fake_non_standard_process = SimpleNamespace(
                NonStandardProcessrun=Mock(),
            )

            class _PreparedRuntime:
                def __enter__(self_inner):
                    return {
                        "StandardProcess": fake_standard_process,
                        "util": object(),
                        "model": "openai/demo-model",
                        "output_root": Path("/tmp/runtime-output"),
                        "tasks_config_path": None,
                    }

                def __exit__(self_inner, exc_type, exc, tb):
                    return False

            fake_requirement_specification = Mock()

            real_import = __import__

            def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name == "RequirementExtraction":
                    raise AssertionError("RequirementExtraction should not be imported when data_path is missing")
                if name == "NonStandardProcess":
                    return fake_non_standard_process
                return real_import(name, globals, locals, fromlist, level)

            with patch.object(runtime_bridge, "_prepared_runtime", return_value=_PreparedRuntime()), patch.object(
                runtime_bridge,
                "RequirementSpecificationrun",
                fake_requirement_specification,
            ), patch("builtins.__import__", side_effect=guarded_import):
                result = runtime_bridge.run_requirements_agent_full(
                    project_name="demo-project",
                    description_text="设计一个推箱子游戏",
                    runtime_home="/tmp/runtime-home",
                    output_root="/tmp/runtime-output",
                    tasks_config_path=None,
                    api_key="secret",
                    base_url="https://example.test/v1",
                    model="demo-model",
                    data_path=None,
                )

            fake_standard_process.StandardProcessrun.assert_called_once()
            fake_non_standard_process.NonStandardProcessrun.assert_called_once()
            fake_requirement_specification.assert_called_once()
            self.assertEqual(result["output_root"], "/tmp/runtime-output")
        finally:
            sys.modules.pop(module_name, None)

    def test_runtime_bridge_normalizes_srs_chapter_payload_with_content_and_chapters_shape(self) -> None:
        module_name, runtime_bridge = self._load_runtime_bridge_module()
        try:
            raw_payload = {
                "title": "文档历史模板",
                "chapter_index": "1",
                "introduction": "本章介绍文档历史。",
                "content": "这里是章节正文。",
                "requirements": [
                    {"index": "1--1", "content": "(high) 必须记录版本号。"},
                    {"index": "1--2", "content": "(medium) 必须记录修改日期。"},
                ],
                "chapters": [
                    {
                        "title": "版本记录初始登记",
                        "chapter_index": "1.1",
                        "content": "这里是子章节正文。",
                        "requirements": [],
                        "chapters": [],
                    }
                ],
            }

            normalized = runtime_bridge._normalize_srs_chapter_payload(raw_payload)

            self.assertEqual(normalized["title"], "文档历史模板")
            self.assertEqual(normalized["chapter_index"], "1")
            self.assertIn("structure", normalized)
            self.assertIn("subchapter", normalized)
            self.assertNotIn("chapters", normalized)
            self.assertEqual(normalized["subchapter"][0]["chapter_index"], "1.1")
            self.assertIn("structure", normalized["subchapter"][0])
            self.assertTrue(
                any("这里是章节正文。" in str(value) for item in normalized["structure"] for value in item.values())
            )
            self.assertTrue(
                any("必须记录版本号" in str(value) for item in normalized["structure"] for value in item.values())
            )
        finally:
            sys.modules.pop(module_name, None)

    def test_injected_prompt_input_provider_returns_injected_text(self) -> None:
        module_name, prompt_bridge = self._load_prompt_input_bridge_module()
        try:
            waiting_payloads: list[dict[str, object]] = []
            waiting_event = threading.Event()
            result: dict[str, str] = {}

            def on_waiting(payload: dict[str, object]) -> None:
                waiting_payloads.append(payload)
                waiting_event.set()

            provider = prompt_bridge.InjectedPromptInputProvider(
                task_id="task-feedback",
                output_files_resolver=lambda: ["business_scope.md"],
                waiting_callback=on_waiting,
            )

            def read_prompt() -> None:
                result["value"] = provider.read_multiline(
                    prompt_text="请查看现有的business_scope.md文档并告诉我有哪些需要改进的地方：",
                    checkpoint="business_scope_review",
                )

            waiter = threading.Thread(target=read_prompt)
            waiter.start()
            self.assertTrue(waiting_event.wait(timeout=2))
            provider.inject_text("请补充成功标准")
            waiter.join(timeout=2)

            self.assertEqual(result["value"], "请补充成功标准")
            self.assertEqual(waiting_payloads[0]["taskId"], "task-feedback")
            self.assertEqual(waiting_payloads[0]["checkpoint"], "business_scope_review")
            self.assertEqual(waiting_payloads[0]["outputFiles"], ["business_scope.md"])
        finally:
            sys.modules.pop(module_name, None)

    def test_injected_prompt_input_provider_close_returns_exit(self) -> None:
        module_name, prompt_bridge = self._load_prompt_input_bridge_module()
        try:
            waiting_event = threading.Event()
            result: dict[str, str] = {}

            provider = prompt_bridge.InjectedPromptInputProvider(
                task_id="task-feedback",
                waiting_callback=lambda payload: waiting_event.set(),
            )

            def read_prompt() -> None:
                result["value"] = provider.read_multiline(
                    prompt_text="请查看现有的BRD.md文档并告诉我有哪些需要改进的地方：",
                    checkpoint="brd_review",
                )

            waiter = threading.Thread(target=read_prompt)
            waiter.start()
            self.assertTrue(waiting_event.wait(timeout=2))
            provider.close()
            waiter.join(timeout=2)

            self.assertEqual(result["value"], "exit")
        finally:
            sys.modules.pop(module_name, None)
