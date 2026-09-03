import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch
import os

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app
from app.services.store import SQLiteStore


class UploadReferenceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(db_path=str(Path(self.temp_dir.name) / "test.db"))

    def tearDown(self) -> None:
        self.store._connection.close()
        self.temp_dir.cleanup()

    def test_assign_uploads_to_project_links_temporary_uploads_in_order(self) -> None:
        project = self.store.create_project("Upload Project", "Testing upload ownership")
        first = self.store.create_upload("brief.md", "markdown", 128, "Project brief")
        second = self.store.create_upload("spec.pdf", "pdf", 512, "Specification")

        assigned = self.store.assign_uploads_to_project([second.id, first.id], project.id)

        self.assertEqual([upload.id for upload in assigned], [second.id, first.id])
        self.assertTrue(all(upload.projectId == project.id for upload in assigned))
        self.assertTrue(all(upload.isTemporary is False for upload in assigned))

    def test_assign_uploads_to_project_ignores_uploads_owned_by_another_project(self) -> None:
        primary_project = self.store.create_project("Primary", "Primary project")
        foreign_project = self.store.create_project("Foreign", "Foreign project")
        owned_elsewhere = self.store.create_upload(
            "locked.md",
            "markdown",
            64,
            "Locked content",
            project_id=foreign_project.id,
        )

        assigned = self.store.assign_uploads_to_project([owned_elsewhere.id], primary_project.id)

        self.assertEqual(assigned, [])
        persisted = self.store.get_uploads([owned_elsewhere.id])[0]
        self.assertEqual(persisted.projectId, foreign_project.id)
        self.assertTrue(persisted.isTemporary is False)

    def test_create_upload_can_persist_original_file_content_for_later_analysis(self) -> None:
        # 教学注释：
        # 这次需求是“首轮分析前重新读取原图做摘要”，所以这里只验证一件事：
        # 上传记录建立后，后端还能把原始文件字节完整读回来。
        upload = self.store.create_upload("screen.png", "image", 18, "IMAGE reference: screen.png (18 bytes)")
        original_content = b"\x89PNG\r\n\x1a\nplatform-image"

        self.store.write_upload_content(upload.id, original_content)

        self.assertEqual(self.store.read_upload_content(upload.id), original_content)

    def test_write_upload_content_keeps_blob_but_removes_disk_cache_when_zero_residual_enabled(self) -> None:
        upload = self.store.create_upload("screen.png", "image", 18, "IMAGE reference: screen.png (18 bytes)")
        original_content = b"\x89PNG\r\n\x1a\nplatform-image"

        with patch.dict(os.environ, {"ISOFTDEVAGENTS_DELETE_LOCAL_FILES_AFTER_PERSIST": "1"}, clear=False):
            disk_path = self.store.write_upload_content(upload.id, original_content)

        self.assertFalse(disk_path.exists())
        self.assertEqual(self.store.read_upload_content_blob(upload.id), original_content)
        self.assertEqual(self.store.read_upload_content(upload.id), original_content)

    def test_read_upload_content_backfills_blob_from_legacy_disk_cache_and_cleans_it_when_enabled(self) -> None:
        upload = self.store.create_upload("legacy.pdf", "pdf", 12, "legacy upload")
        legacy_content = b"legacy-bytes"
        disk_path = self.store._upload_disk_path(upload.filePath)
        disk_path.parent.mkdir(parents=True, exist_ok=True)
        disk_path.write_bytes(legacy_content)

        with patch.dict(os.environ, {"ISOFTDEVAGENTS_DELETE_LOCAL_FILES_AFTER_PERSIST": "1"}, clear=False):
            restored = self.store.read_upload_content(upload.id)

        self.assertEqual(restored, legacy_content)
        self.assertEqual(self.store.read_upload_content_blob(upload.id), legacy_content)
        self.assertFalse(disk_path.exists())


class UploadReferenceApiTests(unittest.TestCase):
    def _default_analysis_payload(self) -> dict:
        return {
            "summary": "Requirements Agent completed the feature analysis.",
            "modules": [
                {
                    "id": "user-system",
                    "label": "User System",
                    "labelEn": "User System",
                    "description": "User registration, sign-in, and access control.",
                    "checked": True,
                },
                {
                    "id": "admin-console",
                    "label": "Admin Console",
                    "labelEn": "Admin Console",
                    "description": "Centralized project, data, and configuration management.",
                    "checked": True,
                },
                {
                    "id": "customer-management",
                    "label": "Customer Management",
                    "labelEn": "Customer Management",
                    "description": "Customer profiles, leads, account records, and lifecycle tracking.",
                    "checked": True,
                },
                {
                    "id": "workflow-automation",
                    "label": "Workflow Automation",
                    "labelEn": "Workflow Automation",
                    "description": "Task routing, approvals, state transitions, and process automation.",
                    "checked": True,
                },
            ],
            "_meta": {
                "source": "requirements_agent",
                "status": "completed",
            },
        }

    async def _default_build_requirements_drafts(self, prompt: str, selected_modules: list[dict], **_kwargs) -> dict:
        module_labels = [str(module.get("labelEn") or module.get("label") or module.get("id") or "Core Module") for module in selected_modules]
        module_lines = "\n".join(f"- {label}" for label in module_labels) or "- Core Module"
        path_lines = []
        for module in selected_modules or [{"id": "core-module", "labelEn": "Core Module"}]:
            module_id = str(module.get("id") or module.get("labelEn") or "core-module").strip() or "core-module"
            path_lines.extend(
                [
                    f"  /api/{module_id}:",
                    "    get:",
                    f"      summary: List {module_id} records",
                    "      responses:",
                    "        '200':",
                    "          description: Successful response",
                ]
            )
        return {
            "prd": f"# Product Requirements Document\n\n## Overview\n{prompt}\n\n## Functional Scope\n{module_lines}\n",
            "ui": f"# UI Pages\n\n## Page Inventory\n{module_lines}\n",
            "api_spec": "openapi: 3.0.0\ninfo:\n  title: Generated API\n  version: 0.1.0\npaths:\n" + "\n".join(path_lines) + "\n",
            "_meta": {
                "source": "requirements_agent",
                "status": "completed",
                "seededFiles": [
                    "feature_tree.md",
                    "use_case.md",
                    "dialog_map.md",
                ],
                "sourceFilesByArtifact": {
                    "prd": [
                        "business_scope.md",
                        "feature_tree.md",
                        "functional_requirements.md",
                        "non_functional_requirements.md",
                        "use_case.md",
                    ],
                    "ui": ["feature_tree.md", "use_case.md", "dialog_map.md"],
                    "api_spec": ["feature_tree.md", "use_case.md"],
                },
            },
        }

    async def _default_build_architecture_draft(self, prompt: str, selected_modules: list[dict], **_kwargs) -> dict:
        module_labels = [str(module.get("labelEn") or module.get("label") or module.get("id") or "Core Module") for module in selected_modules]
        module_lines = "\n".join(f"- {label}" for label in module_labels) or "- Core Module"
        return {
            "architecture": f"# Architecture\n\n## Overview\nGenerated by Architecture Agent.\n\n## Modules\n{module_lines}\n",
            "_meta": {
                "source": "architecture_agent",
                "status": "completed",
                "sourceFilesByArtifact": {
                    "architecture": [
                        "component_design.json",
                        "class_design_raw.md",
                    ]
                },
            },
        }

    async def _default_build_ui_files(self, selected_modules: list[dict], **_kwargs) -> list[dict]:
        module_labels = [str(module.get("labelEn") or module.get("label") or module.get("id") or "Core Module") for module in selected_modules]
        module_lines = "\n".join(f"- {label}" for label in module_labels) or "- Core Module"
        return [
            {"filePath": "page_descriptions.json", "content": "{\"pages\": [\"/\"]}\n"},
            {"filePath": "page_descriptions.md", "content": f"# Page Descriptions\n\n{module_lines}\n"},
            {"filePath": "dar_model.json", "content": "{\"views\": []}\n"},
            {"filePath": "dar_model.md", "content": "# DAR Model\n\nGenerated UI model.\n"},
            {"filePath": "app/index.html", "content": "<!doctype html><html><body><main>Generated UI</main></body></html>\n"},
            {"filePath": "app/css/style.css", "content": "body { font-family: sans-serif; }\n"},
            {"filePath": "app/js/index.js", "content": "console.log('ui');\n"},
            {"filePath": "app/js/api.js", "content": "export async function request() { return {}; }\n"},
        ]

    async def _default_build_code_files(self, selected_modules: list[dict], artifacts: dict, **_kwargs) -> list[dict]:
        files = [
            {"filePath": "docs/PRD.md", "content": str(artifacts.get("prd") or "")},
            {"filePath": "docs/Architecture.md", "content": str(artifacts.get("architecture") or "")},
            {"filePath": "docs/API.yaml", "content": str(artifacts.get("api_spec") or "")},
            {"filePath": "ui/index.html", "content": "<!doctype html><html><body><main>Generated UI</main></body></html>\n"},
            {"filePath": "backend/run.py", "content": "from app import create_app\n\napp = create_app()\n"},
        ]
        for module in selected_modules:
            module_id = str(module.get("id") or module.get("labelEn") or module.get("label") or "core-module").strip() or "core-module"
            files.append(
                {
                    "filePath": f"src/{module_id}/index.ts",
                    "content": f"export const moduleId = \"{module_id}\";\n",
                }
            )
        return files

    async def _default_build_test_files(self, **_kwargs) -> list[dict]:
        return [
            {"filePath": "project_test_plan.md", "content": "# Test Plan\n\n- Smoke\n"},
            {"filePath": "memory/test_plan.json", "content": "{\"cases\": [\"smoke\"]}\n"},
            {"filePath": "project_testcase.md", "content": "# Test Cases\n\n- Smoke case\n"},
        ]

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(db_path=str(Path(self.temp_dir.name) / "test.db"))

        patchers = [
            patch("app.main.store", self.store),
            patch("app.services.workflow.store", self.store),
            patch(
                "app.services.workflow.agent_orchestrator.analyze_prompt",
                new=AsyncMock(side_effect=lambda *args, **kwargs: self._default_analysis_payload()),
            ),
            patch(
                "app.services.workflow.agent_orchestrator.build_requirements_drafts",
                new=AsyncMock(side_effect=self._default_build_requirements_drafts),
            ),
            patch(
                "app.services.workflow.agent_orchestrator.build_architecture_draft",
                new=AsyncMock(side_effect=self._default_build_architecture_draft),
            ),
            patch(
                "app.services.workflow.agent_orchestrator.build_ui_files",
                new=AsyncMock(side_effect=self._default_build_ui_files),
            ),
            patch(
                "app.services.workflow.agent_orchestrator.build_code_files",
                new=AsyncMock(side_effect=self._default_build_code_files),
            ),
            patch(
                "app.services.workflow.agent_orchestrator.build_test_files",
                new=AsyncMock(side_effect=self._default_build_test_files),
            ),
            patch("app.services.workflow.agent_orchestrator.missing_runtime_variables", return_value=[]),
            patch("app.services.workflow.agent_orchestrator.consume_last_usage_metadata", return_value=None),
        ]
        self._patchers = patchers
        for patcher in patchers:
            patcher.start()

        self.client = TestClient(app)

    def _confirm_current_task(self, project_id: str) -> dict:
        current_task_response = self.client.get(f"/api/projects/{project_id}/task/current")
        self.assertEqual(current_task_response.status_code, 200)
        payload = current_task_response.json()
        task = payload["task"]
        self.assertIsNotNone(task)
        confirmation_data = payload.get("confirmationData") or {}
        options = confirmation_data.get("options") or []
        selected_ids = [option["id"] for option in options if option.get("checked", True)]
        confirm_response = self.client.post(
            f"/api/projects/{project_id}/confirm",
            json={"taskId": task["id"], "action": "confirm", "data": {"selectedIds": selected_ids}},
        )
        self.assertEqual(confirm_response.status_code, 200)
        return confirm_response.json()

    def _complete_generate_task(
        self,
        project_id: str,
        *,
        selected_ids: list[str] | None = None,
    ) -> None:
        # 教学注释：
        # 生成链路现在会经过“模块确认 -> 需求草稿确认 -> 完整草稿确认”三段等待态。
        # 这里统一循环确认，避免测试把阶段顺序写死。
        first_confirmation = True
        for _ in range(4):
            current_task_response = self.client.get(f"/api/projects/{project_id}/task/current")
            self.assertEqual(current_task_response.status_code, 200)
            payload = current_task_response.json()
            if payload["status"] != "waiting_user":
                return
            task = payload["task"]
            self.assertIsNotNone(task)
            confirmation_data = payload.get("confirmationData") or {}
            options = confirmation_data.get("options") or []
            chosen_ids = (
                selected_ids
                if first_confirmation and selected_ids is not None
                else [option["id"] for option in options if option.get("checked", True)]
            )
            first_confirmation = False
            confirm_response = self.client.post(
                f"/api/projects/{project_id}/confirm",
                json={"taskId": task["id"], "action": "confirm", "data": {"selectedIds": chosen_ids}},
            )
            self.assertEqual(confirm_response.status_code, 200)
        self.fail("Generate flow did not leave waiting state after the expected confirmations.")

    def _confirm_overwrite(self, project_id: str) -> dict:
        current_task_response = self.client.get(f"/api/projects/{project_id}/task/current")
        self.assertEqual(current_task_response.status_code, 200)
        payload = current_task_response.json()
        self.assertEqual(payload["status"], "waiting_user")
        confirmation_data = payload.get("confirmationData") or {}
        self.assertEqual(confirmation_data.get("confirmationKind"), "coverage_conflict")
        task = payload["task"]
        self.assertIsNotNone(task)
        confirm_response = self.client.post(
            f"/api/projects/{project_id}/confirm",
            json={"taskId": task["id"], "action": "confirm", "data": {"selectedIds": ["confirm_overwrite"]}},
        )
        self.assertEqual(confirm_response.status_code, 200)
        return confirm_response.json()

    def tearDown(self) -> None:
        self.client.close()
        for patcher in reversed(self._patchers):
            patcher.stop()
        self.store._connection.close()
        self.temp_dir.cleanup()

    def test_upload_api_persists_original_image_bytes(self) -> None:
        image_bytes = b"\x89PNG\r\n\x1a\nfake-image-binary"

        response = self.client.post(
            "/api/upload",
            data={"type": "image"},
            files={"file": ("screen.png", image_bytes, "image/png")},
        )

        self.assertEqual(response.status_code, 200)
        upload_id = response.json()["id"]
        self.assertEqual(self.store.read_upload_content(upload_id), image_bytes)

    def test_modify_during_module_confirmation_restarts_feature_tree_analysis_instead_of_continuing_generation(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Module Confirmation Project", "description": "Testing module confirmation regenerate flow"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build a gomoku game", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)

        current_task_response = self.client.get(f"/api/projects/{project_id}/task/current")
        self.assertEqual(current_task_response.status_code, 200)
        waiting_payload = current_task_response.json()
        self.assertEqual(waiting_payload["status"], "waiting_user")
        self.assertEqual(
            waiting_payload.get("task", {}).get("outputData", {}).get("activePhase"),
            "waiting_for_module_confirmation",
        )
        waiting_task_id = waiting_payload["task"]["id"]

        with (
            patch("app.main.start_generate_flow", new=AsyncMock()) as mocked_restart_flow,
            patch("app.main.continue_after_confirmation", new=AsyncMock()) as mocked_continue_after_confirmation,
        ):
            modify_response = self.client.post(
                f"/api/projects/{project_id}/modify",
                json={
                    "taskId": waiting_task_id,
                    "content": "去掉数据与配置，补充 AI 对战模块，并重新整理功能树。",
                    "locale": "zh",
                },
            )

        self.assertEqual(modify_response.status_code, 200)
        mocked_continue_after_confirmation.assert_not_awaited()
        mocked_restart_flow.assert_awaited_once()
        restart_call = mocked_restart_flow.await_args
        self.assertEqual(restart_call.args[0], project_id)
        self.assertNotEqual(restart_call.args[1], waiting_task_id)
        self.assertEqual(restart_call.args[3], [])
        self.assertIn("Build a gomoku game", restart_call.args[2])
        self.assertIn("AI 对战模块", restart_call.args[2])
        self.assertIn("功能树", restart_call.args[2])

        waiting_task = self.store.get_task(waiting_task_id)
        self.assertIsNotNone(waiting_task)
        assert waiting_task is not None
        self.assertEqual(waiting_task.status, "waiting_user")

        refreshed_task = self.store.get_task(restart_call.args[1])
        self.assertIsNotNone(refreshed_task)
        assert refreshed_task is not None
        self.assertEqual(refreshed_task.status, "running")
        self.assertEqual(refreshed_task.taskType, "generate")
        self.assertIn("AI 对战模块", str(refreshed_task.inputData.get("prompt") or ""))

    def test_module_confirmation_ignores_selected_ids_and_keeps_all_analyzed_modules_selected(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Ignore SelectedIds Project", "description": "Testing module confirmation without selectedIds logic"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build a workflow dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        task_id = generate_response.json()["taskId"]

        confirm_response = self.client.post(
            f"/api/projects/{project_id}/confirm",
            json={"taskId": task_id, "action": "confirm", "data": {"selectedIds": ["user-system"]}},
        )
        self.assertEqual(confirm_response.status_code, 200)

        modules_response = self.client.get(f"/api/projects/{project_id}/modules")
        self.assertEqual(modules_response.status_code, 200)
        selected_ids = [module["id"] for module in modules_response.json()["modules"] if module["isSelected"]]
        self.assertEqual(
            selected_ids,
            ["user-system", "admin-console", "customer-management", "workflow-automation"],
        )

    def test_confirm_endpoint_accepts_only_the_first_confirmation_attempt(self) -> None:
        project = self.store.create_project("Single Confirm Project", "Testing duplicate confirmation protection")
        task = self.store.create_task(
            project.id,
            "generate",
            status="waiting_user",
            input_data={"prompt": "Build a workflow dashboard", "uploadedFiles": []},
        )
        self.store.update_task(
            task.id,
            status="waiting_user",
            output_data={
                "confirmationKind": "artifact_review",
                "activePhase": "waiting_for_requirements_artifact_review",
                "selectedModuleIds": ["user-system", "admin-console"],
            },
        )

        with patch("app.main.continue_after_confirmation", new=AsyncMock()) as mocked_continue_after_confirmation:
            first_response = self.client.post(
                f"/api/projects/{project.id}/confirm",
                json={"taskId": task.id, "action": "confirm", "data": {"selectedIds": ["user-system"]}},
            )
            second_response = self.client.post(
                f"/api/projects/{project.id}/confirm",
                json={"taskId": task.id, "action": "confirm", "data": {"selectedIds": ["user-system"]}},
            )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 409)
        self.assertIn("already accepted", second_response.json()["detail"])
        mocked_continue_after_confirmation.assert_awaited_once()

        refreshed_task = self.store.get_task(task.id)
        self.assertIsNotNone(refreshed_task)
        assert refreshed_task is not None
        self.assertEqual(refreshed_task.status, "running")
        self.assertTrue(bool((refreshed_task.outputData or {}).get("confirmationAcceptedAt")))

    def test_generate_uses_image_summary_for_first_pass_requirements_analysis(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Image Summary Project", "description": "Testing image summary flow"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        upload_response = self.client.post(
            "/api/upload",
            data={"type": "image"},
            files={"file": ("screen.png", b"\x89PNG\r\n\x1a\nimage-for-analysis", "image/png")},
        )
        self.assertEqual(upload_response.status_code, 200)
        upload_id = upload_response.json()["id"]

        analysis_mock = AsyncMock(return_value=self._default_analysis_payload())
        image_summary = (
            "[Image Summary]\n"
            "主题：CRM 首页原型\n"
            "可见文字：Sales Dashboard, New Lead\n"
            "关键界面元素：顶部导航、线索卡片、待办区域\n"
            "业务流程/角色/状态：销售查看线索并推进跟进状态\n"
            "需求提示：需要首页概览、线索列表、待办提醒。\n"
        )
        with patch("app.services.workflow.build_image_reference_summary", new=AsyncMock(return_value=image_summary)), patch(
            "app.services.workflow.agent_orchestrator.analyze_prompt",
            new=analysis_mock,
        ):
            generate_response = self.client.post(
                f"/api/projects/{project_id}/generate",
                json={"prompt": "Build a CRM workspace", "uploadedFiles": [upload_id]},
            )

        self.assertEqual(generate_response.status_code, 200)
        analysis_mock.assert_awaited_once()
        _, reference_materials = analysis_mock.await_args.args[:2]
        self.assertEqual(len(reference_materials), 1)
        self.assertEqual(reference_materials[0]["fileType"], "image")
        self.assertEqual(reference_materials[0]["fileName"], "screen.png")
        self.assertEqual(reference_materials[0]["contentPreview"], image_summary)

    def test_generate_skips_failed_image_summary_and_current_references_show_hint(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Image Failure Project", "description": "Testing image summary failure flow"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        upload_response = self.client.post(
            "/api/upload",
            data={"type": "image"},
            files={"file": ("screen.png", b"\x89PNG\r\n\x1a\nimage-failure-case", "image/png")},
        )
        self.assertEqual(upload_response.status_code, 200)
        upload_id = upload_response.json()["id"]

        analysis_mock = AsyncMock(return_value=self._default_analysis_payload())
        with patch(
            "app.services.workflow.build_image_reference_summary",
            new=AsyncMock(side_effect=RuntimeError("Image summary model is not configured.")),
        ), patch(
            "app.services.workflow.agent_orchestrator.analyze_prompt",
            new=analysis_mock,
        ):
            generate_response = self.client.post(
                f"/api/projects/{project_id}/generate",
                json={"prompt": "Build a CRM workspace", "uploadedFiles": [upload_id]},
            )

        self.assertEqual(generate_response.status_code, 200)
        _, reference_materials = analysis_mock.await_args.args[:2]
        self.assertEqual(reference_materials, [])

        current_references_response = self.client.get(f"/api/projects/{project_id}/references/current")
        self.assertEqual(current_references_response.status_code, 200)
        current_references = current_references_response.json()
        self.assertEqual(len(current_references), 1)
        self.assertIn("Skipped in first-pass analysis", current_references[0]["contentPreview"])

    def test_generate_links_uploaded_files_and_project_references_endpoint_returns_them(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Generated Project", "description": "Testing"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        upload = self.store.create_upload("brief.md", "markdown", 128, "Uploaded context")

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build an internal dashboard", "uploadedFiles": [upload.id]},
        )

        self.assertEqual(generate_response.status_code, 200)
        persisted_upload = self.store.get_uploads([upload.id])[0]
        self.assertEqual(persisted_upload.projectId, project_id)
        self.assertFalse(persisted_upload.isTemporary)

        references_response = self.client.get(f"/api/projects/{project_id}/references")
        self.assertEqual(references_response.status_code, 200)
        payload = references_response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], upload.id)
        self.assertEqual(payload[0]["projectId"], project_id)

        current_task_response = self.client.get(f"/api/projects/{project_id}/task/current")
        self.assertEqual(current_task_response.status_code, 200)
        confirmation_data = current_task_response.json()["confirmationData"]
        self.assertEqual(len(confirmation_data["referenceFiles"]), 1)
        self.assertEqual(confirmation_data["referenceFiles"][0]["id"], upload.id)

    def test_completed_project_message_starts_modify_task(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Modification Project", "description": "Testing modify flow"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build an admin dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        self._complete_generate_task(project_id)

        completed_task = self.client.get(f"/api/projects/{project_id}/task/current").json()
        self.assertEqual(completed_task["status"], "completed")
        self.assertEqual(completed_task["task"]["taskType"], "generate")

        message_response = self.client.post(
            f"/api/projects/{project_id}/messages",
            json={"content": "Change login to phone number sign-in", "type": "text"},
        )
        self.assertEqual(message_response.status_code, 200)

        waiting_modify_task = self.client.get(f"/api/projects/{project_id}/task/current").json()
        self.assertEqual(waiting_modify_task["status"], "waiting_user")
        self.assertEqual(waiting_modify_task["task"]["taskType"], "modify")
        self.assertEqual(waiting_modify_task["confirmationData"]["confirmationKind"], "coverage_conflict")

        self._confirm_overwrite(project_id)

        latest_task = self.client.get(f"/api/projects/{project_id}/task/current").json()
        self.assertEqual(latest_task["status"], "completed")
        self.assertEqual(latest_task["task"]["taskType"], "modify")
        self.assertIn("existingArtifacts", latest_task["task"]["outputData"])
        self.assertTrue(latest_task["task"]["outputData"]["existingArtifacts"])

    def test_generate_flow_requests_artifact_review_after_core_drafts(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Artifact Review Project", "description": "Testing post-generation review"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build an admin dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)

        self._confirm_current_task(project_id)

        current_task = self.client.get(f"/api/projects/{project_id}/task/current").json()
        self.assertEqual(current_task["status"], "waiting_user")
        self.assertEqual(current_task["confirmationData"]["confirmationKind"], "artifact_review")
        self.assertEqual(current_task["confirmationData"]["confirmText"], "Approve Requirements Drafts & Continue")
        artifact_option_ids = [option["id"] for option in current_task["confirmationData"]["options"]]
        self.assertEqual(artifact_option_ids, ["prd", "ui", "api_spec"])
        self.assertIn("artifactSources", current_task["confirmationData"])
        self.assertEqual(current_task["confirmationData"]["artifactSources"]["prd"]["source"], "requirements_agent")
        self.assertEqual(
            current_task["confirmationData"]["contextSummary"]["selectedModuleCount"],
            len(current_task["confirmationData"]["selectedModuleIds"]),
        )
        project = self.store.get_project(project_id)
        assert project is not None
        self.assertEqual(self.store.list_code_files(project_id, version=project.currentVersion), [])

    def test_second_confirmation_starts_code_generation_after_artifact_review(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Artifact Approval Project", "description": "Testing final approval"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build an admin dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)

        with patch(
            "app.services.workflow.agent_orchestrator.build_code_files",
            new=AsyncMock(return_value=[{"filePath": "README.md", "content": "# Generated"}]),
        ) as mock_build_code, patch(
            "app.services.workflow.agent_orchestrator.missing_runtime_variables",
            return_value=[],
        ):
            self._confirm_current_task(project_id)
            mock_build_code.assert_not_awaited()
            self._confirm_current_task(project_id)
            mock_build_code.assert_not_awaited()
            self._confirm_current_task(project_id)
            mock_build_code.assert_awaited_once()

        current_task = self.client.get(f"/api/projects/{project_id}/task/current").json()
        self.assertEqual(current_task["status"], "completed")
        self.assertEqual(current_task["task"]["taskType"], "generate")
        self.assertIn("artifactSources", current_task["task"]["outputData"])

    def test_modify_flow_passes_existing_artifact_content_to_orchestrator(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Context Project", "description": "Testing modify context"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build an admin dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        self._complete_generate_task(project_id, selected_ids=["user-system", "admin-console"])

        original_prd = self.store.get_artifact(project_id, "prd")
        self.assertIsNotNone(original_prd)

        async_mock = AsyncMock(
            return_value={
                "prd": "# Updated PRD\n\nChanged login flow.",
                "ui": "# Updated UI\n\nPhone login screen.",
                "architecture": "# Updated Architecture\n\nAuth service updated.",
                "api_spec": "openapi: 3.1.0\ninfo:\n  title: Updated API\n  version: 0.1.0\n",
            }
        )

        with patch("app.services.workflow.agent_orchestrator.build_artifacts", async_mock):
            message_response = self.client.post(
                f"/api/projects/{project_id}/messages",
                json={"content": "Change login to phone number sign-in", "type": "text"},
            )
            self.assertEqual(message_response.status_code, 200)
            self._confirm_overwrite(project_id)

        call = async_mock.await_args
        self.assertIsNotNone(call)
        existing_artifacts = call.kwargs.get("existing_artifacts")
        self.assertIsInstance(existing_artifacts, list)
        self.assertTrue(existing_artifacts)
        self.assertEqual(existing_artifacts[0]["type"], "prd")
        self.assertIn("Build an admin dashboard", existing_artifacts[0]["content"])

    def test_modify_flow_exposes_artifact_sources_and_context_summary(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Modify Source Project", "description": "Testing modify source metadata"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build an admin dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        self._complete_generate_task(project_id, selected_ids=["user-system", "admin-console"])

        async_mock = AsyncMock(
            return_value={
                "prd": "# Updated PRD\n\nChanged login flow.",
                "ui": "# Updated UI\n\nPhone login screen.",
                "architecture": "# Updated Architecture\n\nAuth service updated.",
                "api_spec": "openapi: 3.1.0\ninfo:\n  title: Updated API\n  version: 0.1.0\n",
                "_meta": {
                    "requirements": {"source": "requirements_agent", "status": "completed"},
                    "architecture": {"source": "architecture_agent", "status": "completed"},
                },
            }
        )

        with patch("app.services.workflow.agent_orchestrator.build_artifacts", async_mock):
            message_response = self.client.post(
                f"/api/projects/{project_id}/messages",
                json={"content": "Change login to phone number sign-in", "type": "text"},
            )
            self.assertEqual(message_response.status_code, 200)
            self._confirm_overwrite(project_id)

        current_task = self.client.get(f"/api/projects/{project_id}/task/current").json()
        self.assertEqual(current_task["task"]["taskType"], "modify")
        output_data = current_task["task"]["outputData"]
        self.assertEqual(output_data["artifactSources"]["prd"]["source"], "requirements_agent")
        self.assertEqual(output_data["artifactSources"]["architecture"]["source"], "architecture_agent")
        self.assertEqual(output_data["contextSummary"]["existingArtifactCount"], 4)
        module_count = len(self.client.get(f"/api/projects/{project_id}/modules").json()["modules"])
        self.assertEqual(output_data["contextSummary"]["selectedModuleCount"], module_count)

    def test_modify_flow_nests_artifact_cards_under_process_log(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Nested Modify Project", "description": "Testing modify artifact nesting"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build an admin dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        self._complete_generate_task(project_id, selected_ids=["user-system", "admin-console"])

        message_response = self.client.post(
            f"/api/projects/{project_id}/messages",
            json={"content": "Change login to phone number sign-in", "type": "text"},
        )
        self.assertEqual(message_response.status_code, 200)
        self._confirm_overwrite(project_id)

        messages_response = self.client.get(f"/api/projects/{project_id}/messages?page=1&limit=200")
        self.assertEqual(messages_response.status_code, 200)
        messages = messages_response.json()["messages"]

        modify_logs = [
            message for message in messages
            if message["type"] == "process_log"
            and (message.get("metadata") or {}).get("taskName") == "Applying requested changes"
        ]
        self.assertTrue(modify_logs)
        modify_log_id = modify_logs[-1]["id"]

        modify_artifact_cards = [
            message for message in messages
            if message["type"] == "artifact_card" and message.get("parentId") == modify_log_id
        ]
        self.assertEqual(len(modify_artifact_cards), 4)

    def test_put_prd_updates_artifact_and_creates_new_version_checkpoint(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Editable Project", "description": "Testing direct artifact updates"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build a reporting dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        task_id = generate_response.json()["taskId"]

        confirm_response = self.client.post(
            f"/api/projects/{project_id}/confirm",
            json={"taskId": task_id, "action": "confirm", "data": {"selectedIds": ["user-system", "admin-console"]}},
        )
        self.assertEqual(confirm_response.status_code, 200)
        self._confirm_current_task(project_id)

        original_artifact = self.client.get(f"/api/projects/{project_id}/artifacts/prd")
        self.assertEqual(original_artifact.status_code, 200)
        original_payload = original_artifact.json()

        update_response = self.client.put(
            f"/api/projects/{project_id}/artifacts/prd",
            json={"content": "# Updated PRD\n\n## Overview\nDirectly edited content."},
        )
        self.assertEqual(update_response.status_code, 200)
        updated_payload = update_response.json()
        self.assertEqual(updated_payload["type"], "prd")
        self.assertIn("Directly edited content", updated_payload["content"])
        self.assertNotEqual(updated_payload["id"], original_payload["id"])

        project_payload = self.client.get(f"/api/projects/{project_id}").json()
        self.assertEqual(project_payload["currentVersion"], 4)

        versions_payload = self.client.get(f"/api/projects/{project_id}/versions").json()
        self.assertEqual(len(versions_payload["versions"]), 3)
        self.assertEqual(versions_payload["versions"][-1]["description"], "Updated PRD in edit mode.")
        self.assertEqual(versions_payload["versions"][-1]["versionKind"], "artifact_edit")
        self.assertEqual(versions_payload["versions"][-1]["sourceVersion"], 3)
        self.assertIsNone(versions_payload["versions"][-1]["restoredFromVersion"])
        self.assertEqual(versions_payload["versions"][-1]["createdByType"], "user")
        self.assertEqual(versions_payload["versions"][-1]["changes"][0]["status"], "Modified")
        self.assertEqual(versions_payload["versions"][-1]["changes"][0]["type"], "prd")
        self.assertIn("PRD", versions_payload["versions"][-1]["changes"][0]["description"])

    def test_get_artifact_by_version_returns_historical_prd_content(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Versioned Artifact Project", "description": "Testing versioned artifact reads"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build a metrics dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        task_id = generate_response.json()["taskId"]

        confirm_response = self.client.post(
            f"/api/projects/{project_id}/confirm",
            json={"taskId": task_id, "action": "confirm", "data": {"selectedIds": ["user-system", "admin-console"]}},
        )
        self.assertEqual(confirm_response.status_code, 200)
        self._confirm_current_task(project_id)

        original_response = self.client.get(f"/api/projects/{project_id}/artifacts/prd")
        self.assertEqual(original_response.status_code, 200)
        original_payload = original_response.json()
        self.assertEqual(original_payload["version"], 3)

        update_response = self.client.put(
            f"/api/projects/{project_id}/artifacts/prd",
            json={"content": "# Updated PRD\n\n## Overview\nHistorical snapshot check."},
        )
        self.assertEqual(update_response.status_code, 200)
        updated_payload = update_response.json()
        self.assertEqual(updated_payload["version"], 4)
        self.assertIn("Historical snapshot check", updated_payload["content"])

        latest_response = self.client.get(f"/api/projects/{project_id}/artifacts/prd")
        self.assertEqual(latest_response.status_code, 200)
        self.assertEqual(latest_response.json()["version"], 4)

        historical_response = self.client.get(f"/api/projects/{project_id}/artifacts/prd?version=3")
        self.assertEqual(historical_response.status_code, 200)
        historical_payload = historical_response.json()
        self.assertEqual(historical_payload["version"], 3)
        self.assertEqual(historical_payload["id"], original_payload["id"])
        self.assertEqual(historical_payload["content"], original_payload["content"])
        self.assertNotIn("Historical snapshot check", historical_payload["content"])

    def test_rollback_creates_new_version_from_historical_snapshot(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Rollback Project", "description": "Testing rollback flow"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build a sales dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        task_id = generate_response.json()["taskId"]

        confirm_response = self.client.post(
            f"/api/projects/{project_id}/confirm",
            json={"taskId": task_id, "action": "confirm", "data": {"selectedIds": ["user-system", "admin-console"]}},
        )
        self.assertEqual(confirm_response.status_code, 200)
        self._confirm_current_task(project_id)

        version_two_prd = self.client.get(f"/api/projects/{project_id}/artifacts/prd").json()
        self.assertEqual(version_two_prd["version"], 3)

        update_response = self.client.put(
            f"/api/projects/{project_id}/artifacts/prd",
            json={"content": "# Updated PRD\n\n## Overview\nRollback target check."},
        )
        self.assertEqual(update_response.status_code, 200)
        updated_prd = update_response.json()
        self.assertEqual(updated_prd["version"], 4)

        rollback_response = self.client.post(f"/api/projects/{project_id}/versions/3/rollback")
        self.assertEqual(rollback_response.status_code, 200)
        rollback_payload = rollback_response.json()
        self.assertEqual(rollback_payload["status"], "success")
        self.assertEqual(rollback_payload["newVersion"], 5)
        self.assertIn("Rolled back to version 3", rollback_payload["message"])

        latest_project = self.client.get(f"/api/projects/{project_id}").json()
        self.assertEqual(latest_project["currentVersion"], 5)

        latest_prd = self.client.get(f"/api/projects/{project_id}/artifacts/prd").json()
        self.assertEqual(latest_prd["version"], 5)
        self.assertEqual(latest_prd["content"], version_two_prd["content"])
        self.assertNotEqual(latest_prd["id"], version_two_prd["id"])
        self.assertNotIn("Rollback target check", latest_prd["content"])

        preserved_v3 = self.client.get(f"/api/projects/{project_id}/artifacts/prd?version=4").json()
        self.assertEqual(preserved_v3["version"], 4)
        self.assertIn("Rollback target check", preserved_v3["content"])

        versions_payload = self.client.get(f"/api/projects/{project_id}/versions").json()
        self.assertEqual(len(versions_payload["versions"]), 4)
        self.assertEqual(versions_payload["versions"][-1]["version"], 5)
        self.assertEqual(versions_payload["versions"][-1]["description"], "Rolled back to version 3.")
        self.assertEqual(versions_payload["versions"][-1]["versionKind"], "rollback")
        self.assertEqual(versions_payload["versions"][-1]["sourceVersion"], 4)
        self.assertEqual(versions_payload["versions"][-1]["restoredFromVersion"], 3)
        self.assertEqual(versions_payload["versions"][-1]["createdByType"], "user")

    def test_code_files_tree_and_versioned_file_reads_follow_project_versions(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Code Files Project", "description": "Testing code snapshot APIs"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build a CRM dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        self._complete_generate_task(project_id, selected_ids=["user-system", "admin-console"])

        tree_response = self.client.get(f"/api/projects/{project_id}/code/files")
        self.assertEqual(tree_response.status_code, 200)
        tree_payload = tree_response.json()
        self.assertEqual(tree_payload["projectId"], project_id)
        self.assertEqual(tree_payload["version"], 3)
        root_names = [node["name"] for node in tree_payload["tree"]]
        self.assertIn("docs", root_names)
        self.assertIn("src", root_names)
        self.assertIn("ui", root_names)

        prd_file_response = self.client.get(f"/api/projects/{project_id}/code/files/docs/PRD.md")
        self.assertEqual(prd_file_response.status_code, 200)
        original_prd_file = prd_file_response.json()
        self.assertEqual(original_prd_file["path"], "docs/PRD.md")
        self.assertEqual(original_prd_file["language"], "markdown")
        self.assertIn("Build a CRM dashboard", original_prd_file["content"])

        update_response = self.client.put(
            f"/api/projects/{project_id}/artifacts/prd",
            json={"content": "# Updated PRD\n\n## Overview\nVersioned file reads should follow snapshots."},
        )
        self.assertEqual(update_response.status_code, 200)

        latest_prd_file = self.client.get(f"/api/projects/{project_id}/code/files/docs/PRD.md").json()
        self.assertIn("Versioned file reads should follow snapshots", latest_prd_file["content"])

        historical_prd_file = self.client.get(f"/api/projects/{project_id}/code/files/docs/PRD.md?version=3").json()
        self.assertEqual(historical_prd_file["version"], 3)
        self.assertEqual(historical_prd_file["content"], original_prd_file["content"])
        self.assertNotIn("Versioned file reads should follow snapshots", historical_prd_file["content"])

    def test_code_tree_and_modules_return_empty_payload_before_first_snapshot_exists(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Empty Code Project", "description": "Testing empty code payloads"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        tree_response = self.client.get(f"/api/projects/{project_id}/code/files?version=1")
        self.assertEqual(tree_response.status_code, 200)
        self.assertEqual(tree_response.json()["tree"], [])
        self.assertEqual(tree_response.json()["version"], 1)

        modules_response = self.client.get(f"/api/projects/{project_id}/code/modules?version=1")
        self.assertEqual(modules_response.status_code, 200)
        self.assertEqual(modules_response.json()["modules"], [])

    def test_unified_project_files_endpoint_lists_requirements_artifacts_and_workspace_files(self) -> None:
        project = self.store.create_project("Unified Files Project", "Testing unified file tree")
        self.store.register_agent_artifacts(
            project.id,
            version=project.currentVersion,
            task_id=None,
            agent_name="requirements_agent",
            artifacts=[
                {
                    "fileName": "feature_tree.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Feature Tree\n\n- User System\n",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd", "ui", "api_spec"],
                },
                {
                    "fileName": "business_scope.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Business Scope\n\nScope text.\n",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd"],
                },
            ],
        )
        self.store.upsert_artifact(
            project.id,
            "prd",
            "PRD Draft",
            "# Product Requirements Document\n\nCurrent artifact.\n",
        )
        self.store.replace_code_files(
            project.id,
            project.currentVersion,
            [
                {"filePath": "backend/run.py", "content": "print('ok')\n"},
            ],
        )
        self.store.create_version(
            project.id,
            "Seed current snapshot",
            [{"file": "feature_tree.md", "status": "Added"}],
            version_kind="generation",
            created_by_type="agent",
            created_by="requirements_agent",
            state_manifest={
                "artifacts": ["prd"],
                "codeFiles": ["backend/run.py"],
                "agentArtifacts": {"requirements_agent": ["feature_tree.md", "business_scope.md"]},
            },
            modules_snapshot=[],
        )

        response = self.client.get(f"/api/projects/{project.id}/files")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["version"], 1)
        paths = {item["path"]: item for item in payload["files"]}
        self.assertIn("requirements/feature_tree.md", paths)
        self.assertIn("requirements/business_scope.md", paths)
        self.assertIn("artifacts/prd.md", paths)
        self.assertIn("workspace/backend/run.py", paths)
        self.assertEqual(paths["requirements/feature_tree.md"]["stage"], "requirements")
        self.assertEqual(paths["artifacts/prd.md"]["stage"], "artifacts")
        self.assertEqual(paths["workspace/backend/run.py"]["stage"], "workspace")
        self.assertTrue(paths["requirements/feature_tree.md"]["isEditable"])

    def test_saving_requirements_file_creates_new_project_version_and_preserves_previous_snapshot(self) -> None:
        project = self.store.create_project("Requirements Edit Project", "Testing requirements raw file save")
        self.store.register_agent_artifacts(
            project.id,
            version=project.currentVersion,
            task_id=None,
            agent_name="requirements_agent",
            artifacts=[
                {
                    "fileName": "feature_tree.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Feature Tree\n\n- User System\n",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd", "ui", "api_spec"],
                }
            ],
        )
        self.store.create_version(
            project.id,
            "Seed requirements snapshot",
            [{"file": "feature_tree.md", "status": "Added"}],
            version_kind="generation",
            created_by_type="agent",
            created_by="requirements_agent",
            state_manifest={
                "artifacts": [],
                "codeFiles": [],
                "agentArtifacts": {"requirements_agent": ["feature_tree.md"]},
            },
            modules_snapshot=[],
        )

        update_response = self.client.put(
            f"/api/projects/{project.id}/files/requirements/feature_tree.md",
            json={"content": "# Feature Tree\n\n- User System\n- Billing Center\n", "version": 1},
        )

        self.assertEqual(update_response.status_code, 200)
        updated_payload = update_response.json()
        self.assertEqual(updated_payload["version"], 2)
        self.assertEqual(updated_payload["stage"], "requirements")
        self.assertIn("Billing Center", updated_payload["content"])

        historical_response = self.client.get(f"/api/projects/{project.id}/files/requirements/feature_tree.md?version=1")
        self.assertEqual(historical_response.status_code, 200)
        self.assertNotIn("Billing Center", historical_response.json()["content"])

        latest_response = self.client.get(f"/api/projects/{project.id}/files/requirements/feature_tree.md")
        self.assertEqual(latest_response.status_code, 200)
        self.assertIn("Billing Center", latest_response.json()["content"])

        versions_payload = self.client.get(f"/api/projects/{project.id}/versions").json()
        self.assertEqual(versions_payload["versions"][-1]["versionKind"], "file_edit")
        self.assertEqual(versions_payload["versions"][-1]["sourceVersion"], 1)

    def test_saving_project_file_draft_does_not_create_new_version_until_commit(self) -> None:
        project = self.store.create_project("Project Draft Save", "Testing project draft save")
        self.store.register_agent_artifacts(
            project.id,
            version=project.currentVersion,
            task_id=None,
            agent_name="requirements_agent",
            artifacts=[
                {
                    "fileName": "feature_tree.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Feature Tree\n\n- User System\n",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd", "ui", "api_spec"],
                }
            ],
        )
        self.store.create_version(
            project.id,
            "Seed requirements snapshot",
            [{"file": "requirements/feature_tree.md", "status": "Added"}],
            version_kind="generation",
            created_by_type="agent",
            created_by="requirements_agent",
            state_manifest={
                "artifacts": [],
                "codeFiles": [],
                "agentArtifacts": {"requirements_agent": ["feature_tree.md"]},
            },
            modules_snapshot=[],
        )

        draft_response = self.client.put(
            f"/api/projects/{project.id}/files/requirements/feature_tree.md/draft",
            json={"content": "# Feature Tree\n\n- User System\n- Billing Center\n", "version": 1, "userId": "tester"},
        )

        self.assertEqual(draft_response.status_code, 200)
        draft_payload = draft_response.json()
        self.assertTrue(draft_payload["hasDraft"])
        self.assertEqual(draft_payload["version"], 1)
        self.assertIn("Billing Center", draft_payload["content"])

        project_payload = self.client.get(f"/api/projects/{project.id}").json()
        self.assertEqual(project_payload["currentVersion"], 1)

        versions_payload = self.client.get(f"/api/projects/{project.id}/versions").json()
        self.assertEqual(len(versions_payload["versions"]), 1)

        file_payload = self.client.get(f"/api/projects/{project.id}/files/requirements/feature_tree.md").json()
        self.assertTrue(file_payload["hasDraft"])
        self.assertIn("Billing Center", file_payload["content"])

        drafts_payload = self.client.get(f"/api/projects/{project.id}/drafts").json()
        self.assertEqual(drafts_payload["projectId"], project.id)
        self.assertEqual(drafts_payload["baseVersion"], 1)
        self.assertEqual(drafts_payload["totalFiles"], 1)
        self.assertEqual(drafts_payload["files"][0]["path"], "requirements/feature_tree.md")

    def test_committing_multiple_project_file_drafts_creates_one_new_version_with_real_changes(self) -> None:
        project = self.store.create_project("Project Draft Commit", "Testing project draft commit")
        self.store.register_agent_artifacts(
            project.id,
            version=project.currentVersion,
            task_id=None,
            agent_name="requirements_agent",
            artifacts=[
                {
                    "fileName": "business_scope.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Business Scope\n\nOriginal scope.\n",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd"],
                },
                {
                    "fileName": "feature_tree.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Feature Tree\n\n- User System\n",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd", "ui", "api_spec"],
                },
                {
                    "fileName": "functional_requirements.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Functional Requirements\n\n- Requirement A\n",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd"],
                },
                {
                    "fileName": "non_functional_requirements.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Non Functional Requirements\n\n- Requirement B\n",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd"],
                },
                {
                    "fileName": "use_case.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Use Case\n\n- Login\n",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd", "ui", "api_spec"],
                },
            ],
        )
        self.store.upsert_artifact(
            project.id,
            "prd",
            "PRD Draft",
            "# Product Requirements Document\n\nOriginal scope.\n",
        )
        self.store.replace_code_files(
            project.id,
            project.currentVersion,
            [{"filePath": "backend/run.py", "content": "print('v1')\n"}],
        )
        self.store.create_version(
            project.id,
            "Seed project snapshot",
            [{"file": "requirements/business_scope.md", "status": "Added"}],
            version_kind="generation",
            created_by_type="agent",
            created_by="requirements_agent",
            state_manifest={
                "artifacts": ["prd"],
                "codeFiles": ["backend/run.py"],
                "agentArtifacts": {
                    "requirements_agent": [
                        "business_scope.md",
                        "feature_tree.md",
                        "functional_requirements.md",
                        "non_functional_requirements.md",
                        "use_case.md",
                    ]
                },
            },
            modules_snapshot=[],
        )

        draft_one = self.client.put(
            f"/api/projects/{project.id}/files/requirements/business_scope.md/draft",
            json={"content": "# Business Scope\n\nUpdated scope.\n", "version": 1, "userId": "tester"},
        )
        self.assertEqual(draft_one.status_code, 200)

        draft_two = self.client.put(
            f"/api/projects/{project.id}/files/workspace/backend/run.py/draft",
            json={"content": "print('v2')\n", "version": 1, "userId": "tester"},
        )
        self.assertEqual(draft_two.status_code, 200)

        commit_response = self.client.post(
            f"/api/projects/{project.id}/drafts/commit",
            json={"description": "Commit working draft", "userId": "tester"},
        )

        self.assertEqual(commit_response.status_code, 200)
        commit_payload = commit_response.json()
        self.assertEqual(commit_payload["newVersion"], 2)
        self.assertEqual(sorted(commit_payload["committedPaths"]), ["requirements/business_scope.md", "workspace/backend/run.py"])

        project_payload = self.client.get(f"/api/projects/{project.id}").json()
        self.assertEqual(project_payload["currentVersion"], 2)

        versions_payload = self.client.get(f"/api/projects/{project.id}/versions").json()
        self.assertEqual(len(versions_payload["versions"]), 2)
        latest_version = versions_payload["versions"][-1]
        self.assertEqual(latest_version["versionKind"], "file_edit")
        self.assertEqual(latest_version["sourceVersion"], 1)
        changed_files = {item["file"]: item["status"] for item in latest_version["changes"]}
        self.assertEqual(changed_files["requirements/business_scope.md"], "Modified")
        self.assertEqual(changed_files["workspace/backend/run.py"], "Modified")
        self.assertEqual(changed_files["artifacts/prd.md"], "Modified")

        latest_scope = self.client.get(f"/api/projects/{project.id}/files/requirements/business_scope.md").json()
        self.assertIn("Updated scope", latest_scope["content"])
        self.assertFalse(latest_scope["hasDraft"])

        latest_workspace_file = self.client.get(f"/api/projects/{project.id}/files/workspace/backend/run.py").json()
        self.assertIn("v2", latest_workspace_file["content"])
        self.assertFalse(latest_workspace_file["hasDraft"])

        drafts_payload = self.client.get(f"/api/projects/{project.id}/drafts").json()
        self.assertEqual(drafts_payload["totalFiles"], 0)

    def test_editing_requirements_file_during_review_changes_following_architecture_inputs(self) -> None:
        project = self.store.create_project("Requirements Review Edit Project", "Testing review-stage propagation")
        self.store.replace_modules(
            project.id,
            [
                {"id": "user-system", "name": "User System", "nameEn": "User System", "isSelected": True},
                {"id": "admin-console", "name": "Admin Console", "nameEn": "Admin Console", "isSelected": True},
            ],
        )
        self.store.bump_project_version(project.id)
        self.store.register_agent_artifacts(
            project.id,
            version=2,
            task_id=None,
            agent_name="requirements_agent",
            artifacts=[
                {
                    "fileName": "business_scope.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Business Scope\n\nOriginal scope.\n",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd"],
                },
                {
                    "fileName": "feature_tree.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Feature Tree\n\n- User System\n- Admin Console\n",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd", "ui", "api_spec"],
                },
                {
                    "fileName": "functional_requirements.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Functional Requirements\n\n- Requirement A\n",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd"],
                },
                {
                    "fileName": "non_functional_requirements.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Non Functional Requirements\n\n- Requirement B\n",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd"],
                },
                {
                    "fileName": "use_case.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Use Case\n\n- Login\n",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd", "ui", "api_spec"],
                },
            ],
        )
        self.store.create_version(
            project.id,
            "Requirements drafts ready for review.",
            [{"file": "business_scope.md", "status": "Added"}],
            version_kind="requirements_review",
            source_version=1,
            created_by_type="agent",
            created_by="requirements_agent",
            state_manifest={
                "artifacts": [],
                "codeFiles": [],
                "agentArtifacts": {
                    "requirements_agent": [
                        "business_scope.md",
                        "feature_tree.md",
                        "functional_requirements.md",
                        "non_functional_requirements.md",
                        "use_case.md",
                    ]
                },
            },
            modules_snapshot=[
                {"id": "user-system", "name": "User System", "nameEn": "User System", "isSelected": True},
                {"id": "admin-console", "name": "Admin Console", "nameEn": "Admin Console", "isSelected": True},
            ],
        )
        task = self.store.create_task(
            project.id,
            "generate",
            status="waiting_user",
            input_data={"prompt": "Build a support dashboard", "uploadedFiles": []},
        )
        self.store.update_task(
            task.id,
            status="waiting_user",
            output_data={
                "confirmationKind": "artifact_review",
                "activePhase": "waiting_for_requirements_artifact_review",
                "selectedModuleIds": ["user-system", "admin-console"],
            },
        )

        edit_response = self.client.put(
            f"/api/projects/{project.id}/files/requirements/business_scope.md",
            json={"content": "# Business Scope\n\nEdited scope for architecture.\n", "version": 2},
        )
        self.assertEqual(edit_response.status_code, 200)
        self.assertEqual(edit_response.json()["version"], 3)

        confirm_response = self.client.post(
            f"/api/projects/{project.id}/confirm",
            json={"taskId": task.id, "action": "confirm", "data": {"selectedIds": []}},
        )
        self.assertEqual(confirm_response.status_code, 200)

        latest_prd_response = self.client.get(f"/api/projects/{project.id}/artifacts/prd")
        self.assertEqual(latest_prd_response.status_code, 200)
        self.assertIn("Edited scope for architecture", latest_prd_response.json()["content"])

    def test_updating_current_code_file_creates_new_version_and_preserves_previous_snapshot(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Current Code Edit Project", "description": "Testing direct code edits"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build a support dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        self._complete_generate_task(project_id, selected_ids=["user-system", "admin-console"])

        update_response = self.client.put(
            f"/api/projects/{project_id}/code/files/docs/PRD.md",
            json={"content": "# Direct File Edit\n\nCurrent version should stay stable.", "version": 3},
        )
        self.assertEqual(update_response.status_code, 200)
        updated_payload = update_response.json()
        self.assertEqual(updated_payload["version"], 4)
        self.assertIn("Current version should stay stable", updated_payload["content"])

        project_payload = self.client.get(f"/api/projects/{project_id}").json()
        self.assertEqual(project_payload["currentVersion"], 4)

        versions_payload = self.client.get(f"/api/projects/{project_id}/versions").json()
        self.assertEqual(len(versions_payload["versions"]), 3)
        self.assertEqual(versions_payload["versions"][-1]["versionKind"], "code_edit")
        self.assertEqual(versions_payload["versions"][-1]["sourceVersion"], 3)

        latest_file = self.client.get(f"/api/projects/{project_id}/code/files/docs/PRD.md").json()
        self.assertEqual(latest_file["version"], 4)
        self.assertIn("Current version should stay stable", latest_file["content"])

        previous_file = self.client.get(f"/api/projects/{project_id}/code/files/docs/PRD.md?version=3").json()
        self.assertEqual(previous_file["version"], 3)
        self.assertNotIn("Current version should stay stable", previous_file["content"])

    def test_updating_historical_code_file_creates_new_version_from_selected_snapshot(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Historical Code Edit Project", "description": "Testing versioned code edits"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build a warehouse dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        self._complete_generate_task(project_id, selected_ids=["user-system", "admin-console"])

        v2_file = self.client.get(f"/api/projects/{project_id}/code/files/docs/PRD.md?version=3").json()

        update_response = self.client.put(
            f"/api/projects/{project_id}/artifacts/prd",
            json={"content": "# Newer Version\n\nBase current version changed."},
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["version"], 4)

        historical_edit_response = self.client.put(
            f"/api/projects/{project_id}/code/files/docs/PRD.md",
            json={"content": "# Historical Edit\n\nThis should create a new version.", "version": 3},
        )
        self.assertEqual(historical_edit_response.status_code, 200)
        historical_edit_payload = historical_edit_response.json()
        self.assertEqual(historical_edit_payload["version"], 5)
        self.assertIn("This should create a new version", historical_edit_payload["content"])

        project_payload = self.client.get(f"/api/projects/{project_id}").json()
        self.assertEqual(project_payload["currentVersion"], 5)

        latest_file = self.client.get(f"/api/projects/{project_id}/code/files/docs/PRD.md").json()
        self.assertEqual(latest_file["version"], 5)
        self.assertIn("This should create a new version", latest_file["content"])

        preserved_v3 = self.client.get(f"/api/projects/{project_id}/code/files/docs/PRD.md?version=4").json()
        self.assertIn("Base current version changed", preserved_v3["content"])
        self.assertEqual(v2_file["version"], 3)

        versions_payload = self.client.get(f"/api/projects/{project_id}/versions").json()
        self.assertEqual(len(versions_payload["versions"]), 4)
        self.assertEqual(versions_payload["versions"][-1]["version"], 5)
        self.assertEqual(versions_payload["versions"][-1]["description"], "Updated docs/PRD.md from version 3.")
        self.assertEqual(versions_payload["versions"][-1]["versionKind"], "code_edit")
        self.assertEqual(versions_payload["versions"][-1]["sourceVersion"], 3)

    def test_code_modules_endpoint_returns_module_folder_metrics(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Module Metrics Project", "description": "Testing code module summaries"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build an operations dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        self._complete_generate_task(project_id, selected_ids=["user-system", "admin-console"])

        project_modules = self.client.get(f"/api/projects/{project_id}/modules").json()["modules"]
        expected_selected_ids = {module["id"] for module in project_modules if module["isSelected"]}

        modules_response = self.client.get(f"/api/projects/{project_id}/code/modules")
        self.assertEqual(modules_response.status_code, 200)
        payload = modules_response.json()
        self.assertEqual(len(payload["modules"]), len(expected_selected_ids))

        first_module = payload["modules"][0]
        self.assertIn(first_module["id"], expected_selected_ids)
        self.assertTrue(first_module["folderPath"].startswith("src/"))
        self.assertGreaterEqual(first_module["fileCount"], 1)
        self.assertGreaterEqual(first_module["lineCount"], 1)

        folder_paths = {module["folderPath"] for module in payload["modules"]}
        self.assertEqual(folder_paths, {f"src/{module_id}" for module_id in expected_selected_ids})

    def test_code_preview_returns_html_for_ui_files_only(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Code Preview Project", "description": "Testing HTML preview"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build a marketing dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        self._complete_generate_task(project_id, selected_ids=["user-system", "admin-console"])

        preview_response = self.client.get(f"/api/projects/{project_id}/code/preview/ui/index.html")
        self.assertEqual(preview_response.status_code, 200)
        self.assertTrue(preview_response.headers["content-type"].startswith("text/html"))
        self.assertIn("<!doctype html>", preview_response.text.lower())

        invalid_preview_response = self.client.get(f"/api/projects/{project_id}/code/preview/docs/PRD.md")
        self.assertEqual(invalid_preview_response.status_code, 400)

    def test_code_download_returns_zip_snapshot_for_requested_version(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Code Download Project", "description": "Testing ZIP download"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build a reporting workspace", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        self._complete_generate_task(project_id, selected_ids=["user-system", "admin-console"])

        original_file = self.client.get(f"/api/projects/{project_id}/code/files/docs/PRD.md?version=3").json()

        update_response = self.client.put(
            f"/api/projects/{project_id}/artifacts/prd",
            json={"content": "# Downloaded Snapshot\n\nNewest content for ZIP verification."},
        )
        self.assertEqual(update_response.status_code, 200)

        latest_download = self.client.get(f"/api/projects/{project_id}/code/download")
        self.assertEqual(latest_download.status_code, 200)
        self.assertTrue(latest_download.headers["content-type"].startswith("application/zip"))
        self.assertIn(".zip", latest_download.headers.get("content-disposition", ""))

        with zipfile.ZipFile(BytesIO(latest_download.content)) as archive:
            latest_names = set(archive.namelist())
            self.assertIn("code/docs/PRD.md", latest_names)
            latest_prd = archive.read("code/docs/PRD.md").decode("utf-8")
            self.assertIn("Newest content for ZIP verification", latest_prd)

        historical_download = self.client.get(f"/api/projects/{project_id}/code/download?version=3")
        self.assertEqual(historical_download.status_code, 200)

        with zipfile.ZipFile(BytesIO(historical_download.content)) as archive:
            historical_prd = archive.read("code/docs/PRD.md").decode("utf-8")
            self.assertEqual(historical_prd, original_file["content"])
            self.assertNotIn("Newest content for ZIP verification", historical_prd)

    def test_code_download_includes_agent_docs_even_without_code_files(self) -> None:
        project = self.store.create_project("Docs Only Download", "Testing docs-only ZIP download")
        self.store.register_agent_artifacts(
            project.id,
            version=project.currentVersion,
            task_id=None,
            agent_name="requirements_agent",
            artifacts=[
                {
                    "fileName": "feature_tree.md",
                    "fileType": "markdown",
                    "contentType": "text/markdown",
                    "content": "# Feature Tree\n\n- User System",
                    "isPrimarySource": True,
                    "mappedArtifactTypes": ["prd"],
                }
            ],
        )

        download_response = self.client.get(f"/api/projects/{project.id}/code/download")
        self.assertEqual(download_response.status_code, 200)

        with zipfile.ZipFile(BytesIO(download_response.content)) as archive:
            names = set(archive.namelist())
            self.assertIn("docs/requirements_agent/feature_tree.md", names)
            self.assertEqual(
                archive.read("docs/requirements_agent/feature_tree.md").decode("utf-8"),
                "# Feature Tree\n\n- User System",
            )

    def test_code_download_supports_non_ascii_project_name_in_attachment_header(self) -> None:
        project = self.store.create_project("开发一个贪吃蛇游戏", "Testing non-ascii ZIP filename")
        self.store.replace_code_files(
            project.id,
            project.currentVersion,
            [
                {
                    "filePath": "backend/run.py",
                    "content": "print('snake')\n",
                }
            ],
        )

        download_response = self.client.get(f"/api/projects/{project.id}/code/download")
        self.assertEqual(download_response.status_code, 200)
        self.assertTrue(download_response.headers["content-type"].startswith("application/zip"))
        disposition = download_response.headers.get("content-disposition", "")
        self.assertIn("attachment;", disposition)
        self.assertIn("filename=", disposition)
        self.assertIn("filename*=", disposition)

    def test_code_file_lock_prevents_another_user_from_editing_same_file(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Code Lock Project", "description": "Testing file lock behavior"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build an approval dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        self._complete_generate_task(project_id, selected_ids=["user-system", "admin-console"])

        first_lock = self.client.post(
            f"/api/projects/{project_id}/code/files/docs/PRD.md/lock",
            json={"userId": "user-a", "version": 3},
        )
        self.assertEqual(first_lock.status_code, 200)
        first_payload = first_lock.json()
        self.assertEqual(first_payload["filePath"], "docs/PRD.md")
        self.assertEqual(first_payload["lockedBy"], "user-a")
        self.assertFalse(first_payload["isConflict"])

        second_lock = self.client.post(
            f"/api/projects/{project_id}/code/files/docs/PRD.md/lock",
            json={"userId": "user-b", "version": 3},
        )
        self.assertEqual(second_lock.status_code, 409)
        second_payload = second_lock.json()
        self.assertEqual(second_payload["detail"]["errorType"], "CODE_FILE_LOCKED")
        self.assertEqual(second_payload["detail"]["lock"]["lockedBy"], "user-a")

        release_response = self.client.delete(
            f"/api/projects/{project_id}/code/files/docs/PRD.md/lock",
            params={"userId": "user-a"},
        )
        self.assertEqual(release_response.status_code, 200)
        self.assertEqual(release_response.json()["status"], "released")

        third_lock = self.client.post(
            f"/api/projects/{project_id}/code/files/docs/PRD.md/lock",
            json={"userId": "user-b", "version": 3},
        )
        self.assertEqual(third_lock.status_code, 200)
        self.assertEqual(third_lock.json()["lockedBy"], "user-b")

    def test_autosave_updates_current_snapshot_without_creating_new_version(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Code Autosave Project", "description": "Testing autosave flow"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build a finance workspace", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        self._complete_generate_task(project_id, selected_ids=["user-system", "admin-console"])

        lock_response = self.client.post(
            f"/api/projects/{project_id}/code/files/docs/PRD.md/lock",
            json={"userId": "user-a", "version": 3},
        )
        self.assertEqual(lock_response.status_code, 200)

        autosave_response = self.client.put(
            f"/api/projects/{project_id}/code/files/docs/PRD.md/autosave",
            json={"content": "# Draft PRD\n\nAutosaved content.", "version": 3, "userId": "user-a"},
        )
        self.assertEqual(autosave_response.status_code, 200)
        autosave_payload = autosave_response.json()
        self.assertEqual(autosave_payload["version"], 3)
        self.assertIn("Autosaved content", autosave_payload["content"])
        self.assertIsNotNone(autosave_payload["lock"])
        self.assertEqual(autosave_payload["lock"]["lockedBy"], "user-a")

        project_payload = self.client.get(f"/api/projects/{project_id}").json()
        self.assertEqual(project_payload["currentVersion"], 3)

        versions_payload = self.client.get(f"/api/projects/{project_id}/versions").json()
        self.assertEqual(len(versions_payload["versions"]), 2)

        latest_file = self.client.get(f"/api/projects/{project_id}/code/files/docs/PRD.md").json()
        self.assertEqual(latest_file["version"], 3)
        self.assertIn("Autosaved content", latest_file["content"])

        historical_autosave = self.client.put(
            f"/api/projects/{project_id}/code/files/docs/PRD.md/autosave",
            json={"content": "# Should Fail\n\nHistorical autosave.", "version": 1, "userId": "user-a"},
        )
        self.assertEqual(historical_autosave.status_code, 409)
        self.assertEqual(historical_autosave.json()["detail"]["errorType"], "AUTOSAVE_REQUIRES_CURRENT_VERSION")

    def test_versioned_code_file_returns_404_when_file_is_not_part_of_exact_snapshot(self) -> None:
        project = self.store.create_project("Exact Snapshot Project", "Testing exact manifest reads")
        self.store.replace_code_files(
            project.id,
            2,
            [
                {"filePath": "docs/PRD.md", "content": "# PRD\n"},
                {"filePath": "backend/app.py", "content": "print('ok')\n"},
            ],
        )
        self.store.create_version(
            project.id,
            "Seed version 2",
            [{"file": "docs/PRD.md", "status": "Added"}],
            version_kind="generation",
            source_version=1,
            state_manifest={
                "artifacts": ["prd"],
                "codeFiles": ["docs/PRD.md", "backend/app.py"],
                "agentArtifacts": {},
            },
            modules_snapshot=[],
            created_by_type="agent",
        )
        self.store.bump_project_version(project.id)
        self.store.replace_code_files(
            project.id,
            3,
            [
                {"filePath": "docs/PRD.md", "content": "# PRD v3\n"},
            ],
        )
        self.store.create_version(
            project.id,
            "Seed version 3",
            [{"file": "backend/app.py", "status": "Deleted"}],
            version_kind="code_edit",
            source_version=2,
            state_manifest={
                "artifacts": ["prd"],
                "codeFiles": ["docs/PRD.md"],
                "agentArtifacts": {},
            },
            modules_snapshot=[],
            created_by_type="user",
        )

        missing_response = self.client.get(f"/api/projects/{project.id}/code/files/backend/app.py?version=3")
        self.assertEqual(missing_response.status_code, 404)

    def test_rollback_restores_selected_modules_snapshot(self) -> None:
        project_response = self.client.post(
            "/api/projects",
            json={"name": "Rollback Modules Project", "description": "Testing module rollback"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        generate_response = self.client.post(
            f"/api/projects/{project_id}/generate",
            json={"prompt": "Build a service dashboard", "uploadedFiles": []},
        )
        self.assertEqual(generate_response.status_code, 200)
        self._complete_generate_task(project_id, selected_ids=["user-system", "admin-console"])

        baseline_modules = self.client.get(f"/api/projects/{project_id}/modules").json()["modules"]
        baseline_selected_ids = [module["id"] for module in baseline_modules if module["isSelected"]]
        self.assertEqual(baseline_selected_ids, [module["id"] for module in baseline_modules])

        toggle_response = self.client.post(
            f"/api/projects/{project_id}/modules",
            json={"selectedModules": ["customer-management"]},
        )
        self.assertEqual(toggle_response.status_code, 200)
        changed_selected_ids = [module["id"] for module in toggle_response.json()["modules"] if module["isSelected"]]
        self.assertEqual(changed_selected_ids, ["customer-management"])

        rollback_response = self.client.post(f"/api/projects/{project_id}/versions/3/rollback")
        self.assertEqual(rollback_response.status_code, 200)

        restored_modules = self.client.get(f"/api/projects/{project_id}/modules").json()["modules"]
        restored_selected_ids = [module["id"] for module in restored_modules if module["isSelected"]]
        self.assertEqual(restored_selected_ids, baseline_selected_ids)

    def test_rollback_version_changes_are_computed_from_real_snapshot_diff(self) -> None:
        project = self.store.create_project("Rollback Diff Project", "Testing rollback diff")
        self.store.replace_code_files(
            project.id,
            1,
            [
                {"filePath": "docs/PRD.md", "content": "# PRD v1\n"},
            ],
        )
        self.store.create_version(
            project.id,
            "Seed version 1",
            [{"file": "workspace/docs/PRD.md", "status": "Added"}],
            version_kind="generation",
            source_version=None,
            state_manifest={
                "artifacts": [],
                "codeFiles": ["docs/PRD.md"],
                "agentArtifacts": {},
            },
            modules_snapshot=[],
            created_by_type="agent",
        )
        self.store.bump_project_version(project.id)
        self.store.replace_code_files(
            project.id,
            2,
            [
                {"filePath": "docs/PRD.md", "content": "# PRD v2\n"},
                {"filePath": "backend/extra.py", "content": "print('extra')\n"},
            ],
        )
        self.store.create_version(
            project.id,
            "Seed version 2",
            [{"file": "workspace/backend/extra.py", "status": "Added"}],
            version_kind="code_edit",
            source_version=1,
            state_manifest={
                "artifacts": [],
                "codeFiles": ["docs/PRD.md", "backend/extra.py"],
                "agentArtifacts": {},
            },
            modules_snapshot=[],
            created_by_type="user",
        )

        rollback_response = self.client.post(f"/api/projects/{project.id}/versions/1/rollback")

        self.assertEqual(rollback_response.status_code, 200)
        versions_payload = self.client.get(f"/api/projects/{project.id}/versions").json()
        latest_version = versions_payload["versions"][-1]
        changed_files = {item["file"]: item["status"] for item in latest_version["changes"]}
        self.assertEqual(changed_files["workspace/backend/extra.py"], "Deleted")
        self.assertEqual(changed_files["workspace/docs/PRD.md"], "Modified")


if __name__ == "__main__":
    unittest.main()
