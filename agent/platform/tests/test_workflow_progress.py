import sys
import tempfile
import asyncio
import os
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import workflow
from app.services.agent_output_contracts import (
    build_main_panel_contract,
    planned_architecture_files,
    planned_code_files,
    planned_requirements_analysis_files,
    planned_requirements_full_files,
    planned_test_files,
    planned_ui_files,
)
from app.services.store import SQLiteStore


class WorkflowProgressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.outputs_dir = Path(self.temp_dir.name) / "project-outputs"
        self.store = SQLiteStore(db_path=str(Path(self.temp_dir.name) / "test.db"))
        self.project = self.store.create_project("Realtime UX Project", "Progress streaming")
        self.workflow_store_patcher = patch("app.services.workflow.store", self.store)
        self.workflow_store_patcher.start()
        self.workflow_output_root_patcher = patch("app.services.workflow._PROJECT_OUTPUTS_ROOT", self.outputs_dir)
        self.workflow_output_root_patcher.start()

    def tearDown(self) -> None:
        self.workflow_output_root_patcher.stop()
        self.workflow_store_patcher.stop()
        self.store._connection.close()
        self.temp_dir.cleanup()

    def test_project_task_output_dir_uses_project_and_task_hierarchy(self) -> None:
        output_dir = workflow._project_task_output_dir(
            self.project.id,
            "task-123",
            "requirements-analysis",
        )

        self.assertEqual(
            output_dir,
            self.outputs_dir / self.project.id / "tasks" / "task-123" / "requirements-analysis",
        )

    def test_extract_output_file_from_status_ignores_prompt_reference_noise(self) -> None:
        self.assertIsNone(workflow._extract_output_file_from_status("Survey reference: # Project Request"))
        self.assertIsNone(
            workflow._extract_output_file_from_status(
                "LiteLLM:WARNING get_model_cost_map.py:271 - Failed to fetch remote model cost map"
            )
        )

    def test_extract_output_file_from_status_maps_feature_tree_attempt(self) -> None:
        self.assertEqual(
            workflow._extract_output_file_from_status("[FeatureTreeDev] Attempt 1/3"),
            "feature_tree.md",
        )

    def test_extract_output_file_from_status_does_not_map_requirements_keywords_for_test_agent_logs(self) -> None:
        self.assertIsNone(
            workflow._structured_status_update(
                "Test Agent: Generating test cases from functional requirements",
                locale="zh",
            )
        )

    def test_extract_output_file_from_status_keeps_requirements_keyword_mapping_for_requirements_agent_logs(self) -> None:
        structured = workflow._structured_status_update(
            "Requirements Agent: Generating functional requirements",
            locale="zh",
        )

        self.assertIsNotNone(structured)
        assert structured is not None
        self.assertEqual(structured["rawFileName"], "functional_requirements.md")

    def test_filter_output_files_for_requirements_analysis_keeps_only_feature_tree(self) -> None:
        self.assertEqual(
            workflow._filter_visible_output_files_for_phase(
                "requirements_analysis",
                ["user_introduction.md", "draft_context_diagram.md", "feature_tree.md"],
            ),
            ["feature_tree.md"],
        )

    def test_filter_output_files_for_architecture_phase_ignores_requirements_files(self) -> None:
        self.assertEqual(
            workflow._filter_visible_output_files_for_phase(
                "architecture_generation_started",
                ["non_functional_requirements.md", "analysis_task_output.txt", "component_design.json"],
            ),
            ["analysis_task_output.txt", "component_design.json"],
        )

    def test_filter_seeded_output_files_excludes_reused_files_from_step_outputs(self) -> None:
        self.assertEqual(
            workflow._filter_seeded_output_files(
                ["feature_tree.md", "survey.md", "business_scope.md"],
                seeded_files=["feature_tree.md"],
            ),
            ["survey.md", "business_scope.md"],
        )

    def test_user_facing_primary_output_files_hides_modify_and_pickle_files(self) -> None:
        self.assertEqual(
            workflow._user_facing_primary_output_files(
                ["BRD.md", "BRD_modify.md", "BusinessRequirementDocument.pkl"]
            ),
            ["BRD.md"],
        )

    def test_requirements_feedback_confirmation_payload_uses_only_user_facing_primary_files(self) -> None:
        payload = workflow._requirements_feedback_confirmation_payload(
            locale="zh",
            prompt_text="",
            output_files=["BRD.md", "BRD_modify.md", "BusinessRequirementDocument.pkl"],
            return_phase="requirements_feedback_required",
            return_agent="requirements_agent",
        )

        self.assertEqual(payload["outputFiles"], ["BRD.md"])
        self.assertIn("BRD.md", payload["message"])
        self.assertNotIn("BRD_modify.md", payload["message"])
        self.assertNotIn(".pkl", payload["message"])

    def test_requirements_artifact_review_confirmation_payload_uses_only_user_facing_primary_files(self) -> None:
        payload = workflow._requirements_artifact_review_confirmation_payload(
            locale="zh",
            reference_snapshot=[],
            selected_module_ids=[],
            artifact_sources={
                "prd": {
                    "source": "requirements_agent",
                    "status": "completed",
                    "sourceFiles": ["BRD.md", "BRD_modify.md", "BusinessRequirementDocument.pkl"],
                },
                "ui": {
                    "source": "requirements_agent",
                    "status": "completed",
                    "sourceFiles": ["use_case.md"],
                },
                "api_spec": {
                    "source": "requirements_agent",
                    "status": "completed",
                    "sourceFiles": ["api_design.md"],
                },
            },
            context_summary={},
        )

        self.assertIn("BRD.md", payload["message"])
        self.assertIn("use_case.md", payload["message"])
        self.assertNotIn("BRD_modify.md", payload["message"])
        self.assertNotIn(".pkl", payload["message"])
        self.assertEqual(payload["outputFiles"], ["BRD.md", "use_case.md", "api_design.md"])

    def test_list_relative_output_files_returns_sorted_relative_paths(self) -> None:
        output_root = Path(self.temp_dir.name) / "agent-output"
        (output_root / "nested").mkdir(parents=True, exist_ok=True)
        (output_root / "b.md").write_text("b", encoding="utf-8")
        (output_root / "nested" / "a.md").write_text("a", encoding="utf-8")

        self.assertEqual(
            workflow._list_relative_output_files(output_root),
            ["b.md", "nested/a.md"],
        )

    def test_record_pending_agent_artifacts_version_keeps_waiting_task_waiting(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="waiting_user",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.update_task(
            task.id,
            output_data={
                "confirmationKind": "requirements_feedback",
                "activePhase": "requirements_feedback_required",
                "activeAgent": "requirements_agent",
            },
        )
        self.store.register_agent_artifacts(
            self.project.id,
            version=2,
            task_id=task.id,
            agent_name="requirements_agent",
            artifacts=[
                {
                    "fileName": "feature_tree.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Feature Tree",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd", "ui", "api_spec"],
                }
            ],
        )

        workflow._record_pending_agent_artifacts_version(
            self.project.id,
            task.id,
            pending_version=2,
            active_phase="requirements_drafts_started",
            active_agent="requirements_agent",
        )

        live_task = self.store.get_task(task.id)
        self.assertIsNotNone(live_task)
        assert live_task is not None
        self.assertEqual(live_task.status, "waiting_user")

    def test_reconciled_stage_usage_prefers_streaming_snapshot_when_final_usage_is_missing(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.update_task(
            task.id,
            output_data={
                "streamingUsage": {
                    "architecture": {
                        "model": "openai/gpt-5.4",
                        "inputTokens": 120,
                        "outputTokens": 40,
                        "totalTokens": 160,
                        "costAmount": 0.12,
                        "sourceAgent": "architecture_agent",
                    }
                }
            },
        )

        reconciled = workflow._reconciled_stage_usage(
            task.id,
            stream_key="architecture",
            final_usage=None,
            default_model="openai/gpt-5.4",
        )

        self.assertEqual(
            reconciled,
            {
                "model": "openai/gpt-5.4",
                "inputTokens": 120,
                "outputTokens": 40,
                "totalTokens": 160,
                "costAmount": 0.12,
            },
        )

    def test_wait_for_running_task_stop_reports_timeout_details_when_completion_was_never_signaled(self) -> None:
        cancel_event = threading.Event()
        completion_event = threading.Event()
        # 教学注释：
        # 这里故意只注册、不收尾，模拟“旧 Agent 逻辑上应该结束了，
        # 但 completion_event 没有回写，registry 也没清掉”的现场。
        workflow.register_running_task(
            "task-stop-timeout",
            cancel_event=cancel_event,
            completion_event=completion_event,
            agent_name="architecture_agent",
            runtime_state="running",
            output_root="/tmp/architecture-output",
        )

        details = workflow.wait_for_running_task_stop("task-stop-timeout", timeout_seconds=0.01)

        self.assertFalse(details["stopped_cleanly"])
        self.assertEqual(details["agent_name"], "architecture_agent")
        self.assertEqual(details["stop_reason"], "completion_timeout")
        self.assertTrue(details["registry_present"])
        self.assertFalse(details["completion_signaled"])
        workflow.unregister_running_task("task-stop-timeout")

    async def test_stop_running_task_before_stage_transition_persists_handoff_debug_bundle_on_timeout(self) -> None:
        cancel_event = threading.Event()
        completion_event = threading.Event()
        workflow.register_running_task(
            "task-handoff-timeout",
            cancel_event=cancel_event,
            completion_event=completion_event,
            agent_name="architecture_agent",
            runtime_state="running",
            runtime_home="/tmp/architecture-runtime",
            output_root="/tmp/architecture-output",
            latest_output_file="analysis_task_output.txt",
            stdout_preview="Architecture Agent: Generating analysis_task_output.txt.",
            stderr_preview="",
        )

        with patch(
            "app.services.workflow._AGENT_SHUTDOWN_WAIT_SECONDS",
            0.01,
        ), patch.object(
            workflow.agent_orchestrator,
            "_persist_agent_debug_bundle",
            return_value=Path("/tmp/agent-debug/architecture-agent/failure-handoff"),
        ) as persist_debug_bundle:
            with self.assertRaisesRegex(RuntimeError, "architecture live recovery handoff"):
                await workflow._stop_running_task_before_stage_transition(
                    "task-handoff-timeout",
                    stage_name="architecture live recovery handoff",
                )

        persist_debug_bundle.assert_called_once()
        self.assertEqual(persist_debug_bundle.call_args.kwargs["agent_name"], "architecture-agent")
        self.assertIn("handoff_timeout", persist_debug_bundle.call_args.kwargs["context"]["reason"])
        workflow.unregister_running_task("task-handoff-timeout")

    async def test_recover_incomplete_tasks_restores_waiting_task_when_confirmation_card_was_already_written(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.add_message(
            workflow.Message(
                projectId=self.project.id,
                role="agent",
                type="select_options",
                content="请选择下一步",
                metadata={
                    "taskId": task.id,
                    "taskStatus": "waiting_user",
                    "confirmationKind": "artifact_review",
                    "activePhase": "waiting_for_artifact_review",
                    "title": "架构评审",
                    "message": "请确认当前草稿",
                    "options": [{"id": "prd", "label": "PRD", "labelEn": "PRD"}],
                },
            )
        )

        await workflow.recover_incomplete_tasks()

        refreshed_task = self.store.get_task(task.id)
        self.assertIsNotNone(refreshed_task)
        assert refreshed_task is not None
        self.assertEqual(refreshed_task.status, "waiting_user")
        self.assertEqual(refreshed_task.outputData["confirmationKind"], "artifact_review")
        self.assertEqual(refreshed_task.outputData["activePhase"], "waiting_for_artifact_review")

    def test_requirements_stage_output_contract_covers_expected_files(self) -> None:
        contract = workflow._requirements_stage_output_contract()

        self.assertEqual(sorted(contract.keys()), ["api_spec", "architecture", "prd", "ui"])
        self.assertEqual([item["fileName"] for item in contract["prd"]], ["feature_tree.md"])
        # 原因注释：
        # UI 主面板现在明确只留给 UI Agent 自己的页面产物，
        # 需求阶段的 `feature_tree.md` 虽然会影响后续 UI 生成，
        # 但它本身仍然属于需求输入，不应该直接出现在 UI 标签里。
        self.assertEqual([item["fileName"] for item in contract["ui"]], [])
        self.assertEqual([item["fileName"] for item in contract["api_spec"]], [])
        self.assertEqual(contract["architecture"], [])

    def test_full_output_contract_keeps_api_panel_focused_on_real_api_sources(self) -> None:
        contract = workflow._full_output_contract()

        # 接口注释：
        # API 标签页现在不再预挂一个并不存在的 planned file。
        # 真正有 API artifact 内容时，前端会直接展示 artifact，
        # 但不会再额外显示一条“docs/API.yaml 待生成/失败”的假文件行。
        self.assertEqual([item["fileName"] for item in contract["api_spec"]], [])

    def test_main_panel_contract_assigns_each_panel_a_stable_boundary(self) -> None:
        contract = build_main_panel_contract(
            requirements_mode="full",
            include_architecture=True,
            include_ui_agent_outputs=True,
        )

        # 教学注释：
        # 这组断言不是为了测试文件顺序这么简单，
        # 更重要的是把四个主标签页的边界直接钉死。
        # 以后如果有人改了归类规则，这里会第一时间提示“哪个面板被改脏了”。
        self.assertEqual(
            [item["fileName"] for item in contract["prd"]],
            [
                "survey.md",
                "user_introduction.md",
                "feature_tree.md",
                "business_scope.md",
                "BRD.md",
                "non_functional_requirements.md",
                "functional_requirements.md",
                "SRS.md",
            ],
        )
        self.assertEqual(
            [item["fileName"] for item in contract["ui"]],
            [
                "page_descriptions.json",
                "page_descriptions.md",
                "dar_model.json",
                "dar_model.md",
                "app/index.html",
                "app/css/style.css",
                "app/js/index.js",
                "app/js/api.js",
            ],
        )
        self.assertEqual([item["fileName"] for item in contract["api_spec"]], [])
        self.assertEqual(
            [item["fileName"] for item in contract["architecture"]],
            [
                "analysis_task_output.txt",
                "component_design.json",
                "class_design_structured.json",
                "class_design_raw.md",
            ],
        )

    def test_real_agent_output_contract_helpers_match_the_new_plan(self) -> None:
        self.assertEqual(planned_requirements_analysis_files(), ["feature_tree.md"])
        self.assertEqual(
            planned_requirements_full_files(),
            [
                "survey.md",
                "draft_context_diagram.md",
                "draft_event_list.md",
                "user_introduction.md",
                "feature_tree.md",
                "business_scope.md",
                "BRD.md",
                "use_case.md",
                "non_functional_requirements.md",
                "functional_requirements.md",
                "data_flow_diagram.md",
                "entity_relationship_diagram.md",
                "data_dictionary.md",
                "dialog_map.md",
                "usage_scenario.md",
                "state_transition_diagram.md",
                "SRS.md",
            ],
        )
        self.assertEqual(
            planned_architecture_files(),
            [
                "analysis_task_output.txt",
                "component_design.json",
                "class_design_structured.json",
                "class_design_raw.md",
            ],
        )
        self.assertEqual(
            planned_ui_files(),
            [
                "page_descriptions.json",
                "page_descriptions.md",
                "dar_model.json",
                "dar_model.md",
                "app/index.html",
                "app/css/style.css",
                "app/js/index.js",
                "app/js/api.js",
            ],
        )
        self.assertEqual(
            planned_code_files(["customer", "order"]),
            [
                "backend/app/config.py",
                "backend/app/models/__init__.py",
                "backend/app/models/customer.py",
                "backend/app/models/order.py",
                "backend/app/repositories/__init__.py",
                "backend/app/repositories/customer_repository.py",
                "backend/app/repositories/order_repository.py",
                "backend/app/services/__init__.py",
                "backend/app/services/customer_service.py",
                "backend/app/services/order_service.py",
                "backend/app/api/__init__.py",
                "backend/app/api/customer_api.py",
                "backend/app/api/order_api.py",
                "backend/app/__init__.py",
                "backend/run.py",
            ],
        )
        self.assertEqual(
            planned_test_files("crm"),
            [
                "crm_test_plan.md",
                "memory/test_plan.json",
                "crm_testcase.md",
            ],
        )

    async def test_record_streaming_usage_delta_updates_project_statistics_immediately(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a CRM", "uploadedFiles": []},
        )
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")

        with patch("app.services.workflow._broadcast", new=AsyncMock()) as mock_broadcast:
            await workflow._record_streaming_usage_delta(
                self.project.id,
                task.id,
                stream_key="requirements_drafts",
                source_agent="requirements_agent",
                usage_delta={
                    "model": "moonshot/kimi-k2.5",
                    "inputTokens": 25,
                    "outputTokens": 10,
                    "totalTokens": 35,
                    "costAmount": 0.12,
                },
            )

        stats = self.store.get_statistics(task.id)
        self.assertIsNotNone(stats)
        assert stats is not None
        self.assertEqual(stats.inputTokens, 25)
        self.assertEqual(stats.outputTokens, 10)
        self.assertEqual(stats.totalTokens, 35)
        self.assertEqual(stats.costAmount, 0.12)

        payload = workflow._statistics_payload(task.id)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload.usageStatus, "reported")
        self.assertEqual(payload.tokens["total"], 35)

        live_task = self.store.get_task(task.id)
        self.assertIsNotNone(live_task)
        assert live_task is not None
        self.assertEqual(
            ((live_task.outputData or {}).get("streamingUsage") or {}).get("requirements_drafts", {}).get("totalTokens"),
            35,
        )
        self.assertTrue(any(call.args[1] == "statistics" for call in mock_broadcast.await_args_list))

    async def test_enter_waiting_state_preserves_streaming_usage_for_requirements_analysis(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a CRM", "uploadedFiles": []},
        )
        self.store.create_statistics(self.project.id, task.id, model_used="openai/gpt-5.4")
        self.store.update_task(
            task.id,
            output_data={
                "activePhase": "requirements_analysis",
                "activeAgent": "requirements_agent",
                "streamingUsage": {
                    "requirements_analysis": {
                        "model": "openai/gpt-5.4",
                        "sourceAgent": "requirements_agent",
                        "inputTokens": 61,
                        "outputTokens": 24,
                        "totalTokens": 85,
                        "lastEventAt": "2026-04-08T12:00:00+00:00",
                    }
                },
            },
        )
        self.store.update_statistics(
            task.id,
            inputTokens=61,
            outputTokens=24,
            totalTokens=85,
            modelUsed="openai/gpt-5.4",
        )
        self.store.add_step_record(
            task.id,
            "Analyze requirements",
            "process_log",
            duration=1.2,
            tokens_used=0,
            cost=0.0,
            status="completed",
            metadata={
                "usageStatus": "unreported",
                "sourceAgent": "requirements_agent",
            },
        )

        with patch("app.services.workflow._append_process_log", new=AsyncMock(return_value=None)), patch(
            "app.services.workflow._update_message",
            new=AsyncMock(return_value=None),
        ):
            await workflow._enter_waiting_state(
                self.project.id,
                task.id,
                {
                    "title": "确认模块",
                    "message": "请选择模块",
                    "options": [],
                    "confirmText": "继续",
                    "cancelText": "取消",
                    "activeAgent": "requirements_agent",
                    "activePhase": "waiting_for_module_confirmation",
                },
            )

        live_task = self.store.get_task(task.id)
        self.assertIsNotNone(live_task)
        assert live_task is not None
        self.assertIn("streamingUsage", live_task.outputData)

        payload = workflow._statistics_payload(task.id)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload.usageStatus, "reported")

    async def test_record_streaming_usage_snapshot_only_adds_new_remainder(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a CRM", "uploadedFiles": []},
        )
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")

        with patch("app.services.workflow._broadcast", new=AsyncMock()) as mock_broadcast:
            await workflow._record_streaming_usage_snapshot(
                self.project.id,
                task.id,
                stream_key="architecture",
                source_agent="architecture_agent",
                usage_snapshot={
                    "model": "moonshot/kimi-k2.5",
                    "inputTokens": 40,
                    "outputTokens": 20,
                    "totalTokens": 60,
                    "costAmount": 0.2,
                },
            )
            await workflow._record_streaming_usage_snapshot(
                self.project.id,
                task.id,
                stream_key="architecture",
                source_agent="architecture_agent",
                usage_snapshot={
                    "model": "moonshot/kimi-k2.5",
                    "inputTokens": 55,
                    "outputTokens": 25,
                    "totalTokens": 80,
                    "costAmount": 0.3,
                },
            )

        stats = self.store.get_statistics(task.id)
        self.assertIsNotNone(stats)
        assert stats is not None
        self.assertEqual(stats.inputTokens, 55)
        self.assertEqual(stats.outputTokens, 25)
        self.assertEqual(stats.totalTokens, 80)
        self.assertEqual(stats.costAmount, 0.3)

        live_task = self.store.get_task(task.id)
        self.assertIsNotNone(live_task)
        assert live_task is not None
        self.assertEqual(
            ((live_task.outputData or {}).get("streamingUsage") or {}).get("architecture", {}).get("totalTokens"),
            80,
        )
        self.assertGreaterEqual(len(mock_broadcast.await_args_list), 2)

    def test_statistics_payload_includes_agent_usage_breakdown_from_steps_and_active_stream(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a CRM", "uploadedFiles": []},
        )
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")
        self.store.update_statistics(
            task.id,
            inputTokens=90,
            outputTokens=40,
            totalTokens=130,
            costAmount=0.5,
            modelUsed="moonshot/kimi-k2.5",
        )
        self.store.update_task(
            task.id,
            output_data={
                "activePhase": "test_generation_started",
                "activeAgent": "test_agent",
                "streamingUsage": {
                    "test": {
                        "model": "moonshot/kimi-k2.5",
                        "sourceAgent": "test_agent",
                        "inputTokens": 20,
                        "outputTokens": 10,
                        "totalTokens": 30,
                        "costAmount": 0.1,
                        "lastEventAt": "2026-04-08T12:00:00+00:00",
                    }
                },
            },
        )
        self.store.add_step_record(
            task.id,
            "Generate requirements drafts",
            "generation",
            duration=10.0,
            tokens_used=80,
            cost=0.4,
            status="completed",
            metadata={
                "usageStatus": "reported",
                "model": "moonshot/kimi-k2.5",
                "sourceAgent": "requirements_agent",
            },
        )
        self.store.add_step_record(
            task.id,
            "Generate architecture draft",
            "generation",
            duration=5.0,
            tokens_used=0,
            cost=0.0,
            status="completed",
            metadata={
                "usageStatus": "unreported",
                "model": "moonshot/kimi-k2.5",
                "sourceAgent": "architecture_agent",
            },
        )

        payload = workflow._statistics_payload(task.id)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(
            payload.agentUsage,
            [
                {
                    "agent": "requirements_agent",
                    "totalTokens": 80,
                    "cost": 0.4,
                    "model": "moonshot/kimi-k2.5",
                    "usageStatus": "reported",
                },
                {
                    "agent": "architecture_agent",
                    "totalTokens": 0,
                    "cost": 0.0,
                    "model": "moonshot/kimi-k2.5",
                    "usageStatus": "unreported",
                },
                {
                    "agent": "test_agent",
                    "totalTokens": 30,
                    "cost": 0.1,
                    "model": "moonshot/kimi-k2.5",
                    "usageStatus": "reported",
                },
            ],
        )

    def test_remaining_usage_after_streaming_only_keeps_the_unreported_remainder(self) -> None:
        self.assertEqual(
            workflow._remaining_usage_after_streaming(
                {
                    "model": "moonshot/kimi-k2.5",
                    "inputTokens": 70,
                    "outputTokens": 30,
                    "totalTokens": 100,
                    "costAmount": 1.5,
                },
                {
                    "model": "moonshot/kimi-k2.5",
                    "inputTokens": 50,
                    "outputTokens": 20,
                    "totalTokens": 70,
                    "costAmount": 1.0,
                },
            ),
            {
                "model": "moonshot/kimi-k2.5",
                "inputTokens": 20,
                "outputTokens": 10,
                "totalTokens": 30,
                "costAmount": 0.5,
            },
        )

    def test_build_generate_resume_plan_prefers_the_next_stage_after_last_completed_stage(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="failed",
            input_data={"prompt": "Build a CRM", "uploadedFiles": []},
        )
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")
        self.store.replace_modules(
            self.project.id,
            [
                {
                    "id": "customer-management",
                    "name": "Customer Management",
                    "nameEn": "Customer Management",
                    "description": "Manage customer records",
                    "isSelected": True,
                }
            ],
        )
        current_project = self.store.get_project(self.project.id)
        assert current_project is not None
        self.store.register_agent_artifacts(
            self.project.id,
            version=current_project.currentVersion,
            task_id=task.id,
            agent_name="requirements_agent",
            artifacts=[
                {
                    "fileName": "SRS.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# SRS",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd"],
                },
                {
                    "fileName": "use_case.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Use Case",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["ui", "api_spec"],
                },
                {
                    "fileName": "dialog_map.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Dialog Map",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["ui"],
                },
            ],
        )
        self.store.add_step_record(
            task.id,
            "Generate requirements drafts",
            "generation",
            duration=10.0,
            tokens_used=100,
            cost=1.0,
            status="completed",
            metadata={"sourceAgent": "requirements_agent", "usageStatus": "reported"},
        )

        resume_plan = workflow._build_generate_resume_plan(self.project.id, task.id)

        self.assertEqual(resume_plan["mode"], "retry_from_checkpoint")
        self.assertEqual(resume_plan["resumeFromStage"], "architecture")
        self.assertEqual(resume_plan["skippedStages"], ["requirements_analysis", "requirements_drafts"])

    def test_build_planned_artifact_files_for_architecture_stage_marks_real_running_and_failed_statuses(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a CRM", "uploadedFiles": []},
        )
        self.store.update_task(
            task.id,
            output_data={
                "activeAgent": "architecture_agent",
                "activePhase": "architecture_generation_started",
                "pendingAgentArtifactsVersion": 1,
            },
        )
        self.store.register_agent_artifacts(
            self.project.id,
            version=1,
            task_id=task.id,
            agent_name="requirements_agent",
            artifacts=[
                {
                    "fileName": "feature_tree.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Feature Tree",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd", "ui", "api_spec"],
                },
                {
                    "fileName": "SRS.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# SRS",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd"],
                },
            ],
        )

        planned = workflow.build_planned_artifact_files_for_task(self.project.id, self.store.get_task(task.id))
        prd_files = {item.fileName: item for item in planned["prd"]}
        architecture_files = {item.fileName: item for item in planned["architecture"]}

        self.assertEqual(prd_files["feature_tree.md"].status, "completed")
        self.assertEqual(prd_files["business_scope.md"].status, "failed")
        self.assertEqual(architecture_files["component_design.json"].status, "running")
        self.assertEqual(architecture_files["class_design_raw.md"].status, "running")

    def test_build_planned_artifact_files_for_failed_architecture_stage_marks_remaining_files_failed(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="failed",
            input_data={"prompt": "Build a CRM", "uploadedFiles": []},
        )
        self.store.update_task(
            task.id,
            output_data={
                "activeAgent": "architecture_agent",
                "activePhase": "architecture_generation_started",
                "pendingAgentArtifactsVersion": 1,
            },
        )

        planned = workflow.build_planned_artifact_files_for_task(self.project.id, self.store.get_task(task.id))
        architecture_files = {item.fileName: item for item in planned["architecture"]}

        self.assertEqual(architecture_files["component_design.json"].status, "failed")
        self.assertEqual(architecture_files["class_design_raw.md"].status, "failed")

    def test_build_planned_artifact_files_keeps_ui_panel_reserved_for_ui_agent_outputs(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="completed",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.update_task(
            task.id,
            output_data={
                "activeAgent": "requirements_agent",
                "activePhase": "requirements_drafts_started",
                "pendingAgentArtifactsVersion": 1,
            },
        )
        self.store.register_agent_artifacts(
            self.project.id,
            version=1,
            task_id=task.id,
            agent_name="requirements_agent",
            artifacts=[
                {
                    "fileName": "feature_tree.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Feature Tree",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd", "ui", "api_spec"],
                },
                {
                    "fileName": "use_case.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Use Case",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["ui", "api_spec"],
                },
            ],
        )

        planned = workflow.build_planned_artifact_files_for_task(self.project.id, self.store.get_task(task.id))

        self.assertEqual(planned["ui"], [])

    def test_build_requirements_payload_from_agent_artifacts_reconstructs_review_docs_without_stored_artifacts(self) -> None:
        self.store.register_agent_artifacts(
            self.project.id,
            version=2,
            task_id="task-123",
            agent_name="requirements_agent",
            artifacts=[
                {
                    "fileName": "business_scope.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Business Scope\n\nBuild a snake game for the browser.",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd"],
                },
                {
                    "fileName": "feature_tree.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Feature Tree\n\n- Snake Core",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd", "ui", "api_spec"],
                },
            ],
        )

        payload = workflow._build_requirements_payload_from_agent_artifacts(
            project_id=self.project.id,
            version=2,
            prompt="Build a snake game",
            selected_modules=[
                {
                    "label": "Snake Core",
                    "labelEn": "Snake Core",
                }
            ],
            source_files_by_artifact={
                "prd": ["business_scope.md", "feature_tree.md"],
                "ui": ["feature_tree.md"],
                "api_spec": ["feature_tree.md"],
            },
        )

        self.assertIn("Product Requirements Document", payload["prd"])
        self.assertIn("Page Inventory", payload["ui"])
        self.assertIn("openapi: 3.0.0", payload["api_spec"])

    def test_list_agent_artifacts_keeps_previous_stage_files_visible_in_later_versions(self) -> None:
        self.store.register_agent_artifacts(
            self.project.id,
            version=1,
            task_id="task-1",
            agent_name="requirements_agent",
            artifacts=[
                {
                    "fileName": "feature_tree.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Feature Tree",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd"],
                }
            ],
        )
        self.store.register_agent_artifacts(
            self.project.id,
            version=2,
            task_id="task-2",
            agent_name="architecture_agent",
            artifacts=[
                {
                    "fileName": "component_design.json",
                    "fileType": "json",
                    "contentType": "application/json",
                    "content": "{\"components\": []}",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["architecture"],
                }
            ],
        )

        visible = self.store.list_agent_artifacts(self.project.id, version=2)

        self.assertEqual(
            [(artifact.agent, artifact.fileName) for artifact in visible],
            [
                ("architecture_agent", "component_design.json"),
                ("requirements_agent", "feature_tree.md"),
            ],
        )

    async def test_register_live_agent_output_dir_persists_docs_immediately_and_broadcasts_refresh(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "survey.md").write_text("# Survey\n\nRealtime draft", encoding="utf-8")

            with patch("app.services.workflow._broadcast", new=AsyncMock()) as mocked_broadcast:
                output_files = await workflow._register_live_agent_output_dir(
                    self.project.id,
                    task.id,
                    version=2,
                    agent_name="requirements_agent",
                    archive_stage="requirements-drafts",
                    output_dir=str(output_root),
                )

        self.assertEqual(output_files, ["survey.md"])
        registered = self.store.list_agent_artifacts(self.project.id, version=2, agent_name="requirements_agent")
        self.assertEqual([item.fileName for item in registered], ["survey.md"])
        archived_path = self.outputs_dir / self.project.id / "tasks" / task.id / "requirements-drafts" / "survey.md"
        self.assertTrue(archived_path.exists())
        self.assertEqual(archived_path.read_text(encoding="utf-8"), "# Survey\n\nRealtime draft")
        artifact_events = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3 and call.args[1] == "artifact_update"
        ]
        self.assertEqual(len(artifact_events), 1)
        self.assertEqual(artifact_events[0]["action"], "raw_output_registered")

    def test_register_coding_agent_outputs_archives_files_under_project_task_stage(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "modify",
            status="running",
            input_data={"prompt": "Update the backend", "uploadedFiles": []},
        )

        output_files = workflow._register_coding_agent_outputs(
            self.project.id,
            task.id,
            version=3,
            archive_stage="coding",
            files=[
                {
                    "filePath": "backend/run.py",
                    "content": "print('generated')\n",
                }
            ],
        )

        self.assertEqual(output_files, ["backend/run.py"])
        archived_path = self.outputs_dir / self.project.id / "tasks" / task.id / "coding" / "backend" / "run.py"
        self.assertTrue(archived_path.exists())
        self.assertEqual(archived_path.read_text(encoding="utf-8"), "print('generated')\n")

    async def test_start_generate_flow_broadcasts_detailed_progress_events(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )

        with (
            patch(
                "app.services.workflow._broadcast",
                new=AsyncMock(),
            ) as mocked_broadcast,
            patch.object(
                workflow.agent_orchestrator,
                "analyze_prompt",
                new=AsyncMock(
                    return_value={
                        "summary": "Feature analysis complete.",
                        "modules": [
                            {
                                "id": "snake-core",
                                "label": "Snake Core",
                                "labelEn": "Snake Core",
                                "description": "Gameplay loop",
                                "checked": True,
                            }
                        ],
                    }
                ),
            ),
            patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
        ):
            await workflow.start_generate_flow(self.project.id, task.id, "Build a snake game", [])

        progress_events = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3 and call.args[1] == "agent_progress"
        ]

        self.assertGreaterEqual(len(progress_events), 4)
        self.assertEqual(
            [event["phase"] for event in progress_events],
            [
                "queued",
                "reading_context",
                "requirements_analysis",
                "modules_ready",
                "waiting_for_module_confirmation",
            ],
        )
        self.assertEqual(progress_events[-1]["status"], "waiting")
        self.assertEqual(progress_events[-1]["moduleCount"], 1)
        self.assertEqual(progress_events[2]["agentName"], "requirements_agent")

    async def test_continue_after_confirmation_stops_for_requirements_artifact_review_before_architecture(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="waiting_user",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.update_task(task.id, output_data={})
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")
        self.store.replace_modules(
            self.project.id,
            [
                {
                    "id": "snake-core",
                    "label": "Snake Core",
                    "labelEn": "Snake Core",
                    "description": "Gameplay loop",
                    "checked": True,
                }
            ],
        )

        with (
            patch(
                "app.services.workflow._broadcast",
                new=AsyncMock(),
            ) as mocked_broadcast,
            patch.object(
                workflow.agent_orchestrator,
                "build_requirements_drafts",
                new=AsyncMock(
                    return_value={
                        "prd": "# PRD\n",
                        "ui": "# UI\n",
                        "api_spec": "openapi: 3.0.0\ninfo:\n  title: Snake API\npaths: {}\n",
                        "_meta": {
                            "source": "requirements_agent",
                            "outputDir": "",
                            "seededFiles": ["feature_tree.md"],
                            "sourceFilesByArtifact": {
                                "prd": ["feature_tree.md", "business_scope.md"],
                                "ui": ["feature_tree.md", "use_case.md"],
                                "api_spec": ["feature_tree.md", "use_case.md"],
                            },
                        },
                    }
                ),
            ) as mock_build_requirements,
            patch.object(
                workflow.agent_orchestrator,
                "build_architecture_draft",
                new=AsyncMock(),
            ) as mock_build_architecture,
            patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
            patch.object(workflow.agent_orchestrator, "missing_runtime_variables", return_value=[]),
        ):
            await workflow.continue_after_confirmation(self.project.id, task.id, ["snake-core"])

        project_after_requirements_review = self.store.get_project(self.project.id)
        self.assertIsNotNone(project_after_requirements_review)
        self.assertEqual(project_after_requirements_review.currentVersion, 1)
        self.assertEqual(self.store.list_versions(self.project.id), [])

        mock_build_requirements.assert_awaited_once()
        mock_build_architecture.assert_not_awaited()
        progress_events = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3 and call.args[1] == "agent_progress"
        ]

        phases = [event["phase"] for event in progress_events]
        self.assertIn("requirements_drafts_started", phases)
        self.assertNotIn("architecture_generation_started", phases)
        self.assertNotIn("code_generation_started", phases)
        self.assertIn("waiting_for_requirements_artifact_review", phases)
        self.assertEqual(
            [
                event.get("artifactType")
                for event in progress_events
                if event["phase"] == "artifact_generated"
            ],
            ["prd", "ui", "api_spec"],
        )

        live_task = self.store.get_task(task.id)
        self.assertIsNotNone(live_task)
        assert live_task is not None
        self.assertEqual(live_task.status, "waiting_user")
        self.assertEqual(live_task.outputData["confirmationKind"], "artifact_review")
        self.assertEqual(live_task.outputData["activeAgent"], "requirements_agent")
        self.assertEqual(live_task.outputData["activePhase"], "waiting_for_requirements_artifact_review")
        self.assertEqual(self.store.list_artifacts(self.project.id), [])

        messages, _ = self.store.list_messages(self.project.id, 1, 100)
        waiting_log = next(
            message
            for message in reversed(messages)
            if message.type == "process_log"
            and (message.metadata or {}).get("taskId") == task.id
            and (message.metadata or {}).get("phase") == "waiting_for_requirements_artifact_review"
        )
        self.assertEqual(waiting_log.metadata["taskName"], "Waiting for requirements draft review")
        self.assertEqual(
            waiting_log.content,
            "The requirements drafts are ready. Confirm them to start the Architecture Agent.",
        )

    async def test_artifact_review_confirmation_starts_code_generation(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="waiting_user",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")
        self.store.update_task(
            task.id,
            output_data={
                "confirmationKind": "artifact_review",
                "title": "Generated Drafts",
                "message": "Review the drafts before code generation.",
                "options": [],
            },
        )
        self.store.replace_modules(
            self.project.id,
            [
                {
                    "id": "snake-core",
                    "label": "Snake Core",
                    "labelEn": "Snake Core",
                    "description": "Gameplay loop",
                    "checked": True,
                }
            ],
        )
        self.store.bump_project_version(self.project.id)
        self.store.upsert_artifact(self.project.id, "prd", "PRD Draft", "# PRD\n")
        self.store.upsert_artifact(self.project.id, "ui", "UI Draft", "# UI\n")
        self.store.upsert_artifact(self.project.id, "architecture", "Architecture Draft", "# Architecture\n")
        self.store.upsert_artifact(self.project.id, "api_spec", "API Design", "openapi: 3.0.0\npaths: {}\n")

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()) as mocked_broadcast,
            patch.object(workflow.agent_orchestrator, "missing_runtime_variables", return_value=[]),
            patch.object(
                workflow.agent_orchestrator,
                "build_code_files",
                new=AsyncMock(return_value=[{"filePath": "README.md", "content": "# Snake"}]),
            ) as mock_build_code,
        ):
            await workflow.continue_after_confirmation(self.project.id, task.id, ["prd", "ui", "architecture", "api_spec"])

        mock_build_code.assert_awaited_once()
        progress_events = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3 and call.args[1] == "agent_progress"
        ]
        phases = [event["phase"] for event in progress_events]
        self.assertIn("code_generation_started", phases)
        self.assertIn("code_generation_completed", phases)

    async def test_artifact_review_confirmation_accumulates_ui_code_and_test_usage_into_statistics(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="waiting_user",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")
        self.store.update_task(
            task.id,
            output_data={
                "confirmationKind": "artifact_review",
                "title": "Generated Drafts",
                "message": "Review the drafts before code generation.",
                "options": [],
            },
        )
        self.store.replace_modules(
            self.project.id,
            [
                {
                    "id": "snake-core",
                    "label": "Snake Core",
                    "labelEn": "Snake Core",
                    "description": "Gameplay loop",
                    "checked": True,
                }
            ],
        )
        self.store.upsert_artifact(self.project.id, "prd", "PRD Draft", "# PRD\n")
        self.store.upsert_artifact(self.project.id, "ui", "UI Draft", "# UI\n")
        self.store.upsert_artifact(self.project.id, "architecture", "Architecture Draft", "# Architecture\n")
        self.store.upsert_artifact(self.project.id, "api_spec", "API Design", "openapi: 3.0.0\npaths: {}\n")
        self.store.register_agent_artifacts(
            self.project.id,
            version=self.store.get_project(self.project.id).currentVersion,  # type: ignore[union-attr]
            task_id=task.id,
            agent_name="requirements_agent",
            artifacts=[
                {
                    "fileName": "use_case.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Use Case\n\n- Play game",
                    "isPrimarySource": False,
                    "mappedArtifactTypes": ["ui", "api_spec"],
                },
                {
                    "fileName": "dialog_map.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Dialog Map\n\n- Main screen",
                    "isPrimarySource": False,
                    "mappedArtifactTypes": ["ui"],
                },
            ],
        )

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()),
            patch.object(workflow.agent_orchestrator, "missing_runtime_variables", return_value=[]),
            patch.object(
                workflow.agent_orchestrator,
                "build_ui_files",
                new=AsyncMock(return_value=[{"filePath": "app/index.html", "content": "<!doctype html>\n"}]),
            ),
            patch.object(
                workflow.agent_orchestrator,
                "build_code_files",
                new=AsyncMock(return_value=[{"filePath": "backend/run.py", "content": "print('snake')\n"}]),
            ),
            patch.object(
                workflow.agent_orchestrator,
                "build_test_files",
                new=AsyncMock(
                    return_value=[
                        {"filePath": "build-a-snake-game_test_plan.md", "content": "# Test Plan\n"},
                        {"filePath": "memory/test_plan.json", "content": '{"modules": []}\n'},
                        {"filePath": "build-a-snake-game_testcase.md", "content": "# Test Cases\n"},
                    ]
                ),
            ),
            patch.object(
                workflow.agent_orchestrator,
                "consume_last_usage_metadata",
                side_effect=[
                    {
                        "inputTokens": 10,
                        "outputTokens": 5,
                        "totalTokens": 15,
                        "costAmount": 0.01,
                        "model": "openai/moonshot/kimi-k2.5",
                    },
                    {
                        "inputTokens": 20,
                        "outputTokens": 10,
                        "totalTokens": 30,
                        "costAmount": 0.02,
                        "model": "openai/moonshot/kimi-k2.5",
                    },
                    {
                        "inputTokens": 30,
                        "outputTokens": 15,
                        "totalTokens": 45,
                        "costAmount": 0.03,
                        "model": "openai/moonshot/kimi-k2.5",
                    },
                ],
            ),
        ):
            await workflow.continue_after_confirmation(self.project.id, task.id, ["prd", "ui", "architecture", "api_spec"])

        stats = self.store.get_statistics(task.id)
        self.assertIsNotNone(stats)
        assert stats is not None
        self.assertEqual(stats.inputTokens, 60)
        self.assertEqual(stats.outputTokens, 30)
        self.assertEqual(stats.totalTokens, 90)
        self.assertEqual(stats.costAmount, 0.06)
        self.assertEqual(stats.modelUsed, "openai/moonshot/kimi-k2.5")

        payload = workflow._statistics_payload(task.id)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload.usageStatus, "reported")
        self.assertEqual(payload.reportedSteps, 3)
        self.assertEqual(payload.unreportedSteps, 0)

    async def test_start_generate_flow_records_measured_duration_and_known_tokens_only(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )

        async def delayed_analysis(*_args, **_kwargs):
            await asyncio.sleep(0.05)
            return {
                "summary": "Feature analysis complete.",
                "modules": [
                    {
                        "id": "snake-core",
                        "label": "Snake Core",
                        "labelEn": "Snake Core",
                        "description": "Gameplay loop",
                        "checked": True,
                    }
                ],
            }

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()),
            patch.object(
                workflow.agent_orchestrator,
                "analyze_prompt",
                new=AsyncMock(side_effect=delayed_analysis),
            ),
            patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
        ):
            await workflow.start_generate_flow(self.project.id, task.id, "Build a snake game", [])

        stats = self.store.get_statistics(task.id)
        self.assertIsNotNone(stats)
        assert stats is not None
        self.assertGreater(stats.totalDuration, 0)
        self.assertLess(stats.totalDuration, 1.0)

        steps = self.store.list_step_records(task.id)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].tokensUsed, 0)
        self.assertEqual((steps[0].metadata or {}).get("outputFiles"), [])

    async def test_start_generate_flow_emits_heartbeat_progress_during_long_analysis(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )

        async def delayed_analysis(*_args, **_kwargs):
            await asyncio.sleep(0.12)
            return {
                "summary": "Feature analysis complete.",
                "modules": [
                    {
                        "id": "snake-core",
                        "label": "Snake Core",
                        "labelEn": "Snake Core",
                        "description": "Gameplay loop",
                        "checked": True,
                    }
                ],
            }

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()) as mocked_broadcast,
            patch.object(workflow, "_PROGRESS_HEARTBEAT_INTERVAL_SECONDS", 0.02),
            patch.object(
                workflow.agent_orchestrator,
                "analyze_prompt",
                new=AsyncMock(side_effect=delayed_analysis),
            ),
            patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
        ):
            await workflow.start_generate_flow(self.project.id, task.id, "Build a snake game", [])

        analysis_events = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3
            and call.args[1] == "agent_progress"
            and call.args[2].get("phase") == "requirements_analysis"
        ]

        self.assertGreaterEqual(len(analysis_events), 2)
        self.assertGreater(analysis_events[-1]["progress"], analysis_events[0]["progress"])

    async def test_generate_code_workspace_records_reported_usage_to_step_and_project_statistics(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()),
            patch.object(
                workflow.agent_orchestrator,
                "build_code_files",
                new=AsyncMock(return_value=[{"filePath": "backend/run.py", "content": "print('snake')\n"}]),
            ),
            patch.object(
                workflow.agent_orchestrator,
                "consume_last_usage_metadata",
                return_value={
                    "inputTokens": 120,
                    "outputTokens": 45,
                    "totalTokens": 165,
                    "costAmount": 0.23,
                    "model": "openai/moonshot/kimi-k2.5",
                },
            ),
        ):
            await workflow._generate_code_workspace(
                self.project.id,
                task.id,
                prompt="Build a snake game",
                selected_modules_payload=[{"id": "snake-core", "labelEn": "Snake Core"}],
                locale="zh",
                running_message="正在生成代码工作区。",
                completed_message="已生成代码工作区。",
            )

        steps = self.store.list_step_records(task.id)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].stepName, "Generate code workspace")
        self.assertEqual(steps[0].tokensUsed, 165)
        self.assertEqual((steps[0].metadata or {}).get("usageStatus"), "reported")
        self.assertEqual((steps[0].metadata or {}).get("model"), "openai/moonshot/kimi-k2.5")

        stats = self.store.get_statistics(task.id)
        self.assertIsNotNone(stats)
        assert stats is not None
        self.assertEqual(stats.inputTokens, 120)
        self.assertEqual(stats.outputTokens, 45)
        self.assertEqual(stats.totalTokens, 165)
        self.assertEqual(stats.costAmount, 0.23)
        self.assertEqual(stats.modelUsed, "openai/moonshot/kimi-k2.5")

    async def test_start_generate_flow_streams_requirements_agent_status_updates_into_process_log_updates(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )

        async def streamed_analysis(*_args, status_callback=None, **_kwargs):
            if status_callback is not None:
                await status_callback("Requirements Agent: Drafting feature tree")
            return {
                "summary": "Feature analysis complete.",
                "modules": [
                    {
                        "id": "snake-core",
                        "label": "Snake Core",
                        "labelEn": "Snake Core",
                        "description": "Gameplay loop",
                        "checked": True,
                    }
                ],
            }

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()) as mocked_broadcast,
            patch.object(
                workflow.agent_orchestrator,
                "analyze_prompt",
                new=AsyncMock(side_effect=streamed_analysis),
            ),
            patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
        ):
            await workflow.start_generate_flow(self.project.id, task.id, "Build a snake game", [])

        message_updates = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3 and call.args[1] == "message_update"
        ]
        self.assertTrue(any(event["content"] == "Generating feature_tree.md." for event in message_updates))
        self.assertTrue(
            any(
                event.get("metadata", {}).get("outputFiles") == ["feature_tree.md"]
                for event in message_updates
            )
        )
        analysis_progress_updates = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3 and call.args[1] == "agent_progress" and call.args[2].get("phase") == "requirements_analysis"
        ]
        self.assertTrue(any(event.get("outputHint") == "feature_tree.md" for event in analysis_progress_updates))
        self.assertTrue(any(event.get("rawFileName") == "feature_tree.md" for event in analysis_progress_updates))

    async def test_process_log_status_callback_deduplicates_repeated_file_starts_and_marks_success(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")

        with patch("app.services.workflow._broadcast", new=AsyncMock()) as mocked_broadcast:
            log_message = await workflow._append_process_log(
                self.project.id,
                task.id,
                phase="artifact_generation_started",
                task_name="Generating core artifacts",
                content="Starting generation.",
            )
            callback = workflow._process_log_status_callback(
                [log_message],
                project_id=self.project.id,
                task_id=task.id,
                phase="artifact_generation_started",
                locale="en",
            )
            await callback("Requirements Agent: Drafting business scope")
            await callback("Requirements Agent: Drafting business scope")
            await callback("Requirements Agent: Success")

        message_updates = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3 and call.args[1] == "message_update"
        ]
        self.assertEqual(
            [event["content"] for event in message_updates],
            ["Generating business_scope.md.", "Generated business_scope.md."],
        )
        self.assertTrue(all(event.get("metadata", {}).get("outputFiles") == ["business_scope.md"] for event in message_updates))

    async def test_process_log_status_callback_keeps_emitting_srs_chapter_progress_for_same_temp_file(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")

        with patch("app.services.workflow._broadcast", new=AsyncMock()) as mocked_broadcast:
            log_message = await workflow._append_process_log(
                self.project.id,
                task.id,
                phase="requirements_drafts_started",
                task_name="Generating requirements drafts",
                content="Generating the requirements draft files needed for PRD, UI, and API review.",
            )
            callback = workflow._process_log_status_callback(
                [log_message],
                project_id=self.project.id,
                task_id=task.id,
                phase="requirements_drafts_started",
                locale="en",
            )
            await callback("Requirements Agent: SRS Chapter 1")
            await callback("Requirements Agent: SRS Chapter 2")

        message_updates = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3 and call.args[1] == "message_update"
        ]
        self.assertEqual(len(message_updates), 2)
        self.assertNotEqual(message_updates[0]["content"], message_updates[1]["content"])
        self.assertTrue(all("software_requirements_specification_chapter.md" in event["content"] for event in message_updates))

    async def test_process_log_status_callback_does_not_let_architecture_phase_claim_requirements_files(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")

        with patch("app.services.workflow._broadcast", new=AsyncMock()) as mocked_broadcast:
            log_message = await workflow._append_process_log(
                self.project.id,
                task.id,
                phase="architecture_generation_started",
                task_name="Generating architecture draft",
                content="Generating the architecture draft file for review.",
            )
            callback = workflow._process_log_status_callback(
                [log_message],
                project_id=self.project.id,
                task_id=task.id,
                phase="architecture_generation_started",
                locale="en",
            )
            await callback("Architecture Agent: Generating non_functional_requirements.md.")
            await callback("Architecture Agent: Generating analysis_task_output.txt.")

        message_updates = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3 and call.args[1] == "message_update"
        ]
        self.assertEqual(len(message_updates), 1)
        self.assertEqual(message_updates[0]["content"], "Generating analysis_task_output.txt.")

    async def test_process_log_status_callback_normalizes_code_agent_temp_output_paths(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")

        with patch("app.services.workflow._broadcast", new=AsyncMock()):
            log_message = await workflow._append_process_log(
                self.project.id,
                task.id,
                phase="code_generation_started",
                task_name="Generating code workspace",
                content="Generating the backend code workspace from the approved drafts.",
            )
            callback = workflow._process_log_status_callback(
                [log_message],
                project_id=self.project.id,
                task_id=task.id,
                phase="code_generation_started",
                locale="en",
            )
            await callback(
                "Coding Agent: Generating /var/folders/60/demo/T/coding-agent-runtime-1288hblc/generated/backend/app/models/module_1.py"
            )
            await callback(
                "Coding Agent: Generating hblc/generated/backend/app/repositories/module_1_repository.py"
            )

        messages, _ = self.store.list_messages(self.project.id, 1, 100)
        refreshed = next((message for message in messages if message.id == log_message.id), None)
        self.assertIsNotNone(refreshed)
        assert refreshed is not None
        metadata = refreshed.metadata or {}
        self.assertEqual(
            metadata.get("outputFiles"),
            [
                "backend/app/models/module_1.py",
                "backend/app/repositories/module_1_repository.py",
            ],
        )
        self.assertEqual(metadata.get("rawFileName"), "backend/app/repositories/module_1_repository.py")

    async def test_update_latest_task_phase_process_log_replaces_stale_file_message_for_waiting_feedback(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )

        log_message = await workflow._append_process_log(
            self.project.id,
            task.id,
            phase="requirements_drafts_started",
            task_name="Generating requirements drafts",
            content="Generating business_requirements_chapter.md.",
        )
        self.store.update_message(
            log_message.id,
            metadata={
                **(log_message.metadata or {}),
                "rawFileName": "business_requirements_chapter.md",
                "outputFiles": ["business_requirements_chapter.md"],
            },
        )

        with patch("app.services.workflow._broadcast", new=AsyncMock()):
            refreshed = await workflow._update_latest_task_phase_process_log(
                self.project.id,
                task.id,
                phase="requirements_drafts_started",
                content="Waiting for your feedback before continuing the requirements drafts.",
                clear_raw_file_name=True,
            )

        self.assertIsNotNone(refreshed)
        assert refreshed is not None
        self.assertEqual(refreshed.content, "Waiting for your feedback before continuing the requirements drafts.")
        self.assertNotIn("rawFileName", refreshed.metadata or {})
        self.assertEqual((refreshed.metadata or {}).get("outputFiles"), ["business_requirements_chapter.md"])

    async def test_update_latest_task_phase_process_log_reads_messages_via_store_io(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )

        await workflow._append_process_log(
            self.project.id,
            task.id,
            phase="requirements_drafts_started",
            task_name="Generating requirements drafts",
            content="Generating business_requirements_chapter.md.",
        )

        real_store_io = workflow._store_io

        async def tracked_store_io(callable_obj, /, *args: Any, **kwargs: Any) -> Any:
            tracked_store_io.calls.append(getattr(callable_obj, "__name__", str(callable_obj)))
            return await real_store_io(callable_obj, *args, **kwargs)

        tracked_store_io.calls = []

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()),
            patch("app.services.workflow._store_io", new=tracked_store_io),
        ):
            refreshed = await workflow._update_latest_task_phase_process_log(
                self.project.id,
                task.id,
                phase="requirements_drafts_started",
                content="Waiting for your feedback before continuing the requirements drafts.",
                clear_raw_file_name=True,
            )

        self.assertIsNotNone(refreshed)
        self.assertIn("list_messages", tracked_store_io.calls)

    async def test_start_modify_flow_reads_initial_store_state_via_store_io(self) -> None:
        self.store.replace_modules(
            self.project.id,
            [
                {
                    "id": "customer-management",
                    "label": "Customer Management",
                    "labelEn": "Customer Management",
                    "checked": True,
                }
            ],
        )
        modify_task = self.store.create_task(
            self.project.id,
            "modify",
            status="running",
            input_data={"prompt": "Refine the dashboard copy", "uploadedFiles": []},
        )

        real_store_io = workflow._store_io

        async def tracked_store_io(callable_obj, /, *args: Any, **kwargs: Any) -> Any:
            tracked_store_io.calls.append(getattr(callable_obj, "__name__", str(callable_obj)))
            return await real_store_io(callable_obj, *args, **kwargs)

        tracked_store_io.calls = []

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()),
            patch("app.services.workflow._store_io", new=tracked_store_io),
            patch("app.services.workflow.agent_orchestrator.missing_runtime_variables", return_value=[]),
            patch(
                "app.services.workflow.agent_orchestrator.build_artifacts",
                new=AsyncMock(side_effect=RuntimeError("stop after initial context load")),
            ),
        ):
            await workflow.start_modify_flow(self.project.id, modify_task.id, "Refine the dashboard copy")

        self.assertIn("get_modules", tracked_store_io.calls)
        self.assertIn("list_project_uploads", tracked_store_io.calls)
        self.assertIn("list_artifacts", tracked_store_io.calls)
        self.assertIn("get_task", tracked_store_io.calls)

    async def test_submit_requirements_feedback_replaces_stale_file_message_with_resumed_status(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="waiting_user",
            input_data={"prompt": "Build a snake game", "uploadedFiles": [], "locale": "en"},
        )
        self.store.update_task(
            task.id,
            output_data={
                "confirmationKind": "requirements_feedback",
                "returnPhase": "requirements_drafts_started",
                "returnAgent": "requirements_agent",
            },
        )
        log_message = await workflow._append_process_log(
            self.project.id,
            task.id,
            phase="requirements_drafts_started",
            task_name="Generating requirements drafts",
            content="Generating business_requirements_chapter.md.",
        )
        self.store.update_message(
            log_message.id,
            metadata={
                **(log_message.metadata or {}),
                "rawFileName": "business_requirements_chapter.md",
                "outputFiles": ["business_requirements_chapter.md"],
            },
        )

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()),
            patch.object(workflow.agent_orchestrator, "submit_requirements_feedback", return_value=True),
        ):
            await workflow.submit_requirements_feedback(self.project.id, task.id, "no")

        messages, _ = self.store.list_messages(self.project.id, 1, 50)
        latest_log = next(
            message
            for message in reversed(messages)
            if message.type == "process_log" and (message.metadata or {}).get("taskId") == task.id
        )
        self.assertEqual(latest_log.content, "Received your feedback and resumed generating the requirements drafts.")
        self.assertNotIn("rawFileName", latest_log.metadata or {})
        updated_task = self.store.get_task(task.id)
        self.assertIsNotNone(updated_task)
        assert updated_task is not None
        self.assertEqual(updated_task.status, "running")

    async def test_start_generate_flow_persists_running_then_completed_process_logs_for_the_same_task_round(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()),
            patch.object(
                workflow.agent_orchestrator,
                "analyze_prompt",
                new=AsyncMock(
                    return_value={
                        "summary": "Feature analysis complete.",
                        "modules": [
                            {
                                "id": "snake-core",
                                "label": "Snake Core",
                                "labelEn": "Snake Core",
                                "description": "Gameplay loop",
                                "checked": True,
                            }
                        ],
                    }
                ),
            ),
            patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
        ):
            await workflow.start_generate_flow(self.project.id, task.id, "Build a snake game", [])

        messages, _ = self.store.list_messages(self.project.id, 1, 50)
        anchor = next(message for message in messages if message.role == "user" and message.type == "text")
        process_logs = [message for message in messages if message.type == "process_log"]
        reading_context_log = next(message for message in process_logs if message.metadata["phase"] == "reading_context")
        analysis_log = next(message for message in process_logs if message.metadata["phase"] == "requirements_analysis")

        self.assertEqual(anchor.metadata["taskId"], task.id)
        self.assertEqual(anchor.metadata["taskRoundRole"], "anchor")
        self.assertEqual(reading_context_log.metadata["taskId"], task.id)
        self.assertEqual(reading_context_log.metadata["status"], "completed")
        self.assertEqual(analysis_log.metadata["taskId"], task.id)
        self.assertEqual(analysis_log.metadata["status"], "completed")
        self.assertEqual(analysis_log.metadata["phase"], "requirements_analysis")

    async def test_start_generate_flow_passes_locale_and_localizes_waiting_messages(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": [], "locale": "zh"},
        )

        mocked_analyze = AsyncMock(
            return_value={
                "summary": "需求分析已完成，请确认建议的功能模块。",
                "modules": [
                    {
                        "id": "snake-core",
                        "label": "Snake Core",
                        "labelEn": "Snake Core",
                        "description": "Gameplay loop",
                        "checked": True,
                    }
                ],
            }
        )

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()),
            patch.object(workflow.agent_orchestrator, "analyze_prompt", new=mocked_analyze),
            patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
        ):
            await workflow.start_generate_flow(self.project.id, task.id, "Build a snake game", [])

        self.assertEqual(mocked_analyze.await_args.kwargs["locale"], "zh")
        messages, _ = self.store.list_messages(self.project.id, 1, 200)
        # 教学注释：
        # 生成流程现在会先发送“模块确认”，随后再发送“需求产物确认”。
        # 这里必须按 activePhase 精确拿到第一张模块确认卡，
        # 否则会误把后面的产物确认卡当成当前断言对象。
        confirmation_message = next(
            message
            for message in messages
            if message.type == "select_options"
            and isinstance(message.metadata, dict)
            and message.metadata.get("activePhase") == "waiting_for_module_confirmation"
        )
        process_logs = [message for message in messages if message.type == "process_log"]
        self.assertEqual(confirmation_message.metadata["title"], "功能模块")
        self.assertEqual(
            confirmation_message.content,
            "请先查看 feature_tree.md，确认当前这版功能树是否可以继续用于后续生成。",
        )
        self.assertTrue(any("已读取提示词与可用参考上下文" in message.content for message in process_logs))

    async def test_start_generate_flow_includes_feature_tree_preview_in_confirmation_metadata(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": [], "locale": "zh"},
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "feature_tree.md").write_text(
                "# Feature Tree\n\n- 核心玩法\n  - 推箱子移动\n",
                encoding="utf-8",
            )

            mocked_analyze = AsyncMock(
                return_value={
                    "summary": "需求分析已完成，请确认建议的功能模块。",
                    "modules": [
                        {
                            "id": "snake-core",
                            "label": "Snake Core",
                            "labelEn": "Snake Core",
                            "description": "Gameplay loop",
                            "checked": True,
                        }
                    ],
                    "_meta": {
                        "source": "requirements_agent",
                        "outputDir": str(output_root),
                    },
                }
            )

            with (
                patch("app.services.workflow._broadcast", new=AsyncMock()),
                patch.object(workflow.agent_orchestrator, "analyze_prompt", new=mocked_analyze),
                patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
            ):
                await workflow.start_generate_flow(self.project.id, task.id, "Build a snake game", [])

        registered = self.store.list_agent_artifacts(self.project.id, version=1, agent_name="requirements_agent")
        feature_tree = next(artifact for artifact in registered if artifact.fileName == "feature_tree.md")
        self.assertIn("核心玩法", feature_tree.content)

    async def test_requirements_analysis_status_updates_ignore_non_contract_fallback_files(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a sokoban game", "uploadedFiles": []},
        )
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")

        with patch("app.services.workflow._broadcast", new=AsyncMock()) as mocked_broadcast:
            log_message = await workflow._append_process_log(
                self.project.id,
                task.id,
                phase="requirements_analysis",
                task_name="Analyzing requirements",
                content="Analyzing requirements.",
            )
            callback = workflow._process_log_status_callback(
                [log_message],
                project_id=self.project.id,
                task_id=task.id,
                phase="requirements_analysis",
                locale="en",
            )
            await callback("Requirements Agent: Generating user_introduction.md")
            await callback("Requirements Agent: Generating feature_tree.md")

        message_updates = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3 and call.args[1] == "message_update"
        ]
        self.assertFalse(any(event["content"] == "Generating user_introduction.md." for event in message_updates))
        self.assertTrue(any(event["content"] == "Generating feature_tree.md." for event in message_updates))

    async def test_continue_after_confirmation_streams_coding_agent_status_updates_into_process_log_updates(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="waiting_user",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.update_task(task.id, output_data={})
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")
        self.store.replace_modules(
            self.project.id,
            [
                {
                    "id": "snake-core",
                    "label": "Snake Core",
                    "labelEn": "Snake Core",
                    "description": "Gameplay loop",
                    "checked": True,
                }
            ],
        )

        async def streamed_code_files(*_args, status_callback=None, **_kwargs):
            if status_callback is not None:
                await status_callback("Coding Agent: Generating backend/run.py")
            return [{"filePath": "backend/run.py", "content": "print('snake')\n"}]

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()) as mocked_broadcast,
            patch.object(
                workflow.agent_orchestrator,
                "build_requirements_drafts",
                new=AsyncMock(
                    return_value={
                        "prd": "# PRD\n",
                        "ui": "# UI\n",
                        "api_spec": "openapi: 3.0.0\ninfo:\n  title: Snake API\npaths: {}\n",
                        "_meta": {
                            "source": "requirements_agent",
                            "outputDir": "",
                            "sourceFilesByArtifact": {},
                        },
                    }
                ),
            ),
            patch.object(
                workflow.agent_orchestrator,
                "build_architecture_draft",
                new=AsyncMock(
                    return_value={
                        "architecture": "# Architecture\n",
                        "_meta": {
                            "source": "architecture_agent",
                            "outputDir": "",
                            "sourceFilesByArtifact": {},
                        },
                    }
                ),
            ),
            patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
            patch.object(workflow.agent_orchestrator, "missing_runtime_variables", return_value=[]),
            patch.object(
                workflow.agent_orchestrator,
                "build_code_files",
                new=AsyncMock(side_effect=streamed_code_files),
            ),
        ):
            await workflow.continue_after_confirmation(self.project.id, task.id, ["snake-core"])
            await workflow.continue_after_confirmation(
                self.project.id,
                task.id,
                ["prd", "ui", "api_spec"],
            )
            await workflow.continue_after_confirmation(
                self.project.id,
                task.id,
                ["prd", "ui", "architecture", "api_spec"],
            )

        message_updates = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3 and call.args[1] == "message_update"
        ]
        self.assertTrue(any(event["content"] == "Generating backend/run.py." for event in message_updates))
        code_progress_updates = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3 and call.args[1] == "agent_progress" and call.args[2].get("phase") == "code_generation_started"
        ]
        self.assertTrue(any(event.get("outputHint") == "backend/run.py" for event in code_progress_updates))
        self.assertTrue(any(event.get("rawFileName") == "backend/run.py" for event in code_progress_updates))

    async def test_continue_after_confirmation_passes_locale_to_generation_agents(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="waiting_user",
            input_data={"prompt": "Build a snake game", "uploadedFiles": [], "locale": "zh"},
        )
        self.store.update_task(task.id, output_data={})
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")
        self.store.replace_modules(
            self.project.id,
            [
                {
                    "id": "snake-core",
                    "label": "Snake Core",
                    "labelEn": "Snake Core",
                    "description": "Gameplay loop",
                    "checked": True,
                }
            ],
        )

        mocked_build_requirements_drafts = AsyncMock(
            return_value={
                "prd": "# PRD\n",
                "ui": "# UI\n",
                "api_spec": "openapi: 3.0.0\ninfo:\n  title: Snake API\npaths: {}\n",
                "_meta": {
                    "source": "requirements_agent",
                    "outputDir": "",
                    "sourceFilesByArtifact": {},
                },
            }
        )
        mocked_build_architecture_draft = AsyncMock(
            return_value={
                "architecture": "# Architecture\n",
                "_meta": {
                    "source": "architecture_agent",
                    "outputDir": "",
                    "sourceFilesByArtifact": {},
                },
            }
        )
        mocked_build_code_files = AsyncMock(return_value=[{"filePath": "backend/run.py", "content": "print('snake')\n"}])

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()),
            patch.object(workflow.agent_orchestrator, "build_requirements_drafts", new=mocked_build_requirements_drafts),
            patch.object(workflow.agent_orchestrator, "build_architecture_draft", new=mocked_build_architecture_draft),
            patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
            patch.object(workflow.agent_orchestrator, "missing_runtime_variables", return_value=[]),
            patch.object(workflow.agent_orchestrator, "build_code_files", new=mocked_build_code_files),
        ):
            await workflow.continue_after_confirmation(self.project.id, task.id, ["snake-core"])
            await workflow.continue_after_confirmation(
                self.project.id,
                task.id,
                ["prd", "ui", "api_spec"],
            )
            await workflow.continue_after_confirmation(
                self.project.id,
                task.id,
                ["prd", "ui", "architecture", "api_spec"],
            )

        self.assertEqual(mocked_build_requirements_drafts.await_args.kwargs["locale"], "zh")
        self.assertEqual(mocked_build_architecture_draft.await_args.kwargs["locale"], "zh")
        self.assertEqual(mocked_build_code_files.await_args.kwargs["locale"], "zh")

    async def test_continue_after_confirmation_records_pending_agent_output_version_before_version_bump(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="waiting_user",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.update_task(task.id, output_data={})
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")
        self.store.replace_modules(
            self.project.id,
            [
                {
                    "id": "snake-core",
                    "label": "Snake Core",
                    "labelEn": "Snake Core",
                    "description": "Gameplay loop",
                    "checked": True,
                }
            ],
        )

        async def build_requirements_drafts_side_effect(**kwargs):
            artifact_file_callback = kwargs["artifact_file_callback"]
            with tempfile.TemporaryDirectory() as temp_dir:
                output_root = Path(temp_dir)
                (output_root / "feature_tree.md").write_text("# Feature Tree\n\n- Snake Core\n", encoding="utf-8")
                await artifact_file_callback(
                    {
                        "agentName": "requirements_agent",
                        "outputDir": str(output_root),
                        "fileName": "feature_tree.md",
                    }
                )
                live_task = self.store.get_task(task.id)
                self.assertIsNotNone(live_task)
                self.assertEqual(live_task.outputData["pendingAgentArtifactsVersion"], 2)
                self.assertEqual(
                    [artifact.fileName for artifact in self.store.list_agent_artifacts(self.project.id, version=2)],
                    ["feature_tree.md"],
                )
                return {
                    "prd": "# PRD\n",
                    "ui": "# UI\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: Snake API\npaths: {}\n",
                    "_meta": {
                        "source": "requirements_agent",
                        "outputDir": str(output_root),
                        "sourceFilesByArtifact": {
                            "prd": ["feature_tree.md"],
                            "ui": ["feature_tree.md"],
                            "api_spec": ["feature_tree.md"],
                        },
                    },
                }

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()) as mocked_broadcast,
            patch.object(
                workflow.agent_orchestrator,
                "build_requirements_drafts",
                new=AsyncMock(side_effect=build_requirements_drafts_side_effect),
            ),
            patch.object(
                workflow.agent_orchestrator,
                "build_architecture_draft",
                new=AsyncMock(
                    return_value={
                        "architecture": "# Architecture\n",
                        "_meta": {
                            "source": "architecture_agent",
                            "outputDir": "",
                            "sourceFilesByArtifact": {},
                        },
                    }
                ),
            ),
            patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
            patch.object(workflow.agent_orchestrator, "missing_runtime_variables", return_value=[]),
        ):
            await workflow.continue_after_confirmation(self.project.id, task.id, ["snake-core"])

    async def test_continue_after_confirmation_registers_architecture_outputs_while_generation_is_still_running(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="waiting_user",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.update_task(task.id, output_data={})
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")
        self.store.replace_modules(
            self.project.id,
            [
                {
                    "id": "snake-core",
                    "label": "Snake Core",
                    "labelEn": "Snake Core",
                    "description": "Gameplay loop",
                    "checked": True,
                }
            ],
        )

        async def build_requirements_drafts_side_effect(**kwargs):
            artifact_file_callback = kwargs["artifact_file_callback"]
            with tempfile.TemporaryDirectory() as temp_dir:
                output_root = Path(temp_dir)
                (output_root / "feature_tree.md").write_text("# Feature Tree\n\n- Snake Core\n", encoding="utf-8")
                await artifact_file_callback(
                    {
                        "agentName": "requirements_agent",
                        "outputDir": str(output_root),
                        "fileName": "feature_tree.md",
                    }
                )
                return {
                    "prd": "# PRD\n",
                    "ui": "# UI\n",
                    "api_spec": "openapi: 3.0.0\ninfo:\n  title: Snake API\npaths: {}\n",
                    "_meta": {
                        "source": "requirements_agent",
                        "outputDir": str(output_root),
                        "sourceFilesByArtifact": {
                            "prd": ["feature_tree.md"],
                            "ui": ["feature_tree.md"],
                            "api_spec": ["feature_tree.md"],
                        },
                    },
                }

        async def build_architecture_draft_side_effect(**kwargs):
            runtime_event_callback = kwargs["runtime_event_callback"]
            with tempfile.TemporaryDirectory() as temp_dir:
                output_root = Path(temp_dir)
                (output_root / "analysis_task_output.txt").write_text("architecture analysis", encoding="utf-8")
                (output_root / "component_design.json").write_text("{\"components\":[]}", encoding="utf-8")
                await runtime_event_callback(
                    {
                        "runtimeState": "running",
                        "outputDir": str(output_root),
                        "latestOutputFile": "component_design.json",
                        "secondsSinceLastOutput": 0,
                        "elapsedSeconds": 12,
                    }
                )
                live_task = self.store.get_task(task.id)
                self.assertIsNotNone(live_task)
                self.assertEqual(live_task.outputData["pendingAgentArtifactsVersion"], 2)
                self.assertEqual(
                    [
                        (artifact.agent, artifact.fileName)
                        for artifact in self.store.list_agent_artifacts(self.project.id, version=2)
                    ],
                    [
                        ("architecture_agent", "analysis_task_output.txt"),
                        ("architecture_agent", "component_design.json"),
                        ("requirements_agent", "feature_tree.md"),
                    ],
                )
                return {
                    "architecture": "# Architecture\n",
                    "_meta": {
                        "source": "architecture_agent",
                        "outputDir": str(output_root),
                        "sourceFilesByArtifact": {
                            "architecture": ["component_design.json", "analysis_task_output.txt"],
                        },
                    },
                }

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()) as mocked_broadcast,
            patch.object(
                workflow.agent_orchestrator,
                "build_requirements_drafts",
                new=AsyncMock(side_effect=build_requirements_drafts_side_effect),
            ),
            patch.object(
                workflow.agent_orchestrator,
                "build_architecture_draft",
                new=AsyncMock(side_effect=build_architecture_draft_side_effect),
            ),
            patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
            patch.object(workflow.agent_orchestrator, "missing_runtime_variables", return_value=[]),
        ):
            await workflow.continue_after_confirmation(self.project.id, task.id, ["snake-core"])
            await workflow.continue_after_confirmation(
                self.project.id,
                task.id,
                ["prd", "ui", "api_spec"],
            )

        architecture_artifact_events = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3
            and call.args[1] == "artifact_update"
            and call.args[2].get("agentName") == "architecture_agent"
        ]
        self.assertTrue(architecture_artifact_events)
        self.assertEqual(architecture_artifact_events[0]["action"], "raw_output_registered")
        self.assertEqual(
            architecture_artifact_events[0]["outputFiles"],
            ["analysis_task_output.txt", "component_design.json"],
        )
        project_after_architecture_preview = self.store.get_project(self.project.id)
        self.assertIsNotNone(project_after_architecture_preview)
        self.assertEqual(project_after_architecture_preview.currentVersion, 1)
        self.assertEqual(self.store.list_versions(self.project.id), [])
        project_after_architecture_preview = self.store.get_project(self.project.id)
        self.assertIsNotNone(project_after_architecture_preview)
        self.assertEqual(project_after_architecture_preview.currentVersion, 1)
        self.assertEqual(self.store.list_versions(self.project.id), [])

    async def test_continue_after_confirmation_recovers_when_requirements_agent_outputs_are_complete_but_call_hangs(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="waiting_user",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.update_task(task.id, output_data={})
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")
        self.store.replace_modules(
            self.project.id,
            [
                {
                    "id": "snake-core",
                    "label": "Snake Core",
                    "labelEn": "Snake Core",
                    "description": "Gameplay loop",
                    "checked": True,
                }
            ],
        )

        async def hanging_build_requirements_drafts(**kwargs):
            artifact_file_callback = kwargs["artifact_file_callback"]
            with tempfile.TemporaryDirectory() as temp_dir:
                output_root = Path(temp_dir)
                # 接口注释：这里准备的是 requirements full 阶段真正的最小可交付集合。
                # 只要 `SRS.md`、`feature_tree.md` 和 `use_case.md` 都到位，
                # 平台就应该能够从落盘文件里恢复出 review 所需的 PRD / UI / API 草稿内容。
                (output_root / "SRS.md").write_text("# SRS\n\n## Scope\nSnake game scope\n", encoding="utf-8")
                (output_root / "feature_tree.md").write_text("# Feature Tree\n\n- Snake Core\n", encoding="utf-8")
                (output_root / "use_case.md").write_text("[]", encoding="utf-8")
                await artifact_file_callback(
                    {
                        "agentName": "requirements_agent",
                        "outputDir": str(output_root),
                        "fileName": "SRS.md",
                    }
                )
                await asyncio.Event().wait()

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()) as mocked_broadcast,
            patch.object(
                workflow.agent_orchestrator,
                "build_requirements_drafts",
                new=AsyncMock(side_effect=hanging_build_requirements_drafts),
            ),
            patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
            patch.object(workflow.agent_orchestrator, "missing_runtime_variables", return_value=[]),
            patch("app.services.workflow._LIVE_OUTPUT_RECOVERY_POLL_SECONDS", 0.01),
            patch("app.services.workflow._LIVE_OUTPUT_RECOVERY_GRACE_SECONDS", 0.02),
        ):
            await asyncio.wait_for(
                workflow.continue_after_confirmation(self.project.id, task.id, ["snake-core"]),
                timeout=1,
            )

        live_task = self.store.get_task(task.id)
        self.assertIsNotNone(live_task)
        assert live_task is not None
        self.assertEqual(live_task.status, "waiting_user")
        self.assertEqual(live_task.outputData["confirmationKind"], "artifact_review")
        self.assertEqual(live_task.outputData["activePhase"], "waiting_for_requirements_artifact_review")

        messages, _ = self.store.list_messages(self.project.id, 1, 100)
        self.assertTrue(any(message.type == "select_options" for message in messages))
        progress_events = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3 and call.args[1] == "agent_progress"
        ]
        self.assertIn("waiting_for_requirements_artifact_review", [event["phase"] for event in progress_events])

    async def test_requirements_live_recovery_cancels_operation_before_waiting_for_registry_cleanup(self) -> None:
        task_id = "task-requirements-live-recovery-stop-order"
        cancel_event = threading.Event()
        completion_event = threading.Event()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            (output_root / "SRS.md").write_text("# SRS\n", encoding="utf-8")
            (output_root / "feature_tree.md").write_text("# Feature Tree\n\n- Snake Core\n", encoding="utf-8")
            (output_root / "use_case.md").write_text("[]", encoding="utf-8")

            self.store.register_agent_artifacts(
                self.project.id,
                version=2,
                task_id=task_id,
                agent_name="requirements_agent",
                artifacts=[
                    {"fileName": "SRS.md", "content": "# SRS\n", "mappedArtifactTypes": ["prd"]},
                    {"fileName": "feature_tree.md", "content": "# Feature Tree\n\n- Snake Core\n", "mappedArtifactTypes": ["prd", "ui", "api_spec"]},
                    {"fileName": "use_case.md", "content": "[]", "mappedArtifactTypes": ["prd"]},
                ],
            )

            async def hanging_operation() -> dict[str, Any]:
                workflow.register_running_task(
                    task_id,
                    cancel_event=cancel_event,
                    completion_event=completion_event,
                    agent_name="requirements_agent",
                    runtime_state="running",
                    output_root=str(output_root),
                )
                try:
                    await asyncio.Event().wait()
                    return {}
                finally:
                    workflow.mark_running_task_completion(task_id, runtime_state="cancelled")
                    workflow.unregister_running_task(task_id)

            with (
                patch("app.services.workflow._LIVE_OUTPUT_RECOVERY_POLL_SECONDS", 0.01),
                patch("app.services.workflow._LIVE_OUTPUT_RECOVERY_GRACE_SECONDS", 0.02),
            ):
                recovered_payload, _, recovered = await asyncio.wait_for(
                    workflow._await_requirements_drafts_or_recover_from_live_outputs(
                        self.project.id,
                        task_id,
                        pending_version=2,
                        prompt="Build a snake game",
                        selected_modules=[{"label": "Snake Core", "labelEn": "Snake Core"}],
                        operation=hanging_operation(),
                    ),
                    timeout=1,
                )

        self.assertTrue(recovered)
        self.assertEqual(recovered_payload["_meta"]["status"], "recovered_live_output")
        self.assertEqual(
            workflow.wait_for_running_task_stop(task_id, timeout_seconds=0.01)["stop_reason"],
            "not_registered",
        )

    async def test_continue_after_confirmation_recovers_from_database_outputs_without_local_archive(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="waiting_user",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.update_task(task.id, output_data={})
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")
        self.store.replace_modules(
            self.project.id,
            [
                {
                    "id": "snake-core",
                    "label": "Snake Core",
                    "labelEn": "Snake Core",
                    "description": "Gameplay loop",
                    "checked": True,
                }
            ],
        )

        async def hanging_build_requirements_drafts(**kwargs):
            artifact_file_callback = kwargs["artifact_file_callback"]
            with tempfile.TemporaryDirectory() as temp_dir:
                output_root = Path(temp_dir)
                (output_root / "SRS.md").write_text("# SRS\n\n## Scope\nSnake game scope\n", encoding="utf-8")
                (output_root / "feature_tree.md").write_text("# Feature Tree\n\n- Snake Core\n", encoding="utf-8")
                (output_root / "use_case.md").write_text("[]", encoding="utf-8")
                await artifact_file_callback(
                    {
                        "agentName": "requirements_agent",
                        "outputDir": str(output_root),
                        "fileName": "SRS.md",
                    }
                )
                await asyncio.Event().wait()

        with (
            patch.dict(os.environ, {"ISOFTDEVAGENTS_DELETE_LOCAL_FILES_AFTER_PERSIST": "1"}, clear=False),
            patch("app.services.workflow._broadcast", new=AsyncMock()),
            patch.object(
                workflow.agent_orchestrator,
                "build_requirements_drafts",
                new=AsyncMock(side_effect=hanging_build_requirements_drafts),
            ),
            patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
            patch.object(workflow.agent_orchestrator, "missing_runtime_variables", return_value=[]),
            patch("app.services.workflow._LIVE_OUTPUT_RECOVERY_POLL_SECONDS", 0.01),
            patch("app.services.workflow._LIVE_OUTPUT_RECOVERY_GRACE_SECONDS", 0.02),
        ):
            await asyncio.wait_for(
                workflow.continue_after_confirmation(self.project.id, task.id, ["snake-core"]),
                timeout=1,
            )

        live_task = self.store.get_task(task.id)
        self.assertIsNotNone(live_task)
        assert live_task is not None
        self.assertEqual(live_task.status, "waiting_user")
        self.assertEqual(live_task.outputData["activePhase"], "waiting_for_requirements_artifact_review")
        self.assertFalse(workflow._project_task_output_dir(self.project.id, task.id, "requirements-drafts").exists())

    async def test_await_architecture_draft_or_recover_from_live_outputs_recovers_from_registered_artifacts(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.update_task(task.id, output_data={"pendingAgentArtifactsVersion": 2})

        async def hanging_operation():
            await asyncio.sleep(0.01)
            self.store.register_agent_artifacts(
                self.project.id,
                version=2,
                task_id=task.id,
                agent_name="architecture_agent",
                artifacts=[
                    {
                        "fileName": "analysis_task_output.txt",
                        "content": "Architecture analysis",
                        "mappedArtifactTypes": ["architecture"],
                    },
                    {
                        "fileName": "component_design.json",
                        "content": "{\"component_diagram\":\"graph TD\\nA-->B\",\"components\":[]}",
                        "mappedArtifactTypes": ["architecture"],
                    },
                    {
                        "fileName": "class_design_raw.md",
                        "content": "## Component: Snake Core",
                        "mappedArtifactTypes": ["architecture"],
                    },
                    {
                        "fileName": "class_design_structured.json",
                        "content": "{\"classes\":[]}",
                        "mappedArtifactTypes": ["architecture"],
                    },
                ],
            )
            await asyncio.Event().wait()

        with (
            patch("app.services.workflow._LIVE_OUTPUT_RECOVERY_POLL_SECONDS", 0.01),
            patch("app.services.workflow._LIVE_OUTPUT_RECOVERY_GRACE_SECONDS", 0.02),
        ):
            recovered_payload, recovered_output_files, recovered = await asyncio.wait_for(
                workflow._await_architecture_draft_or_recover_from_live_outputs(
                    self.project.id,
                    task.id,
                    pending_version=2,
                    operation=hanging_operation(),
                ),
                timeout=1,
            )

        self.assertTrue(recovered)
        self.assertEqual(recovered_payload["_meta"]["status"], "recovered_live_output")
        self.assertEqual(recovered_payload["_meta"]["source"], "architecture_agent")
        self.assertEqual(recovered_payload["_meta"]["outputDir"], "db://agent_artifacts/architecture_agent")
        self.assertIn("## Module Design", recovered_payload["architecture"])
        self.assertEqual(
            recovered_output_files,
            [
                "analysis_task_output.txt",
                "class_design_raw.md",
                "class_design_structured.json",
                "component_design.json",
            ],
        )

    async def test_await_architecture_draft_or_recover_from_live_outputs_does_not_recover_without_class_design(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="running",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.update_task(task.id, output_data={"pendingAgentArtifactsVersion": 2})

        async def incomplete_operation():
            await asyncio.sleep(0.01)
            self.store.register_agent_artifacts(
                self.project.id,
                version=2,
                task_id=task.id,
                agent_name="architecture_agent",
                artifacts=[
                    {
                        "fileName": "analysis_task_output.txt",
                        "content": "Architecture analysis",
                        "mappedArtifactTypes": ["architecture"],
                    },
                    {
                        "fileName": "component_design.json",
                        "content": "{\"component_diagram\":\"graph TD\\nA-->B\",\"components\":[]}",
                        "mappedArtifactTypes": ["architecture"],
                    },
                ],
            )
            await asyncio.Event().wait()

        with (
            patch("app.services.workflow._LIVE_OUTPUT_RECOVERY_POLL_SECONDS", 0.01),
            patch("app.services.workflow._LIVE_OUTPUT_RECOVERY_GRACE_SECONDS", 0.02),
        ):
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    workflow._await_architecture_draft_or_recover_from_live_outputs(
                        self.project.id,
                        task.id,
                        pending_version=2,
                        operation=incomplete_operation(),
                    ),
                    timeout=0.2,
                )

    def test_latest_visible_output_file_prefers_user_visible_architecture_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            invisible_path = output_root / "modeling-6.module_design_output.txt"
            visible_old_path = output_root / "analysis_task_output.txt"
            visible_new_path = output_root / "class_design_raw.md"
            visible_old_path.write_text("analysis", encoding="utf-8")
            visible_new_path.write_text("class design", encoding="utf-8")
            invisible_path.write_text("module design", encoding="utf-8")

            os.utime(visible_old_path, (1_710_000_000, 1_710_000_000))
            os.utime(visible_new_path, (1_710_000_010, 1_710_000_010))
            os.utime(invisible_path, (1_710_000_020, 1_710_000_020))

            self.assertEqual(
                workflow._latest_visible_output_file_in_dir(
                    phase="architecture_generation_started",
                    output_dir=output_root,
                ),
                "class_design_raw.md",
            )

    async def test_requirements_drafts_runtime_event_keeps_file_progress_message(self) -> None:
        task = self.store.create_task(
            self.project.id,
            "generate",
            status="waiting_user",
            input_data={"prompt": "Build a snake game", "uploadedFiles": []},
        )
        self.store.update_task(task.id, output_data={})
        self.store.create_statistics(self.project.id, task.id, model_used="moonshot/kimi-k2.5")
        self.store.replace_modules(
            self.project.id,
            [
                {
                    "id": "snake-core",
                    "label": "Snake Core",
                    "labelEn": "Snake Core",
                    "description": "Gameplay loop",
                    "checked": True,
                }
            ],
        )

        async def build_requirements_drafts_side_effect(**kwargs):
            runtime_event_callback = kwargs["runtime_event_callback"]
            await runtime_event_callback(
                {
                    "runtimeState": "running",
                    "latestOutputFile": "data_flow_diagram.md",
                    "secondsSinceLastOutput": 95,
                    "elapsedSeconds": 140,
                }
            )
            return {
                "prd": "# PRD\n",
                "ui": "# UI\n",
                "api_spec": "openapi: 3.0.0\ninfo:\n  title: Snake API\npaths: {}\n",
                "_meta": {
                    "source": "requirements_agent",
                    "outputDir": "",
                    "sourceFilesByArtifact": {},
                },
            }

        with (
            patch("app.services.workflow._broadcast", new=AsyncMock()) as mocked_broadcast,
            patch.object(
                workflow.agent_orchestrator,
                "build_requirements_drafts",
                new=AsyncMock(side_effect=build_requirements_drafts_side_effect),
            ),
            patch.object(
                workflow.agent_orchestrator,
                "build_architecture_draft",
                new=AsyncMock(
                    return_value={
                        "architecture": "# Architecture\n",
                        "_meta": {
                            "source": "architecture_agent",
                            "outputDir": "",
                            "sourceFilesByArtifact": {},
                        },
                    }
                ),
            ),
            patch.object(workflow.agent_orchestrator, "consume_last_usage_metadata", return_value=None),
            patch.object(workflow.agent_orchestrator, "missing_runtime_variables", return_value=[]),
        ):
            await workflow.continue_after_confirmation(self.project.id, task.id, ["snake-core"])

        message_updates = [
            call.args[2]
            for call in mocked_broadcast.await_args_list
            if len(call.args) >= 3 and call.args[1] == "message_update"
        ]
        file_progress_updates = [
            event
            for event in message_updates
            if event.get("content") == "Generating data_flow_diagram.md."
        ]
        self.assertTrue(file_progress_updates)
        self.assertEqual(file_progress_updates[-1]["metadata"]["secondsSinceLastOutput"], 95)
        self.assertEqual(file_progress_updates[-1]["metadata"]["runtimeState"], "running")
