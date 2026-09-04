"""依赖项附录生成。

设计原因：
这里的文案是代码直接拼出来的，不经过 LLM，所以 run_with_retry 注入的
output_language_instruction 对它无效。必须在这里自己按检测到的输出语言切换，
否则英文需求也会在 BRD.md / SRS.md 末尾混进中文小节。
"""

from util.lang_detect import get_detected_language

# 附录标题。中文需求保持中文，其余语言统一用英文。
_APPENDIX_TITLE = {
    "zh": "附录：依赖项说明",
    "en": "Appendix: Dependency notes",
}

# 工件 key -> 各输出语言下的条目文案。
_ARTIFACT_LABELS = {
    "BRD": {
        "zh": "业务需求文档（BRD）参见 BRD.md",
        "en": "Business requirements document (BRD): see BRD.md",
    },
    "context_diagram": {
        "zh": "上下文图参见 draft_context_diagram.md",
        "en": "Context diagram: see draft_context_diagram.md",
    },
    "user_introduction": {
        "zh": "用户介绍参见 user_introduction.md",
        "en": "User introduction: see user_introduction.md",
    },
    "event_list": {
        "zh": "外部事件列表参见 event_list.md",
        "en": "External event list: see event_list.md",
    },
    "ERD": {
        "zh": "实体关系表参见 entity_relationship_diagram.md",
        "en": "Entity relationship diagram: see entity_relationship_diagram.md",
    },
    "competitive_analysis": {
        "zh": "竞品分析参见 competitive_analysis.md",
        "en": "Competitive analysis: see competitive_analysis.md",
    },
    "user_case": {
        "zh": "用户用例说明参见 user_case.md",
        "en": "Use case specification: see user_case.md",
    },
    "dialog_map": {
        "zh": "对话图参见 dialog_map.md",
        "en": "Dialog map: see dialog_map.md",
    },
    "data_flow_diagram": {
        "zh": "数据流图参见 data_flow_diagram.md",
        "en": "Data flow diagram: see data_flow_diagram.md",
    },
    "data_dictionary": {
        "zh": "数据字典参见 data_dictionary.md",
        "en": "Data dictionary: see data_dictionary.md",
    },
    "survey": {
        "zh": "现有解决方案调研参见 survey.md",
        "en": "Existing solution survey: see survey.md",
    },
    "state_transition_diagram": {
        "zh": "状态转换图参见 state_transition_diagram.md",
        "en": "State transition diagram: see state_transition_diagram.md",
    },
    "feature_tree": {
        "zh": "系统特性树参见 feature_tree.md",
        "en": "System feature tree: see feature_tree.md",
    },
    "functional_requirements": {
        "zh": "功能需求参见 functional_requirements.md",
        "en": "Functional requirements: see functional_requirements.md",
    },
    "non_functional_requirements": {
        "zh": "非功能性需求参见 non_functional_requirements.md",
        "en": "Non-functional requirements: see non_functional_requirements.md",
    },
    "usage_scenario": {
        "zh": "使用场景参见 usage_scenario.md",
        "en": "Usage scenario: see usage_scenario.md",
    },
}


def _appendix_language() -> str:
    """返回附录使用的语言。

    这段附录是静态文案，没法像 LLM 输出那样覆盖 lang_detect 支持的全部语言，
    所以只区分“中文”和“其余”，后者统一走英文。
    """
    return "zh" if (get_detected_language() or "").strip().lower() == "zh" else "en"


def get_dependence_appendix(dependence_list: list):
    all_artifacts = set()
    for line in dependence_list:
        for artifact in line:
            all_artifacts.add(artifact)
    language = _appendix_language()
    result = ''
    # 这个判断恒为真，保持原有行为不变（见改动说明）。
    if len(all_artifacts) >= 0:
        result += f'# {_APPENDIX_TITLE[language]}\n'
    for artifact in all_artifacts:
        label = _ARTIFACT_LABELS.get(artifact, {}).get(language)
        if label:
            result += f"- {label}\n"
    return result
