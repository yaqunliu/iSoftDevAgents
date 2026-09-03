from util.util import store_path
from util import *
from RequirementAnalysis import DataDictionaryCrew, ERDCrew, DataFlowDiagramCrew, FRCrew, DialogMapCrew
import pdb
import hashlib
import json
import re
from BusinessRequirements import *


def classify_review_answer(answer: str) -> str:
    """
    统一判断人工反馈答案该走哪条分支。

    这里单独抽成函数，是因为 `exit` 必须先于“不是 no”被识别。
    否则一旦输入源被关闭，`exit` 就会被误当成普通修改意见，
    最后错误地送进 modify_agent。
    """

    normalized = str(answer or "").strip().lower()
    if normalized == "exit":
        return "exit"
    if normalized == "no":
        return "skip"
    return "modify"


def normalize_modify_execute_payload(payload):
    """
    把修改阶段返回的“下一轮要重跑哪些工件”统一整理成字典。

    接口注释：
    后续 BRD / Elicitation 各个 run() 都默认 `execute` 支持 `.get()`，
    所以这里负责把上游模型可能给出的不同形状统一掉。

    教学注释：
    - 理想情况：模型返回 `{"feature_tree": "...", "business_scope": "..."}` 这样的字典
    - 兼容情况：模型只返回 `["feature_tree", "business_scope"]` 这样的列表
      这时我们至少把它转换成可继续执行的空说明字典，避免流程直接崩溃
    """

    if isinstance(payload, dict):
        normalized_payload = {}
        for key, value in payload.items():
            normalized_key = str(key).strip()
            if not normalized_key:
                continue
            normalized_payload[normalized_key] = str(value or "")
        return normalized_payload

    if isinstance(payload, list):
        normalized_payload = {}
        for item in payload:
            normalized_key = str(item).strip()
            if not normalized_key:
                continue
            normalized_payload[normalized_key] = ""
        return normalized_payload

    raise TypeError("modify execute payload must be a dict or list")


def _extract_first_json_payload(raw_text: str) -> str:
    """
    接口注释：
    从一段可能夹杂解释文字的文本里，提取第一个完整 JSON 对象或数组。

    设计注释：
    Requirements Agent 的模型输出偶尔会长这样：
    1. ```json ... ```
    2. ```JSON ... ```
    3. 普通 ``` ... ```
    4. JSON 前后再夹一两句解释

    如果这里只做简单的 `.replace("```json", "")`，
    一遇到大小写变化、普通围栏、或者前后多一句说明，就还是会崩。
    所以这里改成按字符扫描，真正找出第一段完整的 JSON 结构。
    """

    start_index = -1
    opening_char = ""
    for index, char in enumerate(raw_text):
        if char in "{[":
            start_index = index
            opening_char = char
            break

    if start_index < 0:
        raise ValueError("文本中没有找到 JSON 起始符号 '{' 或 '['")

    closing_char = "}" if opening_char == "{" else "]"
    depth = 0
    in_string = False
    escaping = False

    for index in range(start_index, len(raw_text)):
        char = raw_text[index]

        if in_string:
            if escaping:
                escaping = False
                continue
            if char == "\\":
                escaping = True
                continue
            if char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char == opening_char:
            depth += 1
            continue

        if char == closing_char:
            depth -= 1
            if depth == 0:
                return raw_text[start_index : index + 1]

    raise ValueError("找到了 JSON 开头，但没有找到完整结束位置")


def load_json_payload_from_markdown(raw_text: str):
    """
    接口注释：
    把模型写进 Markdown 文件里的 JSON 安全解析成 Python 对象。

    教学注释：
    这个函数故意按“从最原始到最宽松”的顺序尝试：
    1. 直接按纯 JSON 解析
    2. 去掉 ```json / ```JSON / ``` 围栏后再解析
    3. 从带说明文字的整段文本里提取第一段完整 JSON 再解析

    这样既兼容最干净的输出，也能兜住 LLM 常见的 Markdown 包裹格式。
    """

    text = str(raw_text or "").strip()
    # qwen3 等模型会输出 <think>...</think> 思考标签，
    # 其中常包含 JSON 示例片段，会干扰后续的 JSON 提取逻辑，先剥掉。
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    if not text:
        raise ValueError("JSON 内容为空，无法解析")

    candidates: list[str] = [text]

    fenced_match = re.match(r"^\s*```(?:\s*[A-Za-z0-9_-]+)?\s*\n([\s\S]*?)\n?```\s*$", text, flags=re.IGNORECASE)
    if fenced_match:
        candidates.append(fenced_match.group(1).strip())

    try:
        candidates.append(_extract_first_json_payload(text).strip())
    except ValueError:
        pass

    if fenced_match:
        try:
            candidates.append(_extract_first_json_payload(fenced_match.group(1)).strip())
        except ValueError:
            pass

    last_error = None
    seen: set[str] = set()
    for candidate in candidates:
        normalized_candidate = str(candidate or "").strip()
        if not normalized_candidate or normalized_candidate in seen:
            continue
        seen.add(normalized_candidate)
        try:
            return json.loads(normalized_candidate)
        except json.JSONDecodeError as error:
            last_error = error

    if last_error is not None:
        raise last_error
    raise ValueError("没有找到可解析的 JSON 内容")


def modify_agent(feedback, project_name: str, Description: str,reference = ['survey', 'feature_tree', 'context_diagram', 'event_list', 'user_introduction', 'business_scope']): # 历史上的改变需要变成列表叠加
    # 设计注释：
    # StandardProcess 模块在文件加载时已经通过 `from BusinessRequirements import *`
    # 把 BRDModifyCrew / BRDModifyLocateCrew 放进当前模块作用域。
    # 这里不要在收到人工反馈后再次临时导入一次，
    # 否则平台长链路运行时一旦 import 路径发生波动，就会在“修改分支”现场崩掉，
    # 表现出来就是前面的草稿文件都有了，但后续 SRS.md 永远产不出来。
    inputs = {
        'feedback': '\n'.join([i for i in feedback]),
        'reference': get_reference(reference, artifact = False)
    }
    def modify_post_process():
        content = read_markdown(f"{store_path}/BRD_modify.md")
        if len(content) < 3:
            raise ValueError("修改结果过短，可能是修改失败了，请检查反馈内容是否符合要求，或者调整修改的参数")
        re_execute = load_json_payload_from_markdown(read_markdown(f"{store_path}/BRD_modify.md"))
        return re_execute
    try:
        re_execute = run_with_retry(
            BRDModifyLocateCrew,
            inputs=inputs,
            name=f"BRDModifyCrew",
            post_process_callable=modify_post_process,
        )
    except:
        raise FileNotFoundError("can not modify BRD.")
    reference = list(get_dependent_artifacts(re_execute) & set(reference))
    inputs = {
        'feedback': '\n'.join([i for i in feedback]),
        'Description': Description,
        'project_name': project_name,
        'reference': get_reference(reference,)
    }
    try:
        re_execute = run_with_retry(
            BRDModifyCrew,
            inputs=inputs,
            name=f"BRDModifyCrew",
            post_process_callable=modify_post_process,
        )
    except:
        raise FileNotFoundError("can not modify BRD.")
    return normalize_modify_execute_payload(re_execute)

def justfordebug():
    return  

def MetaAnalysisrun(doc_example_path, SRS_template = 'Initial', project_name = None, Description = None):
    if not doc_example_path and not SRS_template:
        raise ValueError("必须至少提供 --srs_example_path 或 --srs_template 之一")
    from MetaAnalysis import ExtractDocumentCrew, ArtifactPlanningCrew, DocContentCrew, ChapterDependenceCrew
    def sha256(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    if doc_example_path:
        hash_template = sha256(read_markdown(doc_example_path))
    else:
        if SRS_template == 'IEEE':
            hash_template = sha256('util/doc_template/BusinessRequirement/IEEE_template.py')
        elif SRS_template == '438C-08':
            hash_template = sha256('util/doc_template/BusinessRequirement/template_438C_08.py')
        elif SRS_template == 'Initial':
            hash_template = sha256('util/doc_template/BusinessRequirement/Initial_template.py')
    if os.path.exists(f"template/document_template_{hash_template}.pkl"):
        with open(f"template/document_template_{hash_template}.pkl", "rb") as f:
            (document_template, document_skeleton, doc_planning, chapter_dependence, artifact_planing) = pickle.load(f)
        return document_template, document_skeleton, doc_planning, chapter_dependence, artifact_planing
    else:
        #===================== Step 1: Document Extraction =====================
        def skeleton_post_process():
            document_skeleton = get_document_skeleton()
            document_template = parse_skeleton_to_document_template(
            skeleton_json=document_skeleton,
            authors='csl-gpt4.1'
        )
            return document_template, document_skeleton
        if SRS_template == 'IEEE':
            document_template = get_srs_Template(template = 'IEEE', authors='csl')
        elif SRS_template == '438C-08':
            document_template = get_srs_Template(template = '438C-08', authors='csl')
        elif SRS_template == 'Initial':
            document_template = get_srs_Template(authors='csl')
        else:
            document_example = read_markdown(doc_example_path)
            EDC_inputs = {
        'document_chapter': document_example,
    }
            document_template, document_skeleton = run_with_retry(
            ExtractDocumentCrew,
            inputs=EDC_inputs,
            name=f"ExtractDocumentCrew",
            post_process_callable=skeleton_post_process,
        )

        # For known templates, generate skeleton from template
        if SRS_template in ('IEEE', '438C-08', 'Initial'):
            document_skeleton = generate_skeleton_from_template(document_template)

        # ===================== Step 2: Document planning =====================
        def doc_planning_post_process():
            doc_planning = load_json_payload_from_markdown(read_markdown(f"{store_path}/doc_content.md"))
            return doc_planning
        srs_document_content = read_markdown(doc_example_path) if doc_example_path else document_template.get_whole_document(introduction=True)
        doc_planning_inputs = {
            'SRS_Document_Content': srs_document_content, # 忽略第一个
            }
        doc_planning = run_with_retry(
            DocContentCrew,
            inputs=doc_planning_inputs,
            name=f"DocContentCrew",
            post_process_callable=doc_planning_post_process,
        )
        # ===================== Step 3: chapter dependence =====================
        def chapter_dependence_post_process():
            chapter_dependence = load_json_payload_from_markdown(read_markdown(f"{store_path}/chapter_dependence.md"))
            return chapter_dependence
        chapter_dependence_inputs = {
        'doc_planning': doc_planning_post_process(), # 忽略第一个
        }
        chapter_dependence = run_with_retry(
            ChapterDependenceCrew,
            inputs=chapter_dependence_inputs,
            name=f"ChapterDependenceCrew",
            post_process_callable=chapter_dependence_post_process,
        )
        # ===================== Step 4: Artifact Planning =====================
        def artifact_post_process():
            artifact_DAG = to_artifact_DAG(get_artifact_planing())
            assert len(chapter_dependence) == len(get_artifact_planing())
        APC_inputs = {
        # 'document_structure': document_template.get_whole_document(),
        'artifact_to_choose': get_reference(artifact = False),
        'document_structure': get_document_skeleton()
    }
        run_with_retry(
            ArtifactPlanningCrew,
            inputs=APC_inputs,
            name=f"ArtifactPlanningCrew",
            post_process_callable=artifact_post_process,
        )
        artifact_planing = get_artifact_planing()
        with open(f"template/document_template_{hash_template}.pkl", "wb") as f:
            pickle.dump((document_template, document_skeleton, doc_planning, chapter_dependence, artifact_planing), f)
        return document_template, document_skeleton, doc_planning, chapter_dependence, artifact_planing


def BRDevrun(project_name: str, Description: str, initial_phase: str = 'survey', execute = {'all': ''},  feedback_list = []):

    detect_and_set_language(Description)
    feedback = '本轮没有人类意见'
    while execute:
        BR_Initial_Template = get_br_Initial_Template(authors='csl')
        artifact_dict = {
        'survey' : surveyRun(project_name=project_name,Description=Description, BR_Initial_Template=BR_Initial_Template),
        # 'competitive_analysis' : CompetitiveAnalysisRun(project_name=project_name),
        'context_diagram' : ContextDiagramRun(project_name=project_name,Description=Description),
        'event_list' : eventlistRun(project_name=project_name,Description=Description),
        'user_introduction' : UserIntroductionRun(project_name=project_name,Description=Description),
        'feature_tree': FeatureTreeRun(project_name=project_name,Description=Description),
        'business_scope': BusinessScopeRun(project_name=project_name,Description=Description)
    }
        if 'all' not in execute:
            feedback = f'这是用户的第{len(feedback_list)}轮反馈：{feedback_list[-1]}\n'
        if ('all' in execute and initial_phase == 'survey') or 'survey' in execute:
            artifact_dict['survey'].run(feedback,execute)
        if ('all' in execute and initial_phase == 'competitive_analysis') or 'competitive_analysis' in execute:
            artifact_dict['competitive_analysis'].run(feedback,execute)
            initial_info = get_competitive_analysis()
        if 'all' in execute or 'context_diagram' in execute:
            artifact_dict['context_diagram'].run(feedback,execute)
        if 'all' in execute or 'event_list' in execute:
            artifact_dict['event_list'].run(feedback,execute)
        if 'all' in execute or 'user_introduction' in execute:
            artifact_dict['user_introduction'].run(feedback,execute)
        if 'all' in execute or 'feature_tree' in execute:
            artifact_dict['feature_tree'].run(feedback,execute,get_survey())
        # ===================== Step 5: business scope ===================
        artifact_dict['business_scope'].run(feedback,execute)
        print("请查看现有的business_scope.md文档并告诉我有哪些需要改进的地方：")
        answer = multiline_input(checkpoint="business_scope_review")
        review_action = classify_review_answer(answer)
        if review_action == "exit":
                print("business_scope_review 收到退出信号，结束当前运行。")
                exit()
        if review_action == "modify":
            print("business_scope_review 收到修改意见，开始重新定位需要重做的需求产物。")
            feedback_list.append(answer)
            execute = modify_agent(feedback_list,project_name=project_name,Description=Description)
            continue
        print("business_scope_review 确认无需修改，继续进入 BRD 生成阶段。")
                
        # ===================== Step 6: BRD Chapter Generation ===================
        BRD = get_br_Initial_Template(authors='csl')
        BRD_Reference = [
            ['survey', 'business_scope'],
            ['survey', 'business_scope', 'feature_tree', 'context_diagram', 'event_list'],
            ['survey', 'user_introduction', 'business_scope'],
        ]
        def post_process():
            chapter = read_markdown(f"{store_path}/business_requirements_chapter.md")
            chapter = load_json_payload_from_markdown(chapter)
            BRD.write_file(chapter)
            with open(f"{store_path}/BusinessRequirementDocument.pkl", "wb") as f:
                pickle.dump(BRD, f)
            with open(f"{store_path}/BRD.md", "w", encoding="utf-8") as f:
                f.write(f"{BRD.get_whole_document()}{get_dependence_appendix(BRD_Reference)}")
            
        for i in range(len(BR_Initial_Template.SUBCHAPTERS)):
            BRD_inputs = {
                'Description': Description,
                'project_name': project_name,
                'document_format_reference': BR_Initial_Template.SUBCHAPTERS[i].get_all_content(introduction = True),
                'reference': get_reference(BRD_Reference[i]),
                'chapter_index': i + 1,
            }
            run_with_retry(BRDev, 
                        BRD_inputs, 
                        name=f"BRDev Chapter {i+1}",
                        post_process_callable=post_process)
        with open(f"{store_path}/BRD.md", "w", encoding="utf-8") as f:
            f.write(f"{BRD.get_whole_document(only_show_written = True)}{get_dependence_appendix(BRD_Reference)}")

        print("请查看现有的BRD.md文档(建议着重关注2.1章)并告诉我有哪些需要改进的地方：")
        answer = multiline_input(checkpoint="brd_review")
        review_action = classify_review_answer(answer)
        if review_action == "exit":
                print("brd_review 收到退出信号，结束当前运行。")
                exit()
        if review_action == "modify":
            print("brd_review 收到修改意见，开始重新定位需要重做的需求产物。")
            feedback_list.append(answer)
            execute = modify_agent(feedback_list,project_name=project_name,Description=Description)
        else:
            print("brd_review 确认无需修改，本轮 BRD 草稿阶段完成。")
            return
    return 



def RequirementElicitationrun(project_name, Description: str, execute = {'all': ''},  feedback_list = []):
    from RequirementElicitation import UserCaseRun,  NFRRun
    artifact_dict = {
        'use_case' : UserCaseRun(project_name=project_name,Description=Description),
        # 'competitive_analysis' : CompetitiveAnalysisRun(project_name=project_name),
        'non_functional_requirements' : NFRRun(project_name=project_name,Description=Description),
    }
    feedback = '本轮没有人类意见'
    while execute:
        if (('all' in execute) or
            ('survey' in execute) or
            ('context_diagram' in execute) or
            ('event_list' in execute) or 
            ('user_introduction' in execute) or
            ('feature_tree' in execute)):
            pass
            BRDevrun(project_name=project_name,Description=Description, initial_phase='survey', execute = execute, feedback_list = feedback_list)
        if 'all' not in execute:
            feedback = f'这是用户的第{len(feedback_list)}轮反馈：{feedback_list[-1]}\n'
        if 'all' in execute or 'use_case' in execute:
            artifact_dict['use_case'].run(feedback,execute)       
        if 'all' in execute or 'non_functional_requirements' in execute:
            artifact_dict['non_functional_requirements'].run(feedback,execute)    
        print("请查看现有的non_functional_requirements.md和use_case.md文档并告诉我有哪些需要改进的地方？，如果没有请直接输入no：")
        answer = multiline_input(checkpoint="elicitation_review")
        review_action = classify_review_answer(answer)
        if review_action == "exit":
                print("elicitation_review 收到退出信号，结束当前运行。")
                exit()
        if review_action == "modify":
            print("elicitation_review 收到修改意见，开始重新定位需要重做的需求产物。")
            feedback_list.append(answer)
            execute = modify_agent(feedback_list, reference = ['survey', 'feature_tree', 'context_diagram', 'event_list', 'user_introduction', 'use_case', 'non_functional_requirements', 'business_scope']
                                   ,project_name=project_name,Description=Description)
        else:
            print("elicitation_review 确认无需修改，继续进入后续需求分析阶段。")
            return

def RequirementAnalysisrun(project_name,Description,artifact_planing):
    from RequirementAnalysis import datadictionaryRun, DataFlowDiagramRun, FunctionRequirementRun, DialogMaprun, ERDRun
    order = topological_sort(to_artifact_DAG(artifact_planing), reverse=False)
    artifact_dict = {
        'data_dictionary' : datadictionaryRun(project_name=project_name,Description=Description),
        'ERD' : ERDRun(project_name=project_name,Description=Description),
        'data_flow_diagram' : DataFlowDiagramRun(project_name=project_name,Description=Description),
        'functional_requirements' : FunctionRequirementRun(project_name=project_name,Description=Description),
        'dialog_map' : DialogMaprun(project_name=project_name,Description=Description)
    }
    for artifact in order:
        if artifact in artifact_dict.keys():
            artifact_dict[artifact].run()
    

def StandardProcessrun(project_name, Description, srs_example_path, SRS_template):
    detect_and_set_language(Description)
    document_template, document_skeleton, doc_planning, chapter_dependence, artifact_planing = MetaAnalysisrun(srs_example_path, SRS_template, Description=Description, project_name=project_name)
    RequirementElicitationrun(project_name, Description=Description)
    RequirementAnalysisrun(project_name,Description,artifact_planing)
    return document_template, document_skeleton, doc_planning, chapter_dependence, artifact_planing
