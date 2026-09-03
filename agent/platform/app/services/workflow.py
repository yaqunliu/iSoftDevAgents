from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import re
import shutil
import threading
import time
from collections.abc import Awaitable
from pathlib import Path
from typing import Any

from app.agents.orchestrator import agent_orchestrator
from app.config import delete_local_files_after_persist_enabled
from app.localization import Locale, normalize_locale, t
from app.schemas import AgentEvent, Message, PlannedArtifactFile, StatisticsResponse, TaskErrorType, utc_now
from app.services.agent_output_contracts import (
    build_main_panel_contract,
    planned_architecture_files,
    planned_requirements_full_files,
    planned_requirements_analysis_files,
    planned_test_files,
    planned_ui_files,
)
from app.services.image_reference_summary import summarize_image_reference
from app.services.store import store
from app.ws.manager import ws_manager

_PROGRESS_HEARTBEAT_INTERVAL_SECONDS = float(
    os.getenv("ISOFTDEVAGENTS_PROGRESS_HEARTBEAT_INTERVAL") or "5.0"
)
_LIVE_OUTPUT_RECOVERY_POLL_SECONDS = 0.5
_LIVE_OUTPUT_RECOVERY_GRACE_SECONDS = 5.0
_PROJECT_OUTPUTS_ROOT = Path(__file__).resolve().parents[2] / "data" / "projects"
logger = logging.getLogger("uvicorn.error")
_AGENT_SHUTDOWN_WAIT_SECONDS = float(os.getenv("ISOFTDEVAGENTS_AGENT_SHUTDOWN_WAIT_SECONDS") or "30")

_running_task_processes: dict[str, dict[str, Any]] = {}
_processes_lock = threading.Lock()

# ---------------------------------------------------------------------------
# 并发工作流限制
# ---------------------------------------------------------------------------
# 每个工作流跑一整套 Agent（需求/架构/UI/编码/测试），长达数小时。
# 不限制并发数会导致线程池、内存和 LLM API 同时过载。
# ---------------------------------------------------------------------------
_MAX_CONCURRENT_WORKFLOWS = int(os.getenv("ISOFTDEVAGENTS_MAX_CONCURRENT_WORKFLOWS") or "8")
_workflow_semaphore: asyncio.Semaphore | None = None


def _get_workflow_semaphore() -> asyncio.Semaphore:
    """延迟初始化，确保在正确的 event loop 中创建。"""
    global _workflow_semaphore
    if _workflow_semaphore is None:
        _workflow_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_WORKFLOWS)
    return _workflow_semaphore


def _now_iso_text() -> str:
    return utc_now().isoformat()


def _normalize_runtime_path(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _process_alive(process: Any) -> bool:
    try:
        import subprocess as sp
        if isinstance(process, sp.Popen):
            return process.poll() is None
    except Exception:
        logger.debug("Failed to inspect process liveness.", exc_info=True)
    return False


def _running_task_snapshot(task_id: str) -> dict[str, Any] | None:
    with _processes_lock:
        entry = _running_task_processes.get(task_id)
        if entry is None:
            return None
        snapshot = dict(entry)
    process = snapshot.get("process")
    snapshot["process_alive"] = _process_alive(process)
    return snapshot


def update_running_task(task_id: str, **updates: Any) -> None:
    """
    接口注释：
    更新运行中任务的实时状态快照。

    教学注释：
    registry 现在不只是“能不能 cancel”，
    它还承担“handoff 失败时最后现场长什么样”的真相来源。
    所以所有 Agent 都应该把 runtime_state、latest_output_file、stdout/stderr 预览持续写回这里。
    """

    normalized_updates = dict(updates)
    for path_key in ("runtime_home", "output_root"):
        if path_key in normalized_updates:
            normalized_updates[path_key] = _normalize_runtime_path(normalized_updates.get(path_key))
    with _processes_lock:
        entry = _running_task_processes.get(task_id)
        if entry is None:
            return
        entry.update({key: value for key, value in normalized_updates.items() if value is not None})


def mark_running_task_completion(task_id: str, *, runtime_state: str = "stopped") -> None:
    completion_signaled_at = _now_iso_text()
    with _processes_lock:
        entry = _running_task_processes.get(task_id)
        if entry is None:
            return
        entry["runtime_state"] = runtime_state
        entry["completion_signaled_at"] = completion_signaled_at
        completion_event = entry.get("completion_event")
        if completion_event is not None:
            completion_event.set()


def register_running_task(
    task_id: str,
    *,
    process: Any = None,
    cancel_event: threading.Event | None = None,
    completion_event: threading.Event | None = None,
    agent_name: str | None = None,
    runtime_home: str | Path | None = None,
    output_root: str | Path | None = None,
    runtime_state: str = "starting",
    latest_output_file: str | None = None,
    runtime_pid: int | None = None,
    stdout_preview: str | None = None,
    stderr_preview: str | None = None,
) -> None:
    with _processes_lock:
        if task_id in _running_task_processes:
            logger.warning("Task %s already registered, overwriting", task_id)
        _running_task_processes[task_id] = {
            "task_id": task_id,
            "process": process,
            "cancel_event": cancel_event or threading.Event(),
            "completion_event": completion_event or threading.Event(),
            "agent_name": agent_name,
            "runtime_home": _normalize_runtime_path(runtime_home),
            "output_root": _normalize_runtime_path(output_root),
            "runtime_state": runtime_state,
            "latest_output_file": latest_output_file,
            "runtime_pid": runtime_pid,
            "stdout_preview": stdout_preview,
            "stderr_preview": stderr_preview,
            "registered_at": _now_iso_text(),
            "cancel_requested_at": None,
            "completion_signaled_at": None,
            "registry_unregistered_at": None,
        }
    logger.info("Registered running task: %s agent=%s state=%s", task_id, agent_name or "-", runtime_state)


def unregister_running_task(task_id: str) -> None:
    with _processes_lock:
        if task_id in _running_task_processes:
            entry = _running_task_processes[task_id]
            entry["registry_unregistered_at"] = _now_iso_text()
            completion_event = entry.get("completion_event")
            if completion_event:
                completion_event.set()
            del _running_task_processes[task_id]
            logger.info("Unregistered running task: %s agent=%s", task_id, entry.get("agent_name") or "-")


def cancel_running_task(task_id: str) -> bool:
    with _processes_lock:
        if task_id not in _running_task_processes:
            logger.warning("Task %s not found in running processes", task_id)
            return False
        entry = _running_task_processes[task_id]
        cancel_event = entry.get("cancel_event")
        if cancel_event:
            cancel_event.set()
            entry["cancel_requested_at"] = _now_iso_text()
            entry["runtime_state"] = "cancelling"
            logger.info("Cancel signal sent to task: %s agent=%s", task_id, entry.get("agent_name") or "-")
        process = entry.get("process")
        if process is not None:
            try:
                import subprocess as sp
                if isinstance(process, sp.Popen) and process.poll() is None:
                    process.terminate()
                    logger.info("Process terminated for task: %s", task_id)
            except Exception as exc:
                logger.warning("Failed to terminate process for task %s: %s", task_id, exc)
        return True


def wait_for_running_task_stop(task_id: str, *, timeout_seconds: float) -> dict[str, Any]:
    snapshot = _running_task_snapshot(task_id)
    if snapshot is None:
        return {
            "task_id": task_id,
            "agent_name": None,
            "stopped_cleanly": True,
            "stop_reason": "not_registered",
            "registry_present": False,
            "completion_signaled": True,
            "process_alive": False,
            "runtime_state": "stopped",
        }

    completion_event = snapshot.get("completion_event")
    if completion_event is None:
        refreshed = _running_task_snapshot(task_id)
        return {
            "task_id": task_id,
            "agent_name": snapshot.get("agent_name"),
            "stopped_cleanly": False,
            "stop_reason": "missing_completion_event",
            "registry_present": refreshed is not None,
            "completion_signaled": False,
            "process_alive": bool((refreshed or snapshot).get("process_alive")),
            "runtime_state": str((refreshed or snapshot).get("runtime_state") or ""),
            "snapshot": refreshed or snapshot,
        }

    completion_signaled = bool(completion_event.wait(timeout=max(0.0, timeout_seconds)))
    refreshed = _running_task_snapshot(task_id)
    registry_present = refreshed is not None
    latest = refreshed or snapshot
    process_alive = bool(latest.get("process_alive"))
    runtime_state = str(latest.get("runtime_state") or "")
    completion_recorded = bool(latest.get("completion_signaled_at")) or completion_signaled or completion_event.is_set()
    stopped_cleanly = completion_recorded and not registry_present and not process_alive
    stop_reason = "stopped_cleanly"
    if not completion_signaled:
        stop_reason = "completion_timeout"
    elif process_alive:
        stop_reason = "process_still_alive"
    elif registry_present:
        stop_reason = "registry_still_present"

    return {
        "task_id": task_id,
        "agent_name": latest.get("agent_name"),
        "stopped_cleanly": stopped_cleanly,
        "stop_reason": stop_reason,
        "registry_present": registry_present,
        "completion_signaled": completion_recorded,
        "process_alive": process_alive,
        "runtime_state": runtime_state,
        "snapshot": latest,
    }


def _persist_handoff_timeout_debug_bundle(task_id: str, *, stage_name: str, stop_details: dict[str, Any]) -> Path | None:
    snapshot = stop_details.get("snapshot") if isinstance(stop_details.get("snapshot"), dict) else {}
    agent_name = str(snapshot.get("agent_name") or "unknown-agent").replace("_", "-")
    output_root_text = _normalize_runtime_path(snapshot.get("output_root"))
    runtime_home_text = _normalize_runtime_path(snapshot.get("runtime_home"))
    stdout_preview = str(snapshot.get("stdout_preview") or "")
    stderr_preview = str(snapshot.get("stderr_preview") or "")
    extra_paths: dict[str, Path | None] = {}
    if runtime_home_text:
        extra_paths["runtime-home"] = Path(runtime_home_text)
    try:
        return agent_orchestrator._persist_agent_debug_bundle(
            agent_name=agent_name,
            output_root=Path(output_root_text) if output_root_text else None,
            stdout_text=stdout_preview,
            stderr_text=stderr_preview,
            context={
                "reason": "handoff_timeout",
                "stageName": stage_name,
                "taskId": task_id,
                "agentName": snapshot.get("agent_name"),
                "runtimeState": snapshot.get("runtime_state"),
                "latestOutputFile": snapshot.get("latest_output_file"),
                "cancelRequestedAt": snapshot.get("cancel_requested_at"),
                "completionSignaledAt": snapshot.get("completion_signaled_at"),
                "registryUnregisteredAt": snapshot.get("registry_unregistered_at"),
                "stopReason": stop_details.get("stop_reason"),
                "processAlive": stop_details.get("process_alive"),
                "registryPresent": stop_details.get("registry_present"),
            },
            extra_paths=extra_paths,
        )
    except Exception:
        logger.warning("Failed to persist handoff-timeout debug bundle for task %s.", task_id, exc_info=True)
        return None


async def _stop_running_task_before_stage_transition(task_id: str, *, stage_name: str) -> None:
    """
    在切到下一个 Agent 之前，先确保上一个运行实例已经真正收尾。

    设计注释：
    以前这里最容易出的问题是：前一个 Agent 已经被判定“逻辑上完成”，
    但后台线程其实还没停，结果新旧两个 Agent 的日志和重试混在一起。
    现在阶段切换前统一走这一层，至少要先发取消，再等旧实例收尾完成。
    """

    cancel_running_task(task_id)
    stop_details = await asyncio.to_thread(
        wait_for_running_task_stop,
        task_id,
        timeout_seconds=_AGENT_SHUTDOWN_WAIT_SECONDS,
    )
    if not stop_details.get("stopped_cleanly"):
        debug_bundle = _persist_handoff_timeout_debug_bundle(
            task_id,
            stage_name=stage_name,
            stop_details=stop_details,
        )
        raise RuntimeError(
            f"Previous agent did not stop cleanly before entering {stage_name} within "
            f"{_AGENT_SHUTDOWN_WAIT_SECONDS:.0f}s. agent={stop_details.get('agent_name') or '-'} "
            f"reason={stop_details.get('stop_reason') or '-'} debug_bundle={debug_bundle or '-'}"
        )


def cancel_running_task_sync(task_id: str) -> bool:
    return cancel_running_task(task_id)


async def cancel_task_async(project_id: str, task_id: str) -> None:
    cancel_running_task(task_id)

_TEXT_FILE_EXTENSIONS = {
    ".md": ("markdown", "text/markdown"),
    ".markdown": ("markdown", "text/markdown"),
    ".txt": ("text", "text/plain"),
    ".json": ("json", "application/json"),
    ".yaml": ("yaml", "application/yaml"),
    ".yml": ("yaml", "application/yaml"),
    ".html": ("html", "text/html"),
    ".htm": ("html", "text/html"),
    ".ts": ("typescript", "text/plain"),
    ".tsx": ("tsx", "text/plain"),
    ".js": ("javascript", "text/plain"),
    ".jsx": ("jsx", "text/plain"),
    ".py": ("python", "text/plain"),
    ".css": ("css", "text/css"),
    ".svg": ("svg", "image/svg+xml"),
}

_REQUIREMENTS_AGENT_OUTPUT_FILES = {
    "SurveyCrew": "survey.md",
    "CompetitiveAnalysisCrew": "competitive_analysis.md",
    "DraftContentDiagramCrew": "draft_context_diagram.md",
    "DraftEventListCrew": "draft_event_list.md",
    "UserIntroductionDev": "user_introduction.md",
    "FeatureTreeDev": "feature_tree.md",
    "BusinessScopeDev": "business_scope.md",
    "UserCaseCrew": "use_case.md",
    "NFRCrew": "non_functional_requirements.md",
    "UsageScenarioCrew": "usage_scenario.md",
    "STDCrew": "state_transition_diagram.md",
    "FRCrew": "functional_requirements.md",
    "DataFlowDiagramCrew": "data_flow_diagram.md",
    "ERDCrew": "entity_relationship_diagram.md",
    "DataDictionaryCrew": "data_dictionary.md",
    "DialogMapCrew": "dialog_map.md",
    "ExtractDocumentCrew": "document_skeleton.md",
    "DocContentCrew": "doc_content.md",
    "ChapterDependenceCrew": "chapter_dependence.md",
    "ArtifactPlanningCrew": "artifact_planning.md",
    "BRDModifyCrew": "BRD_modify.md",
}

_REQUIREMENTS_AGENT_PREFIX_FILE_HINTS = (
    ("SRS Chapter planning", "srs_planning.md"),
    ("SRS Chapter", "software_requirements_specification_chapter.md"),
    ("BRDev Chapter", "business_requirements_chapter.md"),
)

_REQUIREMENTS_AGENT_KEYWORD_FILE_HINTS = (
    ("feature tree", "feature_tree.md"),
    ("context diagram", "draft_context_diagram.md"),
    ("event list", "draft_event_list.md"),
    ("business scope", "business_scope.md"),
    ("use case", "use_case.md"),
    ("non-functional requirement", "non_functional_requirements.md"),
    ("non functional requirement", "non_functional_requirements.md"),
    ("functional requirement", "functional_requirements.md"),
    ("data flow diagram", "data_flow_diagram.md"),
    ("data dictionary", "data_dictionary.md"),
    ("dialog map", "dialog_map.md"),
    ("entity relationship diagram", "entity_relationship_diagram.md"),
    ("erd", "entity_relationship_diagram.md"),
    ("survey", "survey.md"),
)

_STRUCTURED_PROGRESS_FILE_ALLOWLIST = {
    *set(_REQUIREMENTS_AGENT_OUTPUT_FILES.values()),
    "srs_planning.md",
    "software_requirements_specification_chapter.md",
    "business_requirements_chapter.md",
    "analysis_task_output.txt",
    "component_design.json",
    "class_design_structured.json",
    "class_design_raw.md",
    "api.yaml",
    "api.yml",
    "prd.md",
    "architecture.md",
    "index.html",
}

_STRUCTURED_PROGRESS_ACTION_HINTS = (
    "attempt",
    "generating",
    "generate",
    "creating",
    "create ",
    "writing",
    "write ",
    "producing",
    "produce",
    "drafting",
    "draft ",
    "生成",
    "写入",
    "输出",
)

_PLANNED_STAGE_ORDER = {
    "requirements_analysis": 1,
    "requirements_full": 2,
    "architecture": 3,
    "ui": 4,
    "code": 4,
    "test": 5,
}


def _event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return AgentEvent(type=event_type, data=data).model_dump(mode="json")


def _preview_log_text(value: str | None, *, limit: int = 160) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _int_value(value: Any) -> int:
    """
    接口注释：
    把运行时事件里的计数字段安全转成整数。

    Requirements Agent 和 Architecture Agent 的运行时快照里，
    这些值有时会是 `None`、字符串，或者别的可转数字类型。
    这里统一收口，避免监控分支因为类型波动直接报错。
    """

    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _silence_background_asyncio_task(task: asyncio.Task[Any]) -> None:
    """
    后台兜底取消后的任务结果回收器。

    设计注释：
    live output 恢复会在“关键文件已经齐了”时提前放行主流程。
    这时原始 await 任务可能还挂在桥接线程上。
    这里统一吞掉取消后的结果，避免事件循环里出现 “Task exception was never retrieved”。
    """

    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        logger.warning("Suppressed background task exception after live-output recovery.", exc_info=True)


def _phase_agent_name(phase: str, artifact_type: str | None = None) -> str:
    if phase in {"queued", "reading_context", "requirements_analysis", "modules_ready", "waiting_for_module_confirmation", "requirements_feedback_required"}:
        return "requirements_agent"
    if phase == "requirements_drafts_started":
        return "requirements_agent"
    if phase == "waiting_for_requirements_artifact_review":
        return "requirements_agent"
    if phase == "architecture_generation_started":
        return "architecture_agent"
    if phase == "artifact_generated" and artifact_type == "architecture":
        return "architecture_agent"
    if phase in {"artifact_generation_started", "artifact_generated", "waiting_for_artifact_review"}:
        return "architecture_agent"
    if phase in {"ui_generation_started", "ui_generation_completed"}:
        return "ui_agent"
    if phase in {"code_generation_started", "code_generation_completed", "artifact_review_completed"}:
        return "coding_agent"
    if phase in {"test_generation_started", "test_generation_completed"}:
        return "test_agent"
    if phase == "modification_started":
        return "requirements_agent"
    return "orchestrator"


def _artifact_file_identity(file_name: str) -> str:
    return file_name.strip().replace("\\", "/")


def _artifact_file_meta(file_name: str) -> tuple[str, str]:
    suffix = Path(file_name).suffix.lower()
    if suffix in _TEXT_FILE_EXTENSIONS:
        return _TEXT_FILE_EXTENSIONS[suffix]
    guessed_content_type, _ = mimetypes.guess_type(file_name)
    return suffix.lstrip(".") or "binary", guessed_content_type or "application/octet-stream"


def _project_task_output_dir(project_id: str, task_id: str, stage_name: str) -> Path:
    return _PROJECT_OUTPUTS_ROOT / project_id / "tasks" / task_id / stage_name


def _cleanup_local_path_if_configured(path: str | Path | None) -> None:
    if path is None or not delete_local_files_after_persist_enabled():
        return
    normalized = str(path).strip()
    if not normalized or "://" in normalized:
        return
    target = Path(normalized)
    try:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
    except FileNotFoundError:
        return


def _archive_output_dir(project_id: str, task_id: str, stage_name: str, source_root: Path) -> list[str]:
    """同步版本，由 asyncio.to_thread 调用。"""
    if delete_local_files_after_persist_enabled():
        return []
    archive_root = _project_task_output_dir(project_id, task_id, stage_name)
    archive_root.mkdir(parents=True, exist_ok=True)
    archived_files: list[str] = []
    for path in sorted(candidate for candidate in source_root.rglob("*") if candidate.is_file()):
        relative_name = path.relative_to(source_root).as_posix()
        destination = archive_root / relative_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        archived_files.append(relative_name)
    return archived_files
    return archived_files


def _archive_output_files(
    project_id: str,
    task_id: str,
    stage_name: str,
    files: list[dict[str, Any]],
) -> list[str]:
    if delete_local_files_after_persist_enabled():
        return []
    archive_root = _project_task_output_dir(project_id, task_id, stage_name)
    archive_root.mkdir(parents=True, exist_ok=True)
    archived_files: list[str] = []
    for file in files:
        file_name = str(file.get("filePath") or file.get("fileName") or "").strip()
        if not file_name:
            continue
        destination = archive_root / file_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(str(file.get("content") or ""), encoding="utf-8")
        archived_files.append(file_name)
    return archived_files


def _read_agent_output_content(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def _mapped_artifact_types(source_files_by_artifact: dict[str, Any], file_name: str) -> list[str]:
    normalized = _artifact_file_identity(file_name)
    mapped: list[str] = []
    for artifact_type, source_files in source_files_by_artifact.items():
        if not isinstance(source_files, list):
            continue
        if normalized in {_artifact_file_identity(str(item)) for item in source_files}:
            mapped.append(str(artifact_type))
    return mapped


def _requirements_stage_output_contract() -> dict[str, list[dict[str, Any]]]:
    return build_main_panel_contract(
        requirements_mode="analysis",
        include_architecture=False,
        include_ui_agent_outputs=False,
    )


def _full_output_contract() -> dict[str, list[dict[str, Any]]]:
    return build_main_panel_contract(
        requirements_mode="full",
        include_architecture=True,
        include_ui_agent_outputs=False,
    )


def _requirements_mode_for_planned_files(active_phase: str | None) -> str:
    analysis_phases = {
        "",
        "queued",
        "reading_context",
        "requirements_analysis",
        "modules_ready",
        "waiting_for_module_confirmation",
    }
    return "analysis" if (active_phase or "") in analysis_phases else "full"


def _current_planned_stage(output_data: dict[str, Any]) -> str | None:
    """
    把当前任务的 activePhase 折叠成 planned files 用的阶段名。

    注意 `requirements_feedback_required` 本身只说明“正在等人给反馈”，
    真正应该算哪个阶段，要看 `returnPhase`。
    """

    active_phase = str(output_data.get("activePhase") or "").strip()
    if active_phase == "requirements_feedback_required":
        active_phase = str(output_data.get("returnPhase") or "").strip()

    if active_phase in {"", "queued", "reading_context", "requirements_analysis", "modules_ready", "waiting_for_module_confirmation"}:
        return "requirements_analysis"
    if active_phase in {"requirements_drafts_started", "waiting_for_requirements_artifact_review", "modification_started"}:
        return "requirements_full"
    if active_phase in {"architecture_generation_started", "waiting_for_artifact_review"}:
        return "architecture"
    if active_phase.startswith("code_generation"):
        return "code"
    if active_phase.startswith("ui_generation"):
        return "ui"
    if active_phase.startswith("test_generation"):
        return "test"
    return None


def _planned_file_status(
    *,
    task_status: str,
    current_stage: str | None,
    planned_stage: str,
    completed: bool,
) -> str:
    if completed:
        return "completed"

    if current_stage is not None:
        current_order = _PLANNED_STAGE_ORDER.get(current_stage, 0)
        planned_order = _PLANNED_STAGE_ORDER.get(planned_stage, 0)
        if current_order > planned_order:
            return "failed"

    if task_status == "failed" and current_stage == planned_stage:
        return "failed"

    if task_status in {"running", "waiting_user"} and current_stage == planned_stage:
        return "running"

    if task_status not in {"running", "waiting_user", "failed"}:
        return "pending"
    return "pending"


async def build_planned_artifact_files_for_task(project_id: str, task) -> dict[str, list[PlannedArtifactFile]]:
    """
    接口注释：
    把“预期应该出现的文件”和“当前已经注册的原始文件”合并成一个稳定结构。

    这样前端即使在文件还没生成出来之前，也能先把待生成项渲染出来。

    这里有一个非常重要的边界：
    - 主面板该显示哪些文件，由 `build_main_panel_contract(...)` 决定
    - 这里负责的是“把那份合同转成当前任务的状态”

    也就是说，这里不能自行扩充主面板文件范围。
    如果某个文件不在主合同里，即使它已经被 Agent 产出了，
    也不应该在这里临时塞回主面板。
    """

    output_data = task.outputData if isinstance(task.outputData, dict) else {}
    active_phase = str(output_data.get("activePhase") or "")
    current_stage = _current_planned_stage(output_data)
    requirements_mode = _requirements_mode_for_planned_files(active_phase)
    explicit_version = output_data.get("pendingAgentArtifactsVersion")
    if isinstance(explicit_version, int) and explicit_version >= 1:
        live_version = explicit_version
    else:
        project = await store.get_project(project_id)
        live_version = project.currentVersion if project is not None else None

    registered = await store.list_agent_artifacts(project_id, version=live_version) if live_version is not None else []
    registered_lookup = {
        (artifact.agent, _artifact_file_identity(artifact.fileName)): artifact
        for artifact in registered
    }
    registered_agents = {artifact.agent for artifact in registered}

    panel_contract = build_main_panel_contract(
        requirements_mode=requirements_mode,  # type: ignore[arg-type]
        include_architecture=requirements_mode == "full" or "architecture_agent" in registered_agents,
        include_ui_agent_outputs=("ui_agent" in registered_agents or str(output_data.get("activeAgent") or "") == "ui_agent"),
    )
    # 设计注释：
    # 主面板文件名单必须完全来自这份后端合同。
    # 这样前端、测试、运行时状态三边才会一直对齐。

    planned: dict[str, list[PlannedArtifactFile]] = {}
    for artifact_type, items in panel_contract.items():
        planned[artifact_type] = []
        for item in items:
            normalized_name = _artifact_file_identity(item["fileName"])
            matched = registered_lookup.get((item["agent"], normalized_name))
            planned[artifact_type].append(
                PlannedArtifactFile(
                    fileName=item["fileName"],
                    label=item["label"],
                    agent=item["agent"],
                    mappedArtifactTypes=list(item.get("mappedArtifactTypes") or [artifact_type]),
                    status=_planned_file_status(
                        task_status=str(task.status),
                        current_stage=current_stage,
                        planned_stage=str(item.get("stage") or ""),
                        completed=matched is not None,
                    ),
                    contentAvailable=bool(matched is not None and matched.content is not None),
                )
            )
    return planned


def _filter_seeded_output_files(output_files: list[str], *, seeded_files: list[str] | None = None) -> list[str]:
    seeded_identities = {
        _artifact_file_identity(str(file_name))
        for file_name in (seeded_files or [])
        if str(file_name).strip()
    }
    if not seeded_identities:
        return list(output_files)
    return [
        file_name
        for file_name in output_files
        if _artifact_file_identity(file_name) not in seeded_identities
    ]


def _filter_visible_output_files_for_phase(phase: str, output_files: list[str]) -> list[str]:
    """
    只保留当前阶段应该对用户可见的文件。

    需求分析阶段是个特殊点：
    Requirements Agent 真实运行时，偶尔会顺手吐出一些 fallback 草稿文件，
    但平台合同里这个阶段只认 `feature_tree.md`。
    所以这里必须过滤掉那些“真实写盘了，但当前阶段不该展示”的文件，
    保证左侧步骤输出和右侧主面板永远对齐。
    """

    allowed_files: list[str] | None = None
    if phase == "requirements_analysis":
        allowed_files = planned_requirements_analysis_files()
    elif phase in {"architecture_generation_started", "waiting_for_artifact_review"}:
        allowed_files = planned_architecture_files()
    elif phase.startswith("ui_generation"):
        allowed_files = planned_ui_files()
    elif phase.startswith("test_generation"):
        # 教学注释：
        # test 阶段的文件名会带动态的数据集前缀，这里暂时不做硬过滤。
        # 否则像 `build-a-snake-game_test_plan.md` 这类真实输出会被误删。
        allowed_files = None

    if allowed_files is None:
        return list(output_files)

    allowed = {
        _artifact_file_identity(file_name)
        for file_name in allowed_files
    }
    return [
        file_name
        for file_name in output_files
        if _artifact_file_identity(file_name) in allowed
    ]


def _is_user_facing_primary_output_file(file_name: str) -> bool:
    """
    只保留适合直接提示给用户阅读的主文件。

    设计注释：
    像 `*_modify.md` 这种文件只是“这次修改影响了什么”的辅助说明，
    `.pkl` 这类序列化文件也不适合让用户直接查看。
    这里单独抽一层，保证所有“请先看哪个文件”的提示都走同一套规则。
    """

    normalized = str(file_name or "").strip().lower()
    if not normalized:
        return False
    if normalized.endswith(".pkl"):
        return False
    if "_modify." in normalized:
        return False
    return normalized.endswith((".md", ".markdown", ".txt", ".json"))


def _user_facing_primary_output_files(output_files: list[str]) -> list[str]:
    filtered = [
        str(file_name).strip()
        for file_name in output_files
        if _is_user_facing_primary_output_file(str(file_name))
    ]
    return filtered or [str(file_name).strip() for file_name in output_files if str(file_name).strip()]


def _localized_file_list(locale: Locale, file_names: list[str], *, max_items: int = 3) -> str:
    visible = [str(file_name).strip() for file_name in file_names if str(file_name).strip()][:max_items]
    if not visible:
        return ""
    if len(visible) == 1:
        return visible[0]
    if normalize_locale(locale) == "zh":
        return "、".join(visible)
    return ", ".join(visible[:-1]) + f" and {visible[-1]}"


def _latest_visible_output_file_in_dir(*, phase: str, output_dir: Path) -> str | None:
    """
    从真实输出目录里找“当前阶段对用户可见”的最近文件。

    设计注释：
    架构 Agent 会产出很多中间文件，比如 `modeling-6.*`、`component_parser_output.txt`。
    这些文件对排查有用，但不应该直接拿去驱动主进度文案。
    否则界面会出现“最近文件是 modeling-6，但当前动作还卡在 analysis_task_output”的错位。
    这里专门补一层可见文件筛选，让进度文案优先跟用户真正看得到的文件走。
    """

    if not output_dir.exists() or not output_dir.is_dir():
        return None

    visible_files = _filter_visible_output_files_for_phase(
        phase,
        [
            path.relative_to(output_dir).as_posix()
            for path in output_dir.rglob("*")
            if path.is_file()
        ],
    )
    if not visible_files:
        return None

    latest_file = max(
        visible_files,
        key=lambda file_name: (output_dir / file_name).stat().st_mtime,
    )
    return latest_file


def _scan_and_read_output_files(
    output_root: Path,
    source_mapping: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """同步扫描目录并读取所有输出文件内容。由 asyncio.to_thread 调用，不阻塞 event loop。"""
    payloads: list[dict[str, Any]] = []
    output_files: list[str] = []
    for path in sorted(candidate for candidate in output_root.rglob("*") if candidate.is_file()):
        relative_name = path.relative_to(output_root).as_posix()
        file_type, content_type = _artifact_file_meta(relative_name)
        mapped_artifact_types = _mapped_artifact_types(source_mapping, relative_name)
        payloads.append(
            {
                "fileName": relative_name,
                "fileType": file_type,
                "contentType": content_type,
                "content": _read_agent_output_content(path),
                "isPrimarySource": bool(mapped_artifact_types),
                "mappedArtifactTypes": mapped_artifact_types,
            }
        )
        output_files.append(relative_name)
    return payloads, output_files


async def _register_agent_output_dir(
    project_id: str,
    task_id: str,
    *,
    version: int,
    agent_name: str,
    archive_stage: str | None = None,
    output_dir: str | None,
    source_files_by_artifact: dict[str, Any] | None = None,
) -> list[str]:
    if not output_dir:
        return []
    output_root = Path(output_dir)
    if not output_root.exists() or not output_root.is_dir():
        return []
    source_mapping = source_files_by_artifact if isinstance(source_files_by_artifact, dict) else {}
    # 文件扫描+读取放到线程池，不阻塞 event loop
    payloads, output_files = await asyncio.to_thread(_scan_and_read_output_files, output_root, source_mapping)
    await store.register_agent_artifacts(
        project_id,
        version=version,
        task_id=task_id,
        agent_name=agent_name,
        artifacts=payloads,
    )
    if archive_stage:
        await asyncio.to_thread(_archive_output_dir, project_id, task_id, archive_stage, output_root)
    return output_files


async def _register_coding_agent_outputs(
    project_id: str,
    task_id: str,
    *,
    version: int,
    archive_stage: str | None = None,
    files: list[dict[str, Any]],
) -> list[str]:
    return await _register_workspace_agent_outputs(
        project_id,
        task_id,
        version=version,
        agent_name="coding_agent",
        archive_stage=archive_stage,
        files=files,
    )


async def _register_workspace_agent_outputs(
    project_id: str,
    task_id: str,
    *,
    version: int,
    agent_name: str,
    archive_stage: str | None = None,
    files: list[dict[str, Any]],
) -> list[str]:
    payloads: list[dict[str, Any]] = []
    output_files: list[str] = []
    for file in files:
        file_name = str(file.get("filePath") or "").strip()
        if not file_name:
            continue
        file_type, content_type = _artifact_file_meta(file_name)
        payloads.append(
            {
                "fileName": file_name,
                "fileType": file_type,
                "contentType": content_type,
                "content": str(file.get("content") or ""),
                "isPrimarySource": False,
                "mappedArtifactTypes": [],
            }
        )
        output_files.append(file_name)
    await store.register_agent_artifacts(
        project_id,
        version=version,
        task_id=task_id,
        agent_name=agent_name,
        artifacts=payloads,
    )
    if archive_stage:
        _archive_output_files(project_id, task_id, archive_stage, files)
    return output_files


def _merge_workspace_files(*file_sets: list[dict[str, Any]]) -> list[dict[str, str]]:
    """
    合并工作区文件快照。

    规则很直接：
    - 先放旧文件
    - 后来的同路径文件覆盖前面的内容
    - 不做“兼容修补”，只按真实 Agent 结果覆盖
    """

    merged: dict[str, str] = {}
    for files in file_sets:
        for file in files:
            file_path = str(file.get("filePath") or "").strip()
            if not file_path:
                continue
            merged[file_path] = str(file.get("content") or "")
    return [{"filePath": file_path, "content": content} for file_path, content in merged.items()]


async def _copy_agent_artifacts_to_version(
    project_id: str,
    *,
    source_version: int,
    target_version: int,
    task_id: str,
    agent_name: str,
) -> list[str]:
    copied = await store.list_agent_artifacts(project_id, version=source_version, agent_name=agent_name)
    if not copied:
        return []
    await store.register_agent_artifacts(
        project_id,
        version=target_version,
        task_id=task_id,
        agent_name=agent_name,
        artifacts=[
            {
                "fileName": artifact.fileName,
                "fileType": artifact.fileType,
                "contentType": artifact.contentType,
                "content": artifact.content,
                "isPrimarySource": artifact.isPrimarySource,
                "mappedArtifactTypes": list(artifact.mappedArtifactTypes),
            }
            for artifact in copied
        ],
    )
    return [artifact.fileName for artifact in copied]


async def _register_live_agent_output_dir(
    project_id: str,
    task_id: str,
    *,
    version: int,
    agent_name: str,
    archive_stage: str | None = None,
    output_dir: str | None,
    source_files_by_artifact: dict[str, Any] | None = None,
) -> list[str]:
    output_files = await _register_agent_output_dir(
        project_id,
        task_id,
        version=version,
        agent_name=agent_name,
        archive_stage=archive_stage,
        output_dir=output_dir,
        source_files_by_artifact=source_files_by_artifact,
    )
    if output_files:
        await _broadcast(
            project_id,
            "artifact_update",
            {
                "action": "raw_output_registered",
                "agentName": agent_name,
                "version": version,
                "outputFiles": output_files,
            },
        )
    return output_files


async def _merge_task_output(task_id: str, **updates: Any) -> dict[str, Any]:
    output_data = await _task_output_data(task_id)
    output_data.update({key: value for key, value in updates.items() if value is not None})
    return output_data


async def _pending_preview_version(project_id: str, task_id: str) -> int:
    """
    接口注释：
    返回当前任务应该继续写入的“预览版本号”。

    设计注释：
    需求阶段和架构阶段现在都不再提前提交正式版本，
    所以这里要优先复用任务里已经记住的预览版本号。
    只有当前任务还没有预览版本时，才回退到“正式版本号 + 1”。
    """

    output_data = await _task_output_data(task_id)
    explicit_version = output_data.get("pendingAgentArtifactsVersion")
    project = await store.get_project(project_id)
    current_version = project.currentVersion if project is not None else 1
    if isinstance(explicit_version, int) and explicit_version > current_version:
        return explicit_version
    return current_version + 1


async def _list_agent_artifact_files(
    project_id: str,
    *,
    version: int,
    agent_name: str,
) -> list[str]:
    return [
        artifact.fileName
        for artifact in await store.list_agent_artifacts(project_id, version=version, agent_name=agent_name)
    ]


async def _promote_pending_preview_to_current_version(project_id: str, task_id: str) -> tuple[int, int]:
    """
    接口注释：
    在真正开始生成代码工作区前，把挂起预览版本提升成新的正式版本号。

    教学注释：
    前面的需求、架构阶段只往“预览版本”里写原始文件，不推进项目正式版本。
    等用户确认要开始代码生成时，才把正式版本从 V1 推到 V2。
    这样用户在架构审查前一直看到的都还是旧正式版本。
    """

    project = await store.get_project(project_id)
    if project is None:
        return (1, 1)

    previous_version = project.currentVersion
    preview_version = await _pending_preview_version(project_id, task_id)
    if preview_version <= previous_version:
        return (previous_version, previous_version)

    # 教学注释：
    # 升级正式版本号之前，先把上一版已经确认的主制品和工作区文件复制到新版本。
    # 这样代码生成阶段是在完整上下文上继续叠加，而不是从一个只有预览原始文件的空版本开始。
    previous_artifacts = await store.list_artifacts_for_version(project_id, previous_version)
    previous_code_files = [
        {
            "filePath": code_file.filePath,
            "content": code_file.content,
        }
        for code_file in await store.list_code_files(project_id, version=previous_version)
        if code_file.version == previous_version
    ]

    while True:
        refreshed = await store.get_project(project_id)
        if refreshed is None or refreshed.currentVersion >= preview_version:
            break
        await store.bump_project_version(project_id)

    promoted_project = await store.get_project(project_id)
    if promoted_project is None:
        return (previous_version, previous_version)

    for artifact in previous_artifacts:
        await store.upsert_artifact(
            project_id,
            artifact.type,  # type: ignore[arg-type]
            artifact.title,
            artifact.content,
            metadata=artifact.metadata,
        )
    await store.replace_code_files(project_id, promoted_project.currentVersion, previous_code_files)
    await store.update_task(
        task_id,
        output_data=await _merge_task_output(
            task_id,
            codeGenerationSourceVersion=previous_version,
        ),
    )
    return (previous_version, promoted_project.currentVersion)


async def _record_pending_agent_artifacts_version(
    project_id: str,
    task_id: str,
    *,
    pending_version: int,
    active_phase: str,
    active_agent: str,
) -> dict[str, Any]:
    output_data = await _merge_task_output(
        task_id,
        pendingAgentArtifactsVersion=pending_version,
        activePhase=active_phase,
        activeAgent=active_agent,
        agentOutputsReady=sorted(
            {
                artifact.agent
                for artifact in await store.list_agent_artifacts(project_id, version=pending_version)
            }
        ),
    )
    current_task = await store.get_task(task_id)
    next_status = "running"
    if current_task is not None and current_task.status != "running":
        # 设计注释：这里只是在补记“当前已经能看到哪些 Agent 产物”，
        # 不是流程状态切换点，所以不能把 waiting_user、completed、failed 这类真实状态冲掉。
        # 之前这里强制改成 running，会把需求反馈等待态悄悄覆盖掉，前端点提交时就会看到
        # “confirmationKind 还是 requirements_feedback，但 task.status 已经变成 running”的错乱状态。
        next_status = current_task.status
    await store.update_task(task_id, status=next_status, output_data=output_data)
    return output_data


async def _broadcast(project_id: str, event_type: str, data: dict[str, Any]) -> None:
    """
    Fire-and-forget 广播：把 WebSocket 消息发射出去，不等待完成。

    之前所有 await _broadcast(...) 都会等 ws_manager 把消息逐个推送给
    每个浏览器标签页（每个最多等 1 秒超时），导致工作流 coroutine 被拖慢，
    event loop 排满广播任务后 HTTP 请求无法及时处理。
    改成 create_task 后，广播在后台执行，工作流和 HTTP 互不阻塞。
    """
    logger.debug(
        "Workflow broadcast: project_id=%s event_type=%s task_id=%s phase=%s agent_name=%s",
        project_id,
        event_type,
        data.get("taskId"),
        data.get("phase"),
        data.get("agentName"),
    )
    asyncio.create_task(_do_broadcast(project_id, event_type, data))


async def _do_broadcast(project_id: str, event_type: str, data: dict[str, Any]) -> None:
    try:
        await ws_manager.broadcast(project_id, _event(event_type, data))
    except Exception:
        logger.warning("Background broadcast failed: project_id=%s event_type=%s", project_id, event_type, exc_info=True)


async def _task_locale(task_id: str, fallback: Any = None) -> Locale:
    task = await store.get_task(task_id)
    if task is None:
        return normalize_locale(fallback)
    return normalize_locale(task.inputData.get("locale") if isinstance(task.inputData, dict) else fallback)


def _progress_event_id(task_id: str, phase: str, status: str, *, artifact_type: str | None = None) -> str:
    suffix = f":{artifact_type}" if artifact_type else ""
    return f"{task_id}:{phase}:{status}{suffix}"


async def _broadcast_progress(
    project_id: str,
    task_id: str,
    *,
    phase: str,
    status: str,
    progress: int | None = None,
    artifact_type: str | None = None,
    agent_name: str | None = None,
    module_count: int | None = None,
    reference_count: int | None = None,
    confirmation_kind: str | None = None,
    error_type: str | None = None,
    message: str | None = None,
    output_hint: str | None = None,
    raw_file_name: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "id": _progress_event_id(task_id, phase, status, artifact_type=artifact_type),
        "taskId": task_id,
        "phase": phase,
        "status": status,
        "createdAt": utc_now().isoformat(),
        "agentName": agent_name or _phase_agent_name(phase, artifact_type),
    }
    if progress is not None:
        payload["progress"] = progress
    if artifact_type:
        payload["artifactType"] = artifact_type
    if module_count is not None:
        payload["moduleCount"] = module_count
    if reference_count is not None:
        payload["referenceCount"] = reference_count
    if confirmation_kind:
        payload["confirmationKind"] = confirmation_kind
    if error_type:
        payload["errorType"] = error_type
    if message:
        payload["message"] = message
    if output_hint:
        payload["outputHint"] = output_hint
    if raw_file_name:
        payload["rawFileName"] = raw_file_name
    await _broadcast(project_id, "agent_progress", payload)


async def _run_with_progress_heartbeat(
    project_id: str,
    task_id: str,
    *,
    phase: str,
    initial_progress: int,
    progress_cap: int,
    progress_step: int,
    operation: Awaitable[Any],
    artifact_type: str | None = None,
    agent_name: str | None = None,
    module_count: int | None = None,
    reference_count: int | None = None,
    confirmation_kind: str | None = None,
    error_type: str | None = None,
    message: str | None = None,
    output_hint: str | None = None,
    raw_file_name: str | None = None,
) -> Any:
    stop_event = asyncio.Event()
    current_progress = initial_progress

    async def heartbeat() -> None:
        nonlocal current_progress
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=_PROGRESS_HEARTBEAT_INTERVAL_SECONDS)
                return
            except asyncio.TimeoutError:
                next_progress = min(progress_cap, current_progress + progress_step)
                if next_progress == current_progress:
                    continue
                current_progress = next_progress
                await _broadcast_progress(
                    project_id,
                    task_id,
                    phase=phase,
                    status="running",
                    progress=current_progress,
                    artifact_type=artifact_type,
                    agent_name=agent_name,
                    module_count=module_count,
                    reference_count=reference_count,
                    confirmation_kind=confirmation_kind,
                    error_type=error_type,
                    message=message,
                    output_hint=output_hint,
                    raw_file_name=raw_file_name,
                )

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        return await operation
    finally:
        stop_event.set()
        await heartbeat_task


async def _append_message(message: Message) -> Message:
    record = await store.add_message(message)
    await _broadcast(
        message.projectId,
        "message",
        record.model_dump(mode="json"),
    )
    return record


def _task_log_event_payload(message: Message) -> dict[str, Any]:
    metadata = dict(message.metadata or {})
    return {
        "taskId": metadata.get("taskId"),
        "logId": message.id,
        "timestamp": message.createdAt.isoformat(),
        "phase": metadata.get("phase"),
        "label": metadata.get("taskName"),
        "statusText": message.content,
        "state": metadata.get("status"),
    }


async def _update_message(
    message: Message,
    *,
    content: str | None = None,
    metadata: dict[str, Any] | None = None,
    parent_id: str | None = None,
) -> Message:
    record = await store.update_message(
        message.id,
        content=content,
        metadata=metadata,
        parent_id=parent_id,
    )
    await _broadcast(
        message.projectId,
        "message_update",
        record.model_dump(mode="json"),
    )
    if record.type == "process_log":
        await _broadcast(
            message.projectId,
            "task_log_updated",
            _task_log_event_payload(record),
        )
    return record


def _task_message_metadata(
    task_id: str,
    *,
    phase: str | None = None,
    task_name: str | None = None,
    status: str | None = None,
    task_round_role: str | None = None,
    task_status: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "taskId": task_id,
    }
    if phase:
        metadata["phase"] = phase
    if task_name:
        metadata["taskName"] = task_name
    if status:
        metadata["status"] = status
    if task_round_role:
        metadata["taskRoundRole"] = task_round_role
    if task_status:
        metadata["taskStatus"] = task_status
    return metadata


def _merge_process_log_output_metadata(
    metadata: dict[str, Any] | None,
    *,
    phase: str | None = None,
    source_agent: str | None = None,
    raw_file_name: str | None = None,
    output_files: list[str] | None = None,
) -> dict[str, Any]:
    next_metadata = dict(metadata or {})
    if source_agent:
        next_metadata["sourceAgent"] = source_agent
    normalized_files: list[str] = []
    seen: set[str] = set()
    existing_files = next_metadata.get("outputFiles")
    if isinstance(existing_files, list):
        for item in existing_files:
            value = _normalize_output_file_for_phase(phase, str(item).strip())
            if not value:
                continue
            identity = _artifact_file_identity(value)
            if identity in seen:
                continue
            seen.add(identity)
            normalized_files.append(value)
    for candidate in [*(output_files or []), *( [raw_file_name] if raw_file_name else [] )]:
        value = _normalize_output_file_for_phase(phase, str(candidate).strip())
        if not value:
            continue
        identity = _artifact_file_identity(value)
        if identity in seen:
            continue
        seen.add(identity)
        normalized_files.append(value)
    if normalized_files:
        next_metadata["outputFiles"] = normalized_files
        next_metadata["rawFileName"] = normalized_files[-1]
    return next_metadata


def _normalize_output_file_for_phase(phase: str | None, file_name: str) -> str:
    normalized = str(file_name or "").strip().replace("\\", "/")
    if not normalized:
        return ""

    if phase == "code_generation_started":
        for marker in ("/generated/", "generated/"):
            if marker in normalized:
                normalized = normalized.split(marker, 1)[1]
                break
        normalized = normalized.lstrip("./")

    return normalized


def _merge_process_log_runtime_metadata(
    metadata: dict[str, Any] | None,
    *,
    runtime_event: dict[str, Any],
) -> dict[str, Any]:
    """
    把运行中子进程的监控信息附着到 process_log metadata。

    接口注释：
    这里不改变任务状态，只补充“进程还活着吗、多久没有新输出了、最新写到哪个文件了”。
    前端可以直接用这些字段告诉用户：当前是还在运行，还是已经长时间没有真实动静。
    """

    next_metadata = dict(metadata or {})
    for key in (
        "runtimePid",
        "runtimeState",
        "startedAt",
        "lastHeartbeatAt",
        "lastOutputAt",
        "latestOutputAt",
        "latestOutputFile",
        "outputDir",
        "outputFileCount",
        "stdoutLineCount",
        "stderrLineCount",
        "secondsSinceLastOutput",
        "elapsedSeconds",
    ):
        value = runtime_event.get(key)
        if value is not None:
            next_metadata[key] = value
    return next_metadata



def _list_relative_output_files(output_dir: Path) -> list[str]:
    """
    接口注释：
    列出某个 Agent 输出目录中的全部文件，并返回相对路径列表。

    设计注释：
    目录扫描在架构、需求、UI 等阶段会非常频繁地被 runtime callback 调用。
    这个动作本身是纯文件系统 IO，不应该占着事件循环做。
    所以上层会把它放进 `asyncio.to_thread(...)`，避免 Agent 一边刷文件，一边把 API 拖慢。
    """

    if not output_dir.exists() or not output_dir.is_dir():
        return []
    return [
        path.relative_to(output_dir).as_posix()
        for path in sorted(candidate for candidate in output_dir.rglob("*") if candidate.is_file())
    ]


async def _append_process_log(
    project_id: str,
    task_id: str,
    *,
    phase: str,
    task_name: str,
    content: str,
    status: str = "running",
    parent_id: str | None = None,
) -> Message:
    record = await _append_message(
        Message(
            projectId=project_id,
            role="agent",
            type="process_log",
            content=content,
            metadata=_task_message_metadata(
                task_id,
                phase=phase,
                task_name=task_name,
                status=status,
            ),
            parentId=parent_id,
        )
    )
    await _broadcast(
        project_id,
        "task_log_started",
        _task_log_event_payload(record),
    )
    return record


async def _complete_process_log(
    message: Message,
    *,
    content: str | None = None,
    duration: float | None = None,
    status: str = "completed",
) -> Message:
    next_metadata = dict(message.metadata or {})
    next_metadata["status"] = status
    if duration is not None:
        next_metadata["duration"] = _duration_label(duration)
    record = await _update_message(
        message,
        content=content or message.content,
        metadata=next_metadata,
    )
    await _broadcast(
        message.projectId,
        "task_log_completed",
        _task_log_event_payload(record),
    )
    return record


async def _update_latest_task_phase_process_log(
    project_id: str,
    task_id: str,
    *,
    phase: str,
    content: str,
    clear_raw_file_name: bool = False,
) -> Message | None:
    """
    更新当前任务在某个阶段里的最后一条 process_log。

    接口注释：
    这个辅助函数只负责修正“当前阶段正在显示什么状态文案”，
    不改变任务主状态，也不改这条日志已经累计过的输出文件列表。

    设计注释：
    Requirements Agent 会在同一个阶段里多次停下来等待人工反馈。
    如果我们不主动覆盖最后一条日志内容，界面就会一直挂着上一条
    “正在生成 xxx.md”，哪怕 Agent 其实已经进入等待确认或已经恢复继续运行。
    """

    # 设计注释：
    # 这里会在 Requirements Agent 持续刷状态时被频繁调用。
    # 如果直接在事件循环里同步扫消息表，普通 HTTP 请求也会跟着排队。
    # 所以消息列表读取统一走 await store 异步调用。
    messages, _ = await store.list_messages(project_id, 1, 500)
    for message in reversed(messages):
        if message.type != "process_log":
            continue
        metadata = message.metadata if isinstance(message.metadata, dict) else {}
        if metadata.get("taskId") != task_id:
            continue
        if metadata.get("phase") != phase:
            continue

        next_metadata = dict(metadata)
        if clear_raw_file_name:
            next_metadata.pop("rawFileName", None)
        return await _update_message(
            message,
            content=content,
            metadata=next_metadata,
        )
    return None


def _extract_output_file_from_status(status_text: str, *, agent_name: str | None = None) -> str | None:
    normalized = " ".join(str(status_text).split()).strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    allow_requirements_hints = agent_name in {None, "", "requirements_agent"}

    if allow_requirements_hints:
        crew_match = re.search(r"\[([A-Za-z0-9_]+)\]\s+Attempt\s+\d+/\d+", normalized)
        if crew_match:
            return _REQUIREMENTS_AGENT_OUTPUT_FILES.get(crew_match.group(1))

        for prefix, file_name in _REQUIREMENTS_AGENT_PREFIX_FILE_HINTS:
            if normalized.startswith(prefix):
                return file_name

    if not any(action_hint in lowered for action_hint in _STRUCTURED_PROGRESS_ACTION_HINTS):
        return None

    explicit_file_match = re.search(
        r"([A-Za-z0-9_./-]+\.(?:md|markdown|txt|json|yaml|yml|html|htm|ts|tsx|js|jsx|py|css|svg))",
        normalized,
        flags=re.IGNORECASE,
    )
    if explicit_file_match:
        candidate = explicit_file_match.group(1)
        candidate_name = Path(candidate).name.lower()
        if candidate_name in _STRUCTURED_PROGRESS_FILE_ALLOWLIST or "/" in candidate or "\\" in candidate:
            return candidate

    if allow_requirements_hints:
        for keyword, file_name in _REQUIREMENTS_AGENT_KEYWORD_FILE_HINTS:
            if keyword in lowered:
                return file_name
    return None


def _extract_structured_progress_step_label(status_text: str) -> str | None:
    normalized = " ".join(str(status_text).split()).strip()
    if not normalized:
        return None
    match = re.match(r"^(SRS Chapter planning \d+|SRS Chapter \d+|BRDev Chapter \d+)\b", normalized)
    if match:
        return match.group(1)
    return None


def _localized_progress_step_label(step_label: str, *, locale: Locale) -> str:
    normalized = " ".join(str(step_label).split()).strip()
    if locale != "zh":
        return normalized

    planning_match = re.match(r"^SRS Chapter planning (\d+)$", normalized)
    if planning_match:
        return f"SRS 第 {planning_match.group(1)} 章规划"

    srs_match = re.match(r"^SRS Chapter (\d+)$", normalized)
    if srs_match:
        return f"SRS 第 {srs_match.group(1)} 章"

    brd_match = re.match(r"^BRDev Chapter (\d+)$", normalized)
    if brd_match:
        return f"BRD 第 {brd_match.group(1)} 章"

    return normalized


def _format_structured_file_status(
    *,
    locale: Locale,
    file_name: str,
    step_label: str | None,
    completed: bool,
) -> str:
    if not step_label:
        key = "status.generated_file" if completed else "status.generating_file"
        return t(locale, key, file_name=file_name)

    localized_step = _localized_progress_step_label(step_label, locale=locale)
    if locale == "zh":
        verb = "已生成" if completed else "正在生成"
        return f"{verb}{localized_step}（{file_name}）。"

    verb = "Generated" if completed else "Generating"
    return f"{verb} {localized_step} ({file_name})."


def _structured_status_update(status_text: str, *, locale: Locale) -> dict[str, str] | None:
    normalized = " ".join(str(status_text).split()).strip()
    if not normalized:
        return None

    agent_name = "orchestrator"
    body = normalized
    for candidate_prefix, candidate_agent in (
        ("Requirements Agent:", "requirements_agent"),
        ("Architecture Agent:", "architecture_agent"),
        ("Coding Agent:", "coding_agent"),
        ("Test Agent:", "test_agent"),
    ):
        if body.startswith(candidate_prefix):
            agent_name = candidate_agent
            body = body[len(candidate_prefix) :].strip()
            break

    file_name = _extract_output_file_from_status(body, agent_name=agent_name)
    if not file_name:
        return None
    step_label = _extract_structured_progress_step_label(body)

    return {
        "agentName": agent_name,
        "displayText": _format_structured_file_status(
            locale=locale,
            file_name=file_name,
            step_label=step_label,
            completed=False,
        ),
        "outputHint": file_name,
        "rawFileName": file_name,
        "dedupeIdentity": f"{_artifact_file_identity(file_name)}::{step_label}" if step_label else _artifact_file_identity(file_name),
    }


def _strip_agent_prefix(status_text: str) -> tuple[str, str]:
    normalized = " ".join(str(status_text).split()).strip()
    if not normalized:
        return "orchestrator", ""
    for candidate_prefix, candidate_agent in (
        ("Requirements Agent:", "requirements_agent"),
        ("Architecture Agent:", "architecture_agent"),
        ("Coding Agent:", "coding_agent"),
        ("Test Agent:", "test_agent"),
    ):
        if normalized.startswith(candidate_prefix):
            return candidate_agent, normalized[len(candidate_prefix) :].strip()
    return "orchestrator", normalized


def _success_status_update(
    status_text: str,
    *,
    locale: Locale,
    current_file_name: str | None,
    agent_name: str | None,
) -> dict[str, str] | None:
    if not current_file_name:
        return None
    parsed_agent_name, body = _strip_agent_prefix(status_text)
    lowered = body.lower()
    if lowered not in {"success", "completed", "done", "ok"}:
        return None
    return {
        "agentName": agent_name or parsed_agent_name,
        "displayText": _format_structured_file_status(
            locale=locale,
            file_name=current_file_name,
            step_label=None,
            completed=True,
        ),
        "outputHint": current_file_name,
        "rawFileName": current_file_name,
        "dedupeIdentity": _artifact_file_identity(current_file_name),
    }


def _process_log_status_callback(
    message_ref: list[Message],
    *,
    project_id: str,
    task_id: str,
    phase: str,
    locale: Locale,
):
    last_emitted = {"content": message_ref[0].content}
    seen_files: set[str] = set(
        _artifact_file_identity(str(item))
        for item in ((message_ref[0].metadata or {}).get("outputFiles") or [])
        if str(item).strip()
    )
    current_file_name = {"value": None}
    current_agent_name = {"value": None}

    async def callback(status_text: str) -> None:
        structured = _structured_status_update(status_text, locale=locale)
        is_generating_update = structured is not None
        if structured is None:
            structured = _success_status_update(
                status_text,
                locale=locale,
                current_file_name=current_file_name["value"],
                agent_name=current_agent_name["value"],
            )
        if structured is not None and structured["rawFileName"]:
            # 这里先按当前阶段过滤一次“用户应该看到的文件”。
            # 这样 Requirements Agent 在 analysis 阶段顺手产出的 fallback 草稿，
            # 不会提前混进左侧步骤输出和进度广播里，避免和右侧主面板对不上。
            visible_files = _filter_visible_output_files_for_phase(phase, [structured["rawFileName"]])
            if not visible_files:
                return
            structured["outputHint"] = visible_files[-1]
            structured["rawFileName"] = visible_files[-1]
            current_file_name["value"] = structured["rawFileName"]
            current_agent_name["value"] = structured["agentName"]
            identity = str(structured.get("dedupeIdentity") or _artifact_file_identity(structured["rawFileName"]))
            is_duplicate_file = identity in seen_files and is_generating_update
            if is_duplicate_file:
                return
            seen_files.add(identity)
        cleaned = structured["displayText"] if structured is not None else ""
        if not cleaned or cleaned == last_emitted["content"]:
            return
        last_emitted["content"] = cleaned
        next_metadata = _merge_process_log_output_metadata(
            message_ref[0].metadata or None,
            phase=phase,
            source_agent=structured["agentName"] if structured is not None else None,
            raw_file_name=structured["rawFileName"] if structured is not None else None,
        )
        message_ref[0] = await _update_message(
            message_ref[0],
            content=cleaned,
            metadata=next_metadata,
        )
        if structured is not None:
            await _broadcast_progress(
                project_id,
                task_id,
                phase=phase,
                status="running",
                agent_name=structured["agentName"],
                output_hint=structured["outputHint"],
                raw_file_name=structured["rawFileName"],
            )

    return callback


async def _requirements_live_recovery_payload(
    project_id: str,
    task_id: str,
    *,
    pending_version: int,
    prompt: str,
    selected_modules: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]] | None:
    """
    从已经实时注册的 requirements 输出里重建 review 阶段需要的 payload。

    接口注释：
    这个恢复入口只在“关键文件已经落盘，但 Agent 调用迟迟不返回”的异常场景里使用。
    它不会猜测内容，而是严格从已经归档/注册过的真实文件恢复。
    """

    requirement_artifacts = await store.list_agent_artifacts(
        project_id,
        version=pending_version,
        agent_name="requirements_agent",
    )
    if not requirement_artifacts:
        return None

    payload = agent_orchestrator._requirements_agent_artifact_payload_from_files(
        {
            artifact.fileName: str(artifact.content or "").strip()
            for artifact in requirement_artifacts
            if isinstance(artifact.content, str)
        },
        prompt=prompt,
        selected_modules=selected_modules,
        output_dir="db://agent_artifacts/requirements_agent",
        status="recovered_live_output",
    )
    if payload is None:
        return None

    output_files = [artifact.fileName for artifact in requirement_artifacts]
    return payload, output_files


async def _architecture_live_recovery_payload(
    project_id: str,
    task_id: str,
    *,
    pending_version: int,
) -> tuple[dict[str, Any], list[str]] | None:
    """
    从已经注册进数据库的架构原始文件里重建架构草稿 payload。

    接口注释：
    这个恢复入口处理的是“架构关键文件都已经到位，但子进程迟迟不退出”的场景。
    它只读已经登记过的真实原始文件，不会凭空猜内容。
    """

    architecture_artifacts = await store.list_agent_artifacts(
        project_id,
        version=pending_version,
        agent_name="architecture_agent",
    )
    if not architecture_artifacts:
        return None

    payload = agent_orchestrator._architecture_agent_payload_from_files(
        {
            artifact.fileName: str(artifact.content or "").strip()
            for artifact in architecture_artifacts
            if isinstance(artifact.content, str)
        },
        output_dir="db://agent_artifacts/architecture_agent",
        status="recovered_live_output",
    )
    if payload is None:
        return None

    output_files = [artifact.fileName for artifact in architecture_artifacts]
    return payload, output_files


async def _await_requirements_drafts_or_recover_from_live_outputs(
    project_id: str,
    task_id: str,
    *,
    pending_version: int,
    prompt: str,
    selected_modules: list[dict[str, Any]],
    operation: Awaitable[dict[str, Any]],
) -> tuple[dict[str, Any], list[str] | None, bool]:
    """
    等待 Requirements Agent 返回；如果它卡住，但 live output 已经足够完整，就用真实落盘文件兜底恢复。

    设计注释：
    这次线上问题的关键点是：`SRS.md` 已经写出来了，说明需求阶段事实上完成了，
    但桥接调用没有返回，导致后面的“等待确认需求草稿”卡片永远不出现。
    这里把“文件已经齐了”提升为第二条完成信号，避免整条流程被单点返回卡死。
    """

    operation_task = asyncio.create_task(operation)
    loop = asyncio.get_running_loop()
    recovered_ready_at: float | None = None

    while True:
        try:
            payload = await asyncio.wait_for(
                asyncio.shield(operation_task),
                timeout=_LIVE_OUTPUT_RECOVERY_POLL_SECONDS,
            )
            return payload, None, False
        except asyncio.TimeoutError:
            if agent_orchestrator._requirements_prompt_session_is_waiting(task_id):
                recovered_ready_at = None
                continue

            recovered = await _requirements_live_recovery_payload(
                project_id,
                task_id,
                pending_version=pending_version,
                prompt=prompt,
                selected_modules=selected_modules,
            )
            if recovered is None:
                recovered_ready_at = None
                continue

            if recovered_ready_at is None:
                recovered_ready_at = loop.time()
                continue

            if (loop.time() - recovered_ready_at) < _LIVE_OUTPUT_RECOVERY_GRACE_SECONDS:
                continue

            logger.warning(
                "Requirements draft generation recovered from live outputs. project_id=%s task_id=%s pending_version=%s",
                project_id,
                task_id,
                pending_version,
            )
            operation_task.cancel()
            operation_task.add_done_callback(_silence_background_asyncio_task)
            # 设计注释：
            # Requirements / Architecture 的 registry 清理发生在 operation 自己的 finally 里。
            # 所以这里必须先把 operation_task 取消掉，再让事件循环跑一个切片，
            # 给 finally 里的 unregister 一个真正执行的机会。
            await asyncio.sleep(0)
            await _stop_running_task_before_stage_transition(
                task_id,
                stage_name="requirements live recovery handoff",
            )
            return recovered[0], recovered[1], True


async def _await_architecture_draft_or_recover_from_live_outputs(
    project_id: str,
    task_id: str,
    *,
    pending_version: int,
    operation: Awaitable[dict[str, Any]],
) -> tuple[dict[str, Any], list[str] | None, bool]:
    """
    等待架构 Agent 返回；如果关键文件已经齐了但调用迟迟不结束，就按真实文件恢复后续流程。

    设计注释：
    现在架构 Agent 的真实问题不是“没写出文件”，而是“文件都写完了，进程还不退”。
    平台如果继续只把“函数返回”当成唯一完成信号，就会让任务平白卡满一整小时。
    所以这里补上和 requirements 一样的第二完成信号：真实主文件已经进数据库。
    """

    operation_task = asyncio.create_task(operation)
    loop = asyncio.get_running_loop()
    recovered_ready_at: float | None = None

    while True:
        try:
            payload = await asyncio.wait_for(
                asyncio.shield(operation_task),
                timeout=_LIVE_OUTPUT_RECOVERY_POLL_SECONDS,
            )
            return payload, None, False
        except asyncio.TimeoutError:
            recovered = await _architecture_live_recovery_payload(
                project_id,
                task_id,
                pending_version=pending_version,
            )
            if recovered is None:
                recovered_ready_at = None
                continue

            if recovered_ready_at is None:
                recovered_ready_at = loop.time()
                continue

            if (loop.time() - recovered_ready_at) < _LIVE_OUTPUT_RECOVERY_GRACE_SECONDS:
                continue

            logger.warning(
                "Architecture draft generation recovered from live outputs. project_id=%s task_id=%s pending_version=%s",
                project_id,
                task_id,
                pending_version,
            )
            operation_task.cancel()
            operation_task.add_done_callback(_silence_background_asyncio_task)
            # 设计注释：
            # 这里和 requirements live recovery 一样，必须先取消外层 operation，
            # 否则 handoff 会先等 registry 清理，而 registry 本身又要等 finally 才会清掉。
            await asyncio.sleep(0)
            await _stop_running_task_before_stage_transition(
                task_id,
                stage_name="architecture live recovery handoff",
            )
            return recovered[0], recovered[1], True


class WorkflowTaskError(Exception):
    def __init__(self, error_type: TaskErrorType, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def _classify_exception(exception: Exception, *, recovery: bool = False) -> tuple[TaskErrorType, str]:
    if recovery:
        return "CONTEXT_EXPIRED", "The service restarted while this task was running. Please retry the task."
    if isinstance(exception, WorkflowTaskError):
        return exception.error_type, exception.message
    if isinstance(exception, UnicodeDecodeError):
        return "FILE_PARSE_FAILED", "Failed to parse uploaded file content."
    if isinstance(exception, ValueError):
        return "PARSING_FAILED", "The request could not be parsed. Please provide a clearer requirement."
    return "GENERATION_FAILED", str(exception) or "Task execution failed."


async def _handle_task_exception(project_id: str, task_id: str, exception: Exception, *, recovery: bool = False) -> None:
    error_type, error_message = _classify_exception(exception, recovery=recovery)

    for generation_task in reversed(await store.list_generation_tasks(project_id)):
        if generation_task.status in {"pending", "running"}:
            generation_task = await store.update_generation_task(
                generation_task.id,
                project_id,
                status="failed",
                progress=generation_task.progress,
                error_message=error_message,
            )
            await _broadcast(project_id, "task_update", generation_task.model_dump(mode="json"))
            break

    stats = await store.get_statistics(task_id)
    if stats is not None and stats.completedAt is None:
        await store.update_statistics(task_id, completedAt=utc_now())

    task = await store.get_task(task_id)
    output_data: dict[str, Any] = {}
    if task and isinstance(task.outputData, dict):
        output_data.update(task.outputData)
    output_data.update(
        {
            "errorType": error_type,
            "errorMessage": error_message,
        }
    )
    await store.update_task(task_id, status="failed", output_data=output_data, error_message=error_message, completed=True)
    await store.touch_project(project_id, status="failed")
    await _append_message(
        Message(
            projectId=project_id,
            role="system",
            type="text",
            content=error_message,
            metadata=_task_message_metadata(task_id, task_status="failed"),
        )
    )
    await _broadcast(
        project_id,
        "status_change",
        {"oldStatus": "running", "newStatus": "failed"},
    )
    await _broadcast(
        project_id,
        "error",
        {
            "errorType": error_type,
            "message": error_message,
            "taskId": task_id,
        },
    )
    await _broadcast(
        project_id,
        "task_round_finished",
        {
            "taskId": task_id,
            "status": "failed",
            "errorType": error_type,
            "message": error_message,
            "createdAt": utc_now().isoformat(),
        },
    )
    await _broadcast_progress(
        project_id,
        task_id,
        phase="task_failed",
        status="failed",
        error_type=error_type,
        message=error_message,
    )
    payload = await _statistics_payload(task_id)
    if payload is not None:
        await _broadcast(project_id, "statistics", payload.model_dump(mode="json"))


async def _statistics_payload(task_id: str) -> StatisticsResponse | None:
    stats = await store.get_statistics(task_id)
    if stats is None:
        return None
    steps = await store.list_step_records(task_id)
    reported_steps = 0
    unreported_steps = 0
    for step in steps:
        metadata = step.metadata if isinstance(step.metadata, dict) else {}
        usage_status = str(metadata.get("usageStatus") or ("reported" if step.tokensUsed > 0 else "unreported"))
        if usage_status == "reported":
            reported_steps += 1
        elif usage_status == "unreported":
            unreported_steps += 1
    task = await store.get_task(task_id)
    output_data = task.outputData if task is not None and isinstance(task.outputData, dict) else {}
    streaming_usage = output_data.get("streamingUsage") if isinstance(output_data.get("streamingUsage"), dict) else {}
    has_streaming_usage = any(
        isinstance(item, dict) and int(item.get("totalTokens") or 0) > 0
        for item in streaming_usage.values()
    )
    if unreported_steps > 0 and not has_streaming_usage:
        usage_status = "unreported"
    elif reported_steps > 0 or has_streaming_usage or stats.totalTokens > 0:
        usage_status = "reported"
    elif task is not None and task.status in {"running", "waiting_user"}:
        usage_status = "pending"
    else:
        usage_status = "unreported"

    def step_source_agent(step) -> str:
        metadata = step.metadata if isinstance(step.metadata, dict) else {}
        source_agent = str(metadata.get("sourceAgent") or "").strip()
        if source_agent:
            return source_agent
        step_name = str(step.stepName or "")
        if step_name == "Analyze requirements":
            return "requirements_agent"
        if step_name == "Generate requirements drafts":
            return "requirements_agent"
        if step_name == "Generate architecture draft":
            return "architecture_agent"
        if step_name == "Generate UI workspace":
            return "ui_agent"
        if step_name == "Generate code workspace":
            return "coding_agent"
        if step_name == "Generate test workspace":
            return "test_agent"
        return ""

    def active_stream_keys_for_phase(active_phase: str) -> list[str]:
        if active_phase == "requirements_analysis":
            return ["requirements_analysis"]
        if active_phase in {"requirements_drafts_started", "requirements_feedback_required"}:
            return ["requirements_drafts"]
        if active_phase == "architecture_generation_started":
            return ["architecture"]
        if active_phase == "ui_generation_started":
            return ["ui"]
        if active_phase == "code_generation_started":
            return ["coding"]
        if active_phase == "test_generation_started":
            return ["test"]
        return []

    agent_usage_rollup: dict[str, dict[str, Any]] = {}

    def ensure_agent_bucket(agent_name: str) -> dict[str, Any]:
        bucket = agent_usage_rollup.get(agent_name)
        if bucket is None:
            bucket = {
                "agent": agent_name,
                "totalTokens": 0,
                "cost": 0.0,
                "model": None,
                "usageStatus": "unreported",
            }
            agent_usage_rollup[agent_name] = bucket
        return bucket

    for step in steps:
        agent_name = step_source_agent(step)
        if not agent_name:
            continue
        metadata = step.metadata if isinstance(step.metadata, dict) else {}
        bucket = ensure_agent_bucket(agent_name)
        bucket["totalTokens"] += int(step.tokensUsed or 0)
        bucket["cost"] += float(step.cost or 0.0)
        if not bucket["model"] and isinstance(metadata.get("model"), str):
            bucket["model"] = str(metadata.get("model") or "")
        step_usage_status = str(metadata.get("usageStatus") or ("reported" if step.tokensUsed > 0 else "unreported"))
        if int(step.tokensUsed or 0) > 0 or step_usage_status == "reported":
            bucket["usageStatus"] = "reported"
        elif bucket["usageStatus"] != "reported" and step_usage_status == "pending":
            bucket["usageStatus"] = "pending"

    # 原因注释：
    # streaming_usage 是运行中的实时累计，step_records 是完成后的持久记录。
    # 只有当 streaming 对应的阶段已经产出了 step record 时才跳过，
    # 否则同一个 agent 跨阶段的 streaming 会被误跳（如分析阶段的 step 导致
    # 生成阶段的 streaming 被忽略）。
    active_phase = str(output_data.get("activePhase") or "")
    active_stream_keys = set(active_stream_keys_for_phase(active_phase))

    # 收集已经有 step record 的 stream_key，用于精确去重
    stream_key_to_step_name = {
        "requirements_analysis": "Analyze requirements",
        "requirements_drafts": "Generate requirements drafts",
        "architecture": "Generate architecture draft",
        "ui": "Generate UI workspace",
        "coding": "Generate code workspace",
        "test": "Generate test workspace",
    }
    completed_stream_keys: set[str] = set()
    for stream_key in active_stream_keys:
        expected_step = stream_key_to_step_name.get(stream_key)
        if expected_step and any(
            str(s.stepName or "") == expected_step and int(s.tokensUsed or 0) > 0
            for s in steps
        ):
            completed_stream_keys.add(stream_key)

    for stream_key in active_stream_keys:
        if stream_key in completed_stream_keys:
            continue
        stream_payload = streaming_usage.get(stream_key)
        if not isinstance(stream_payload, dict):
            continue
        agent_name = str(stream_payload.get("sourceAgent") or "")
        if not agent_name:
            continue
        bucket = ensure_agent_bucket(agent_name)
        bucket["totalTokens"] += int(stream_payload.get("totalTokens") or 0)
        bucket["cost"] += float(stream_payload.get("costAmount") or 0.0)
        if not bucket["model"] and isinstance(stream_payload.get("model"), str):
            bucket["model"] = str(stream_payload.get("model") or "")
        if int(stream_payload.get("totalTokens") or 0) > 0:
            bucket["usageStatus"] = "reported"
        elif bucket["usageStatus"] != "reported" and task is not None and task.status in {"running", "waiting_user"}:
            bucket["usageStatus"] = "pending"

    agent_order = {
        "requirements_agent": 10,
        "architecture_agent": 20,
        "ui_agent": 30,
        "coding_agent": 40,
        "test_agent": 50,
    }
    agent_usage = [
        {
            "agent": bucket["agent"],
            "totalTokens": int(bucket["totalTokens"] or 0),
            "cost": float(bucket["cost"] or 0.0),
            "model": bucket["model"],
            "usageStatus": bucket["usageStatus"],
        }
        for bucket in sorted(
            agent_usage_rollup.values(),
            key=lambda item: (agent_order.get(str(item.get("agent") or ""), 999), str(item.get("agent") or "")),
        )
    ]
    return StatisticsResponse(
        totalDuration=stats.totalDuration,
        stepsCount=stats.stepsCount,
        itemsRead=stats.itemsRead,
        tokens={
            "input": stats.inputTokens,
            "output": stats.outputTokens,
            "total": stats.totalTokens,
        },
        cost=stats.costAmount,
        model=stats.modelUsed,
        usageStatus=usage_status,  # type: ignore[arg-type]
        reportedSteps=reported_steps,
        unreportedSteps=unreported_steps,
        agentUsage=agent_usage,
        startedAt=stats.startedAt,
        completedAt=stats.completedAt,
    )


def _remaining_usage_after_streaming(
    final_usage: dict[str, Any] | None,
    streamed_usage: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    设计注释：
    流式累计和阶段结束对账会走两次。

    这里专门算“还没记过的剩余量”，避免阶段结束时把已经实时累加过的 token
    再重复加一遍，导致项目统计越跑越大。
    """

    if not final_usage:
        return None
    if not streamed_usage:
        return dict(final_usage)

    def remainder_int(field: str) -> int:
        return max(0, int(final_usage.get(field) or 0) - int(streamed_usage.get(field) or 0))

    def remainder_float(field: str) -> float:
        value = float(final_usage.get(field) or 0.0) - float(streamed_usage.get(field) or 0.0)
        return max(0.0, value)

    return {
        "model": _usage_model(final_usage, str(final_usage.get("model") or "")),
        "inputTokens": remainder_int("inputTokens"),
        "outputTokens": remainder_int("outputTokens"),
        "totalTokens": remainder_int("totalTokens"),
        "costAmount": remainder_float("costAmount"),
    }


async def _record_streaming_usage_delta(
    project_id: str,
    task_id: str,
    *,
    stream_key: str,
    source_agent: str,
    usage_delta: dict[str, Any] | None,
) -> None:
    """
    接口注释：
    把执行中的 usage 增量立刻累计到项目统计里。

    这个入口只做三件事：
    1. 给 `task_statistics` 做增量累加
    2. 把当前流式累计快照写进 `task.outputData.streamingUsage`
    3. 立即广播 `statistics`，让前端数字刷新
    """

    if not usage_delta:
        return

    stats = await store.get_statistics(task_id)
    if stats is None:
        return

    normalized_delta = {
        "model": _usage_model(usage_delta, stats.modelUsed),
        "inputTokens": int(usage_delta.get("inputTokens") or 0),
        "outputTokens": int(usage_delta.get("outputTokens") or 0),
        "totalTokens": int(usage_delta.get("totalTokens") or 0),
        "costAmount": float(usage_delta.get("costAmount") or 0.0),
        "sourceAgent": source_agent,
        "eventAt": utc_now().isoformat(),
    }
    if (
        normalized_delta["inputTokens"] <= 0
        and normalized_delta["outputTokens"] <= 0
        and normalized_delta["totalTokens"] <= 0
        and normalized_delta["costAmount"] <= 0
    ):
        return

    live_task = await store.get_task(task_id)
    output_data = dict(live_task.outputData or {}) if live_task and isinstance(live_task.outputData, dict) else {}
    streaming_usage = dict(output_data.get("streamingUsage") or {})
    current_stream = dict(streaming_usage.get(stream_key) or {})
    streaming_usage[stream_key] = {
        "model": normalized_delta["model"],
        "sourceAgent": source_agent,
        "inputTokens": int(current_stream.get("inputTokens") or 0) + normalized_delta["inputTokens"],
        "outputTokens": int(current_stream.get("outputTokens") or 0) + normalized_delta["outputTokens"],
        "totalTokens": int(current_stream.get("totalTokens") or 0) + normalized_delta["totalTokens"],
        "costAmount": float(current_stream.get("costAmount") or 0.0) + normalized_delta["costAmount"],
        "lastEventAt": normalized_delta["eventAt"],
    }
    output_data["streamingUsage"] = streaming_usage
    await store.update_task(task_id, output_data=output_data)

    await store.update_statistics(
        task_id,
        inputTokens=stats.inputTokens + normalized_delta["inputTokens"],
        outputTokens=stats.outputTokens + normalized_delta["outputTokens"],
        totalTokens=stats.totalTokens + normalized_delta["totalTokens"],
        costAmount=stats.costAmount + normalized_delta["costAmount"],
        modelUsed=str(normalized_delta["model"] or stats.modelUsed),
    )

    payload = await _statistics_payload(task_id)
    if payload is not None:
        await _broadcast(project_id, "statistics", payload.model_dump(mode="json"))


async def _record_streaming_usage_snapshot(
    project_id: str,
    task_id: str,
    *,
    stream_key: str,
    source_agent: str,
    usage_snapshot: dict[str, Any] | None,
) -> None:
    """
    接口注释：
    这个入口给“只能拿到当前累计值、拿不到本次增量”的 Agent 用。

    它会先读取这个流上一次已经累计到哪，再自动算出这一次真正新增的差值，
    然后继续复用统一的增量累计逻辑。
    """

    if not usage_snapshot:
        return

    previous_snapshot = await _streaming_usage_snapshot(task_id, stream_key)
    usage_delta = _remaining_usage_after_streaming(usage_snapshot, previous_snapshot)
    if not usage_delta:
        return
    usage_delta["model"] = _usage_model(usage_snapshot, str(usage_snapshot.get("model") or ""))
    await _record_streaming_usage_delta(
        project_id,
        task_id,
        stream_key=stream_key,
        source_agent=source_agent,
        usage_delta=usage_delta,
    )


async def _streaming_usage_snapshot(task_id: str, stream_key: str) -> dict[str, Any] | None:
    task = await store.get_task(task_id)
    if task is None or not isinstance(task.outputData, dict):
        return None
    streaming_usage = task.outputData.get("streamingUsage")
    if not isinstance(streaming_usage, dict):
        return None
    payload = streaming_usage.get(stream_key)
    return dict(payload) if isinstance(payload, dict) else None


_GENERATE_STAGE_SEQUENCE = [
    "requirements_analysis",
    "requirements_drafts",
    "architecture",
    "ui",
    "coding",
    "test",
]


def _resume_stage_index(stage_name: str) -> int:
    try:
        return _GENERATE_STAGE_SEQUENCE.index(stage_name)
    except ValueError:
        return -1


def _step_matches_stage(step, *, stage_name: str) -> bool:
    metadata = step.metadata if isinstance(step.metadata, dict) else {}
    source_agent = str(metadata.get("sourceAgent") or "")
    step_name = str(step.stepName or "")
    return {
        "requirements_analysis": step_name == "Analyze requirements",
        "requirements_drafts": step_name == "Generate requirements drafts" or source_agent == "requirements_agent",
        "architecture": step_name == "Generate architecture draft" or source_agent == "architecture_agent",
        "ui": step_name == "Generate UI workspace" or source_agent == "ui_agent",
        "coding": step_name == "Generate code workspace" or source_agent == "coding_agent",
        "test": step_name == "Generate test workspace" or source_agent == "test_agent",
    }.get(stage_name, False)


async def _validated_generate_stage_artifacts(project_id: str, *, version: int, stage_name: str) -> list[str]:
    """
    教学注释：
    阶段恢复不能只看 step 记录，因为 step 有可能写进去了，但文件没真的落全。
    所以这里把“真实可见文件”再查一遍，作为第二层确认。
    """

    agent_artifacts = await store.list_agent_artifacts(project_id, version=version)
    artifact_names = {
        _artifact_file_identity(artifact.fileName)
        for artifact in agent_artifacts
    }
    code_file_names = {
        _artifact_file_identity(code_file.filePath)
        for code_file in await store.list_code_files(project_id, version=version)
    }

    if stage_name == "requirements_analysis":
        required_files = planned_requirements_analysis_files()
        return [file_name for file_name in required_files if _artifact_file_identity(file_name) in artifact_names]
    if stage_name == "requirements_drafts":
        required_files = ["SRS.md", "use_case.md", "dialog_map.md"]
        return [file_name for file_name in required_files if _artifact_file_identity(file_name) in artifact_names]
    if stage_name == "architecture":
        required_files = ["component_design.json", "class_design_raw.md", "class_design_structured.json"]
        return [file_name for file_name in required_files if _artifact_file_identity(file_name) in artifact_names]
    if stage_name == "ui":
        required_files = [
            file_name
            for file_name in planned_ui_files()
            if file_name != "app/js/api.js"
        ]
        return [file_name for file_name in required_files if _artifact_file_identity(file_name) in code_file_names or _artifact_file_identity(file_name) in artifact_names]
    if stage_name == "coding":
        return sorted(code_file_names)
    if stage_name == "test":
        test_file_matches = [
            file_name
            for file_name in code_file_names
            if "test" in Path(file_name).name.lower() or file_name.endswith("_testcase.md") or file_name.endswith("_test_plan.md")
        ]
        return sorted(test_file_matches)
    return []


async def _stage_is_reliably_completed(project_id: str, task_id: str, *, version: int, stage_name: str) -> tuple[bool, list[str]]:
    steps = await store.list_step_records(task_id)
    has_completed_step = any(
        step.status == "completed" and _step_matches_stage(step, stage_name=stage_name)
        for step in steps
    )
    validated_files = await _validated_generate_stage_artifacts(project_id, version=version, stage_name=stage_name)

    if stage_name == "requirements_analysis":
        return has_completed_step and bool(validated_files), validated_files
    if stage_name == "requirements_drafts":
        return has_completed_step and len(validated_files) >= 3, validated_files
    if stage_name == "architecture":
        return has_completed_step and len(validated_files) >= 3, validated_files
    if stage_name == "ui":
        return has_completed_step and len(validated_files) >= 6, validated_files
    if stage_name == "coding":
        return has_completed_step and bool(validated_files), validated_files
    if stage_name == "test":
        return has_completed_step and bool(validated_files), validated_files
    return False, validated_files


async def _build_generate_resume_plan(project_id: str, task_id: str) -> dict[str, Any]:
    task = await store.get_task(task_id)
    project = await store.get_project(project_id)
    if task is None or project is None:
        return {
            "mode": "retry_from_checkpoint",
            "resumeFromStage": "requirements_analysis",
            "resumeReason": "missing_context",
            "skippedStages": [],
            "validatedArtifacts": {},
            "originalTaskId": task_id,
        }

    last_completed_stage: str | None = None
    validated_artifacts: dict[str, list[str]] = {}
    for stage_name in _GENERATE_STAGE_SEQUENCE:
        completed, validated_files = await _stage_is_reliably_completed(
            project_id,
            task_id,
            version=project.currentVersion,
            stage_name=stage_name,
        )
        if validated_files:
            validated_artifacts[stage_name] = validated_files
        if completed:
            last_completed_stage = stage_name
            continue

    if last_completed_stage is None:
        resume_from_stage = "requirements_analysis"
        skipped_stages: list[str] = []
        resume_reason = "no_reliable_completed_stage"
    else:
        next_index = _resume_stage_index(last_completed_stage) + 1
        if next_index >= len(_GENERATE_STAGE_SEQUENCE):
            resume_from_stage = _GENERATE_STAGE_SEQUENCE[-1]
        else:
            resume_from_stage = _GENERATE_STAGE_SEQUENCE[next_index]
        skipped_stages = _GENERATE_STAGE_SEQUENCE[:next_index]
        resume_reason = f"resume_after_{last_completed_stage}"

    return {
        "mode": "retry_from_checkpoint",
        "resumeFromStage": resume_from_stage,
        "resumeReason": resume_reason,
        "skippedStages": skipped_stages,
        "validatedArtifacts": validated_artifacts,
        "originalTaskId": task_id,
    }


_STAGE_TO_STEP_NAMES: dict[str, list[str]] = {
    "requirements_analysis": ["Analyze requirements"],
    "requirements_drafts": ["Generate requirements drafts"],
    "architecture": ["Generate architecture draft"],
    "ui": ["Generate UI workspace"],
    "coding": ["Generate code workspace"],
    "test": ["Generate test workspace"],
}


async def _inherit_completed_steps_from_parent_task(task_id: str, start_stage: str) -> None:
    """
    重试时把旧 task 已完成阶段的 step records 复制到新 task，
    同时把已完成阶段的 token 累加到新 task 的 statistics。

    这样前端查看新 task 时能看到完整的步骤历史和 token 统计。
    """

    task = await store.get_task(task_id)
    if task is None:
        return
    output_data = task.outputData if isinstance(task.outputData, dict) else {}
    original_task_id = str(output_data.get("originalTaskId") or "").strip()
    if not original_task_id:
        return

    original_steps = await store.list_step_records(original_task_id)
    if not original_steps:
        return

    # 已完成的阶段列表（start_stage 之前的所有阶段）
    start_index = _resume_stage_index(start_stage)
    if start_index <= 0:
        return
    completed_stages = _GENERATE_STAGE_SEQUENCE[:start_index]
    completed_step_names: set[str] = set()
    for stage in completed_stages:
        completed_step_names.update(_STAGE_TO_STEP_NAMES.get(stage, []))

    inherited_tokens = 0
    inherited_cost = 0.0
    inherited_duration = 0.0
    for step in original_steps:
        if str(step.stepName or "") not in completed_step_names:
            continue
        await store.add_step_record(
            task_id,
            str(step.stepName or ""),
            str(step.stepType or "process_log"),
            duration=float(step.duration or 0),
            tokens_used=int(step.tokensUsed or 0),
            cost=float(step.cost or 0),
            status=str(step.status or "completed"),
            metadata={**(step.metadata if isinstance(step.metadata, dict) else {}), "inheritedFromTask": original_task_id},
        )
        inherited_tokens += int(step.tokensUsed or 0)
        inherited_cost += float(step.cost or 0)
        inherited_duration += float(step.duration or 0)

    if inherited_tokens > 0 or inherited_cost > 0:
        stats = await store.get_statistics(task_id)
        if stats is not None:
            await store.update_statistics(
                task_id,
                inputTokens=stats.inputTokens + 0,
                outputTokens=stats.outputTokens + 0,
                totalTokens=stats.totalTokens + inherited_tokens,
                costAmount=stats.costAmount + inherited_cost,
                totalDuration=stats.totalDuration + inherited_duration,
            )


async def _maybe_generate_test_workspace(
    project_id: str,
    task_id: str,
    *,
    prompt: str,
    selected_modules_payload: list[dict[str, Any]],
    locale: Locale,
    running_message: str,
    completed_message: str,
    step_extra: dict[str, Any] | None = None,
) -> float:
    """
    设计注释：
    修改流和运行时变量恢复流的主目标，是先把主产物补齐。

    Test Agent 在某些轻量测试场景下可能暂时不给文件。
    这里把它降级成“尽力而为”，避免主流程已经成功，却因为测试补充为空而整轮失败。
    """

    try:
        return await _generate_test_workspace(
            project_id,
            task_id,
            prompt=prompt,
            selected_modules_payload=selected_modules_payload,
            locale=locale,
            running_message=running_message,
            completed_message=completed_message,
            step_extra=step_extra,
        )
    except Exception as exc:
        logger.warning(
            "Test Agent optional generation skipped. project_id=%s task_id=%s error=%s",
            project_id,
            task_id,
            exc,
        )
        return 0.0


async def _reference_materials(upload_ids: list[str]) -> list[dict[str, Any]]:
    uploads = await store.get_uploads(upload_ids)
    return [
        {
            "id": upload.id,
            "fileName": upload.fileName,
            "fileType": upload.fileType,
            "fileSize": upload.fileSize,
            "contentPreview": upload.contentPreview,
        }
        for upload in uploads
        if upload.contentPreview
    ]


async def build_image_reference_summary(upload: Any) -> str:
    # 接口注释：
    # workflow 测试会直接 patch 这个入口，避免碰真实模型。
    # 这里保持成单独函数，流程层就不用知道图片总结服务的底层实现细节。
    content = await store.read_upload_content(upload.id)
    if not content:
        raise RuntimeError("Original image file is missing.")
    return await summarize_image_reference(file_name=upload.fileName, content=content)


def _render_analysis_reference_preview(
    upload: Any,
    analysis_detail: dict[str, Any] | None,
) -> str | None:
    if upload.fileType != "image":
        return upload.contentPreview

    detail = analysis_detail or {}
    status = str(detail.get("status") or "").strip().lower()
    summary = str(detail.get("summary") or "").strip()
    error_text = str(detail.get("error") or "").strip()

    if status == "completed" and summary:
        return summary

    base_preview = (upload.contentPreview or "").strip()
    if status == "failed" and error_text:
        failure_hint = f"[Skipped in first-pass analysis: {error_text}]"
        if base_preview:
            return f"{base_preview}\n\n{failure_hint}"
        return failure_hint

    return upload.contentPreview


async def _reference_snapshot(
    upload_ids: list[str],
    *,
    analysis_details: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    uploads = await store.get_uploads(upload_ids)
    analysis_details = analysis_details or {}
    return [
        {
            "id": upload.id,
            "fileName": upload.fileName,
            "filePath": upload.filePath,
            "fileType": upload.fileType,
            "fileSize": upload.fileSize,
            "contentPreview": _render_analysis_reference_preview(upload, analysis_details.get(upload.id)),
            "projectId": upload.projectId,
            "isTemporary": upload.isTemporary,
        }
        for upload in uploads
    ]


async def build_current_reference_snapshot(upload_ids: list[str]) -> list[dict[str, Any]]:
    return await _reference_snapshot(
        upload_ids,
        analysis_details=await store.list_upload_analysis_details(upload_ids),
    )


async def _prepare_analysis_reference_materials(
    upload_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    uploads = await store.get_uploads(upload_ids)
    cached_details = await store.list_upload_analysis_details(upload_ids)
    reference_materials: list[dict[str, Any]] = []
    refreshed_details = dict(cached_details)

    for upload in uploads:
        if upload.fileType != "image":
            if upload.contentPreview:
                reference_materials.append(
                    {
                        "id": upload.id,
                        "fileName": upload.fileName,
                        "fileType": upload.fileType,
                        "fileSize": upload.fileSize,
                        "contentPreview": upload.contentPreview,
                    }
                )
            continue

        detail = refreshed_details.get(upload.id) or {}
        status = str(detail.get("status") or "").strip().lower()
        summary = str(detail.get("summary") or "").strip()
        if status == "completed" and summary:
            reference_materials.append(
                {
                    "id": upload.id,
                    "fileName": upload.fileName,
                    "fileType": upload.fileType,
                    "fileSize": upload.fileSize,
                    "contentPreview": summary,
                    "summarySource": "image_analysis",
                }
            )
            continue

        if status == "failed":
            continue

        try:
            image_summary = await build_image_reference_summary(upload)
        except Exception as exc:
            error_text = str(exc).strip() or "Image summary failed."
            await store.update_upload_analysis(upload.id, status="failed", error=error_text)
            refreshed_details[upload.id] = {
                "summary": None,
                "status": "failed",
                "error": error_text,
                "updatedAt": utc_now().isoformat(),
            }
            continue

        await store.update_upload_analysis(upload.id, status="completed", summary=image_summary)
        refreshed_details[upload.id] = {
            "summary": image_summary,
            "status": "completed",
            "error": None,
            "updatedAt": utc_now().isoformat(),
        }
        reference_materials.append(
            {
                "id": upload.id,
                "fileName": upload.fileName,
                "fileType": upload.fileType,
                "fileSize": upload.fileSize,
                "contentPreview": image_summary,
                "summarySource": "image_analysis",
            }
        )

    return reference_materials, refreshed_details


async def _image_reference_failures(
    upload_ids: list[str],
    analysis_details: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for upload in await store.get_uploads(upload_ids):
        if upload.fileType != "image":
            continue
        detail = analysis_details.get(upload.id) or {}
        if str(detail.get("status") or "").strip().lower() != "failed":
            continue
        failures.append(
            {
                "fileName": upload.fileName,
                "error": str(detail.get("error") or "Image summary failed.").strip() or "Image summary failed.",
            }
        )
    return failures


def _image_summary_failure_message(locale: Locale, failures: list[dict[str, str]]) -> str:
    file_names = ", ".join(item["fileName"] for item in failures if item.get("fileName")) or "image references"
    if locale == "zh":
        return f"以下图片未能转换成首轮需求分析可用的摘要，已跳过：{file_names}。"
    return f"The following images could not be converted into first-pass analysis summaries and were skipped: {file_names}."


def _apply_usage_metadata(task_id: str, usage_metadata: dict[str, Any] | None, *, default_model: str) -> dict[str, Any]:
    if not usage_metadata:
        return {
            "modelUsed": default_model,
        }
    return {
        "inputTokens": int(usage_metadata.get("inputTokens") or 0),
        "outputTokens": int(usage_metadata.get("outputTokens") or 0),
        "totalTokens": int(usage_metadata.get("totalTokens") or 0),
        "costAmount": float(usage_metadata.get("costAmount") or 0.0),
        "modelUsed": _usage_model(usage_metadata, default_model),
    }


def _usage_total_tokens(usage_metadata: dict[str, Any] | None) -> int:
    if not usage_metadata:
        return 0
    return int(usage_metadata.get("totalTokens") or 0)


def _usage_cost_amount(usage_metadata: dict[str, Any] | None) -> float:
    if not usage_metadata:
        return 0.0
    return float(usage_metadata.get("costAmount") or 0.0)


def _usage_model(usage_metadata: dict[str, Any] | None, fallback_model: str) -> str:
    if not usage_metadata:
        return _strip_litellm_provider_prefix(fallback_model)
    candidate = str(usage_metadata.get("model") or "").strip()
    if not candidate:
        return _strip_litellm_provider_prefix(fallback_model)
    if "/" not in candidate and "/" in fallback_model and fallback_model.endswith(f"/{candidate}"):
        return _strip_litellm_provider_prefix(fallback_model)
    return _strip_litellm_provider_prefix(candidate)


def _strip_litellm_provider_prefix(model: str) -> str:
    """
    原因注释：
    litellm 要求模型名带 'openai/' 前缀来标识 OpenAI 兼容协议，
    但这个前缀不应该出现在面向用户的 usage 统计里。
    """
    normalized = str(model or "").strip()
    if normalized.startswith("openai/"):
        return normalized[len("openai/"):]
    return normalized


def _merge_usage_metadata(
    *usage_payloads: dict[str, Any] | None,
    fallback_model: str,
) -> dict[str, Any] | None:
    payloads = [payload for payload in usage_payloads if payload]
    if not payloads:
        return None
    return {
        "inputTokens": sum(int(payload.get("inputTokens") or 0) for payload in payloads),
        "outputTokens": sum(int(payload.get("outputTokens") or 0) for payload in payloads),
        "totalTokens": sum(int(payload.get("totalTokens") or 0) for payload in payloads),
        "costAmount": sum(float(payload.get("costAmount") or 0.0) for payload in payloads),
        "model": _usage_model(payloads[-1], fallback_model),
    }


async def _reconciled_stage_usage(
    task_id: str,
    *,
    stream_key: str,
    final_usage: dict[str, Any] | None,
    default_model: str,
) -> dict[str, Any] | None:
    """
    接口注释：
    统一返回“某个阶段最终应该记到 step 上的完整 usage”。

    设计注释：
    有些 Agent 会把 token 先通过流式事件上报到 `streamingUsage`，
    但阶段结束时 `consume_last_usage_metadata()` 可能拿不到最终累计值。
    如果 step 这里只盯着最终返回值，就会把本来已经上报过 token 的阶段误记成 `Unreported`。
    所以这里统一把“流式累计值 + 结束时剩余值”拼成完整结果。
    """

    streamed_usage = await _streaming_usage_snapshot(task_id, stream_key)
    remainder_usage = _remaining_usage_after_streaming(final_usage, streamed_usage)
    return _merge_usage_metadata(
        streamed_usage,
        remainder_usage,
        fallback_model=_usage_model(final_usage, default_model),
    )


def _runtime_settings_snapshot() -> dict[str, str | None]:
    return {
        "base_url": agent_orchestrator.base_url,
        "api_key": agent_orchestrator.api_key,
        "model": agent_orchestrator.model,
        "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL"),
        "ISOFTDEVAGENTS_LLM_BASE_URL": os.environ.get("ISOFTDEVAGENTS_LLM_BASE_URL"),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
        "ISOFTDEVAGENTS_LLM_API_KEY": os.environ.get("ISOFTDEVAGENTS_LLM_API_KEY"),
        "OPENAI_MODEL": os.environ.get("OPENAI_MODEL"),
        "ISOFTDEVAGENTS_LLM_MODEL": os.environ.get("ISOFTDEVAGENTS_LLM_MODEL"),
    }


def _restore_runtime_settings(snapshot: dict[str, str | None]) -> None:
    agent_orchestrator.base_url = (snapshot.get("base_url") or "").rstrip("/")
    agent_orchestrator.api_key = snapshot.get("api_key") or ""
    agent_orchestrator.model = snapshot.get("model") or ""

    for key in (
        "OPENAI_BASE_URL",
        "ISOFTDEVAGENTS_LLM_BASE_URL",
        "OPENAI_API_KEY",
        "ISOFTDEVAGENTS_LLM_API_KEY",
        "OPENAI_MODEL",
        "ISOFTDEVAGENTS_LLM_MODEL",
    ):
        value = snapshot.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _step_usage_metadata(
    *,
    usage_metadata: dict[str, Any] | None,
    default_model: str,
    source_agent: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "usageStatus": "reported" if usage_metadata is not None else "unreported",
        "model": _usage_model(usage_metadata, default_model),
        "sourceAgent": source_agent,
    }
    if extra:
        payload.update(extra)
    return payload


def _duration_label(seconds: float) -> str:
    return f"{seconds:.1f}s"


async def _artifact_snapshot(project_id: str) -> list[dict[str, Any]]:
    artifacts = await store.list_artifacts(project_id)
    return [
        {
            "id": artifact.id,
            "type": artifact.type,
            "title": artifact.title,
            "version": artifact.version,
            "content": artifact.content,
        }
        for artifact in artifacts
    ]


async def _build_requirements_payload_from_agent_artifacts(
    *,
    project_id: str,
    version: int,
    prompt: str,
    selected_modules: list[dict[str, Any]],
    source_files_by_artifact: dict[str, list[str]] | None = None,
    status: str = "completed",
) -> dict[str, Any]:
    """
    根据 requirements_agent 的真实输出文件，现场重建后续流程需要的需求草稿内容。

    接口注释：
    这里返回的 `prd/ui/api_spec` 只作为后端后续阶段的上下文输入，
    不代表这些内容需要再次作为“独立文件”落到前端产物面板。
    """

    raw_outputs = {
        artifact.fileName: str(artifact.content or "")
        for artifact in await store.list_agent_artifacts(project_id, version=version, agent_name="requirements_agent")
    }
    business_scope = raw_outputs.get("business_scope.md", "")
    feature_tree = raw_outputs.get("feature_tree.md", "")
    functional_requirements = raw_outputs.get("functional_requirements.md", "")
    non_functional_requirements = raw_outputs.get("non_functional_requirements.md", "")
    use_case_text = raw_outputs.get("use_case.md", "")

    # 教学注释：
    # 这里复用 orchestrator 里已经验证过的拼装方法，避免在 workflow 再复制一套规则，
    # 这样 requirements 阶段展示逻辑和后续代码生成逻辑能继续保持一致。
    module_labels = agent_orchestrator._requirements_agent_module_labels(feature_tree, selected_modules)
    use_cases = agent_orchestrator._parse_requirements_agent_use_cases(use_case_text)
    derived_source_files = {
        "prd": [
            file_name
            for file_name, text in (
                ("business_scope.md", business_scope),
                ("feature_tree.md", feature_tree),
                ("functional_requirements.md", functional_requirements),
                ("non_functional_requirements.md", non_functional_requirements),
                ("use_case.md", use_case_text),
            )
            if text
        ],
        "ui": [
            file_name
            for file_name, text in (
                ("feature_tree.md", feature_tree),
                ("use_case.md", use_case_text),
            )
            if text
        ],
        "api_spec": [
            file_name
            for file_name, text in (
                ("feature_tree.md", feature_tree),
                ("use_case.md", use_case_text),
            )
            if text
        ],
    }
    resolved_source_files = source_files_by_artifact or derived_source_files

    return {
        "prd": agent_orchestrator._requirements_agent_prd_from_outputs(
            prompt=prompt,
            selected_modules=selected_modules,
            business_scope=business_scope,
            feature_tree=feature_tree,
            functional_requirements=functional_requirements,
            non_functional_requirements=non_functional_requirements,
            use_cases=use_cases,
        ),
        "ui": agent_orchestrator._requirements_agent_ui_from_outputs(
            module_labels=module_labels,
            use_cases=use_cases,
        ),
        "api_spec": agent_orchestrator._requirements_agent_api_spec_from_outputs(
            module_labels=module_labels,
            use_cases=use_cases,
        ),
        "_meta": {
            "source": "requirements_agent",
            "status": status,
            "sourceFilesByArtifact": resolved_source_files,
        },
    }


async def _task_output_data(task_id: str) -> dict[str, Any]:
    task = await store.get_task(task_id)
    if task is None or not isinstance(task.outputData, dict):
        return {}
    return dict(task.outputData)


def _legacy_combined_artifact_builder_active() -> bool:
    build_artifacts_impl = agent_orchestrator.build_artifacts
    impl_type = type(build_artifacts_impl)
    return impl_type.__module__.startswith("unittest.mock") and impl_type.__name__ == "AsyncMock"


async def _confirmation_kind(task_id: str) -> str | None:
    output_data = await _task_output_data(task_id)
    value = output_data.get("confirmationKind")
    return str(value) if isinstance(value, str) else None


def _artifact_review_confirmation_payload(
    *,
    locale: Locale,
    reference_snapshot: list[dict[str, Any]],
    selected_module_ids: list[str],
    artifact_types: list[str],
    artifact_sources: dict[str, dict[str, Any]],
    context_summary: dict[str, int],
) -> dict[str, Any]:
    options = [
        {
            "id": "prd",
            "label": t(locale, "artifact_review.option.prd.label"),
            "labelEn": "PRD Draft",
            "description": t(locale, "artifact_review.option.prd.description"),
            "checked": True,
        },
        {
            "id": "ui",
            "label": t(locale, "artifact_review.option.ui.label"),
            "labelEn": "UI Draft",
            "description": t(locale, "artifact_review.option.ui.description"),
            "checked": True,
        },
        {
            "id": "architecture",
            "label": t(locale, "artifact_review.option.architecture.label"),
            "labelEn": "Architecture Draft",
            "description": t(locale, "artifact_review.option.architecture.description"),
            "checked": True,
        },
        {
            "id": "api_spec",
            "label": t(locale, "artifact_review.option.api_spec.label"),
            "labelEn": "API Design",
            "description": t(locale, "artifact_review.option.api_spec.description"),
            "checked": True,
        },
    ]
    return {
        "confirmationKind": "artifact_review",
        "title": t(locale, "artifact_review.title"),
        "message": t(locale, "artifact_review.message"),
        "options": options,
        "confirmText": t(locale, "artifact_review.confirm"),
        "cancelText": t(locale, "artifact_review.cancel"),
        "referenceFiles": reference_snapshot,
        "selectedModuleIds": selected_module_ids,
        "artifactTypes": artifact_types,
        "artifactSources": artifact_sources,
        "contextSummary": context_summary,
    }


def _requirements_artifact_review_confirmation_payload(
    *,
    locale: Locale,
    reference_snapshot: list[dict[str, Any]],
    selected_module_ids: list[str],
    artifact_sources: dict[str, dict[str, Any]],
    context_summary: dict[str, int],
) -> dict[str, Any]:
    source_files: list[str] = []
    for artifact_type in ("prd", "ui", "api_spec"):
        artifact_source = artifact_sources.get(artifact_type) if isinstance(artifact_sources, dict) else None
        if isinstance(artifact_source, dict):
            source_files.extend([str(item) for item in artifact_source.get("sourceFiles") or [] if str(item).strip()])
    output_files = _user_facing_primary_output_files(source_files)
    file_list = _localized_file_list(locale, output_files)
    options = [
        {
            "id": "prd",
            "label": t(locale, "artifact_review.option.prd.label"),
            "labelEn": "PRD Draft",
            "description": t(locale, "artifact_review.option.prd.description"),
            "checked": True,
        },
        {
            "id": "ui",
            "label": t(locale, "artifact_review.option.ui.label"),
            "labelEn": "UI Draft",
            "description": t(locale, "artifact_review.option.ui.description"),
            "checked": True,
        },
        {
            "id": "api_spec",
            "label": t(locale, "artifact_review.option.api_spec.label"),
            "labelEn": "API Design",
            "description": t(locale, "artifact_review.option.api_spec.description"),
            "checked": True,
        },
    ]
    return {
        "confirmationKind": "artifact_review",
        "title": t(locale, "requirements_artifact_review.title"),
        "message": (
            t(locale, "requirements_artifact_review.message_with_files", files=file_list)
            if file_list
            else t(locale, "requirements_artifact_review.message")
        ),
        "options": options,
        "confirmText": t(locale, "requirements_artifact_review.confirm"),
        "cancelText": t(locale, "requirements_artifact_review.cancel"),
        "referenceFiles": reference_snapshot,
        "selectedModuleIds": selected_module_ids,
        "outputFiles": output_files,
        "artifactTypes": ["prd", "ui", "api_spec"],
        "artifactSources": {
            artifact_type: artifact_sources[artifact_type]
            for artifact_type in ("prd", "ui", "api_spec")
        },
        "contextSummary": context_summary,
    }


def _artifact_content_items(payload: dict[str, Any]) -> list[tuple[str, str]]:
    artifact_types = ("prd", "ui", "architecture", "api_spec")
    items: list[tuple[str, str]] = []
    for artifact_type in artifact_types:
        content = payload.get(artifact_type)
        if isinstance(content, str):
            items.append((artifact_type, content))
    return items


def _artifact_sources_payload(artifacts: dict[str, Any], usage_metadata: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    meta = artifacts.get("_meta") if isinstance(artifacts.get("_meta"), dict) else {}
    requirements_meta = meta.get("requirements") if isinstance(meta.get("requirements"), dict) else {}
    architecture_meta = meta.get("architecture") if isinstance(meta.get("architecture"), dict) else {}

    default_source = "unknown"
    default_payload: dict[str, Any] = {
        "source": default_source,
        "status": "unknown",
        "sourceFiles": [],
    }
    if usage_metadata and usage_metadata.get("model"):
        default_payload["model"] = str(usage_metadata["model"])

    def build_entry(source_meta: dict[str, Any] | None, artifact_type: str) -> dict[str, Any]:
        if not source_meta:
            return dict(default_payload)
        source_files_by_artifact = source_meta.get("sourceFilesByArtifact") if isinstance(source_meta.get("sourceFilesByArtifact"), dict) else {}
        entry = {
            "source": str(source_meta.get("source") or default_source),
            "status": str(source_meta.get("status") or default_payload["status"]),
            "sourceFiles": list(source_files_by_artifact.get(artifact_type) or source_meta.get("sourceFiles") or []),
        }
        if source_meta.get("model"):
            entry["model"] = str(source_meta["model"])
        elif usage_metadata and usage_metadata.get("model"):
            entry["model"] = str(usage_metadata["model"])
        return entry

    return {
        "prd": build_entry(requirements_meta or None, "prd"),
        "ui": build_entry(requirements_meta or None, "ui"),
        "api_spec": build_entry(requirements_meta or None, "api_spec"),
        "architecture": build_entry(architecture_meta or None, "architecture"),
    }


def _context_summary_payload(
    *,
    reference_snapshot: list[dict[str, Any]],
    selected_module_ids: list[str],
    existing_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    return {
        "referenceFileCount": len(reference_snapshot),
        "selectedModuleCount": len(selected_module_ids),
        "existingArtifactCount": len(existing_artifacts or []),
    }


def _input_variables_confirmation_payload(
    *,
    locale: Locale,
    prompt: str,
    selected_modules_payload: list[dict[str, Any]],
    next_action: dict[str, Any],
    runtime_variables: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "confirmationKind": "input_variables",
        "actionType": "input_variables",
        "title": t(locale, "input_variables.title"),
        "message": t(locale, "input_variables.message"),
        "variables": runtime_variables,
        "submitText": t(locale, "input_variables.submit"),
        "skipText": t(locale, "input_variables.skip"),
        "pendingPrompt": prompt,
        "selectedModulesPayload": selected_modules_payload,
        "pendingNextAction": next_action,
    }


def _requirements_feedback_confirmation_payload(
    *,
    locale: Locale,
    prompt_text: str,
    output_files: list[str],
    return_phase: str,
    return_agent: str,
) -> dict[str, Any]:
    visible_output_files = _user_facing_primary_output_files(output_files)
    file_list = _localized_file_list(locale, visible_output_files)
    return {
        "confirmationKind": "requirements_feedback",
        "actionType": "input_form",
        "title": t(locale, "requirements_feedback.title"),
        "message": prompt_text.strip() or (
            t(locale, "requirements_feedback.message_with_files", files=file_list)
            if file_list
            else t(locale, "requirements_feedback.message")
        ),
        "variables": [
            {
                "id": "feedback",
                "label": t(locale, "requirements_feedback.field_label"),
                "type": "textarea",
                "required": False,
                "placeholder": t(locale, "requirements_feedback.placeholder"),
            }
        ],
        "submitText": t(locale, "requirements_feedback.submit"),
        "skipText": t(locale, "requirements_feedback.skip"),
        "promptText": prompt_text.strip(),
        "outputFiles": visible_output_files,
        "returnPhase": return_phase,
        "returnAgent": return_agent,
    }


def _coverage_conflict_payload(
    *,
    locale: Locale,
    conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "confirmationKind": "coverage_conflict",
        "title": t(locale, "coverage_conflict.title"),
        "message": t(locale, "coverage_conflict.message"),
        "conflicts": conflicts,
        "options": [
            {
                "id": "confirm_overwrite",
                "label": t(locale, "coverage_conflict.option.label"),
                "labelEn": "Confirm Overwrite",
                "description": t(locale, "coverage_conflict.option.description"),
                "checked": True,
            }
        ],
        "confirmText": t(locale, "coverage_conflict.confirm"),
        "cancelText": t(locale, "coverage_conflict.cancel"),
    }


async def _latest_artifact_payload(project_id: str) -> dict[str, Any]:
    artifacts = await store.list_artifacts(project_id)
    latest_by_type: dict[str, Any] = {}
    for artifact in artifacts:
        latest_by_type[artifact.type] = artifact.content
    return latest_by_type


async def _current_artifact_conflicts(project_id: str, *, target_types: list[str] | None = None) -> list[dict[str, Any]]:
    project = await store.get_project(project_id)
    if project is None:
        return []
    known_types = target_types or sorted({artifact.type for artifact in await store.list_artifacts(project_id)})
    conflicts: list[dict[str, Any]] = []
    for artifact_type in known_types:
        artifact = await store.get_artifact(project_id, artifact_type, version=project.currentVersion)  # type: ignore[arg-type]
        if artifact is None or artifact.version != project.currentVersion:
            continue
        conflicts.append(
            {
                "id": artifact.type,
                "type": artifact.type,
                "name": artifact.title,
                "version": artifact.version,
            }
        )
    return conflicts


def _artifact_record_metadata(
    artifact_type: str,
    artifact_sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source = artifact_sources.get(artifact_type, {})
    payload = {
        "sourceFiles": list(source.get("sourceFiles") or []),
        "sourceAgent": str(source.get("source") or "unknown"),
        "sourceStatus": str(source.get("status") or "unknown"),
        "artifactKind": "synthesized",
        "displayPath": {
            "prd": "docs/PRD.md",
            "ui": "docs/UI.md",
            "architecture": "docs/Architecture.md",
            "api_spec": "docs/API.yaml",
        }.get(artifact_type, artifact_type),
        "rawSourceAvailable": bool(source.get("sourceFiles")),
    }
    if source.get("model"):
        payload["model"] = str(source["model"])
    return payload


async def _selected_modules_snapshot(project_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": module.id,
            "name": module.name,
            "nameEn": module.nameEn,
            "isSelected": module.isSelected,
        }
        for module in await store.get_modules(project_id)
    ]


async def _state_manifest_for_version(project_id: str, version: int) -> dict[str, Any]:
    """
    接口注释：
    为某个版本重新整理精确快照清单。

    原因注释：
    工作流里同一个版本会分阶段追加 artifacts、代码文件、Agent 原始输出。
    如果不在每次追加后刷新 manifest，历史版本读取就会看不到这些后来补进去的文件。
    """

    artifacts = await store.list_artifacts_for_version(project_id, version)
    code_files = [record for record in await store.list_code_files(project_id, version=version) if record.version == version]
    agent_artifacts = await store.list_agent_artifacts_for_version(project_id, version=version)
    grouped_agent_artifacts: dict[str, list[str]] = {}
    for artifact in agent_artifacts:
        grouped_agent_artifacts.setdefault(artifact.agent, []).append(artifact.fileName)
    return {
        "artifacts": sorted({artifact.type for artifact in artifacts}),
        "codeFiles": sorted({code_file.filePath for code_file in code_files}),
        "agentArtifacts": {
            agent_name: sorted(set(file_names))
            for agent_name, file_names in sorted(grouped_agent_artifacts.items())
        },
    }


async def _refresh_version_snapshot(project_id: str, version: int):
    return await store.update_version_snapshot(
        project_id,
        version,
        state_manifest=await _state_manifest_for_version(project_id, version),
        modules_snapshot=await _selected_modules_snapshot(project_id),
    )


async def _build_ui_generation_inputs(
    *,
    project_id: str,
    version: int,
) -> tuple[str, str]:
    """
    从 requirements_agent 已经落库的真实原始文件里，取出 UI Agent 必需输入。

    当前 UI Agent 真正依赖的是：
    - use_case.md
    - dialog_map.md
    所以这里直接从 agent_artifacts 里拿，不再让后端自己猜内容。
    """

    raw_outputs = {
        artifact.fileName: str(artifact.content or "")
        for artifact in await store.list_agent_artifacts(project_id, version=version, agent_name="requirements_agent")
    }
    use_case_text = raw_outputs.get("use_case.md", "").strip()
    dialog_map_text = raw_outputs.get("dialog_map.md", "").strip()
    if not use_case_text:
        raise RuntimeError("UI Agent requires use_case.md from Requirements Agent, but it is missing.")
    if not dialog_map_text:
        raise RuntimeError("UI Agent requires dialog_map.md from Requirements Agent, but it is missing.")
    return use_case_text, dialog_map_text


def _build_ui_artifact_content_from_files(files: list[dict[str, Any]]) -> str:
    lookup = {
        str(file.get("filePath") or "").strip(): str(file.get("content") or "")
        for file in files
        if str(file.get("filePath") or "").strip()
    }
    sections = ["# UI Draft"]
    page_description_md = lookup.get("page_descriptions.md", "").strip()
    dar_model_md = lookup.get("dar_model.md", "").strip()
    if page_description_md:
        sections.extend(["", page_description_md])
    if dar_model_md:
        sections.extend(["", dar_model_md])
    generated_files = [path for path in lookup if path.startswith("app/")]
    if generated_files:
        sections.extend(["", "## Generated UI Files"])
        sections.extend(f"- `{path}`" for path in sorted(generated_files))
    return "\n".join(sections).strip() + "\n"


async def _generate_code_workspace(
    project_id: str,
    task_id: str,
    *,
    prompt: str,
    selected_modules_payload: list[dict[str, Any]],
    locale: Locale,
    running_message: str,
    completed_message: str,
    step_extra: dict[str, Any] | None = None,
    update_task_phase: bool = True,
) -> float:
    current_project = await store.get_project(project_id)
    if current_project is None:
        return 0.0
    if update_task_phase:
        await _record_pending_agent_artifacts_version(
            project_id,
            task_id,
            pending_version=current_project.currentVersion,
            active_phase="code_generation_started",
            active_agent="coding_agent",
        )
    code_started_at = time.perf_counter()
    await _broadcast_progress(
        project_id,
        task_id,
        phase="code_generation_started",
        status="running",
        progress=88,
        agent_name="coding_agent",
        module_count=len(selected_modules_payload),
    )
    code_generation_log = await _append_process_log(
        project_id,
        task_id,
        phase="code_generation_started",
        task_name=t(locale, "process.code_generation.name"),
        content=running_message,
    )
    code_generation_log_ref = [code_generation_log]
    code_runtime_snapshot = {"identity": None}
    async def handle_coding_usage_snapshot(usage_snapshot: dict[str, Any]) -> None:
        await _record_streaming_usage_snapshot(
            project_id,
            task_id,
            stream_key="coding",
            source_agent="coding_agent",
            usage_snapshot=usage_snapshot,
        )

    async def handle_coding_runtime_event(runtime_event: dict[str, Any]) -> None:
        latest_output_file = str(runtime_event.get("latestOutputFile") or "").strip()
        idle_bucket = _int_value(runtime_event.get("secondsSinceLastOutput")) // 10
        elapsed_bucket = _int_value(runtime_event.get("elapsedSeconds")) // 30
        snapshot_identity = (
            str(runtime_event.get("runtimeState") or ""),
            latest_output_file,
            idle_bucket,
            elapsed_bucket,
        )
        if code_runtime_snapshot["identity"] == snapshot_identity:
            return
        code_runtime_snapshot["identity"] = snapshot_identity

        next_metadata = _merge_process_log_runtime_metadata(
            code_generation_log_ref[0].metadata or None,
            runtime_event=runtime_event,
        )
        if latest_output_file:
            next_metadata = _merge_process_log_output_metadata(
                next_metadata,
                phase="code_generation_started",
                source_agent="coding_agent",
                raw_file_name=latest_output_file,
                output_files=[latest_output_file],
            )

        next_content = code_generation_log_ref[0].content
        if latest_output_file:
            next_content = _format_structured_file_status(
                locale=locale,
                file_name=latest_output_file,
                step_label=None,
                completed=False,
            )

        code_generation_log_ref[0] = await _update_message(
            code_generation_log_ref[0],
            content=next_content,
            metadata=next_metadata,
        )

        await _broadcast_progress(
            project_id,
            task_id,
            phase="code_generation_started",
            status="running",
            progress=90,
            agent_name="coding_agent",
            module_count=len(selected_modules_payload),
            output_hint=latest_output_file,
        )

    code_snapshot = await _run_with_progress_heartbeat(
        project_id,
        task_id,
        phase="code_generation_started",
        initial_progress=88,
        progress_cap=95,
        progress_step=2,
        agent_name="coding_agent",
        module_count=len(selected_modules_payload),
        operation=agent_orchestrator.build_code_files(
            prompt=prompt,
            selected_modules=selected_modules_payload,
            artifacts=await _latest_artifact_payload(project_id),
            locale=locale,
            task_id=task_id,
            status_callback=_process_log_status_callback(
                code_generation_log_ref,
                project_id=project_id,
                task_id=task_id,
                phase="code_generation_started",
                locale=locale,
            ),
            usage_event_callback=handle_coding_usage_snapshot,
            runtime_event_callback=handle_coding_runtime_event,
        ),
    )
    existing_snapshot = [
        {
            "filePath": code_file.filePath,
            "content": code_file.content,
        }
        for code_file in await store.list_code_files(project_id, version=current_project.currentVersion)
    ]
    merged_snapshot = _merge_workspace_files(existing_snapshot, code_snapshot)
    await store.replace_code_files(project_id, current_project.currentVersion, merged_snapshot)
    output_files = await _register_coding_agent_outputs(
        project_id,
        task_id,
        version=current_project.currentVersion,
        archive_stage="coding",
        files=code_snapshot,
    )
    await _refresh_version_snapshot(project_id, current_project.currentVersion)
    code_duration = time.perf_counter() - code_started_at
    code_usage = agent_orchestrator.consume_last_usage_metadata()
    code_remainder_usage = _remaining_usage_after_streaming(
        code_usage,
        await _streaming_usage_snapshot(task_id, "coding"),
    )
    code_accounted_usage = await _reconciled_stage_usage(
        task_id,
        stream_key="coding",
        final_usage=code_usage,
        default_model=agent_orchestrator.get_model_name(),
    )
    code_generation_log_ref[0] = await _update_message(
        code_generation_log_ref[0],
        metadata=_merge_process_log_output_metadata(
            code_generation_log_ref[0].metadata or None,
            phase="code_generation_started",
            source_agent="coding_agent",
            output_files=output_files,
        ),
    )
    await _complete_process_log(
        code_generation_log_ref[0],
        content=completed_message,
        duration=code_duration,
    )
    await _broadcast_progress(
        project_id,
        task_id,
        phase="code_generation_completed",
        status="completed",
        progress=96,
        agent_name="coding_agent",
        output_hint=f"{len(code_snapshot)} files generated",
        module_count=len(selected_modules_payload),
    )
    await store.add_step_record(
        task_id,
        "Generate code workspace",
        "generation",
        duration=code_duration,
        tokens_used=_usage_total_tokens(code_accounted_usage),
        cost=_usage_cost_amount(code_accounted_usage),
        status="completed",
        metadata=_step_usage_metadata(
            usage_metadata=code_accounted_usage,
            default_model=agent_orchestrator.get_model_name(),
            source_agent="coding_agent",
            extra={
                **(step_extra or {}),
                "outputFiles": output_files,
            },
        ),
    )
    stats = await store.get_statistics(task_id)
    if stats is not None:
        await store.update_statistics(
            task_id,
            inputTokens=stats.inputTokens + int((code_remainder_usage or {}).get("inputTokens") or 0),
            outputTokens=stats.outputTokens + int((code_remainder_usage or {}).get("outputTokens") or 0),
            totalTokens=stats.totalTokens + int((code_remainder_usage or {}).get("totalTokens") or 0),
            modelUsed=_usage_model(code_accounted_usage, stats.modelUsed),
            costAmount=stats.costAmount + _usage_cost_amount(code_remainder_usage),
            totalDuration=stats.totalDuration + code_duration,
        )
    return code_duration


async def _generate_test_workspace(
    project_id: str,
    task_id: str,
    *,
    prompt: str,
    selected_modules_payload: list[dict[str, Any]],
    locale: Locale,
    running_message: str,
    completed_message: str,
    step_extra: dict[str, Any] | None = None,
) -> float:
    current_project = await store.get_project(project_id)
    if current_project is None:
        return 0.0

    await _record_pending_agent_artifacts_version(
        project_id,
        task_id,
        pending_version=current_project.currentVersion,
        active_phase="test_generation_started",
        active_agent="test_agent",
    )
    test_started_at = time.perf_counter()
    await _broadcast_progress(
        project_id,
        task_id,
        phase="test_generation_started",
        status="running",
        progress=96,
        agent_name="test_agent",
        module_count=len(selected_modules_payload),
    )
    test_generation_log = await _append_process_log(
        project_id,
        task_id,
        phase="test_generation_started",
        task_name=t(locale, "process.test_generation.name"),
        content=running_message,
    )
    test_generation_log_ref = [test_generation_log]
    test_runtime_snapshot = {"identity": None}
    async def handle_test_usage_snapshot(usage_snapshot: dict[str, Any]) -> None:
        await _record_streaming_usage_snapshot(
            project_id,
            task_id,
            stream_key="test",
            source_agent="test_agent",
            usage_snapshot=usage_snapshot,
        )

    async def handle_test_runtime_event(runtime_event: dict[str, Any]) -> None:
        latest_output_file = str(runtime_event.get("latestOutputFile") or "").strip()
        visible_output_files = (
            _filter_visible_output_files_for_phase("test_generation_started", [latest_output_file])
            if latest_output_file
            else []
        )
        visible_output_file = visible_output_files[-1] if visible_output_files else None
        idle_bucket = _int_value(runtime_event.get("secondsSinceLastOutput")) // 10
        elapsed_bucket = _int_value(runtime_event.get("elapsedSeconds")) // 30
        snapshot_identity = (
            str(runtime_event.get("runtimeState") or ""),
            visible_output_file or "",
            idle_bucket,
            elapsed_bucket,
        )
        if test_runtime_snapshot["identity"] == snapshot_identity:
            return
        test_runtime_snapshot["identity"] = snapshot_identity

        next_metadata = _merge_process_log_runtime_metadata(
            test_generation_log_ref[0].metadata or None,
            runtime_event=runtime_event,
        )
        if visible_output_file:
            next_metadata = _merge_process_log_output_metadata(
                next_metadata,
                phase="test_generation_started",
                source_agent="test_agent",
                raw_file_name=visible_output_file,
                output_files=[visible_output_file],
            )

        next_content = test_generation_log_ref[0].content
        if visible_output_file:
            next_content = _format_structured_file_status(
                locale=locale,
                file_name=visible_output_file,
                step_label=None,
                completed=False,
            )

        test_generation_log_ref[0] = await _update_message(
            test_generation_log_ref[0],
            content=next_content,
            metadata=next_metadata,
        )

        await _broadcast_progress(
            project_id,
            task_id,
            phase="test_generation_started",
            status="running",
            progress=96,
            agent_name="test_agent",
            module_count=len(selected_modules_payload),
            output_hint=visible_output_file,
        )

    existing_snapshot = [
        {
            "filePath": code_file.filePath,
            "content": code_file.content,
        }
        for code_file in await store.list_code_files(project_id, version=current_project.currentVersion)
    ]
    test_snapshot = await _run_with_progress_heartbeat(
        project_id,
        task_id,
        phase="test_generation_started",
        initial_progress=96,
        progress_cap=98,
        progress_step=1,
        agent_name="test_agent",
        module_count=len(selected_modules_payload),
        operation=agent_orchestrator.build_test_files(
            prompt=prompt,
            selected_modules=selected_modules_payload,
            artifacts=await _latest_artifact_payload(project_id),
            code_files=existing_snapshot,
            locale=locale,
            task_id=task_id,
            status_callback=_process_log_status_callback(
                test_generation_log_ref,
                project_id=project_id,
                task_id=task_id,
                phase="test_generation_started",
                locale=locale,
            ),
            usage_event_callback=handle_test_usage_snapshot,
            runtime_event_callback=handle_test_runtime_event,
        ),
    )
    merged_snapshot = _merge_workspace_files(existing_snapshot, test_snapshot)
    await store.replace_code_files(project_id, current_project.currentVersion, merged_snapshot)
    output_files = await _register_workspace_agent_outputs(
        project_id,
        task_id,
        version=current_project.currentVersion,
        agent_name="test_agent",
        archive_stage="test",
        files=test_snapshot,
    )
    await _refresh_version_snapshot(project_id, current_project.currentVersion)
    test_duration = time.perf_counter() - test_started_at
    test_usage = agent_orchestrator.consume_last_usage_metadata()
    test_remainder_usage = _remaining_usage_after_streaming(
        test_usage,
        await _streaming_usage_snapshot(task_id, "test"),
    )
    test_accounted_usage = await _reconciled_stage_usage(
        task_id,
        stream_key="test",
        final_usage=test_usage,
        default_model=agent_orchestrator.get_model_name(),
    )
    await _complete_process_log(
        test_generation_log_ref[0],
        content=completed_message,
        duration=test_duration,
    )
    await _broadcast_progress(
        project_id,
        task_id,
        phase="test_generation_completed",
        status="completed",
        progress=99,
        agent_name="test_agent",
        output_hint=f"{len(test_snapshot)} files generated",
        module_count=len(selected_modules_payload),
    )
    await store.add_step_record(
        task_id,
        "Generate test workspace",
        "generation",
        duration=test_duration,
        tokens_used=_usage_total_tokens(test_accounted_usage),
        cost=_usage_cost_amount(test_accounted_usage),
        status="completed",
        metadata=_step_usage_metadata(
            usage_metadata=test_accounted_usage,
            default_model=agent_orchestrator.get_model_name(),
            source_agent="test_agent",
            extra={
                **(step_extra or {}),
                "outputFiles": output_files,
            },
        ),
    )
    stats = await store.get_statistics(task_id)
    if stats is not None:
        await store.update_statistics(
            task_id,
            inputTokens=stats.inputTokens + int((test_remainder_usage or {}).get("inputTokens") or 0),
            outputTokens=stats.outputTokens + int((test_remainder_usage or {}).get("outputTokens") or 0),
            totalTokens=stats.totalTokens + int((test_remainder_usage or {}).get("totalTokens") or 0),
            modelUsed=_usage_model(test_accounted_usage, stats.modelUsed),
            costAmount=stats.costAmount + _usage_cost_amount(test_remainder_usage),
            totalDuration=stats.totalDuration + test_duration,
        )
    return test_duration


async def _generate_ui_workspace(
    project_id: str,
    task_id: str,
    *,
    prompt: str,
    selected_modules_payload: list[dict[str, Any]],
    locale: Locale,
    running_message: str,
    completed_message: str,
    step_extra: dict[str, Any] | None = None,
) -> float:
    current_project = await store.get_project(project_id)
    if current_project is None:
        return 0.0
    try:
        use_case_text, dialog_map_text = await _build_ui_generation_inputs(
            project_id=project_id,
            version=current_project.currentVersion,
        )
    except RuntimeError:
        logger.warning(
            "UI Agent generation skipped because required requirements outputs are missing. project_id=%s version=%s",
            project_id,
            current_project.currentVersion,
        )
        return 0.0
    await _record_pending_agent_artifacts_version(
        project_id,
        task_id,
        pending_version=current_project.currentVersion,
        active_phase="ui_generation_started",
        active_agent="ui_agent",
    )
    ui_started_at = time.perf_counter()
    await _broadcast_progress(
        project_id,
        task_id,
        phase="ui_generation_started",
        status="running",
        progress=84,
        agent_name="ui_agent",
        module_count=len(selected_modules_payload),
    )
    ui_generation_log = await _append_process_log(
        project_id,
        task_id,
        phase="ui_generation_started",
        task_name=t(locale, "process.ui_generation.name"),
        content=running_message,
    )
    ui_generation_log_ref = [ui_generation_log]
    ui_runtime_snapshot = {"identity": None}
    async def handle_ui_usage_delta(usage_delta: dict[str, Any]) -> None:
        await _record_streaming_usage_delta(
            project_id,
            task_id,
            stream_key="ui",
            source_agent="ui_agent",
            usage_delta=usage_delta,
        )

    async def handle_ui_runtime_event(runtime_event: dict[str, Any]) -> None:
        latest_output_file = str(runtime_event.get("latestOutputFile") or "").strip()
        idle_bucket = _int_value(runtime_event.get("secondsSinceLastOutput")) // 10
        elapsed_bucket = _int_value(runtime_event.get("elapsedSeconds")) // 30
        snapshot_identity = (
            str(runtime_event.get("runtimeState") or ""),
            latest_output_file,
            idle_bucket,
            elapsed_bucket,
        )
        if ui_runtime_snapshot["identity"] == snapshot_identity:
            return
        ui_runtime_snapshot["identity"] = snapshot_identity

        next_metadata = _merge_process_log_runtime_metadata(
            ui_generation_log_ref[0].metadata or None,
            runtime_event=runtime_event,
        )
        if latest_output_file:
            next_metadata = _merge_process_log_output_metadata(
                next_metadata,
                phase="ui_generation_started",
                source_agent="ui_agent",
                raw_file_name=latest_output_file,
                output_files=[latest_output_file],
            )

        next_content = ui_generation_log_ref[0].content
        if latest_output_file:
            next_content = _format_structured_file_status(
                locale=locale,
                file_name=latest_output_file,
                step_label=None,
                completed=False,
            )

        ui_generation_log_ref[0] = await _update_message(
            ui_generation_log_ref[0],
            content=next_content,
            metadata=next_metadata,
        )

        await _broadcast_progress(
            project_id,
            task_id,
            phase="ui_generation_started",
            status="running",
            progress=88,
            agent_name="ui_agent",
            module_count=len(selected_modules_payload),
            output_hint=latest_output_file,
        )

    ui_snapshot = await _run_with_progress_heartbeat(
        project_id,
        task_id,
        phase="ui_generation_started",
        initial_progress=84,
        progress_cap=92,
        progress_step=2,
        agent_name="ui_agent",
        module_count=len(selected_modules_payload),
        operation=agent_orchestrator.build_ui_files(
            prompt=prompt,
            selected_modules=selected_modules_payload,
            artifacts=await _latest_artifact_payload(project_id),
            use_case_text=use_case_text,
            dialog_map_text=dialog_map_text,
            locale=locale,
            task_id=task_id,
            status_callback=_process_log_status_callback(
                ui_generation_log_ref,
                project_id=project_id,
                task_id=task_id,
                phase="ui_generation_started",
                locale=locale,
            ),
            usage_event_callback=handle_ui_usage_delta,
            runtime_event_callback=handle_ui_runtime_event,
        ),
    )
    existing_snapshot = [
        {
            "filePath": code_file.filePath,
            "content": code_file.content,
        }
        for code_file in await store.list_code_files(project_id, version=current_project.currentVersion)
    ]
    merged_snapshot = _merge_workspace_files(existing_snapshot, ui_snapshot)
    await store.replace_code_files(project_id, current_project.currentVersion, merged_snapshot)
    output_files = await _register_workspace_agent_outputs(
        project_id,
        task_id,
        version=current_project.currentVersion,
        agent_name="ui_agent",
        archive_stage="ui",
        files=ui_snapshot,
    )
    await _refresh_version_snapshot(project_id, current_project.currentVersion)
    ui_duration = time.perf_counter() - ui_started_at
    ui_usage = agent_orchestrator.consume_last_usage_metadata()
    ui_remainder_usage = _remaining_usage_after_streaming(
        ui_usage,
        await _streaming_usage_snapshot(task_id, "ui"),
    )
    ui_accounted_usage = await _reconciled_stage_usage(
        task_id,
        stream_key="ui",
        final_usage=ui_usage,
        default_model=agent_orchestrator.get_model_name(),
    )
    await _complete_process_log(
        ui_generation_log_ref[0],
        content=completed_message,
        duration=ui_duration,
    )
    await store.upsert_artifact(
        project_id,
        "ui",
        "UI Draft",
        _build_ui_artifact_content_from_files(ui_snapshot),
        metadata={
            "sourceFiles": output_files,
            "sourceAgent": "ui_agent",
            "sourceStatus": "completed",
            "artifactKind": "synthesized",
            "displayPath": "docs/UI.md",
            "rawSourceAvailable": bool(output_files),
            **({"model": str(ui_usage.get("model") or "")} if ui_usage and ui_usage.get("model") else {}),
        },
    )
    await _broadcast_progress(
        project_id,
        task_id,
        phase="ui_generation_completed",
        status="completed",
        progress=93,
        agent_name="ui_agent",
        output_hint=f"{len(ui_snapshot)} files generated",
        module_count=len(selected_modules_payload),
    )
    await store.add_step_record(
        task_id,
        "Generate UI workspace",
        "generation",
        duration=ui_duration,
        tokens_used=_usage_total_tokens(ui_accounted_usage),
        cost=_usage_cost_amount(ui_accounted_usage),
        status="completed",
        metadata=_step_usage_metadata(
            usage_metadata=ui_accounted_usage,
            default_model=agent_orchestrator.get_model_name(),
            source_agent="ui_agent",
            extra={
                **(step_extra or {}),
                "artifactTypes": ["ui"],
                "outputFiles": output_files,
            },
        ),
    )
    stats = await store.get_statistics(task_id)
    if stats is not None:
        await store.update_statistics(
            task_id,
            inputTokens=stats.inputTokens + int((ui_remainder_usage or {}).get("inputTokens") or 0),
            outputTokens=stats.outputTokens + int((ui_remainder_usage or {}).get("outputTokens") or 0),
            totalTokens=stats.totalTokens + int((ui_remainder_usage or {}).get("totalTokens") or 0),
            modelUsed=_usage_model(ui_accounted_usage, stats.modelUsed),
            costAmount=stats.costAmount + _usage_cost_amount(ui_remainder_usage),
            totalDuration=stats.totalDuration + ui_duration,
        )
    return ui_duration


async def _complete_modify_task(project_id: str, task_id: str, output_data: dict[str, Any]) -> None:
    locale = await _task_locale(task_id)
    await store.update_task(
        task_id,
        status="completed",
        output_data=output_data,
        completed=True,
    )
    await store.touch_project(project_id, status="completed")
    await _broadcast(
        project_id,
        "status_change",
        {"oldStatus": "running", "newStatus": "completed"},
    )
    await _broadcast(
        project_id,
        "task_round_finished",
        {
            "taskId": task_id,
            "status": "completed",
            "createdAt": utc_now().isoformat(),
        },
    )
    await _broadcast_progress(
        project_id,
        task_id,
        phase="task_completed",
        status="completed",
        progress=100,
    )
    await _append_message(
        Message(
            projectId=project_id,
            role="agent",
            type="text",
            content=t(locale, "task.completed.modify"),
            metadata=_task_message_metadata(task_id, task_status="completed"),
        )
    )
    payload = await _statistics_payload(task_id)
    if payload is not None:
        await _broadcast(project_id, "statistics", payload.model_dump(mode="json"))


async def _resume_after_runtime_input(
    project_id: str,
    task_id: str,
    response_payload: dict[str, Any] | None,
) -> None:
    locale = await _task_locale(task_id)
    task_output = await _task_output_data(task_id)
    variables = response_payload.get("variables") if isinstance(response_payload, dict) else None
    runtime_snapshot = _runtime_settings_snapshot()
    if isinstance(variables, dict):
        agent_orchestrator.apply_runtime_variables(variables)

    try:
        next_action = task_output.get("pendingNextAction")
        if not isinstance(next_action, dict):
            raise WorkflowTaskError("CONTEXT_EXPIRED", t(locale, "error.runtime_context_missing"))

        prompt = str(task_output.get("pendingPrompt") or "")
        selected_modules_payload = task_output.get("selectedModulesPayload")
        if not isinstance(selected_modules_payload, list):
            selected_modules_payload = []

        mode = str(next_action.get("mode") or "")
        payload = next_action.get("payload")
        if mode == "complete_task" and isinstance(payload, dict):
            await _generate_ui_workspace(
                project_id,
                task_id,
                prompt=prompt,
                selected_modules_payload=selected_modules_payload,
                locale=locale,
                running_message=t(locale, "process.ui_generation.runtime.running"),
                completed_message=t(locale, "process.ui_generation.runtime.completed"),
                step_extra={"resumedFrom": "input_variables"},
            )
            await _generate_code_workspace(
                project_id,
                task_id,
                prompt=prompt,
                selected_modules_payload=selected_modules_payload,
                locale=locale,
                running_message=t(locale, "process.code_generation.runtime.running"),
                completed_message=t(locale, "process.code_generation.runtime.completed"),
                step_extra={"resumedFrom": "input_variables"},
            )
            await _maybe_generate_test_workspace(
                project_id,
                task_id,
                prompt=prompt,
                selected_modules_payload=selected_modules_payload,
                locale=locale,
                running_message=t(locale, "process.test_generation.runtime.running"),
                completed_message=t(locale, "process.test_generation.runtime.completed"),
                step_extra={"resumedFrom": "input_variables"},
            )
            final_output = dict(payload)
            if isinstance(variables, dict) and variables:
                final_output["runtimeVariablesProvided"] = sorted(variables.keys())
                final_output["runtimeVariablesProvidedAt"] = utc_now().isoformat()
            final_output["uiGeneratedAt"] = utc_now().isoformat()
            final_output["codeGeneratedAt"] = utc_now().isoformat()
            final_output["testGeneratedAt"] = utc_now().isoformat()
            await _complete_modify_task(project_id, task_id, final_output)
            return

        if mode == "start_code_generation":
            await _promote_pending_preview_to_current_version(project_id, task_id)
            await _generate_ui_workspace(
                project_id,
                task_id,
                prompt=prompt,
                selected_modules_payload=selected_modules_payload,
                locale=locale,
                running_message=t(locale, "process.ui_generation.runtime.running"),
                completed_message=t(locale, "process.ui_generation.runtime.completed"),
                step_extra={"resumedFrom": "input_variables"},
            )
            await _generate_code_workspace(
                project_id,
                task_id,
                prompt=prompt,
                selected_modules_payload=selected_modules_payload,
                locale=locale,
                running_message=t(locale, "process.code_generation.runtime.running"),
                completed_message=t(locale, "process.code_generation.runtime.completed"),
                step_extra={"resumedFrom": "input_variables"},
            )
            await _maybe_generate_test_workspace(
                project_id,
                task_id,
                prompt=prompt,
                selected_modules_payload=selected_modules_payload,
                locale=locale,
                running_message=t(locale, "process.test_generation.runtime.running"),
                completed_message=t(locale, "process.test_generation.runtime.completed"),
                step_extra={"resumedFrom": "input_variables"},
            )
            final_output = await _task_output_data(task_id)
            if isinstance(variables, dict) and variables:
                final_output["runtimeVariablesProvided"] = sorted(variables.keys())
                final_output["runtimeVariablesProvidedAt"] = utc_now().isoformat()
            final_output["uiGeneratedAt"] = utc_now().isoformat()
            final_output["codeGeneratedAt"] = utc_now().isoformat()
            final_output["testGeneratedAt"] = utc_now().isoformat()
            await _finalize_generated_artifacts(project_id, task_id, output_data_updates=final_output)
            return

        raise WorkflowTaskError("CONTEXT_EXPIRED", t(locale, "error.runtime_resume_missing"))
    finally:
        _restore_runtime_settings(runtime_snapshot)


async def submit_requirements_feedback(project_id: str, task_id: str, feedback_text: str) -> None:
    locale = await _task_locale(task_id)
    task = await store.get_task(task_id)
    if task is None or task.projectId != project_id:
        raise WorkflowTaskError("CONTEXT_EXPIRED", t(locale, "error.feedback_context_missing"))

    logger.info(
        "[USER ACTION] requirements_feedback_submitted project_id=%s task_id=%s feedback=%s",
        project_id,
        task_id,
        _preview_log_text(feedback_text),
    )

    output_data = await _task_output_data(task_id)
    for key in (
        "confirmationKind",
        "actionType",
        "title",
        "message",
        "variables",
        "submitText",
        "skipText",
        "promptText",
        "outputFiles",
    ):
        output_data.pop(key, None)
    output_data["activePhase"] = str(output_data.get("returnPhase") or "requirements_drafts_started")
    output_data["activeAgent"] = str(output_data.get("returnAgent") or "requirements_agent")
    await store.update_task(task_id, status="running", output_data=output_data)
    await store.touch_project(project_id, status="running")
    await _update_latest_task_phase_process_log(
        project_id,
        task_id,
        phase=str(output_data.get("activePhase") or "requirements_drafts_started"),
        content=t(locale, "process.requirements_drafts.resumed"),
        clear_raw_file_name=True,
    )
    logger.info(
        "[AGENT RESUMED] requirements_agent_feedback project_id=%s task_id=%s return_phase=%s return_agent=%s",
        project_id,
        task_id,
        output_data.get("activePhase"),
        output_data.get("activeAgent"),
    )
    await _broadcast(project_id, "status_change", {"oldStatus": "waiting_user", "newStatus": "running"})
    await _broadcast(
        project_id,
        "agent_waiting",
        {"status": "resumed", "message": t(locale, "requirements_feedback.resumed")},
    )
    if not agent_orchestrator.submit_requirements_feedback(task_id, feedback_text):
        raise WorkflowTaskError("CONTEXT_EXPIRED", t(locale, "error.feedback_session_missing"))


async def _request_runtime_variables_if_needed(
    project_id: str,
    task_id: str,
    *,
    prompt: str,
    selected_modules_payload: list[dict[str, Any]],
    next_action: dict[str, Any],
    runtime_variables: list[dict[str, Any]] | None = None,
) -> bool:
    requested_variables = runtime_variables if runtime_variables is not None else agent_orchestrator.missing_runtime_variables()
    if not requested_variables:
        return False
    locale = await _task_locale(task_id)
    confirmation = _input_variables_confirmation_payload(
        locale=locale,
        prompt=prompt,
        selected_modules_payload=selected_modules_payload,
        next_action=next_action,
        runtime_variables=requested_variables,
    )
    await _append_message(
        Message(
            projectId=project_id,
            role="agent",
            type="input_form",
            content=t(locale, "input_variables.content"),
            metadata={
                **confirmation,
                **_task_message_metadata(task_id, task_status="waiting_user"),
            },
        )
    )
    await _enter_waiting_state(project_id, task_id, confirmation)
    return True


def _waiting_progress_metadata(confirmation: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    confirmation_kind = str(confirmation.get("confirmationKind") or "")
    explicit_phase = str(confirmation.get("activePhase") or "").strip()
    if explicit_phase:
        phase = explicit_phase
    elif confirmation_kind == "input_variables":
        phase = "runtime_input_required"
    elif confirmation_kind == "requirements_feedback":
        phase = "requirements_feedback_required"
    elif confirmation_kind == "coverage_conflict":
        phase = "waiting_for_overwrite_confirmation"
    elif confirmation_kind == "artifact_review":
        phase = "waiting_for_artifact_review"
    else:
        phase = "waiting_for_module_confirmation"

    metadata: dict[str, Any] = {
        "confirmation_kind": confirmation_kind or None,
    }
    options = confirmation.get("options")
    if isinstance(options, list) and phase == "waiting_for_module_confirmation":
        metadata["module_count"] = len(options)
    selected_module_ids = confirmation.get("selectedModuleIds")
    if isinstance(selected_module_ids, list):
        metadata["module_count"] = len(selected_module_ids)
    reference_files = confirmation.get("referenceFiles")
    if isinstance(reference_files, list):
        metadata["reference_count"] = len(reference_files)
    return phase, metadata


def _waiting_process_log_details(locale: Locale, phase: str) -> tuple[str, str] | None:
    """
    接口注释：
    为“等待用户确认”的关键阶段生成单独的 process_log 文案。

    设计注释：
    之前 Requirements / Architecture 在产物已经全部写完后，会继续广播 artifact_update。
    但如果没有新的“人类可读日志”覆盖最后一条生成中文案，界面上就会一直残留
    “正在生成 xxx.md / 已生成 xxx.md” 这种旧提示，用户很难判断 Agent 现在
    到底是在等确认，还是还在生成文件。
    """

    if phase == "waiting_for_requirements_artifact_review":
        return (
            t(locale, "process.requirements_artifact_review.name"),
            t(locale, "process.requirements_artifact_review.waiting"),
        )
    if phase == "waiting_for_artifact_review":
        return (
            t(locale, "process.artifact_review.name"),
            t(locale, "process.artifact_review.waiting"),
        )
    return None


def _interaction_confirmation_payload(message: Message | None) -> dict[str, Any] | None:
    if message is None or message.type not in {"select_options", "input_form"}:
        return None
    if not isinstance(message.metadata, dict):
        return None

    confirmation = dict(message.metadata)
    confirmation_kind = str(confirmation.get("confirmationKind") or "").strip()
    if not confirmation_kind:
        return None

    # 接口注释：
    # 消息 metadata 里既有“确认卡真实内容”，也有 taskId、taskStatus 这类消息外壳字段。
    # 这里把外壳字段剥掉，只保留真正能恢复等待态的确认载荷。
    for transient_key in ("taskId", "taskName", "taskRoundRole", "taskStatus", "phase", "status"):
        confirmation.pop(transient_key, None)
    return confirmation


async def restore_waiting_task_from_interaction_message(project_id: str, task_id: str) -> bool:
    """
    接口注释：
    当确认卡已经写入消息表，但任务状态还停留在 running 时，
    用最新的交互消息把任务恢复回 waiting_user。

    原因注释：
    等待卡消息和任务状态切换不是同一条数据库写入。
    用户点得很快，或者服务刚好在这两步之间重启时，就会出现
    “界面已经看到确认卡，但后端仍认为任务在 running”的错位。
    """

    task = await store.get_task(task_id)
    if task is None or task.projectId != project_id or task.status != "running":
        return False
    task_output_data = task.outputData if isinstance(task.outputData, dict) else {}
    if task_output_data.get("confirmationAcceptedAt"):
        return False

    interaction_message = await store.get_latest_task_interaction_message(project_id, task_id)
    confirmation = _interaction_confirmation_payload(interaction_message)
    if confirmation is None:
        return False

    phase, _ = _waiting_progress_metadata(confirmation)
    output_data = await _merge_task_output(task_id, **confirmation)
    output_data.setdefault("activePhase", phase)
    output_data.setdefault("activeAgent", _phase_agent_name(phase))
    if "agentOutputsReady" not in output_data:
        current_project = await store.get_project(project_id)
        version = current_project.currentVersion if current_project is not None else None
        output_data["agentOutputsReady"] = sorted(
            {
                artifact.agent
                for artifact in await store.list_agent_artifacts(project_id, version=version)
            }
        )

    await store.update_task(task_id, status="waiting_user", output_data=output_data)
    await store.touch_project(project_id, status="waiting_user")
    logger.warning(
        "Recovered waiting task state from interaction message. project_id=%s task_id=%s confirmation_kind=%s phase=%s message_id=%s",
        project_id,
        task_id,
        str(confirmation.get("confirmationKind") or ""),
        phase,
        interaction_message.id if interaction_message is not None else "-",
    )
    return True


async def _enter_waiting_state(project_id: str, task_id: str, confirmation: dict[str, Any]) -> None:
    locale = await _task_locale(task_id)
    phase, metadata = _waiting_progress_metadata(confirmation)
    output_data = await _merge_task_output(task_id, **confirmation)
    output_data.setdefault("activePhase", phase)
    output_data.setdefault("activeAgent", _phase_agent_name(phase))
    if "agentOutputsReady" not in output_data:
        current_project = await store.get_project(project_id)
        version = current_project.currentVersion if current_project is not None else None
        output_data["agentOutputsReady"] = sorted(
            {
                artifact.agent
                for artifact in await store.list_agent_artifacts(project_id, version=version)
            }
        )
    waiting_log_details = _waiting_process_log_details(locale, phase)
    if waiting_log_details is not None:
        waiting_log = await _append_process_log(
            project_id,
            task_id,
            phase=phase,
            task_name=waiting_log_details[0],
            content=waiting_log_details[1],
        )
        waiting_output_files = [str(item) for item in confirmation.get("outputFiles") or [] if str(item).strip()]
        if waiting_output_files:
            await _update_message(
                waiting_log,
                metadata=_merge_process_log_output_metadata(
                    waiting_log.metadata or None,
                    source_agent=str(output_data.get("activeAgent") or _phase_agent_name(phase)),
                    output_files=waiting_output_files,
                ),
            )
    await store.update_task(task_id, status="waiting_user", output_data=output_data)
    await store.touch_project(project_id, status="waiting_user")
    confirmation_kind = str(confirmation.get("confirmationKind") or "")
    event_type = "agent_require_input" if confirmation_kind in {"input_variables", "requirements_feedback"} else "agent_require_action"
    action_type = str(
        confirmation.get("actionType")
        or (
            "input_variables"
            if confirmation_kind == "input_variables"
            else "input_form"
            if confirmation_kind == "requirements_feedback"
            else "select_options"
        )
    )
    logger.info(
        "[AGENT WAITING] project_id=%s task_id=%s phase=%s confirmation_kind=%s action_type=%s title=%s output_files=%s",
        project_id,
        task_id,
        phase,
        confirmation_kind,
        action_type,
        _preview_log_text(str(confirmation.get("title") or "")),
        [str(item) for item in confirmation.get("outputFiles") or [] if str(item).strip()],
    )
    await _broadcast(
        project_id,
        event_type,
        {
            "actionType": action_type,
            **confirmation,
            "taskId": task_id,
        },
    )
    await _broadcast(
        project_id,
        "status_change",
        {"oldStatus": "running", "newStatus": "waiting_user"},
    )
    await _broadcast(
        project_id,
        "agent_waiting",
        {"status": "waiting", "message": t(locale, "waiting.message")},
    )
    await _broadcast(
        project_id,
        "task_waiting_for_user",
        {
            "taskId": task_id,
            "confirmationKind": confirmation_kind or None,
            "actionType": action_type,
            "createdAt": utc_now().isoformat(),
        },
    )
    await _broadcast_progress(
        project_id,
        task_id,
        phase=phase,
        status="waiting",
        progress=100,
        agent_name=str(output_data.get("activeAgent") or _phase_agent_name(phase)),
        module_count=metadata.get("module_count"),
        reference_count=metadata.get("reference_count"),
        confirmation_kind=metadata.get("confirmation_kind"),
    )


async def _finalize_generated_artifacts(
    project_id: str,
    task_id: str,
    *,
    output_data_updates: dict[str, Any] | None = None,
) -> None:
    locale = await _task_locale(task_id)
    output_data = await _task_output_data(task_id)
    output_data["reviewConfirmedAt"] = output_data.get("reviewConfirmedAt") or utc_now().isoformat()
    if output_data_updates:
        output_data.update(output_data_updates)
    project = await store.get_project(project_id)
    created_version = None
    if project is not None and await store.get_version_record(project_id, project.currentVersion) is None:
        source_version = output_data.get("codeGenerationSourceVersion")
        if not isinstance(source_version, int) or source_version < 1:
            source_version = max(1, project.currentVersion - 1)
        changes: list[dict[str, Any]] = []
        for artifact in await store.list_artifacts_for_version(project_id, project.currentVersion):
            changes.append({"file": artifact.title, "status": "Added"})
        for code_file in await store.list_code_files(project_id, version=project.currentVersion):
            if code_file.version != project.currentVersion:
                continue
            changes.append({"file": f"workspace/{code_file.filePath}", "status": "Added"})
        created_version = await store.create_version(
            project_id,
            "Generated the approved code workspace.",
            changes,
            version_kind="generation",
            source_version=source_version,
            created_by_type="agent",
            created_by=str(output_data.get("activeAgent") or "coding_agent"),
            state_manifest=await _state_manifest_for_version(project_id, project.currentVersion),
            modules_snapshot=await _selected_modules_snapshot(project_id),
        )
    current_task = await store.get_task(task_id)
    previous_status = current_task.status if current_task is not None else "running"
    await store.update_task(task_id, status="completed", output_data=output_data, completed=True)
    await store.touch_project(project_id, status="completed")
    stats = await store.get_statistics(task_id)
    if stats is not None and stats.completedAt is None:
        await store.update_statistics(task_id, completedAt=utc_now())
    await _append_message(
        Message(
            projectId=project_id,
            role="agent",
            type="text",
            content=t(locale, "task.completed.review"),
            metadata=_task_message_metadata(task_id, task_status="completed"),
        )
    )
    await _broadcast(
        project_id,
        "status_change",
        {"oldStatus": previous_status, "newStatus": "completed"},
    )
    await _broadcast(
        project_id,
        "task_round_finished",
        {
            "taskId": task_id,
            "status": "completed",
            "createdAt": utc_now().isoformat(),
        },
    )
    await _broadcast_progress(
        project_id,
        task_id,
        phase="artifact_review_completed",
        status="completed",
        progress=100,
    )
    if created_version is not None:
        await _broadcast(
            project_id,
            "version_update",
            created_version.model_dump(mode="json"),
        )
    payload = await _statistics_payload(task_id)
    if payload is not None:
        await _broadcast(project_id, "statistics", payload.model_dump(mode="json"))


async def _selected_modules_payload_for_resume(project_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": module.id,
            "label": module.name,
            "labelEn": module.nameEn,
        }
        for module in await store.get_modules(project_id)
        if module.isSelected
    ]


async def _resume_generate_flow_from_stage(
    project_id: str,
    task_id: str,
    *,
    prompt: str,
    start_stage: str,
) -> None:
    """
    接口注释：
    这是主生成链路的“阶段级续跑入口”。

    这里不会尝试恢复运行中内存，只会根据数据库里已经确认存在的上下文，
    从某个阶段重新进入后续流程。
    """

    locale = await _task_locale(task_id)
    selected_modules_payload = await _selected_modules_payload_for_resume(project_id)
    selected_module_ids = [module["id"] for module in selected_modules_payload if module.get("id")]

    if start_stage == "requirements_drafts":
        await continue_after_confirmation(project_id, task_id, selected_module_ids)
        return

    if start_stage == "architecture":
        await store.update_task(
            task_id,
            output_data={
                **await _task_output_data(task_id),
                "confirmationKind": "artifact_review",
                "activePhase": "waiting_for_requirements_artifact_review",
                "selectedModuleIds": selected_module_ids,
            },
        )
        await continue_after_confirmation(project_id, task_id, [])
        return

    # 设计注释：
    # 从 UI / Coding / Test 续跑时，说明 requirements 和 architecture 都已经可靠完成了。
    # 所以下面直接重建后续阶段，不再回到前面的确认卡。
    if start_stage in {"ui", "coding", "test"}:
        if start_stage == "ui":
            await _generate_ui_workspace(
                project_id,
                task_id,
                prompt=prompt,
                selected_modules_payload=selected_modules_payload,
                locale=locale,
                running_message=t(locale, "process.ui_generation.review.running"),
                completed_message=t(locale, "process.ui_generation.review.completed"),
                step_extra={"resumedFrom": "retry_from_checkpoint"},
            )
        if start_stage in {"ui", "coding"}:
            await _generate_code_workspace(
                project_id,
                task_id,
                prompt=prompt,
                selected_modules_payload=selected_modules_payload,
                locale=locale,
                running_message=t(locale, "process.code_generation.review.running"),
                completed_message=t(locale, "process.code_generation.review.completed"),
                step_extra={"resumedFrom": "retry_from_checkpoint"},
                update_task_phase=True,
            )
        await _generate_test_workspace(
            project_id,
            task_id,
            prompt=prompt,
            selected_modules_payload=selected_modules_payload,
            locale=locale,
            running_message=t(locale, "process.test_generation.review.running"),
            completed_message=t(locale, "process.test_generation.review.completed"),
            step_extra={"resumedFrom": "retry_from_checkpoint"},
        )
        await _finalize_generated_artifacts(
            project_id,
            task_id,
            output_data_updates={
                "resumeFromStage": start_stage,
                "uiGeneratedAt": utc_now().isoformat() if start_stage == "ui" else (await _task_output_data(task_id)).get("uiGeneratedAt"),
                "codeGeneratedAt": utc_now().isoformat() if start_stage in {"ui", "coding"} else (await _task_output_data(task_id)).get("codeGeneratedAt"),
                "testGeneratedAt": utc_now().isoformat(),
            },
        )
        return

    raise WorkflowTaskError("CONTEXT_EXPIRED", f"Unsupported resume stage `{start_stage}`.")


async def start_generate_flow(
    project_id: str,
    task_id: str,
    prompt: str,
    uploaded_files: list[str],
    *,
    start_stage: str | None = None,
) -> None:
    async with _get_workflow_semaphore():
        await _start_generate_flow_inner(
            project_id, task_id, prompt, uploaded_files, start_stage=start_stage,
        )


async def _start_generate_flow_inner(
    project_id: str,
    task_id: str,
    prompt: str,
    uploaded_files: list[str],
    *,
    start_stage: str | None = None,
) -> None:
    try:
        flow_started_at = time.perf_counter()
        locale = await _task_locale(task_id)
        logger.info(
            "[AGENT FLOW] start_generate_flow project_id=%s task_id=%s prompt=%s uploaded_files=%s start_stage=%s",
            project_id,
            task_id,
            _preview_log_text(prompt),
            len(uploaded_files),
            start_stage or "requirements_analysis",
        )
        await store.create_statistics(project_id, task_id, model_used=agent_orchestrator.get_model_name())
        if start_stage and start_stage != "requirements_analysis":
            await _inherit_completed_steps_from_parent_task(task_id, start_stage)
            await _resume_generate_flow_from_stage(
                project_id,
                task_id,
                prompt=prompt,
                start_stage=start_stage,
            )
            stats = await store.get_statistics(task_id)
            if stats is not None:
                await store.update_statistics(task_id, totalDuration=time.perf_counter() - flow_started_at)
            payload = await _statistics_payload(task_id)
            if payload is not None:
                await _broadcast(project_id, "statistics", payload.model_dump(mode="json"))
            return

        reference_materials, analysis_reference_details = await _prepare_analysis_reference_materials(uploaded_files)
        reference_snapshot = await _reference_snapshot(uploaded_files, analysis_details=analysis_reference_details)
        image_summary_failures = await _image_reference_failures(uploaded_files, analysis_reference_details)
        await _broadcast_progress(
            project_id,
            task_id,
            phase="queued",
            status="running",
            progress=5,
            reference_count=len(reference_snapshot),
        )
        pipeline_task = await store.create_generation_task(project_id, "Analyzing input")
        pipeline_task = await store.update_generation_task(pipeline_task.id, project_id, status="running", progress=20)
        await _broadcast(project_id, "task_update", pipeline_task.model_dump(mode="json"))

        anchor_message = await _append_message(
            Message(
                projectId=project_id,
                role="user",
                type="text",
                content=prompt,
                metadata=_task_message_metadata(task_id, task_round_role="anchor"),
            )
        )
        await _broadcast(
            project_id,
            "task_round_started",
            {
                "taskId": task_id,
                "anchorMessageId": anchor_message.id,
                "prompt": prompt,
                "createdAt": anchor_message.createdAt.isoformat(),
            },
        )
        reading_context_log = await _append_process_log(
            project_id,
            task_id,
            phase="reading_context",
            task_name=t(locale, "process.reading_context.name"),
            content=t(locale, "process.reading_context.running"),
        )
        await _broadcast_progress(
            project_id,
            task_id,
            phase="reading_context",
            status="running",
            progress=15,
            reference_count=len(reference_snapshot),
        )
        await _complete_process_log(
            reading_context_log,
            content=t(locale, "process.reading_context.completed"),
        )
        if image_summary_failures:
            image_summary_warning_log = await _append_process_log(
                project_id,
                task_id,
                phase="reading_context",
                task_name=t(locale, "process.reading_context.name"),
                content=_image_summary_failure_message(locale, image_summary_failures),
            )
            await _complete_process_log(
                image_summary_warning_log,
                content=_image_summary_failure_message(locale, image_summary_failures),
            )
        analysis_log = await _append_process_log(
            project_id,
            task_id,
            phase="requirements_analysis",
            task_name=t(locale, "process.requirements_analysis.name"),
            content=t(locale, "process.requirements_analysis.running"),
        )
        analysis_log_ref = [analysis_log]
        await _broadcast_progress(
            project_id,
            task_id,
            phase="requirements_analysis",
            status="running",
            progress=35,
            reference_count=len(reference_snapshot),
        )
        analysis_started_at = time.perf_counter()

        async def handle_analysis_usage_delta(usage_delta: dict[str, Any]) -> None:
            await _record_streaming_usage_delta(
                project_id,
                task_id,
                stream_key="requirements_analysis",
                source_agent="requirements_agent",
                usage_delta=usage_delta,
            )

        analysis = await _run_with_progress_heartbeat(
            project_id,
            task_id,
            phase="requirements_analysis",
            initial_progress=35,
            progress_cap=82,
            progress_step=8,
            reference_count=len(reference_snapshot),
            operation=agent_orchestrator.analyze_prompt(
                prompt,
                reference_materials,
                locale=locale,
                status_callback=_process_log_status_callback(
                    analysis_log_ref,
                    project_id=project_id,
                    task_id=task_id,
                    phase="requirements_analysis",
                    locale=locale,
                ),
                usage_event_callback=handle_analysis_usage_delta,
            ),
        )
        analysis_duration = time.perf_counter() - analysis_started_at
        analysis_usage = agent_orchestrator.consume_last_usage_metadata()
        analysis_remainder_usage = _remaining_usage_after_streaming(
            analysis_usage,
            await _streaming_usage_snapshot(task_id, "requirements_analysis"),
        )
        analysis_accounted_usage = await _reconciled_stage_usage(
            task_id,
            stream_key="requirements_analysis",
            final_usage=analysis_usage,
            default_model=_usage_model(analysis_usage, agent_orchestrator.get_model_name()),
        )
        modules = analysis["modules"]
        analysis_meta = analysis.get("_meta") if isinstance(analysis.get("_meta"), dict) else {}
        _analysis_project = await store.get_project(project_id)
        analysis_output_files = await _register_agent_output_dir(
            project_id,
            task_id,
            version=_analysis_project.currentVersion if _analysis_project is not None else 1,
            agent_name=str(analysis_meta.get("source") or "requirements_agent"),
            archive_stage="requirements-analysis",
            output_dir=str(analysis_meta.get("outputDir") or ""),
            source_files_by_artifact=analysis_meta.get("sourceFilesByArtifact") if isinstance(analysis_meta.get("sourceFilesByArtifact"), dict) else None,
        )
        visible_analysis_output_files = _filter_visible_output_files_for_phase(
            "requirements_analysis",
            analysis_output_files,
        )
        await store.replace_modules(project_id, modules)
        analysis_log_ref[0] = await _complete_process_log(
            analysis_log_ref[0],
            content=t(locale, "process.requirements_analysis.completed"),
            duration=analysis_duration,
        )
        analysis_log_ref[0] = await _update_message(
            analysis_log_ref[0],
            metadata=_merge_process_log_output_metadata(
                analysis_log_ref[0].metadata or None,
                source_agent=str(analysis_meta.get("source") or "requirements_agent"),
                output_files=visible_analysis_output_files,
            ),
        )
        await store.add_step_record(
            task_id,
            "Analyze requirements",
            "process_log",
            duration=analysis_duration,
            tokens_used=_usage_total_tokens(analysis_accounted_usage),
            cost=_usage_cost_amount(analysis_accounted_usage),
            status="completed",
            metadata=_step_usage_metadata(
                usage_metadata=analysis_accounted_usage,
                default_model=agent_orchestrator.get_model_name(),
                source_agent=str(analysis_meta.get("source") or "requirements_agent"),
                extra={"outputFiles": visible_analysis_output_files},
            ),
        )
        pipeline_task = await store.update_generation_task(pipeline_task.id, project_id, status="completed", progress=100)
        reconciled_analysis_usage = _merge_usage_metadata(
            await _streaming_usage_snapshot(task_id, "requirements_analysis"),
            analysis_remainder_usage,
            fallback_model=_usage_model(analysis_usage, agent_orchestrator.get_model_name()),
        )
        await store.update_statistics(
            task_id,
            itemsRead=max(1, len(reference_materials)),
            **_apply_usage_metadata(
                task_id,
                reconciled_analysis_usage,
                default_model=_usage_model(analysis_usage, agent_orchestrator.get_model_name()),
            ),
        )
        await _broadcast(project_id, "task_update", pipeline_task.model_dump(mode="json"))
        await _broadcast_progress(
            project_id,
            task_id,
            phase="modules_ready",
            status="completed",
            progress=90,
            module_count=len(modules),
            reference_count=len(reference_snapshot),
        )

        confirmation = {
            "title": t(locale, "feature_modules.title"),
            "message": analysis["summary"],
            "options": modules,
            "confirmText": t(locale, "feature_modules.confirm"),
            "cancelText": t(locale, "feature_modules.cancel"),
            "referenceFiles": reference_snapshot,
            "taskId": task_id,
            "activeAgent": "requirements_agent",
            "activePhase": "waiting_for_module_confirmation",
            "agentOutputsReady": sorted(
                {
                    artifact.agent
                    for artifact in await store.list_agent_artifacts(
                        project_id,
                        version=_analysis_project.currentVersion if _analysis_project is not None else None,
                    )
                }
            ),
        }
        if analysis_meta.get("source"):
            confirmation["analysisSource"] = str(analysis_meta["source"])
        if analysis_meta.get("reason"):
            confirmation["analysisReason"] = str(analysis_meta["reason"])
        await _append_message(
            Message(
                projectId=project_id,
                role="agent",
                type="select_options",
                content=t(locale, "feature_modules.content"),
                metadata={
                    **confirmation,
                    **_task_message_metadata(task_id, task_status="waiting_user"),
                },
            )
        )
        await _enter_waiting_state(project_id, task_id, confirmation)
        await store.update_statistics(task_id, totalDuration=time.perf_counter() - flow_started_at)
        stats = await _statistics_payload(task_id)
        if stats is not None:
            await _broadcast(project_id, "statistics", stats.model_dump(mode="json"))
    except Exception as exc:
        await _handle_task_exception(project_id, task_id, exc)


async def continue_after_confirmation(
    project_id: str,
    task_id: str,
    selected_ids: list[str],
    response_payload: dict[str, Any] | None = None,
    user_note: str | None = None,
) -> None:
    async with _get_workflow_semaphore():
        await _continue_after_confirmation_inner(
            project_id, task_id, selected_ids,
            response_payload=response_payload, user_note=user_note,
        )


async def _continue_after_confirmation_inner(
    project_id: str,
    task_id: str,
    selected_ids: list[str],
    response_payload: dict[str, Any] | None = None,
    user_note: str | None = None,
) -> None:
    try:
        flow_started_at = time.perf_counter()
        locale = await _task_locale(task_id)
        confirmation_kind = await _confirmation_kind(task_id)
        logger.info(
            "[USER ACTION] continue_after_confirmation project_id=%s task_id=%s confirmation_kind=%s selected_ids=%s user_note=%s",
            project_id,
            task_id,
            confirmation_kind,
            selected_ids,
            _preview_log_text(user_note),
        )
        if confirmation_kind == "artifact_review":
            task = await store.get_task(task_id)
            output_data = await _task_output_data(task_id)
            active_phase = str(output_data.get("activePhase") or "")
            selected_module_ids = output_data.get("selectedModuleIds")
            if not isinstance(selected_module_ids, list):
                selected_module_ids = []
            pending_runtime_variables = output_data.get("pendingRuntimeVariables")
            if not isinstance(pending_runtime_variables, list):
                pending_runtime_variables = None
            selected_modules_payload = [
                {
                    "id": module.id,
                    "label": module.name,
                    "labelEn": module.nameEn,
                }
                for module in await store.get_modules(project_id)
                if not selected_module_ids or module.id in selected_module_ids
            ]
            await store.update_task(task_id, status="running")
            await _broadcast(
                project_id,
                "status_change",
                {"oldStatus": "waiting_user", "newStatus": "running"},
            )
            prompt = str(task.inputData.get("prompt", "")) if task is not None else ""
            if active_phase == "waiting_for_requirements_artifact_review":
                uploaded_files = task.inputData.get("uploadedFiles", []) if task else []
                reference_materials = await _reference_materials(uploaded_files if isinstance(uploaded_files, list) else [])
                reference_snapshot = await _reference_snapshot(uploaded_files if isinstance(uploaded_files, list) else [])
                current_project = await store.get_project(project_id)
                previous_version = current_project.currentVersion if current_project is not None else 1
                requirements_preview_version = await _pending_preview_version(project_id, task_id)
                requirements_sources = output_data.get("artifactSources") if isinstance(output_data.get("artifactSources"), dict) else {}
                requirements_payload = await _build_requirements_payload_from_agent_artifacts(
                    project_id=project_id,
                    version=requirements_preview_version,
                    prompt=prompt,
                    selected_modules=selected_modules_payload,
                    source_files_by_artifact={
                        artifact_type: list(
                            (
                                requirements_sources.get(artifact_type, {})
                                if isinstance(requirements_sources.get(artifact_type), dict)
                                else {}
                            ).get("sourceFiles")
                            or []
                        )
                        for artifact_type in ("prd", "ui", "api_spec")
                    },
                )
                existing_artifacts = [
                    {
                        "id": f"requirements:{artifact_type}:{previous_version}",
                        "type": artifact_type,
                        "title": {
                            "prd": "PRD Draft",
                            "ui": "UI Draft",
                            "api_spec": "API Design",
                        }[artifact_type],
                        "version": requirements_preview_version,
                        "content": str(requirements_payload.get(artifact_type) or ""),
                    }
                    for artifact_type in ("prd", "ui", "api_spec")
                    if str(requirements_payload.get(artifact_type) or "").strip()
                ]
                pending_agent_artifact_version = requirements_preview_version
                await _record_pending_agent_artifacts_version(
                    project_id,
                    task_id,
                    pending_version=pending_agent_artifact_version,
                    active_phase="architecture_generation_started",
                    active_agent="architecture_agent",
                )
                await _broadcast_progress(
                    project_id,
                    task_id,
                    phase="architecture_generation_started",
                    status="running",
                    progress=72,
                    module_count=len(selected_modules_payload),
                    reference_count=len(reference_snapshot),
                )
                architecture_log = await _append_process_log(
                    project_id,
                    task_id,
                    phase="architecture_generation_started",
                    task_name=t(locale, "process.architecture_generation.name"),
                    content=t(locale, "process.architecture_generation.running"),
                )
                architecture_log_ref = [architecture_log]
                architecture_runtime_snapshot = {"identity": None}
                architecture_live_output_snapshot = {"identity": None}
                architecture_started_at = time.perf_counter()
                async def handle_architecture_usage_snapshot(usage_snapshot: dict[str, Any]) -> None:
                    await _record_streaming_usage_snapshot(
                        project_id,
                        task_id,
                        stream_key="architecture",
                        source_agent="architecture_agent",
                        usage_snapshot=usage_snapshot,
                    )

                async def handle_architecture_runtime_event(runtime_event: dict[str, Any]) -> None:
                    output_dir_value = str(runtime_event.get("outputDir") or "").strip()
                    live_output_files: list[str] = []
                    latest_visible_live_output_file: str | None = None
                    if output_dir_value:
                        output_root = Path(output_dir_value)
                        # 设计注释：
                        # 架构阶段真实文件写在 Architecture Agent 自己的输出目录里。
                        # 这里只要发现目录里多了文件，就立刻把当前快照登记进数据库并广播给前端，
                        # 避免用户一定要等架构阶段结束，工作台文件列表才一起跳出来。
                        live_output_files = (
                            await asyncio.to_thread(_list_relative_output_files, output_root)
                            if output_root.exists() and output_root.is_dir()
                            else []
                        )
                        latest_visible_live_output_file = await asyncio.to_thread(
                            _latest_visible_output_file_in_dir,
                            phase="architecture_generation_started",
                            output_dir=output_root,
                        )
                        live_output_identity = (str(output_root.resolve()), tuple(live_output_files))
                        if (
                            live_output_files
                            and architecture_live_output_snapshot["identity"] != live_output_identity
                        ):
                            architecture_live_output_snapshot["identity"] = live_output_identity
                            await _register_live_agent_output_dir(
                                project_id,
                                task_id,
                                version=pending_agent_artifact_version,
                                agent_name="architecture_agent",
                                archive_stage="architecture",
                                output_dir=output_dir_value,
                            )
                            await _record_pending_agent_artifacts_version(
                                project_id,
                                task_id,
                                pending_version=pending_agent_artifact_version,
                                active_phase="architecture_generation_started",
                                active_agent="architecture_agent",
                            )

                    latest_output_file = str(runtime_event.get("latestOutputFile") or "").strip()
                    visible_output_files = (
                        _filter_visible_output_files_for_phase("architecture_generation_started", [latest_output_file])
                        if latest_output_file
                        else []
                    )
                    visible_output_file = (
                        visible_output_files[-1]
                        if visible_output_files
                        else latest_visible_live_output_file
                    )
                    idle_bucket = _int_value(runtime_event.get("secondsSinceLastOutput")) // 10
                    elapsed_bucket = _int_value(runtime_event.get("elapsedSeconds")) // 30
                    snapshot_identity = (
                        str(runtime_event.get("runtimeState") or ""),
                        visible_output_file or "",
                        idle_bucket,
                        elapsed_bucket,
                    )
                    if architecture_runtime_snapshot["identity"] == snapshot_identity:
                        return
                    architecture_runtime_snapshot["identity"] = snapshot_identity

                    next_metadata = _merge_process_log_runtime_metadata(
                        architecture_log_ref[0].metadata or None,
                        runtime_event=runtime_event,
                    )
                    if live_output_files:
                        next_metadata = _merge_process_log_output_metadata(
                            next_metadata,
                            phase="architecture_generation_started",
                            source_agent="architecture_agent",
                            raw_file_name=visible_output_file or latest_output_file,
                            output_files=live_output_files,
                        )
                    elif visible_output_file:
                        next_metadata = _merge_process_log_output_metadata(
                            next_metadata,
                            phase="architecture_generation_started",
                            source_agent="architecture_agent",
                            raw_file_name=visible_output_file,
                            output_files=[visible_output_file],
                        )

                    next_content = architecture_log_ref[0].content
                    if visible_output_file:
                        next_content = _format_structured_file_status(
                            locale=locale,
                            file_name=visible_output_file,
                            step_label=None,
                            completed=False,
                        )

                    architecture_log_ref[0] = await _update_message(
                        architecture_log_ref[0],
                        content=next_content,
                        metadata=next_metadata,
                    )

                    if visible_output_file:
                        await _broadcast_progress(
                            project_id,
                            task_id,
                            phase="architecture_generation_started",
                            status="running",
                            progress=72,
                            agent_name="architecture_agent",
                            output_hint=visible_output_file,
                            raw_file_name=visible_output_file,
                            module_count=len(selected_modules_payload),
                            reference_count=len(reference_snapshot),
                        )

                architecture_payload = await _run_with_progress_heartbeat(
                    project_id,
                    task_id,
                    phase="architecture_generation_started",
                    initial_progress=72,
                    progress_cap=88,
                    progress_step=4,
                    module_count=len(selected_modules_payload),
                    reference_count=len(reference_snapshot),
                    operation=_await_architecture_draft_or_recover_from_live_outputs(
                        project_id,
                        task_id,
                        pending_version=pending_agent_artifact_version,
                        operation=agent_orchestrator.build_architecture_draft(
                            prompt=prompt,
                            selected_modules=selected_modules_payload,
                            reference_materials=reference_materials,
                            existing_artifacts=existing_artifacts,
                            locale=locale,
                            task_id=task_id,
                            status_callback=_process_log_status_callback(
                                architecture_log_ref,
                                project_id=project_id,
                                task_id=task_id,
                                phase="architecture_generation_started",
                                locale=locale,
                            ),
                            usage_event_callback=handle_architecture_usage_snapshot,
                            runtime_event_callback=handle_architecture_runtime_event,
                        ),
                    ),
                )
                recovered_architecture_output_files: list[str] | None = None
                architecture_recovered_from_live_outputs = False
                if isinstance(architecture_payload, tuple):
                    architecture_payload, recovered_architecture_output_files, architecture_recovered_from_live_outputs = architecture_payload
                architecture_duration = time.perf_counter() - architecture_started_at
                architecture_usage = agent_orchestrator.consume_last_usage_metadata()
                architecture_remainder_usage = _remaining_usage_after_streaming(
                    architecture_usage,
                    await _streaming_usage_snapshot(task_id, "architecture"),
                )
                architecture_accounted_usage = await _reconciled_stage_usage(
                    task_id,
                    stream_key="architecture",
                    final_usage=architecture_usage,
                    default_model=agent_orchestrator.get_model_name(),
                )
                architecture_log = await _complete_process_log(
                    architecture_log_ref[0],
                    content=t(locale, "process.architecture_generation.completed"),
                    duration=architecture_duration,
                )

                architecture_meta = architecture_payload.get("_meta") if isinstance(architecture_payload.get("_meta"), dict) else {}
                if architecture_recovered_from_live_outputs:
                    architecture_output_files = await _list_agent_artifact_files(
                        project_id,
                        version=pending_agent_artifact_version,
                        agent_name=str(architecture_meta.get("source") or "architecture_agent"),
                    )
                    if not architecture_output_files:
                        architecture_output_files = list(recovered_architecture_output_files or [])
                else:
                    architecture_output_files = await _register_agent_output_dir(
                        project_id,
                        task_id,
                        version=pending_agent_artifact_version,
                        agent_name=str(architecture_meta.get("source") or "architecture_agent"),
                        archive_stage="architecture",
                        output_dir=str(architecture_meta.get("outputDir") or ""),
                        source_files_by_artifact=architecture_meta.get("sourceFilesByArtifact") if isinstance(architecture_meta.get("sourceFilesByArtifact"), dict) else None,
                    )
                _cleanup_local_path_if_configured(str(architecture_meta.get("outputDir") or ""))
                architecture_log = await _update_message(
                    architecture_log,
                    metadata=_merge_process_log_output_metadata(
                        architecture_log.metadata or None,
                        source_agent=str(architecture_meta.get("source") or "architecture_agent"),
                        output_files=architecture_output_files,
                    ),
                )

                artifacts = agent_orchestrator.compose_artifacts(
                    prompt=prompt,
                    selected_modules=selected_modules_payload,
                    requirements_payload=requirements_payload,
                    architecture_payload=architecture_payload,
                )
                artifact_sources = _artifact_sources_payload(artifacts, architecture_usage)
                artifact_titles = {
                    "prd": "PRD Draft",
                    "ui": "UI Draft",
                    "architecture": "Architecture Draft",
                    "api_spec": "API Design",
                }
                changes: list[dict[str, Any]] = []
                for artifact_type, content in _artifact_content_items(artifacts):
                    artifact = await store.upsert_artifact(
                        project_id,
                        artifact_type,  # type: ignore[arg-type]
                        artifact_titles[artifact_type],
                        content,
                        metadata=_artifact_record_metadata(artifact_type, artifact_sources),
                    )
                    changes.append({"file": artifact.title, "status": "Added"})
                    await _broadcast_progress(
                        project_id,
                        task_id,
                        phase="artifact_generated",
                        status="completed",
                        progress=88 if artifact.type != "architecture" else 95,
                        artifact_type=artifact.type,
                        output_hint=artifact.title,
                        raw_file_name=(artifact_sources.get(artifact.type, {}).get("sourceFiles") or [None])[0],
                        module_count=len(selected_modules_payload),
                        reference_count=len(reference_snapshot),
                    )

                await store.add_step_record(
                    task_id,
                    "Generate architecture draft",
                    "generation",
                    duration=architecture_duration,
                    tokens_used=_usage_total_tokens(architecture_accounted_usage),
                    cost=_usage_cost_amount(architecture_accounted_usage),
                    status="completed",
                    metadata=_step_usage_metadata(
                        usage_metadata=architecture_accounted_usage,
                        default_model=agent_orchestrator.get_model_name(),
                        source_agent="architecture_agent",
                        extra={
                            "artifactTypes": ["architecture"],
                            "artifactSources": {"architecture": artifact_sources["architecture"]},
                            "outputFiles": architecture_output_files,
                        },
                    ),
                )
                stats = await store.get_statistics(task_id)
                if stats is not None:
                    await store.update_statistics(
                        task_id,
                        inputTokens=stats.inputTokens + int((architecture_remainder_usage or {}).get("inputTokens") or 0),
                        outputTokens=stats.outputTokens + int((architecture_remainder_usage or {}).get("outputTokens") or 0),
                        totalTokens=stats.totalTokens + int((architecture_remainder_usage or {}).get("totalTokens") or 0),
                        modelUsed=_usage_model(architecture_accounted_usage, stats.modelUsed),
                        costAmount=stats.costAmount + _usage_cost_amount(architecture_remainder_usage),
                        totalDuration=stats.totalDuration + architecture_duration,
                    )
                review_confirmation = _artifact_review_confirmation_payload(
                    locale=locale,
                    reference_snapshot=reference_snapshot,
                    selected_module_ids=[module["id"] for module in selected_modules_payload if module.get("id")],
                    artifact_types=[artifact_type for artifact_type, _ in _artifact_content_items(artifacts)],
                    artifact_sources=artifact_sources,
                    context_summary=_context_summary_payload(
                        reference_snapshot=reference_snapshot,
                        selected_module_ids=[module["id"] for module in selected_modules_payload if module.get("id")],
                    ),
                )
                review_confirmation["pendingRuntimeVariables"] = agent_orchestrator.missing_runtime_variables()
                review_confirmation["activeAgent"] = "architecture_agent"
                review_confirmation["activePhase"] = "waiting_for_artifact_review"
                review_confirmation["agentOutputsReady"] = sorted(
                    {
                        artifact.agent
                        for artifact in await store.list_agent_artifacts(
                            project_id,
                            version=pending_agent_artifact_version,
                        )
                    }
                )
                review_confirmation["pendingAgentArtifactsVersion"] = pending_agent_artifact_version
                await _append_message(
                    Message(
                        projectId=project_id,
                        role="agent",
                        type="select_options",
                        content=t(locale, "artifact_review.content"),
                        metadata={
                            **review_confirmation,
                            **_task_message_metadata(task_id, task_status="waiting_user"),
                        },
                    )
                )
                await _enter_waiting_state(project_id, task_id, review_confirmation)
                stats = await _statistics_payload(task_id)
                if stats is not None:
                    await _broadcast(project_id, "statistics", stats.model_dump(mode="json"))
                return
            if await _request_runtime_variables_if_needed(
                project_id,
                task_id,
                prompt=prompt,
                selected_modules_payload=selected_modules_payload,
                next_action={"mode": "start_code_generation"},
                runtime_variables=pending_runtime_variables,
            ):
                payload = await _statistics_payload(task_id)
                if payload is not None:
                    await _broadcast(project_id, "statistics", payload.model_dump(mode="json"))
                return
            await _promote_pending_preview_to_current_version(project_id, task_id)
            await _generate_ui_workspace(
                project_id,
                task_id,
                prompt=prompt,
                selected_modules_payload=selected_modules_payload,
                locale=locale,
                running_message=t(locale, "process.ui_generation.review.running"),
                completed_message=t(locale, "process.ui_generation.review.completed"),
            )
            await _generate_code_workspace(
                project_id,
                task_id,
                prompt=prompt,
                selected_modules_payload=selected_modules_payload,
                locale=locale,
                running_message=t(locale, "process.code_generation.review.running"),
                completed_message=t(locale, "process.code_generation.review.completed"),
            )
            await _generate_test_workspace(
                project_id,
                task_id,
                prompt=prompt,
                selected_modules_payload=selected_modules_payload,
                locale=locale,
                running_message=t(locale, "process.test_generation.review.running"),
                completed_message=t(locale, "process.test_generation.review.completed"),
            )
            await _finalize_generated_artifacts(
                project_id,
                task_id,
                output_data_updates={
                    "uiGeneratedAt": utc_now().isoformat(),
                    "codeGeneratedAt": utc_now().isoformat(),
                    "testGeneratedAt": utc_now().isoformat(),
                },
            )
            return
        if confirmation_kind == "coverage_conflict":
            if "confirm_overwrite" not in selected_ids:
                raise WorkflowTaskError("COVERAGE_CONFLICT", t(locale, "error.overwrite_not_approved"))
            await store.update_task(task_id, status="running")
            await _broadcast(
                project_id,
                "status_change",
                {"oldStatus": "waiting_user", "newStatus": "running"},
            )
            task = await store.get_task(task_id)
            if task is None:
                raise WorkflowTaskError("CONTEXT_EXPIRED", t(locale, "error.pending_overwrite_missing"))
            if task.taskType in {"modify", "regenerate"}:
                await start_modify_flow(
                    project_id,
                    task_id,
                    str(task.inputData.get("prompt", "")),
                    skip_conflict_check=True,
                )
                return
            raise WorkflowTaskError(
                "CONTEXT_EXPIRED",
                t(locale, "error.unsupported_overwrite_task_type", task_type=task.taskType),
            )
        if confirmation_kind == "input_variables":
            await store.update_task(task_id, status="running")
            await _broadcast(
                project_id,
                "status_change",
                {"oldStatus": "waiting_user", "newStatus": "running"},
            )
            await _resume_after_runtime_input(project_id, task_id, response_payload)
            return
        if confirmation_kind == "requirements_feedback":
            raise WorkflowTaskError("CONTEXT_EXPIRED", t(locale, "error.feedback_resume_direct_only"))

        modules = [module for module in await store.get_modules(project_id) if module.isSelected]
        if not modules:
            modules = list(await store.get_modules(project_id))
        await store.update_task(task_id, status="running")
        await _broadcast(
            project_id,
            "status_change",
            {"oldStatus": "waiting_user", "newStatus": "running"},
        )
        if user_note:
            await _append_message(
                Message(
                    projectId=project_id,
                    role="user",
                    type="text",
                    content=user_note,
                    metadata=_task_message_metadata(task_id),
                )
            )

        pipeline_task = await store.create_generation_task(project_id, "Generating artifacts")
        pipeline_task = await store.update_generation_task(
            pipeline_task.id,
            project_id,
            status="running",
            progress=35,
        )
        await _broadcast(project_id, "task_update", pipeline_task.model_dump(mode="json"))

        task = await store.get_task(task_id)
        prompt = task.inputData.get("prompt", "") if task else ""
        uploaded_files = task.inputData.get("uploadedFiles", []) if task else []
        reference_materials = await _reference_materials(uploaded_files if isinstance(uploaded_files, list) else [])
        reference_snapshot = await _reference_snapshot(uploaded_files if isinstance(uploaded_files, list) else [])
        current_project = await store.get_project(project_id)
        pending_agent_artifact_version = (current_project.currentVersion + 1) if current_project is not None else 1
        await _record_pending_agent_artifacts_version(
            project_id,
            task_id,
            pending_version=pending_agent_artifact_version,
            active_phase="requirements_drafts_started",
            active_agent="requirements_agent",
        )
        await _broadcast_progress(
            project_id,
            task_id,
            phase="requirements_drafts_started",
            status="running",
            progress=40,
            module_count=len(modules),
            reference_count=len(reference_snapshot),
        )
        requirements_log = await _append_process_log(
            project_id,
            task_id,
            phase="requirements_drafts_started",
            task_name=t(locale, "process.requirements_drafts.name"),
            content=t(locale, "process.requirements_drafts.running"),
        )
        requirements_log_ref = [requirements_log]
        requirements_runtime_snapshot = {"identity": None}
        requirements_live_output_snapshot = {"identity": None}
        requirements_started_at = time.perf_counter()
        selected_modules_payload = [
            {
                "id": module.id,
                "label": module.name,
                "labelEn": module.nameEn,
            }
            for module in modules
        ]

        async def handle_live_requirements_output(payload: dict[str, Any]) -> None:
            await _register_live_agent_output_dir(
                project_id,
                task_id,
                version=pending_agent_artifact_version,
                agent_name=str(payload.get("agentName") or "requirements_agent"),
                archive_stage="requirements-drafts",
                output_dir=str(payload.get("outputDir") or ""),
            )
            await _record_pending_agent_artifacts_version(
                project_id,
                task_id,
                pending_version=pending_agent_artifact_version,
                active_phase="requirements_drafts_started",
                active_agent="requirements_agent",
            )

        async def handle_requirements_feedback_request(payload: dict[str, Any]) -> None:
            prompt_text = str(payload.get("promptText") or "").strip()
            output_files = [str(item) for item in payload.get("outputFiles") or [] if str(item).strip()]
            logger.info(
                "[AGENT WAITING] requirements_feedback_requested project_id=%s task_id=%s phase=%s files=%s prompt=%s",
                project_id,
                task_id,
                str(payload.get("phase") or "requirements_drafts_started"),
                output_files,
                _preview_log_text(prompt_text),
            )
            refreshed_log = await _update_latest_task_phase_process_log(
                project_id,
                task_id,
                phase="requirements_drafts_started",
                content=t(locale, "process.requirements_drafts.waiting"),
                clear_raw_file_name=True,
            )
            if refreshed_log is not None:
                requirements_log_ref[0] = refreshed_log
            confirmation = _requirements_feedback_confirmation_payload(
                locale=locale,
                prompt_text=prompt_text,
                output_files=output_files,
                return_phase=str(payload.get("phase") or "requirements_drafts_started"),
                return_agent=str(payload.get("agentName") or "requirements_agent"),
            )
            confirmation["pendingAgentArtifactsVersion"] = pending_agent_artifact_version
            await _append_message(
                Message(
                    projectId=project_id,
                    role="agent",
                    type="input_form",
                    content=t(locale, "requirements_feedback.content"),
                    metadata={
                        **confirmation,
                        **_task_message_metadata(task_id, task_status="waiting_user"),
                    },
                )
            )
            await _enter_waiting_state(project_id, task_id, confirmation)

        async def handle_requirements_runtime_event(runtime_event: dict[str, Any]) -> None:
            output_dir_value = str(runtime_event.get("outputDir") or "").strip()
            live_output_files: list[str] = []
            if output_dir_value:
                output_root = Path(output_dir_value)
                # 设计注释：
                # 需求草稿阶段也可能先把真实文件慢慢写到 Requirements Agent 的输出目录里。
                # 这里只要看到目录中已经出现文件，就立刻登记进平台状态。
                # 这样就算主调用还没有返回，前端也能知道“文件确实在生成中”。
                live_output_files = (
                    await asyncio.to_thread(_list_relative_output_files, output_root)
                    if output_root.exists() and output_root.is_dir()
                    else []
                )
                live_output_identity = (str(output_root.resolve()), tuple(live_output_files))
                if (
                    live_output_files
                    and requirements_live_output_snapshot["identity"] != live_output_identity
                ):
                    requirements_live_output_snapshot["identity"] = live_output_identity
                    await _register_live_agent_output_dir(
                        project_id,
                        task_id,
                        version=pending_agent_artifact_version,
                        agent_name="requirements_agent",
                        archive_stage="requirements-drafts",
                        output_dir=output_dir_value,
                    )
                    await _record_pending_agent_artifacts_version(
                        project_id,
                        task_id,
                        pending_version=pending_agent_artifact_version,
                        active_phase="requirements_drafts_started",
                        active_agent="requirements_agent",
                    )

            latest_output_file = str(runtime_event.get("latestOutputFile") or "").strip()
            visible_output_files = (
                _filter_visible_output_files_for_phase("requirements_drafts_started", [latest_output_file])
                if latest_output_file
                else []
            )
            visible_output_file = visible_output_files[-1] if visible_output_files else None
            idle_seconds = _int_value(runtime_event.get("secondsSinceLastOutput"))
            idle_bucket = idle_seconds // 10
            elapsed_bucket = _int_value(runtime_event.get("elapsedSeconds")) // 30
            snapshot_identity = (
                str(runtime_event.get("runtimeState") or ""),
                visible_output_file or "",
                idle_bucket,
                elapsed_bucket,
            )
            if requirements_runtime_snapshot["identity"] == snapshot_identity:
                return
            requirements_runtime_snapshot["identity"] = snapshot_identity

            next_metadata = _merge_process_log_runtime_metadata(
                requirements_log_ref[0].metadata or None,
                runtime_event=runtime_event,
            )
            if live_output_files:
                next_metadata = _merge_process_log_output_metadata(
                    next_metadata,
                    phase="requirements_drafts_started",
                    source_agent="requirements_agent",
                    raw_file_name=latest_output_file or visible_output_file,
                    output_files=live_output_files,
                )
            elif visible_output_file:
                next_metadata = _merge_process_log_output_metadata(
                    next_metadata,
                    phase="requirements_drafts_started",
                    source_agent="requirements_agent",
                    raw_file_name=visible_output_file,
                    output_files=[visible_output_file],
                )

            next_content = requirements_log_ref[0].content
            if visible_output_file:
                next_content = _format_structured_file_status(
                    locale=locale,
                    file_name=visible_output_file,
                    step_label=None,
                    completed=False,
                )

            requirements_log_ref[0] = await _update_message(
                requirements_log_ref[0],
                content=next_content,
                metadata=next_metadata,
            )

            if visible_output_file:
                await _broadcast_progress(
                    project_id,
                    task_id,
                    phase="requirements_drafts_started",
                    status="running",
                    progress=52,
                    agent_name="requirements_agent",
                    output_hint=visible_output_file,
                    raw_file_name=visible_output_file,
                    module_count=len(modules),
                    reference_count=len(reference_snapshot),
                )

        if _legacy_combined_artifact_builder_active():
            artifacts = await _run_with_progress_heartbeat(
                project_id,
                task_id,
                phase="requirements_drafts_started",
                initial_progress=40,
                progress_cap=82,
                progress_step=6,
                module_count=len(modules),
                reference_count=len(reference_snapshot),
                operation=agent_orchestrator.build_artifacts(
                    prompt=prompt,
                    selected_modules=selected_modules_payload,
                    reference_materials=reference_materials,
                    locale=locale,
                    status_callback=_process_log_status_callback(
                        requirements_log_ref,
                        project_id=project_id,
                        task_id=task_id,
                        phase="requirements_drafts_started",
                        locale=locale,
                    ),
                    artifact_file_callback=handle_live_requirements_output,
                ),
            )
            artifact_duration = time.perf_counter() - requirements_started_at
            artifact_usage = agent_orchestrator.consume_last_usage_metadata()
            requirements_duration = artifact_duration
            requirements_usage = artifact_usage
            requirements_log = await _complete_process_log(
                requirements_log_ref[0],
                content=t(locale, "process.requirements_drafts.completed"),
                duration=requirements_duration,
            )
            await _broadcast_progress(
                project_id,
                task_id,
                phase="architecture_generation_started",
                status="completed",
                progress=82,
                module_count=len(modules),
                reference_count=len(reference_snapshot),
            )
            architecture_log = await _append_process_log(
                project_id,
                task_id,
                phase="architecture_generation_started",
                task_name=t(locale, "process.architecture_generation.name"),
                content=t(locale, "process.architecture_generation.completed"),
            )
            architecture_duration = 0.0
            architecture_usage = None
            architecture_log = await _complete_process_log(
                architecture_log,
                content=t(locale, "process.architecture_generation.completed"),
                duration=architecture_duration,
            )
        else:
            requirements_selected_modules_payload = [
                {
                    "label": module.name,
                    "labelEn": module.nameEn,
                }
                for module in modules
            ]
            async def handle_requirements_drafts_usage_delta(usage_delta: dict[str, Any]) -> None:
                await _record_streaming_usage_delta(
                    project_id,
                    task_id,
                    stream_key="requirements_drafts",
                    source_agent="requirements_agent",
                    usage_delta=usage_delta,
                )

            requirements_payload = await _run_with_progress_heartbeat(
                project_id,
                task_id,
                phase="requirements_drafts_started",
                initial_progress=40,
                progress_cap=66,
                progress_step=6,
                module_count=len(modules),
                reference_count=len(reference_snapshot),
                operation=_await_requirements_drafts_or_recover_from_live_outputs(
                    project_id,
                    task_id,
                    pending_version=pending_agent_artifact_version,
                    prompt=prompt,
                    selected_modules=requirements_selected_modules_payload,
                    operation=agent_orchestrator.build_requirements_drafts(
                        task_id=task_id,
                        prompt=prompt,
                        selected_modules=requirements_selected_modules_payload,
                        reference_materials=reference_materials,
                        locale=locale,
                        status_callback=_process_log_status_callback(
                            requirements_log_ref,
                            project_id=project_id,
                            task_id=task_id,
                            phase="requirements_drafts_started",
                            locale=locale,
                        ),
                        artifact_file_callback=handle_live_requirements_output,
                        human_feedback_callback=handle_requirements_feedback_request,
                        runtime_event_callback=handle_requirements_runtime_event,
                        usage_event_callback=handle_requirements_drafts_usage_delta,
                    ),
                ),
            )
            recovered_requirements_output_files: list[str] | None = None
            requirements_recovered_from_live_outputs = False
            if isinstance(requirements_payload, tuple):
                requirements_payload, recovered_requirements_output_files, requirements_recovered_from_live_outputs = requirements_payload
            requirements_duration = time.perf_counter() - requirements_started_at
            requirements_usage = agent_orchestrator.consume_last_usage_metadata()
            requirements_remainder_usage = _remaining_usage_after_streaming(
                requirements_usage,
                await _streaming_usage_snapshot(task_id, "requirements_drafts"),
            )
            requirements_accounted_usage = await _reconciled_stage_usage(
                task_id,
                stream_key="requirements_drafts",
                final_usage=requirements_usage,
                default_model=agent_orchestrator.get_model_name(),
            )
            requirements_log = await _complete_process_log(
                requirements_log_ref[0],
                content=t(locale, "process.requirements_drafts.completed"),
                duration=requirements_duration,
            )
            requirements_meta = requirements_payload.get("_meta") if isinstance(requirements_payload.get("_meta"), dict) else {}
            requirements_sources_wrapper = {
                "prd": requirements_payload.get("prd"),
                "ui": requirements_payload.get("ui"),
                "api_spec": requirements_payload.get("api_spec"),
                "_meta": {
                    "requirements": requirements_meta,
                },
            }
            requirements_sources = _artifact_sources_payload(requirements_sources_wrapper, requirements_usage)
            requirements_seeded_files = (
                requirements_meta.get("seededFiles")
                if isinstance(requirements_meta.get("seededFiles"), list)
                else None
            )
            preview_version = pending_agent_artifact_version
            if requirements_recovered_from_live_outputs:
                requirements_output_files = await _list_agent_artifact_files(
                    project_id,
                    version=preview_version,
                    agent_name=str(requirements_meta.get("source") or "requirements_agent"),
                )
                if not requirements_output_files:
                    requirements_output_files = list(recovered_requirements_output_files or [])
            else:
                requirements_output_files = await _register_agent_output_dir(
                    project_id,
                    task_id,
                    version=preview_version,
                    agent_name=str(requirements_meta.get("source") or "requirements_agent"),
                    archive_stage="requirements-drafts",
                    output_dir=str(requirements_meta.get("outputDir") or ""),
                    source_files_by_artifact=requirements_meta.get("sourceFilesByArtifact") if isinstance(requirements_meta.get("sourceFilesByArtifact"), dict) else None,
                )
            _cleanup_local_path_if_configured(str(requirements_meta.get("outputDir") or ""))
            requirements_step_output_files = _filter_seeded_output_files(
                requirements_output_files,
                seeded_files=[str(file_name) for file_name in (requirements_seeded_files or [])],
            )
            requirements_log = await _update_message(
                requirements_log,
                metadata=_merge_process_log_output_metadata(
                    requirements_log.metadata or None,
                    source_agent=str(requirements_meta.get("source") or "requirements_agent"),
                    output_files=requirements_step_output_files,
                ),
            )

            requirements_artifact_items = [
                (artifact_type, content)
                for artifact_type, content in _artifact_content_items(requirements_payload)
                if artifact_type in {"prd", "ui", "api_spec"}
            ]
            artifact_count = max(1, len(requirements_artifact_items))
            for index, (artifact_type, _content) in enumerate(requirements_artifact_items):
                await _broadcast_progress(
                    project_id,
                    task_id,
                    phase="artifact_generated",
                    status="completed",
                    progress=45 + int(((index + 1) / artifact_count) * 25),
                    artifact_type=artifact_type,
                    output_hint=(requirements_sources.get(artifact_type, {}).get("sourceFiles") or [artifact_type])[0],
                    raw_file_name=(requirements_sources.get(artifact_type, {}).get("sourceFiles") or [None])[0],
                    module_count=len(modules),
                    reference_count=len(reference_snapshot),
                )

            await store.add_step_record(
                task_id,
                "Generate requirements drafts",
                "generation",
                duration=requirements_duration,
                tokens_used=_usage_total_tokens(requirements_accounted_usage),
                cost=_usage_cost_amount(requirements_accounted_usage),
                status="completed",
                metadata=_step_usage_metadata(
                    usage_metadata=requirements_accounted_usage,
                    default_model=agent_orchestrator.get_model_name(),
                    source_agent="requirements_agent",
                    extra={
                        "artifactTypes": ["prd", "ui", "api_spec"],
                        "artifactSources": {
                            artifact_type: requirements_sources[artifact_type]
                            for artifact_type in ("prd", "ui", "api_spec")
                        },
                        "outputFiles": requirements_step_output_files,
                    },
                ),
            )
            stats = await store.get_statistics(task_id)
            if stats is not None:
                await store.update_statistics(
                    task_id,
                    inputTokens=stats.inputTokens + int((requirements_remainder_usage or {}).get("inputTokens") or 0),
                    outputTokens=stats.outputTokens + int((requirements_remainder_usage or {}).get("outputTokens") or 0),
                    totalTokens=stats.totalTokens + int((requirements_remainder_usage or {}).get("totalTokens") or 0),
                    modelUsed=_usage_model(requirements_accounted_usage, stats.modelUsed),
                    costAmount=stats.costAmount + _usage_cost_amount(requirements_remainder_usage),
                    totalDuration=stats.totalDuration + requirements_duration,
                )

            pipeline_task = await store.update_generation_task(pipeline_task.id, project_id, status="completed", progress=100)
            review_confirmation = _requirements_artifact_review_confirmation_payload(
                locale=locale,
                reference_snapshot=reference_snapshot,
                selected_module_ids=[module.id for module in modules],
                artifact_sources=requirements_sources,
                context_summary=_context_summary_payload(
                    reference_snapshot=reference_snapshot,
                    selected_module_ids=[module.id for module in modules],
                ),
            )
            review_confirmation["activeAgent"] = "requirements_agent"
            review_confirmation["activePhase"] = "waiting_for_requirements_artifact_review"
            review_confirmation["pendingAgentArtifactsVersion"] = preview_version
            review_confirmation["agentOutputsReady"] = sorted(
                {
                    artifact.agent
                    for artifact in await store.list_agent_artifacts(project_id, version=preview_version)
                }
            )
            await _append_message(
                Message(
                    projectId=project_id,
                    role="agent",
                    type="select_options",
                    content=t(locale, "requirements_artifact_review.content"),
                    metadata={
                        **review_confirmation,
                        **_task_message_metadata(task_id, task_status="waiting_user"),
                    },
                )
            )
            await _broadcast(project_id, "task_update", pipeline_task.model_dump(mode="json"))
            await _enter_waiting_state(project_id, task_id, review_confirmation)
            payload = await _statistics_payload(task_id)
            if payload is not None:
                await _broadcast(project_id, "statistics", payload.model_dump(mode="json"))
            return

        artifact_titles = {
            "prd": "PRD Draft",
            "ui": "UI Draft",
            "architecture": "Architecture Draft",
            "api_spec": "API Design",
        }
        artifact_sources = _artifact_sources_payload(artifacts, artifact_usage)
        artifact_meta = artifacts.get("_meta") if isinstance(artifacts.get("_meta"), dict) else {}
        requirements_meta = artifact_meta.get("requirements") if isinstance(artifact_meta.get("requirements"), dict) else {}
        architecture_meta = artifact_meta.get("architecture") if isinstance(artifact_meta.get("architecture"), dict) else {}
        requirements_seeded_files = (
            requirements_meta.get("seededFiles")
            if isinstance(requirements_meta.get("seededFiles"), list)
            else None
        )
        pending_runtime_variables = agent_orchestrator.missing_runtime_variables()
        context_summary = _context_summary_payload(
            reference_snapshot=reference_snapshot,
            selected_module_ids=[module.id for module in modules],
        )
        preview_version = await _pending_preview_version(project_id, task_id)
        requirements_output_files = await _register_agent_output_dir(
            project_id,
            task_id,
            version=preview_version,
            agent_name=str(requirements_meta.get("source") or "requirements_agent"),
            archive_stage="requirements-drafts",
            output_dir=str(requirements_meta.get("outputDir") or ""),
            source_files_by_artifact=requirements_meta.get("sourceFilesByArtifact") if isinstance(requirements_meta.get("sourceFilesByArtifact"), dict) else None,
        )
        _cleanup_local_path_if_configured(str(requirements_meta.get("outputDir") or ""))
        architecture_output_files = await _register_agent_output_dir(
            project_id,
            task_id,
            version=preview_version,
            agent_name=str(architecture_meta.get("source") or "architecture_agent"),
            archive_stage="architecture",
            output_dir=str(architecture_meta.get("outputDir") or ""),
            source_files_by_artifact=architecture_meta.get("sourceFilesByArtifact") if isinstance(architecture_meta.get("sourceFilesByArtifact"), dict) else None,
        )
        _cleanup_local_path_if_configured(str(architecture_meta.get("outputDir") or ""))
        requirements_step_output_files = _filter_seeded_output_files(
            requirements_output_files,
            seeded_files=[str(file_name) for file_name in (requirements_seeded_files or [])],
        )
        requirements_log = await _update_message(
            requirements_log,
            metadata=_merge_process_log_output_metadata(
                requirements_log.metadata or None,
                output_files=requirements_step_output_files,
            ),
        )
        architecture_log = await _update_message(
            architecture_log,
            metadata=_merge_process_log_output_metadata(
                architecture_log.metadata or None,
                output_files=architecture_output_files,
            ),
        )
        changes: list[dict[str, Any]] = []
        artifact_items = _artifact_content_items(artifacts)
        artifact_count = max(1, len(artifact_items))
        for index, (artifact_type, content) in enumerate(artifact_items):
            artifact = await store.upsert_artifact(
                project_id,
                artifact_type,  # type: ignore[arg-type]
                artifact_titles[artifact_type],
                content,
                metadata=_artifact_record_metadata(artifact_type, artifact_sources),
            )
            changes.append({"file": artifact.title, "status": "Added"})
            await _append_message(
                Message(
                    projectId=project_id,
                    role="agent",
                    type="artifact_card",
                    content=artifact.title,
                    parentId=architecture_log.id,
                    metadata={
                        "artifactId": artifact.id,
                        "artifactType": artifact.type,
                        "title": artifact.title,
                        "preview": content[:120],
                    },
                )
            )
            await _broadcast(
                project_id,
                "task_artifact_attached",
                {
                    "taskId": task_id,
                    "logId": architecture_log.id,
                    "artifactType": artifact.type,
                    "artifactId": artifact.id,
                    "title": artifact.title,
                    "createdAt": utc_now().isoformat(),
                },
            )
            await _broadcast(
                project_id,
                "artifact_update",
                {
                    "artifactType": artifact.type,
                    "version": artifact.version,
                    "action": "generated",
                },
            )
            await _broadcast_progress(
                project_id,
                task_id,
                phase="artifact_generated",
                status="completed",
                progress=45 + int(((index + 1) / artifact_count) * 35),
                artifact_type=artifact.type,
                output_hint=artifact.title,
                raw_file_name=(artifact_sources.get(artifact.type, {}).get("sourceFiles") or [None])[0],
                module_count=len(modules),
                reference_count=len(reference_snapshot),
            )

        await store.add_step_record(
            task_id,
            "Generate requirements drafts",
            "generation",
            duration=requirements_duration,
            tokens_used=_usage_total_tokens(requirements_usage),
            cost=_usage_cost_amount(requirements_usage),
            status="completed",
            metadata=_step_usage_metadata(
                usage_metadata=requirements_usage,
                default_model=agent_orchestrator.get_model_name(),
                source_agent="requirements_agent",
                extra={
                    "artifactTypes": ["prd", "ui", "api_spec"],
                    "artifactSources": {
                        artifact_type: artifact_sources[artifact_type]
                        for artifact_type in ("prd", "ui", "api_spec")
                    },
                    "outputFiles": requirements_step_output_files,
                },
            ),
        )
        await store.add_step_record(
            task_id,
            "Generate architecture draft",
            "generation",
            duration=architecture_duration,
            tokens_used=_usage_total_tokens(architecture_usage),
            cost=_usage_cost_amount(architecture_usage),
            status="completed",
            metadata=_step_usage_metadata(
                usage_metadata=architecture_usage,
                default_model=agent_orchestrator.get_model_name(),
                source_agent="architecture_agent",
                extra={
                    "artifactTypes": ["architecture"],
                    "artifactSources": {
                        "architecture": artifact_sources["architecture"],
                    },
                    "outputFiles": architecture_output_files,
                },
            ),
        )
        stats = await store.get_statistics(task_id)
        if stats is not None:
            await store.update_statistics(
                task_id,
                inputTokens=stats.inputTokens + int((artifact_usage or {}).get("inputTokens") or 0),
                outputTokens=stats.outputTokens + int((artifact_usage or {}).get("outputTokens") or 0),
                totalTokens=stats.totalTokens + int((artifact_usage or {}).get("totalTokens") or 0),
                modelUsed=_usage_model(artifact_usage, stats.modelUsed),
                costAmount=stats.costAmount + _usage_cost_amount(artifact_usage),
                totalDuration=stats.totalDuration + artifact_duration,
            )

        pipeline_task = await store.update_generation_task(pipeline_task.id, project_id, status="completed", progress=100)
        review_confirmation = _artifact_review_confirmation_payload(
            locale=locale,
            reference_snapshot=reference_snapshot,
            selected_module_ids=[module.id for module in modules],
            artifact_types=[artifact_type for artifact_type, _ in _artifact_content_items(artifacts)],
            artifact_sources=artifact_sources,
            context_summary=context_summary,
        )
        review_confirmation["pendingRuntimeVariables"] = pending_runtime_variables
        review_confirmation["activeAgent"] = "architecture_agent"
        review_confirmation["activePhase"] = "waiting_for_artifact_review"
        review_confirmation["agentOutputsReady"] = sorted(
            {
                artifact.agent
                for artifact in await store.list_agent_artifacts(project_id, version=preview_version)
            }
        )
        review_confirmation["pendingAgentArtifactsVersion"] = preview_version
        await _append_message(
            Message(
                projectId=project_id,
                role="agent",
                type="select_options",
                content=t(locale, "artifact_review.content"),
                metadata={
                    **review_confirmation,
                    **_task_message_metadata(task_id, task_status="waiting_user"),
                },
            )
        )

        await _broadcast(project_id, "task_update", pipeline_task.model_dump(mode="json"))
        await _enter_waiting_state(project_id, task_id, review_confirmation)
        stats = await store.get_statistics(task_id)
        if stats is not None:
            await store.update_statistics(task_id, totalDuration=time.perf_counter() - flow_started_at)
        payload = await _statistics_payload(task_id)
        if payload is not None:
            await _broadcast(project_id, "statistics", payload.model_dump(mode="json"))
    except Exception as exc:
        await _handle_task_exception(project_id, task_id, exc)


async def start_modify_flow(project_id: str, task_id: str, prompt: str, *, skip_conflict_check: bool = False) -> None:
    async with _get_workflow_semaphore():
        await _start_modify_flow_inner(project_id, task_id, prompt, skip_conflict_check=skip_conflict_check)


async def _start_modify_flow_inner(project_id: str, task_id: str, prompt: str, *, skip_conflict_check: bool = False) -> None:
    try:
        flow_started_at = time.perf_counter()
        locale = await _task_locale(task_id)
        logger.info(
            "[AGENT FLOW] start_modify_flow project_id=%s task_id=%s skip_conflict_check=%s prompt=%s",
            project_id,
            task_id,
            skip_conflict_check,
            _preview_log_text(prompt),
        )
        # 设计注释：
        # 修改流程是线上最常见的长任务入口之一。
        # 这里先把一批同步 store 读取搬到线程里，避免任务刚开始准备上下文时就卡住事件循环。
        modules = [module for module in await store.get_modules(project_id) if module.isSelected]
        if not modules:
            raise WorkflowTaskError(
                "PARSING_FAILED",
                t(locale, "error.no_confirmed_modules"),
            )

        upload_ids = [upload.id for upload in await store.list_project_uploads(project_id)]
        reference_materials = await _reference_materials(upload_ids)
        reference_snapshot = await _reference_snapshot(upload_ids)
        existing_artifacts = await store.list_artifacts(project_id)
        existing_artifact_snapshot = await _artifact_snapshot(project_id)
        existing_artifact_titles = {artifact.type: artifact.title for artifact in existing_artifacts}
        task = await store.get_task(task_id)
        task_type = task.taskType if task is not None else "modify"
        if not skip_conflict_check:
            conflict_types = ["architecture"] if task_type == "regenerate" else None
            conflicts = await _current_artifact_conflicts(project_id, target_types=conflict_types)
            if conflicts:
                await _append_message(
                    Message(
                        projectId=project_id,
                        role="agent",
                        type="select_options",
                        content=t(locale, "coverage_conflict.content"),
                        metadata={
                            **_coverage_conflict_payload(locale=locale, conflicts=conflicts),
                            **_task_message_metadata(task_id, task_status="waiting_user"),
                        },
                    )
                )
                await _enter_waiting_state(
                    project_id,
                    task_id,
                    _coverage_conflict_payload(locale=locale, conflicts=conflicts),
                )
                return
        selected_module_ids = [module.id for module in modules]
        context_summary = _context_summary_payload(
            reference_snapshot=reference_snapshot,
            selected_module_ids=selected_module_ids,
            existing_artifacts=existing_artifact_snapshot,
        )
        context_output = {
            "referenceFiles": reference_snapshot,
            "existingArtifacts": existing_artifact_snapshot,
            "selectedModuleIds": selected_module_ids,
            "requestedPrompt": prompt,
            "contextSummary": context_summary,
        }

        await store.create_statistics(project_id, task_id, model_used=agent_orchestrator.get_model_name())
        await store.update_task(task_id, status="running", output_data=context_output)
        pipeline_task = await store.create_generation_task(project_id, "Applying requested changes")
        pipeline_task = await store.update_generation_task(
            pipeline_task.id,
            project_id,
            status="running",
            progress=25,
        )
        await _broadcast(project_id, "task_update", pipeline_task.model_dump(mode="json"))
        await _broadcast_progress(
            project_id,
            task_id,
            phase="modification_started",
            status="running",
            progress=25,
            module_count=len(modules),
            reference_count=len(reference_snapshot),
        )

        modify_generation_log = await _append_process_log(
            project_id,
            task_id,
            phase="modification_started",
            task_name=t(locale, "process.modify.name"),
            content=t(locale, "process.modify.running"),
        )
        modify_generation_log_ref = [modify_generation_log]
        await asyncio.sleep(0.05)

        prompt_with_context = prompt
        if existing_artifacts:
            artifact_context = "\n".join(f"- {artifact.type}: {artifact.title}" for artifact in existing_artifacts)
            prompt_with_context = f"{prompt}\n\nExisting project artifacts:\n{artifact_context}"

        artifact_started_at = time.perf_counter()
        artifacts = await agent_orchestrator.build_artifacts(
            prompt=prompt_with_context,
            selected_modules=[
                {
                    "label": module.name,
                    "labelEn": module.nameEn,
                }
                for module in modules
            ],
            reference_materials=reference_materials,
            existing_artifacts=existing_artifact_snapshot,
            locale=locale,
            status_callback=_process_log_status_callback(
                modify_generation_log_ref,
                project_id=project_id,
                task_id=task_id,
                phase="modification_started",
                locale=locale,
            ),
        )
        artifact_duration = time.perf_counter() - artifact_started_at
        artifact_usage = agent_orchestrator.consume_last_usage_metadata()
        artifact_sources = _artifact_sources_payload(artifacts, artifact_usage)
        artifact_meta = artifacts.get("_meta") if isinstance(artifacts.get("_meta"), dict) else {}
        requirements_meta = artifact_meta.get("requirements") if isinstance(artifact_meta.get("requirements"), dict) else {}
        architecture_meta = artifact_meta.get("architecture") if isinstance(artifact_meta.get("architecture"), dict) else {}
        requirements_seeded_files = (
            requirements_meta.get("seededFiles")
            if isinstance(requirements_meta.get("seededFiles"), list)
            else None
        )
        modify_generation_log = await _complete_process_log(
            modify_generation_log_ref[0],
            content=t(locale, "process.modify.completed"),
            duration=artifact_duration,
        )

        selected_modules_payload = [
            {
                "id": module.id,
                "label": module.name,
                "labelEn": module.nameEn,
            }
            for module in modules
        ]
        next_project = await store.bump_project_version(project_id)
        requirements_output_files = await _register_agent_output_dir(
            project_id,
            task_id,
            version=next_project.currentVersion,
            agent_name=str(requirements_meta.get("source") or "requirements_agent"),
            archive_stage="requirements-drafts",
            output_dir=str(requirements_meta.get("outputDir") or ""),
            source_files_by_artifact=requirements_meta.get("sourceFilesByArtifact") if isinstance(requirements_meta.get("sourceFilesByArtifact"), dict) else None,
        )
        _cleanup_local_path_if_configured(str(requirements_meta.get("outputDir") or ""))
        architecture_output_files = await _register_agent_output_dir(
            project_id,
            task_id,
            version=next_project.currentVersion,
            agent_name=str(architecture_meta.get("source") or "architecture_agent"),
            archive_stage="architecture",
            output_dir=str(architecture_meta.get("outputDir") or ""),
            source_files_by_artifact=architecture_meta.get("sourceFilesByArtifact") if isinstance(architecture_meta.get("sourceFilesByArtifact"), dict) else None,
        )
        _cleanup_local_path_if_configured(str(architecture_meta.get("outputDir") or ""))
        requirements_step_output_files = _filter_seeded_output_files(
            requirements_output_files,
            seeded_files=[str(file_name) for file_name in (requirements_seeded_files or [])],
        )
        changes: list[dict[str, Any]] = []
        artifact_items = _artifact_content_items(artifacts)
        artifact_count = max(1, len(artifact_items))
        for index, (artifact_type, content) in enumerate(artifact_items):
            artifact = await store.upsert_artifact(
                project_id,
                artifact_type,  # type: ignore[arg-type]
                existing_artifact_titles.get(artifact_type, {
                    "prd": "PRD Draft",
                    "ui": "UI Draft",
                    "architecture": "Architecture Draft",
                    "api_spec": "API Design",
                }[artifact_type]),
                content,
                metadata=_artifact_record_metadata(artifact_type, artifact_sources),
            )
            change_status = "Modified" if artifact_type in existing_artifact_titles else "Added"
            changes.append({"file": artifact.title, "status": change_status})
            await _append_message(
                Message(
                    projectId=project_id,
                    role="agent",
                    type="artifact_card",
                    content=artifact.title,
                    parentId=modify_generation_log.id,
                    metadata={
                        "artifactId": artifact.id,
                        "artifactType": artifact.type,
                        "title": artifact.title,
                        "preview": content[:120],
                    },
                )
            )
            await _broadcast(
                project_id,
                "task_artifact_attached",
                {
                    "taskId": task_id,
                    "logId": modify_generation_log.id,
                    "artifactType": artifact.type,
                    "artifactId": artifact.id,
                    "title": artifact.title,
                    "createdAt": utc_now().isoformat(),
                },
            )
            await _broadcast(
                project_id,
                "artifact_update",
                {
                    "artifactType": artifact.type,
                    "version": artifact.version,
                    "action": "modified",
                },
            )
            await _broadcast_progress(
                project_id,
                task_id,
                phase="artifact_generated",
                status="completed",
                progress=35 + int(((index + 1) / artifact_count) * 35),
                artifact_type=artifact.type,
                module_count=len(modules),
                reference_count=len(reference_snapshot),
            )

        await store.add_step_record(
            task_id,
            "Apply requested changes to generated artifacts",
            "generation",
            duration=artifact_duration,
            tokens_used=_usage_total_tokens(artifact_usage),
            cost=_usage_cost_amount(artifact_usage),
            status="completed",
            metadata=_step_usage_metadata(
                usage_metadata=artifact_usage,
                default_model=agent_orchestrator.get_model_name(),
                source_agent="requirements_agent",
                extra={
                    "artifactTypes": [artifact_type for artifact_type, _ in artifact_items],
                    "artifactSources": artifact_sources,
                    "operation": "modify",
                    "outputFiles": [*requirements_step_output_files, *architecture_output_files],
                },
            ),
        )
        await store.update_statistics(
            task_id,
            itemsRead=max(1, len(reference_materials)),
            inputTokens=int((artifact_usage or {}).get("inputTokens") or 0),
            outputTokens=int((artifact_usage or {}).get("outputTokens") or 0),
            totalTokens=int((artifact_usage or {}).get("totalTokens") or 0),
            modelUsed=_usage_model(artifact_usage, agent_orchestrator.get_model_name()),
            costAmount=_usage_cost_amount(artifact_usage),
            totalDuration=artifact_duration,
        )

        version = await store.create_version(
            project_id,
            "Applied follow-up modifications from the project chat.",
            changes,
            version_kind="modify",
            source_version=next_project.currentVersion - 1,
            created_by_type="agent",
            created_by="requirements_agent",
            state_manifest=await _state_manifest_for_version(project_id, next_project.currentVersion),
            modules_snapshot=await _selected_modules_snapshot(project_id),
        )
        pipeline_task = await store.update_generation_task(pipeline_task.id, project_id, status="completed", progress=100)
        await _broadcast(project_id, "task_update", pipeline_task.model_dump(mode="json"))
        if version:
            await _broadcast(
                project_id,
                "version_update",
                version.model_dump(mode="json"),
            )
        final_output = {
            **context_output,
            "artifactTypes": [artifact_type for artifact_type, _ in _artifact_content_items(artifacts)],
            "artifactSources": artifact_sources,
        }
        if await _request_runtime_variables_if_needed(
            project_id,
            task_id,
            prompt=prompt_with_context,
            selected_modules_payload=selected_modules_payload,
            next_action={
                "mode": "complete_task",
                "payload": final_output,
            },
        ):
            payload = await _statistics_payload(task_id)
            if payload is not None:
                await _broadcast(project_id, "statistics", payload.model_dump(mode="json"))
            return
        current_project = await store.get_project(project_id)
        if current_project is not None:
            await _generate_ui_workspace(
                project_id,
                task_id,
                prompt=prompt_with_context,
                selected_modules_payload=selected_modules_payload,
                locale=locale,
                running_message=t(locale, "process.ui_generation.modify.running"),
                completed_message=t(locale, "process.ui_generation.modify.completed"),
            )
            await _generate_code_workspace(
                project_id,
                task_id,
                prompt=prompt_with_context,
                selected_modules_payload=selected_modules_payload,
                locale=locale,
                running_message=t(locale, "process.code_generation.modify.running"),
                completed_message=t(locale, "process.code_generation.modify.completed"),
                step_extra={"operation": "modify"},
            )
            await _maybe_generate_test_workspace(
                project_id,
                task_id,
                prompt=prompt_with_context,
                selected_modules_payload=selected_modules_payload,
                locale=locale,
                running_message=t(locale, "process.test_generation.modify.running"),
                completed_message=t(locale, "process.test_generation.modify.completed"),
                step_extra={"operation": "modify"},
            )
        stats = await store.get_statistics(task_id)
        if stats is not None:
            await store.update_statistics(task_id, totalDuration=time.perf_counter() - flow_started_at, completedAt=utc_now())
        final_output["testGeneratedAt"] = utc_now().isoformat()
        await _complete_modify_task(project_id, task_id, final_output)
    except Exception as exc:
        await _handle_task_exception(project_id, task_id, exc)


async def cancel_task(project_id: str, task_id: str) -> None:
    await cancel_task_async(project_id, task_id)
    locale = await _task_locale(task_id)
    await store.update_task(task_id, status="cancelled", completed=True)
    await store.touch_project(project_id, status="cancelled")
    await _append_message(
        Message(
            projectId=project_id,
            role="system",
            type="text",
            content=t(locale, "task.cancelled"),
            metadata=_task_message_metadata(task_id, task_status="cancelled"),
        )
    )
    await _broadcast(
        project_id,
        "status_change",
        {"oldStatus": "running", "newStatus": "cancelled"},
    )
    await _broadcast(
        project_id,
        "task_round_finished",
        {
            "taskId": task_id,
            "status": "cancelled",
            "createdAt": utc_now().isoformat(),
        },
    )


async def recover_incomplete_tasks() -> None:
    for task in await store.list_tasks_by_status(["running"]):
        if await restore_waiting_task_from_interaction_message(task.projectId, task.id):
            continue
        await _handle_task_exception(
            task.projectId,
            task.id,
            RuntimeError("Task interrupted during service restart."),
            recovery=True,
        )
