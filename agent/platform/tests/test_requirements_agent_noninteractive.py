import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
import importlib.util
import types
import json
from unittest.mock import patch
from pathlib import Path


class RequirementsAgentNoninteractiveTests(unittest.TestCase):
    def test_standard_process_load_json_payload_from_markdown_accepts_common_code_fences(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        module_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "src" / "reagent" / "StandardProcess.py"
        self.assertTrue(module_path.exists(), f"Missing StandardProcess module: {module_path}")

        fake_util = types.ModuleType("util")
        fake_util.store_path = "output"
        fake_util.__all__ = ["store_path"]

        fake_util_util = types.ModuleType("util.util")
        fake_util_util.store_path = "output"

        fake_requirement_analysis = types.ModuleType("RequirementAnalysis")
        fake_requirement_analysis.DataDictionaryCrew = object()
        fake_requirement_analysis.ERDCrew = object()
        fake_requirement_analysis.DataFlowDiagramCrew = object()
        fake_requirement_analysis.FRCrew = object()
        fake_requirement_analysis.DialogMapCrew = object()

        fake_business_requirements = types.ModuleType("BusinessRequirements")
        fake_business_requirements.__all__ = []

        with patch.dict(
            sys.modules,
            {
                "util": fake_util,
                "util.util": fake_util_util,
                "RequirementAnalysis": fake_requirement_analysis,
                "BusinessRequirements": fake_business_requirements,
            },
            clear=False,
        ):
            spec = importlib.util.spec_from_file_location("reagent_standard_process_json_test", module_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

        expected = {"chapter_index": "1", "title": "Business requirements"}

        self.assertEqual(
            module.load_json_payload_from_markdown("""```json\n{"chapter_index":"1","title":"Business requirements"}\n```"""),
            expected,
        )
        self.assertEqual(
            module.load_json_payload_from_markdown("""```JSON\n{"chapter_index":"1","title":"Business requirements"}\n```"""),
            expected,
        )
        self.assertEqual(
            module.load_json_payload_from_markdown("""```\n{"chapter_index":"1","title":"Business requirements"}\n```"""),
            expected,
        )

    def test_standard_process_load_json_payload_from_markdown_extracts_json_from_wrapped_text(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        module_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "src" / "reagent" / "StandardProcess.py"
        self.assertTrue(module_path.exists(), f"Missing StandardProcess module: {module_path}")

        fake_util = types.ModuleType("util")
        fake_util.store_path = "output"
        fake_util.__all__ = ["store_path"]

        fake_util_util = types.ModuleType("util.util")
        fake_util_util.store_path = "output"

        fake_requirement_analysis = types.ModuleType("RequirementAnalysis")
        fake_requirement_analysis.DataDictionaryCrew = object()
        fake_requirement_analysis.ERDCrew = object()
        fake_requirement_analysis.DataFlowDiagramCrew = object()
        fake_requirement_analysis.FRCrew = object()
        fake_requirement_analysis.DialogMapCrew = object()

        fake_business_requirements = types.ModuleType("BusinessRequirements")
        fake_business_requirements.__all__ = []

        with patch.dict(
            sys.modules,
            {
                "util": fake_util,
                "util.util": fake_util_util,
                "RequirementAnalysis": fake_requirement_analysis,
                "BusinessRequirements": fake_business_requirements,
            },
            clear=False,
        ):
            spec = importlib.util.spec_from_file_location("reagent_standard_process_json_wrap_test", module_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

        payload = module.load_json_payload_from_markdown(
            """下面是章节 JSON，请直接使用。\n```json\n{\"chapter_index\":\"1\",\"title\":\"Business requirements\",\"structure\":[]}\n```\n输出结束。"""
        )
        self.assertEqual(
            payload,
            {
                "chapter_index": "1",
                "title": "Business requirements",
                "structure": [],
            },
        )

    def test_standard_process_classifies_exit_before_modify_branch(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        module_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "src" / "reagent" / "StandardProcess.py"
        self.assertTrue(module_path.exists(), f"Missing StandardProcess module: {module_path}")

        fake_util = types.ModuleType("util")
        fake_util.store_path = "output"
        fake_util.__all__ = ["store_path"]

        fake_util_util = types.ModuleType("util.util")
        fake_util_util.store_path = "output"

        fake_requirement_analysis = types.ModuleType("RequirementAnalysis")
        fake_requirement_analysis.DataDictionaryCrew = object()
        fake_requirement_analysis.ERDCrew = object()
        fake_requirement_analysis.DataFlowDiagramCrew = object()
        fake_requirement_analysis.FRCrew = object()
        fake_requirement_analysis.DialogMapCrew = object()

        fake_business_requirements = types.ModuleType("BusinessRequirements")
        fake_business_requirements.__all__ = []

        with patch.dict(
            sys.modules,
            {
                "util": fake_util,
                "util.util": fake_util_util,
                "RequirementAnalysis": fake_requirement_analysis,
                "BusinessRequirements": fake_business_requirements,
            },
            clear=False,
        ):
            spec = importlib.util.spec_from_file_location("reagent_standard_process_for_test", module_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

        self.assertEqual(module.classify_review_answer("exit"), "exit")
        self.assertEqual(module.classify_review_answer("  no  "), "skip")
        self.assertEqual(module.classify_review_answer("请补充范围边界"), "modify")

    def test_modify_agent_reuses_already_loaded_business_requirements_symbols(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        module_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "src" / "reagent" / "StandardProcess.py"
        self.assertTrue(module_path.exists(), f"Missing StandardProcess module: {module_path}")

        fake_util = types.ModuleType("util")
        fake_util.store_path = "output"
        fake_util.__all__ = ["store_path"]

        fake_util_util = types.ModuleType("util.util")
        fake_util_util.store_path = "output"

        fake_requirement_analysis = types.ModuleType("RequirementAnalysis")
        fake_requirement_analysis.DataDictionaryCrew = object()
        fake_requirement_analysis.ERDCrew = object()
        fake_requirement_analysis.DataFlowDiagramCrew = object()
        fake_requirement_analysis.FRCrew = object()
        fake_requirement_analysis.DialogMapCrew = object()

        fake_business_requirements = types.ModuleType("BusinessRequirements")
        fake_business_requirements.BRDModifyCrew = object()
        fake_business_requirements.BRDModifyLocateCrew = object()
        fake_business_requirements.__all__ = ["BRDModifyCrew", "BRDModifyLocateCrew"]

        with patch.dict(
            sys.modules,
            {
                "util": fake_util,
                "util.util": fake_util_util,
                "RequirementAnalysis": fake_requirement_analysis,
                "BusinessRequirements": fake_business_requirements,
            },
            clear=False,
        ):
            spec = importlib.util.spec_from_file_location("reagent_standard_process_modify_test", module_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

        # 教学注释：
        # 这里刻意把 BusinessRequirements 从 sys.modules 里移走，
        # 模拟平台长流程运行时“前面导入成功，后面临时再导入一次却失败”的现场。
        # 如果 modify_agent 依赖重复导入，这里就会直接炸掉。
        sys.modules.pop("BusinessRequirements", None)

        module.json = json
        module.store_path = "output"
        module.get_reference = lambda reference, artifact=True: f"reference::{','.join(reference)}::{artifact}"
        module.get_dependent_artifacts = lambda re_execute: {"feature_tree", "business_scope"}
        module.read_markdown = lambda path: json.dumps(["feature_tree", "business_scope"])
        module.run_with_retry = lambda crew, inputs, name, post_process_callable: post_process_callable()

        result = module.modify_agent(
            ["去掉人机模式，只保留双人对战模式"],
            project_name="gomoku",
            Description="开发一个五子棋游戏",
        )

        self.assertEqual(
            result,
            {
                "feature_tree": "",
                "business_scope": "",
            },
        )

    def test_non_standard_process_runs_each_supported_artifact_once(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        module_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "src" / "reagent" / "NonStandardProcess.py"
        self.assertTrue(module_path.exists(), f"Missing NonStandardProcess module: {module_path}")

        calls: list[str] = []

        fake_requirement_elicitation = types.ModuleType("RequirementElicitation")
        fake_requirement_elicitation.UsageScenarioCrew = object()

        fake_requirement_analysis = types.ModuleType("RequirementAnalysis")
        fake_requirement_analysis.STDCrew = object()
        fake_requirement_analysis.DialogMapCrew = object()

        fake_util = types.ModuleType("util")
        fake_util.topological_sort = lambda *_args, **_kwargs: ["usage_scenario", "state_transition_diagram", "ignored"]
        fake_util.to_artifact_DAG = lambda planning: planning
        fake_util.run_with_retry = lambda *args, **kwargs: None
        fake_util.get_usage_scenario = lambda: "usage scenario" * 20
        fake_util.get_state_transition_diagram = lambda: "state transition" * 20

        with patch.dict(
            sys.modules,
            {
                "RequirementElicitation": fake_requirement_elicitation,
                "RequirementAnalysis": fake_requirement_analysis,
                "util": fake_util,
            },
            clear=False,
        ):
            spec = importlib.util.spec_from_file_location("reagent_non_standard_process_for_test", module_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

        class FakeUsageScenarioRun:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def run(self) -> None:
                calls.append("usage_scenario")

        class FakeStateTransitionDiagramRun:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def run(self) -> None:
                calls.append("state_transition_diagram")

        module.UsageScenariorun = FakeUsageScenarioRun
        module.StateTransitionDiagramrun = FakeStateTransitionDiagramRun

        module.NonStandardProcessrun("Snake Game", "Build a snake game", ["usage_scenario", "state_transition_diagram"])

        self.assertEqual(calls, ["usage_scenario", "state_transition_diagram"])

    def test_runtime_env_sets_local_crewai_storage_defaults(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        runtime_env_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "util" / "runtime_env.py"
        self.assertTrue(runtime_env_path.exists(), f"Missing runtime env helper: {runtime_env_path}")

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_repo_root = Path(temp_dir) / "repo"
            fake_project_root = fake_repo_root / "agent" / "Requirements Agent" / "reagent"
            fake_repo_root.mkdir(parents=True, exist_ok=True)
            fake_project_root.mkdir(parents=True, exist_ok=True)
            (fake_repo_root / "agent").mkdir(parents=True, exist_ok=True)
            (fake_repo_root / "agent" / "platform").mkdir(parents=True, exist_ok=True)

            spec = importlib.util.spec_from_file_location("reagent_runtime_env_defaults", runtime_env_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            runtime_home = fake_project_root.resolve() / ".runtime-home"
            with patch.dict(os.environ, {}, clear=True):
                loaded = module.load_runtime_env(fake_project_root)
                self.assertEqual(os.environ["HOME"], str(runtime_home))
                self.assertEqual(os.environ["CREWAI_STORAGE_DIR"], str(runtime_home / "crewai-storage"))

            self.assertEqual(loaded["HOME"], str(runtime_home))
            self.assertEqual(loaded["CREWAI_STORAGE_DIR"], str(runtime_home / "crewai-storage"))
            self.assertTrue(runtime_home.exists())
            self.assertTrue((runtime_home / "crewai-storage").exists())

    def test_runtime_env_loads_repo_root_env_local_and_bridges_openai_aliases(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        runtime_env_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "util" / "runtime_env.py"
        self.assertTrue(runtime_env_path.exists(), f"Missing runtime env helper: {runtime_env_path}")

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_repo_root = Path(temp_dir) / "repo"
            fake_project_root = fake_repo_root / "agent" / "Requirements Agent" / "reagent"
            fake_repo_root.mkdir(parents=True, exist_ok=True)
            fake_project_root.mkdir(parents=True, exist_ok=True)
            (fake_repo_root / "agent").mkdir(parents=True, exist_ok=True)
            (fake_repo_root / "agent" / "platform").mkdir(parents=True, exist_ok=True)
            (fake_repo_root / ".env.local").write_text(
                "\n".join(
                    [
                        "ISOFTDEVAGENTS_LLM_API_KEY=repo-key",
                        "ISOFTDEVAGENTS_LLM_BASE_URL=https://repo.example/v1",
                        "ISOFTDEVAGENTS_LLM_MODEL=moonshot/kimi-k2.5",
                    ]
                ),
                encoding="utf-8",
            )

            spec = importlib.util.spec_from_file_location("reagent_runtime_env_for_test", runtime_env_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            with patch.dict(os.environ, {}, clear=True):
                loaded = module.load_runtime_env(fake_project_root)

            self.assertEqual(loaded["ISOFTDEVAGENTS_LLM_API_KEY"], "repo-key")
            self.assertEqual(loaded["OPENAI_API_KEY"], "repo-key")
            self.assertEqual(loaded["ISOFTDEVAGENTS_LLM_BASE_URL"], "https://repo.example/v1")
            self.assertEqual(loaded["OPENAI_BASE_URL"], "https://repo.example/v1")
            self.assertEqual(loaded["ISOFTDEVAGENTS_LLM_MODEL"], "openai/moonshot/kimi-k2.5")
            self.assertEqual(loaded["OPENAI_MODEL"], "openai/moonshot/kimi-k2.5")

    def test_runtime_env_sets_tracing_and_telemetry_disabled_defaults(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        runtime_env_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "util" / "runtime_env.py"
        self.assertTrue(runtime_env_path.exists(), f"Missing runtime env helper: {runtime_env_path}")

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_repo_root = Path(temp_dir) / "repo"
            fake_project_root = fake_repo_root / "agent" / "Requirements Agent" / "reagent"
            fake_repo_root.mkdir(parents=True, exist_ok=True)
            fake_project_root.mkdir(parents=True, exist_ok=True)
            (fake_repo_root / "agent").mkdir(parents=True, exist_ok=True)
            (fake_repo_root / "agent" / "platform").mkdir(parents=True, exist_ok=True)

            spec = importlib.util.spec_from_file_location("reagent_runtime_env_tracing_defaults", runtime_env_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            with patch.dict(os.environ, {}, clear=True):
                loaded = module.load_runtime_env(fake_project_root)

            self.assertEqual(loaded["CREWAI_TRACING_ENABLED"], "false")
            self.assertEqual(loaded["OTEL_SDK_DISABLED"], "true")
            self.assertEqual(loaded["CREWAI_DISABLE_TELEMETRY"], "true")
            self.assertEqual(loaded["CREWAI_DISABLE_TRACKING"], "true")

    def test_runtime_env_can_force_disable_tracing_even_if_external_env_enabled(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        runtime_env_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "util" / "runtime_env.py"
        self.assertTrue(runtime_env_path.exists(), f"Missing runtime env helper: {runtime_env_path}")

        spec = importlib.util.spec_from_file_location("reagent_runtime_env_force_disable", runtime_env_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with patch.dict(
            os.environ,
            {
                "CREWAI_TRACING_ENABLED": "true",
                "OTEL_SDK_DISABLED": "false",
                "CREWAI_DISABLE_TELEMETRY": "false",
                "CREWAI_DISABLE_TRACKING": "false",
            },
            clear=True,
        ):
            applied = module.apply_runtime_observability_defaults(force=True)

            self.assertEqual(os.environ["CREWAI_TRACING_ENABLED"], "false")
            self.assertEqual(os.environ["OTEL_SDK_DISABLED"], "true")
            self.assertEqual(os.environ["CREWAI_DISABLE_TELEMETRY"], "true")
            self.assertEqual(os.environ["CREWAI_DISABLE_TRACKING"], "true")
            self.assertEqual(applied["CREWAI_TRACING_ENABLED"], "false")
            self.assertEqual(applied["OTEL_SDK_DISABLED"], "true")

    def test_util_module_imports_when_prompt_toolkit_is_unavailable(self) -> None:
        import builtins

        repo_root = Path(__file__).resolve().parents[3]
        util_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "util" / "util.py"
        self.assertTrue(util_path.exists(), f"Missing util module: {util_path}")

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "prompt_toolkit" or name.startswith("prompt_toolkit."):
                raise ModuleNotFoundError("No module named 'prompt_toolkit'")
            return real_import(name, globals, locals, fromlist, level)

        with patch.dict(os.environ, {"ISOFTDEVAGENTS_REAGENT_NONINTERACTIVE": "1"}, clear=False), patch(
            "builtins.__import__",
            side_effect=fake_import,
        ):
            spec = importlib.util.spec_from_file_location("reagent_util_missing_prompt_toolkit", util_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.multiline_input(), "no")

    def test_util_module_creates_reagent_store_path_directory(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        util_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "util" / "util.py"
        self.assertTrue(util_path.exists(), f"Missing util module: {util_path}")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "nested" / "reagent-output"
            spec = importlib.util.spec_from_file_location("reagent_util_store_path", util_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)

            with patch.dict(
                os.environ,
                {
                    "ISOFTDEVAGENTS_REAGENT_NONINTERACTIVE": "1",
                    "REAGENT_STORE_PATH": str(output_root),
                },
                clear=True,
            ):
                spec.loader.exec_module(module)
                self.assertEqual(Path(module.store_path), output_root)
                self.assertTrue(output_root.exists())
                self.assertTrue(output_root.is_dir())

    def test_util_module_imports_without_prompt_toolkit_in_noninteractive_mode(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        util_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "util" / "util.py"
        self.assertTrue(util_path.exists(), f"Missing util module: {util_path}")

        script = textwrap.dedent(
            f"""
            import importlib.util
            import os
            import sys

            os.environ["ISOFTDEVAGENTS_REAGENT_NONINTERACTIVE"] = "1"
            spec = importlib.util.spec_from_file_location("reagent_util_for_test", {str(util_path)!r})
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            print(module.multiline_input())
            """
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "check_reagent_util.py"
            script_path.write_text(script, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                env=os.environ.copy(),
                check=False,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "no")

    def test_requirement_specification_import_does_not_override_crewai_storage_dir(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        module_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "src" / "reagent" / "RequirementSpecification.py"
        self.assertTrue(module_path.exists(), f"Missing RequirementSpecification module: {module_path}")

        fake_software_manager = types.ModuleType("util.SoftwareManager")
        fake_software_manager.SoftwareManagerCrew = type("SoftwareManagerCrew", (), {})

        fake_crewai = types.ModuleType("crewai")
        fake_crewai.Agent = object
        fake_crewai.Crew = object
        fake_crewai.Process = object
        fake_crewai.Task = object

        fake_project = types.ModuleType("crewai.project")
        fake_project.CrewBase = lambda cls: cls
        fake_project.agent = lambda func: func
        fake_project.crew = lambda func: func
        fake_project.task = lambda func: func
        fake_project.before_kickoff = lambda func: func
        fake_project.after_kickoff = lambda func: func

        fake_tools = types.ModuleType("crewai_tools")
        fake_tools.WebsiteSearchTool = object

        fake_base_agent = types.ModuleType("crewai.agents.agent_builder.base_agent")
        fake_base_agent.BaseAgent = object

        fake_util_util = types.ModuleType("util.util")
        fake_util_util.store_path = "output"

        with patch.dict(
            sys.modules,
            {
                "util.SoftwareManager": fake_software_manager,
                "crewai": fake_crewai,
                "crewai.project": fake_project,
                "crewai_tools": fake_tools,
                "crewai.agents.agent_builder.base_agent": fake_base_agent,
                "util.util": fake_util_util,
            },
            clear=False,
        ), patch.dict(os.environ, {"CREWAI_STORAGE_DIR": "/tmp/original-storage"}, clear=True):
            spec = importlib.util.spec_from_file_location("reagent_requirement_specification_for_test", module_path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(os.environ["CREWAI_STORAGE_DIR"], "/tmp/original-storage")

    def test_requirement_extraction_writes_summary_files_into_reagent_store_path(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        module_path = repo_root / "agent" / "Requirements Agent" / "reagent" / "src" / "reagent" / "RequirementExtraction.py"
        self.assertTrue(module_path.exists(), f"Missing RequirementExtraction module: {module_path}")

        fake_landingai = types.ModuleType("landingai_ade")
        fake_landingai.LandingAIADE = object

        fake_crewai = types.ModuleType("crewai")
        fake_crewai.Agent = object
        fake_crewai.Crew = object
        fake_crewai.Process = object
        fake_crewai.Task = object

        fake_project = types.ModuleType("crewai.project")
        fake_project.CrewBase = lambda cls: cls
        fake_project.agent = lambda func: func
        fake_project.crew = lambda func: func
        fake_project.task = lambda func: func

        fake_tools = types.ModuleType("crewai_tools")
        fake_tools.WebsiteSearchTool = object

        fake_software_manager = types.ModuleType("util.SoftwareManager")
        fake_software_manager.SoftwareManagerCrew = type("SoftwareManagerCrew", (), {})

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "reagent-output"
            output_root.mkdir(parents=True, exist_ok=True)

            fake_util_pkg = types.ModuleType("util")
            fake_util_pkg.__all__ = ["run_with_retry", "read_markdown"]

            def fake_read_markdown(path: str) -> str:
                return Path(path).read_text(encoding="utf-8")

            def fake_run_with_retry(_crew, _inputs, name, retries=5, delay=15, post_process_callable=None, post_process_params=None):
                (output_root / "information_summary.md").write_text("x" * 120, encoding="utf-8")
                if post_process_callable is None:
                    return None
                if post_process_params is not None:
                    return post_process_callable(post_process_params)
                return post_process_callable()

            fake_util_pkg.run_with_retry = fake_run_with_retry
            fake_util_pkg.read_markdown = fake_read_markdown

            fake_util_util = types.ModuleType("util.util")
            fake_util_util.store_path = str(output_root)

            with patch.dict(
                sys.modules,
                {
                    "landingai_ade": fake_landingai,
                    "crewai": fake_crewai,
                    "crewai.project": fake_project,
                    "crewai_tools": fake_tools,
                    "util.SoftwareManager": fake_software_manager,
                    "util": fake_util_pkg,
                    "util.util": fake_util_util,
                },
                clear=False,
            ):
                spec = importlib.util.spec_from_file_location("reagent_requirement_extraction_for_test", module_path)
                self.assertIsNotNone(spec)
                self.assertIsNotNone(spec.loader)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

            with patch.object(module, "parse_folder_into_md", return_value={"doc-a.md": "hello"}):
                runner = module.RequirementsExtractionRun("Demo", "Desc", "/tmp/input")
                runner.run()

            project_summary_path = output_root / "project_data_summary.md"
            total_data_path = output_root / "total_project_data.md"
            self.assertTrue(project_summary_path.exists())
            self.assertTrue(total_data_path.exists())
            self.assertEqual(json.loads(project_summary_path.read_text(encoding="utf-8")), {"doc-a.md": "x" * 120})
            self.assertEqual(json.loads(total_data_path.read_text(encoding="utf-8")), {"doc-a.md": "hello"})
