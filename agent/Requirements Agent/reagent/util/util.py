from pathlib import Path
import importlib.util
import os
import json
import pickle
import ast
import re
import pdb
import sys

try:
    from util.prompt_input_bridge import (
        TerminalPromptInputProvider,
        get_prompt_input_provider,
    )
except ModuleNotFoundError:
    # 这里兼容“直接按文件路径加载 util.py”的场景。
    # 某些测试和脚本不会把 reagent 根目录提前塞进 sys.path，
    # 所以不能强依赖 `from util.xxx import ...` 这种包路径导入。
    prompt_bridge_path = Path(__file__).resolve().parent / "prompt_input_bridge.py"
    prompt_bridge_spec = importlib.util.spec_from_file_location(
        "reagent_prompt_input_bridge_fallback",
        prompt_bridge_path,
    )
    if prompt_bridge_spec is None or prompt_bridge_spec.loader is None:
        raise
    prompt_bridge_module = importlib.util.module_from_spec(prompt_bridge_spec)
    sys.modules[prompt_bridge_spec.name] = prompt_bridge_module
    prompt_bridge_spec.loader.exec_module(prompt_bridge_module)
    TerminalPromptInputProvider = prompt_bridge_module.TerminalPromptInputProvider
    get_prompt_input_provider = prompt_bridge_module.get_prompt_input_provider

store_path = os.getenv("REAGENT_STORE_PATH", "output")
Path(store_path).mkdir(parents=True, exist_ok=True)

FIELDS = ['chapter_index', 'chapter_title', 'chapter_role', 'chapter_content_focus', 'recommended_expression_form']

def print_doc_content(d):
    return '\n'.join(
        f"{k}: {d[k]}"
        for k in FIELDS
        if k in d
    )

def multiline_input(prompt_text="请输入反馈：", checkpoint=None):
    """
    Requirements Agent 统一的人类反馈入口。

    业务层只应该调用这个函数，不要再直接依赖 prompt_toolkit 细节。
    这样本地终端模式和平台注入模式才能共用同一套调用入口。
    """

    provider = get_prompt_input_provider()
    if provider is None:
        if os.getenv("ISOFTDEVAGENTS_REAGENT_NONINTERACTIVE", "").strip().lower() in {"1", "true", "yes", "on"}:
            return "no"
        provider = TerminalPromptInputProvider()
    try:
        text = provider.read_multiline(prompt_text=prompt_text, checkpoint=checkpoint)
    except (EOFError, KeyboardInterrupt):
        return "exit"

    text = text.strip()
    if not text:
        return "no"
    if text.lower() == "exit":
        return "exit"
    return text

def split_markdown_by_h2(md_text: str) -> list[str]:
    pattern = re.compile(r'(?m)(?=^##\s+)')
    sections = [s.strip() for s in pattern.split(md_text) if s.strip()]
    return sections


def parse_artifact_dependencies(raw_text: str):
    """
    将 AI 输出的 Python 列表（含注释）解析为 list[list[str]]
    """
    # 1. 去掉所有行尾注释
    cleaned = re.sub(r"#.*", "", raw_text)

    # 2. 去掉空行
    cleaned = "\n".join(line for line in cleaned.split("\n") if line.strip())

    # 3. 转换为真正的 Python 对象
    try:
        result = ast.literal_eval(cleaned)
    except Exception as e:
        raise ValueError(f"解析 artifact planning 失败: {e}\n清理后的内容:\n{cleaned}")

    return result


def read_markdown(file_path: str) -> str:
    """
    读取 markdown 文件内容并返回为字符串
    :param file_path: .md 文件路径
    :return: 文件内容字符串
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Markdown file not found: {file_path}")
    
    # 根据需要调整 encoding，例如 'utf-8-sig'
    with path.open('r', encoding='utf-8') as f:
        content = f.read()
    return content

def get_user_case(file_path: str= f"{store_path}/UseCase.pkl") -> dict:
    """
    读取用户用例的 JSON 文件内容并返回为字典
    :param file_path: 用户用例 JSON 文件路径
    :return: 文件内容字典
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"User case file not found: {file_path}")
    
    with path.open('rb') as f:
        UCL = pickle.load(f)
    result = ''
    for uc in UCL:
        result += uc.get_usecase() + "\n"

    return result

def get_project_name():
    if os.path.exists(f'{store_path}/project_name.md'):
        return read_markdown(f'{store_path}/project_name.md')
    else:
        raise FileNotFoundError("project name file not found.")

def get_business_process():
    if os.path.exists(f'{store_path}/business_process_diagram.md'):
        return read_markdown(f'{store_path}/business_process_diagram.md')
    else:
        raise FileNotFoundError("business_process_diagram file not found.")
    
def get_state_transition_diagram():
    if os.path.exists(f'{store_path}/state_transition_diagram.md'):
        return read_markdown(f'{store_path}/state_transition_diagram.md')
    else:
        raise FileNotFoundError("state_transition_diagram file not found.")

def get_feature_tree():
    if os.path.exists(f'{store_path}/feature_tree.md'):
        return read_markdown(f'{store_path}/feature_tree.md')
    else:
        raise FileNotFoundError("feature tree file not found.")
    
def get_context_diagram():
    if os.path.exists(f'{store_path}/draft_context_diagram.md'):
        return read_markdown(f'{store_path}/draft_context_diagram.md')
    else:
        raise FileNotFoundError("Context diagram file not found.")
    
def get_functional_requirements():
    if os.path.exists(f'{store_path}/functional_requirements.md'):
        return read_markdown(f'{store_path}/functional_requirements.md')
    else:
        raise FileNotFoundError("Functional requirements file not found.")
    
def get_event_list():
    if os.path.exists(f'{store_path}/draft_event_list.md'):
        return read_markdown(f'{store_path}/draft_event_list.md')
    else:
        raise FileNotFoundError("Event list file not found.")

def get_business_scope():
    if os.path.exists(f'{store_path}/business_scope.md'):
        return read_markdown(f'{store_path}/business_scope.md')
    else:
        raise FileNotFoundError("business_scope file not found.")

def get_ERD():
    if os.path.exists(f'{store_path}/entity_relationship_diagram.md'):
        return read_markdown(f'{store_path}/entity_relationship_diagram.md')
    else:
        raise FileNotFoundError("ERD file not found.")

def get_usage_scenario():
    if os.path.exists(f'{store_path}/usage_scenario.md'):
        return read_markdown(f'{store_path}/usage_scenario.md')
    else:
        raise FileNotFoundError("Usage scenario file not found.")
    
def get_user_introduction():
    if os.path.exists(f'{store_path}/user_introduction.md'):
        return read_markdown(f'{store_path}/user_introduction.md')
    else:
        raise FileNotFoundError("User introduction file not found.")

def get_competitive_analysis():
    if os.path.exists(f'{store_path}/competitive_analysis.md'):
        return read_markdown(f'{store_path}/competitive_analysis.md')
    else:
        raise FileNotFoundError("Competitive analysis file not found.")
    
def get_survey():
    if os.path.exists(f'{store_path}/survey.md'):
        return read_markdown(f'{store_path}/survey.md')
    else:
        raise FileNotFoundError("Survey file not found.")

def get_BRD():
    if os.path.exists(f'{store_path}/BusinessRequirementDocument.pkl'):
        import pickle
        with open(f"{store_path}/BusinessRequirementDocument.pkl",'rb') as f:
            BRD = pickle.load(f)
        return BRD
    else:
        raise FileNotFoundError("Business Requirement Document file not found.")
    
def get_data_flow_diagram():
    if os.path.exists(f'{store_path}/data_flow_diagram.md'):
        return read_markdown(f'{store_path}/data_flow_diagram.md')
    else:
        raise FileNotFoundError("Data flow diagram file not found.")
    
def get_data_dictionary():
    if os.path.exists(f'{store_path}/data_dictionary.md'):
        return read_markdown(f'{store_path}/data_dictionary.md')
    else:
        raise FileNotFoundError("Data dictionary file not found.")
    
def get_dialog_map():
    if os.path.exists(f'{store_path}/dialog_map.md'):
        return read_markdown(f'{store_path}/dialog_map.md')
    else:
        raise FileNotFoundError("Dialog map file not found.")
    
def get_SRS_chapter():
    if os.path.exists(f'{store_path}/software_requirements_specification_chapter.md'):
        return read_markdown(f'{store_path}/software_requirements_specification_chapter.md')
    else:
        raise FileNotFoundError("Software Requirement Specification file not found.")
    
def get_SRS_planning():
    if os.path.exists(f'{store_path}/srs_planning.md'):
        return read_markdown(f'{store_path}/srs_planning.md')
    else:
        raise FileNotFoundError("Software Requirement Specification prompt file not found.")
    
def generate_skeleton_from_template(document_template):
    """Convert a document template object to skeleton JSON string and save to file."""
    def chapter_to_dict(chapter):
        result = {
            "title": chapter.TITLE,
            "chapter_index": chapter.SECTION,
            "structure": chapter.Structure,
        }
        if chapter.SUBCHAPTERS:
            result["subchapter"] = [chapter_to_dict(sub) for sub in chapter.SUBCHAPTERS]
        return result
    skeleton = [chapter_to_dict(ch) for ch in document_template.SUBCHAPTERS]
    skeleton_json = json.dumps(skeleton, ensure_ascii=False, indent=2)
    os.makedirs(store_path, exist_ok=True)
    with open(f'{store_path}/document_skeleton.md', 'w', encoding='utf-8') as f:
        f.write(skeleton_json)
    return skeleton_json

def get_document_skeleton():
    if os.path.exists(f'{store_path}/document_skeleton.md'):
        return read_markdown(f'{store_path}/document_skeleton.md')
    else:
        raise FileNotFoundError("Document skeleton file not found.")
    
def get_artifact_planing():
    if os.path.exists(f'{store_path}/artifact_planning.md'):
        return parse_artifact_dependencies(read_markdown(f'{store_path}/artifact_planning.md'))
    else:
        raise FileNotFoundError("Artifact planing file not found.")
    
def get_non_functional_requirements():
    if os.path.exists(f'{store_path}/non_functional_requirements.md'):
        return read_markdown(f'{store_path}/non_functional_requirements.md')
    else:
        raise FileNotFoundError("Non-Functional Requirements file not found.")
    
