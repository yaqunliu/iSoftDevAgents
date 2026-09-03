from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task, before_kickoff, after_kickoff
from crewai_tools import WebsiteSearchTool
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List
from util.SoftwareManager import SoftwareManagerCrew
from util.util import store_path
from util import *
from StandardProcess import load_json_payload_from_markdown
class RequirementsElicitationDevCrew(SoftwareManagerCrew):
    pass
    
@CrewBase
class UsageScenarioCrew(RequirementsElicitationDevCrew):
    @task
    def usage_scenario_task(self) -> Task:
        return Task(
            config=self.tasks_config["usage_scenario_task"],
            output_file=f"{store_path}/usage_scenario.md",
            agent = self.SoftwareManager()
        )

@CrewBase
class UserCaseCrew(RequirementsElicitationDevCrew):
    @task
    def user_case_task(self) -> Task:
        return Task(
            config=self.tasks_config["use_case_draft_task"],
            output_file=f"{store_path}/use_case.md",
            agent = self.SoftwareManager()
        )
        

@CrewBase
class NFRCrew(RequirementsElicitationDevCrew):
    @task
    def nfr_task(self) -> Task:
        return Task(
            config=self.tasks_config["nfr_task"],
            output_file=f"{store_path}/non_functional_requirements.md",
            agent = self.SoftwareManager()
        )
    
class UserCaseRun():
    def __init__(self, project_name, Description):
        self.project_name = project_name
        self.Description = Description

    def UC_post_process(self):
        # 设计注释：
        # 先把模型常见的小格式抖动整理掉，再做严格校验。
        # 这样像 `secondary_actor: "Referee Service"` 这种单值写法，
        # 会被自动转成列表，不会让整条需求流程白白重跑五次。
        #
        # 原因注释：
        # LLM 输出的 JSON 经常被 ```json ``` 围栏包裹，或者有轻微格式错误
        # （重复的括号、逗号在引号里等）。这里按优先级尝试：
        # 1. load_json_payload_from_markdown：处理 markdown 围栏 + 提取 JSON
        # 2. json_repair：修复常见的 JSON 语法错误
        raw_text = read_markdown(f"{store_path}/use_case.md")
        try:
            parsed = load_json_payload_from_markdown(raw_text)
        except (json.JSONDecodeError, ValueError):
            try:
                from json_repair import repair_json
                parsed = json.loads(repair_json(raw_text))
            except Exception:
                parsed = json.loads(raw_text)
        UserCaseList = normalize_use_case_payload(parsed)
        is_valid, message = validate_use_case_format(UserCaseList)
        if not is_valid:
            raise ValueError(f"Use case format error: {message}")
        with open(f"{store_path}/use_case.md", "w", encoding="utf-8") as f:
            f.write(json.dumps(UserCaseList, ensure_ascii=False, indent=2))
        UCL = [UserCase(uc) for uc in UserCaseList]
        with open(f"{store_path}/UseCase.pkl", "wb") as f:
            pickle.dump(UCL, f)
    
    def run(self,feedback,execute):
        UC_inputs = {
                'reference': get_reference(['context_diagram', 'event_list', 'user_introduction']),
                'project_name': self.project_name,
                'Description' : self.Description, 
                'feedback': feedback + execute.get('use_case',''),
                'original' : '' if 'all' in execute else get_user_case()
            }
        run_with_retry(UserCaseCrew, 
                        UC_inputs, 
                        name="UserCaseCrew",
                        post_process_callable=self.UC_post_process,)
        
class NFRRun():
    def __init__(self, project_name, Description):
        self.project_name = project_name
        self.Description = Description

    def NFR_post_process(self):
        NFR = get_non_functional_requirements()
        if len(NFR) < 100:
            raise TypeError("Expected NFR too short.")
    
    def run(self,feedback,execute):
        NFR_inputs = {
                'reference': get_reference(['survey']),
                'project_name': self.project_name,
                "Description" : self.Description, 
                'feedback': feedback + execute.get('non_functional_requirements',''),
                'original' : '' if 'all' in execute else get_non_functional_requirements()
            }
        run_with_retry(NFRCrew, 
                    NFR_inputs, 
                    name="NFRCrew",
                    post_process_callable=self.NFR_post_process)
