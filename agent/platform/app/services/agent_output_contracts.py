from __future__ import annotations

from typing import Literal, TypedDict


# 这里专门维护“平台认可的真实文件合同”。
# 目的很简单：
# 1. 不再把真实 Agent 输出文件散落在 workflow 里到处写
# 2. 让前端展示顺序、文件归类、后端 planned files 状态都共用一份定义
# 3. 未来接 Architecture / Code / UI / Test 的统一桥梁时，继续复用这里

ArtifactPanelType = Literal["prd", "ui", "architecture", "api_spec"]
AgentStageName = Literal["requirements_analysis", "requirements_full", "architecture", "ui", "code", "test"]


class PlannedFileContract(TypedDict):
    """
    接口注释：
    这是“主产物面板归类合同”里的最小单元。

    它描述的是：
    - 哪个真实文件
    - 来自哪个 Agent
    - 属于哪个阶段
    - 可以进入哪些主标签页

    注意这里说的是“主面板展示资格”，不是“这个文件在业务上可能和什么有关”。
    如果只是语义上沾边，但不应该出现在主面板，就不要放进 `mappedArtifactTypes`。
    """

    fileName: str
    label: str
    agent: str
    mappedArtifactTypes: list[ArtifactPanelType]
    stage: AgentStageName


def _planned_file(
    file_name: str,
    label: str,
    *,
    agent: str,
    stage: AgentStageName,
    mapped_artifact_types: list[ArtifactPanelType],
) -> PlannedFileContract:
    return {
        "fileName": file_name,
        "label": label,
        "agent": agent,
        "mappedArtifactTypes": mapped_artifact_types,
        "stage": stage,
    }


# 需求分析阶段只认 `feature_tree.md` 这个主合同文件。
# 其它 fallback 草稿文件如果真的出现，会进原始输出和步骤输出，不进主面板。
_REQUIREMENTS_ANALYSIS_PANEL_FILES: list[PlannedFileContract] = [
    _planned_file(
        "feature_tree.md",
        "功能树",
        agent="requirements_agent",
        stage="requirements_analysis",
        mapped_artifact_types=["prd", "ui", "api_spec"],
    ),
]


# Requirements full 阶段这里故意只放“主文件”。
# 中间文件例如 `UseCase.pkl`、`artifact_planning.md` 不进主面板，
# 它们后面会继续保留在 Step Outputs / Agent Raw Outputs 中。
_REQUIREMENTS_FULL_PANEL_FILES: list[PlannedFileContract] = [
    _planned_file("survey.md", "需求背景调研", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=["prd"]),
    _planned_file("draft_context_diagram.md", "上下文图草稿", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=[]),
    _planned_file("draft_event_list.md", "事件清单草稿", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=[]),
    _planned_file("user_introduction.md", "用户介绍", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=["prd"]),
    _planned_file("feature_tree.md", "功能树", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=["prd", "ui", "api_spec"]),
    _planned_file("business_scope.md", "业务范围", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=["prd"]),
    _planned_file("BRD.md", "业务需求文档", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=["prd"]),
    _planned_file("use_case.md", "用例文档", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=["ui", "api_spec"]),
    _planned_file("non_functional_requirements.md", "非功能需求", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=["prd"]),
    _planned_file("functional_requirements.md", "功能需求", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=["prd"]),
    _planned_file("data_flow_diagram.md", "数据流图", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=[]),
    _planned_file("entity_relationship_diagram.md", "实体关系图", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=[]),
    _planned_file("data_dictionary.md", "数据字典", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=[]),
    _planned_file("dialog_map.md", "对话地图", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=["ui"]),
    _planned_file("usage_scenario.md", "使用场景", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=["ui"]),
    _planned_file("state_transition_diagram.md", "状态流转图", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=[]),
    _planned_file("SRS.md", "软件需求规格说明书", agent="requirements_agent", stage="requirements_full", mapped_artifact_types=["prd"]),
]


_ARCHITECTURE_PANEL_FILES: list[PlannedFileContract] = [
    _planned_file("analysis_task_output.txt", "架构任务分析", agent="architecture_agent", stage="architecture", mapped_artifact_types=["architecture"]),
    _planned_file("component_design.json", "组件设计", agent="architecture_agent", stage="architecture", mapped_artifact_types=["architecture"]),
    _planned_file("class_design_structured.json", "结构化类设计", agent="architecture_agent", stage="architecture", mapped_artifact_types=["architecture"]),
    _planned_file("class_design_raw.md", "类设计文档", agent="architecture_agent", stage="architecture", mapped_artifact_types=["architecture"]),
]


_UI_PANEL_FILES: list[PlannedFileContract] = [
    _planned_file("page_descriptions.json", "页面描述 JSON", agent="ui_agent", stage="ui", mapped_artifact_types=["ui"]),
    _planned_file("page_descriptions.md", "页面描述文档", agent="ui_agent", stage="ui", mapped_artifact_types=["ui"]),
    _planned_file("dar_model.json", "DAR 模型 JSON", agent="ui_agent", stage="ui", mapped_artifact_types=["ui"]),
    _planned_file("dar_model.md", "DAR 模型文档", agent="ui_agent", stage="ui", mapped_artifact_types=["ui"]),
    _planned_file("app/index.html", "首页 HTML", agent="ui_agent", stage="ui", mapped_artifact_types=["ui"]),
    _planned_file("app/css/style.css", "页面样式", agent="ui_agent", stage="ui", mapped_artifact_types=["ui"]),
    _planned_file("app/js/index.js", "页面脚本", agent="ui_agent", stage="ui", mapped_artifact_types=["ui"]),
    _planned_file("app/js/api.js", "前端 API 封装", agent="ui_agent", stage="ui", mapped_artifact_types=["ui"]),
]


# 原因注释：
# `api_spec` 目前只有“合成后的 artifact 内容”，
# 并没有一个稳定、真实、一定会由 Agent 落盘的主面板原始文件。
# 之前把 `docs/API.yaml` 作为 planned file 挂在这里，
# 会让前端长期显示“待生成 / 失败”的假文件行，造成误导。
# 所以 API 标签页暂时不再展示 planned file，只在真正有 artifact 内容时展示内容本身。
_CODE_PANEL_FILES: list[PlannedFileContract] = []


def planned_requirements_analysis_files() -> list[str]:
    return [item["fileName"] for item in _REQUIREMENTS_ANALYSIS_PANEL_FILES]


def planned_requirements_full_files() -> list[str]:
    return [item["fileName"] for item in _REQUIREMENTS_FULL_PANEL_FILES]


def planned_architecture_files() -> list[str]:
    return [item["fileName"] for item in _ARCHITECTURE_PANEL_FILES]


def planned_ui_files() -> list[str]:
    return [item["fileName"] for item in _UI_PANEL_FILES]


def planned_code_files(module_names: list[str]) -> list[str]:
    """
    Code Agent 自己不写死输出文件名，所以这里定义平台 v1 合同。
    现在先按后端 Python 工程结构展开，顺序就是前端要展示的顺序。
    """

    normalized_modules = [name.strip() for name in module_names if name.strip()]
    files = [
        "backend/app/config.py",
        "backend/app/models/__init__.py",
    ]
    files.extend(f"backend/app/models/{module}.py" for module in normalized_modules)
    files.append("backend/app/repositories/__init__.py")
    files.extend(f"backend/app/repositories/{module}_repository.py" for module in normalized_modules)
    files.append("backend/app/services/__init__.py")
    files.extend(f"backend/app/services/{module}_service.py" for module in normalized_modules)
    files.append("backend/app/api/__init__.py")
    files.extend(f"backend/app/api/{module}_api.py" for module in normalized_modules)
    files.extend(
        [
            "backend/app/__init__.py",
            "backend/run.py",
        ]
    )
    return files


def planned_test_files(dataset_name: str) -> list[str]:
    dataset = dataset_name.strip() or "project"
    return [
        f"{dataset}_test_plan.md",
        "memory/test_plan.json",
        f"{dataset}_testcase.md",
    ]


def build_main_panel_contract(
    *,
    requirements_mode: Literal["analysis", "full"],
    include_architecture: bool,
    include_ui_agent_outputs: bool,
) -> dict[ArtifactPanelType, list[PlannedFileContract]]:
    """
    接口注释：
    返回主面板要显示的 planned files。

    这里是平台主产物面板归类的唯一规则入口。
    只要是 `PRD / UI / Architecture / API SPEC` 这 4 个标签页应该展示什么，
    都必须先看这里，再看前端。

    这里不返回中间文件，避免 PRD / UI / API / Architecture 面板被临时文件淹没。
    不适合主面板的文件，应该继续留在 Agent 原始输出和步骤输出里。
    """

    panel_contract: dict[ArtifactPanelType, list[PlannedFileContract]] = {
        "prd": [],
        "ui": [],
        "api_spec": [],
        "architecture": [],
    }

    requirements_files = (
        _REQUIREMENTS_ANALYSIS_PANEL_FILES
        if requirements_mode == "analysis"
        else _REQUIREMENTS_FULL_PANEL_FILES
    )
    for item in requirements_files:
        for artifact_type in item["mappedArtifactTypes"]:
            # 原因注释：
            # UI 标签页现在明确只展示 UI Agent 自己产出的页面原型文件。
            # 需求阶段那些 `use_case.md`、`dialog_map.md` 虽然会被 UI Agent 消费，
            # 但它们本质上还是“前置需求输入”，不应该混进 UI 页面主面板。
            if artifact_type == "ui":
                continue
            # 原因注释：
            # API 标签页只展示 API 自己的正式文件。
            # `feature_tree.md`、`use_case.md` 这些需求文件仍然会参与 API 生成，
            # 但它们属于“上游输入”，不应该在 API 主面板里伪装成 API 文件。
            if artifact_type == "api_spec":
                continue
            panel_contract[artifact_type].append(dict(item))

    if include_architecture:
        for item in _ARCHITECTURE_PANEL_FILES:
            panel_contract["architecture"].append(dict(item))

    if include_ui_agent_outputs:
        for item in _UI_PANEL_FILES:
            panel_contract["ui"].append(dict(item))

    for item in _CODE_PANEL_FILES:
        for artifact_type in item["mappedArtifactTypes"]:
            panel_contract[artifact_type].append(dict(item))

    return panel_contract
