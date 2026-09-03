from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List
import os
from datetime import datetime
import json
from pymongo import MongoClient


def _llm_request_timeout_seconds() -> float | None:
    """
    返回单次 LLM 请求允许等待的秒数。

    教学注释：
    架构阶段的某些任务会把前面整理好的大量需求材料整包送给模型。
    如果单次请求超时太短，就会表现成“文件已经陆续写出来了，但后面某一步一直慢、一直重试”。
    """

    raw_value = str(
        os.getenv("ISOFTDEVAGENTS_LLM_REQUEST_TIMEOUT_SECONDS")
        or os.getenv("ISOFTDEVAGENTS_AGENT_LLM_REQUEST_TIMEOUT_SECONDS")
        or ""
    ).strip()
    if not raw_value:
        return None
    try:
        timeout_seconds = float(raw_value)
    except ValueError:
        return None
    return timeout_seconds if timeout_seconds > 0 else None


class LLMWithCache(LLM):
    def __new__(cls, *args, **kwargs):
        return object.__new__(cls)
    def __init__(self, **kwargs):
        self._llm = LLM(**kwargs)
        self.model = kwargs.get('model')
        self.seed = kwargs.get('seed')
        
        self.mongo_uri = os.getenv("MONGO_URI")
        self.use_cache = True if self.mongo_uri else False
        
        if self.use_cache:
            self.client = MongoClient(self.mongo_uri)
            self.db = self.client["chatgpt"]
            self.collection = self.db["arch_design"]
    
    def serialize(self, obj):
        return json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)
    
    def call(self, messages, tools=None, callbacks=None, **kwargs):

        if self.use_cache:
            query = {
                "messages": self.serialize(messages),
                "seed": self.seed,
                "tools": [tool.__class__.__name__ for tool in tools] if tools else None,
                "callbacks": [cb.__class__.__name__ for cb in callbacks] if callbacks else None,
                "model": self.model
            }
            try:
                cached_doc = self.collection.find_one(query)
                if cached_doc:
                    return cached_doc['result']
            except Exception as e:
                print(f"Error accessing cache: {e}")

        # Call the parent method
        res = self._llm.call(messages, tools, callbacks, **kwargs)
        
        if self.use_cache:
            doc = query.copy()
            doc['result'] = res
            doc['timestamp'] = datetime.now()
            self.collection.insert_one(doc)
        
        return res

    def __getattr__(self, name):
        return getattr(self._llm, name)
    
# If you want to run a snippet of code before or after the crew starts,
# you can use the @before_kickoff and @after_kickoff decorators
# https://docs.crewai.com/concepts/crews#example-crew-class-with-decorators

@CrewBase
class ArchDesign():
    """ArchAgent crew"""

    agents: List[BaseAgent]
    tasks: List[Task]
    timestamp: str
    
    arch_llm: LLMWithCache
    output_dir: str
    project_name: str


    # Learn more about YAML configuration files here:
    # Agents: https://docs.crewai.com/concepts/agents#yaml-configuration-recommended
    # Tasks: https://docs.crewai.com/concepts/tasks#yaml-configuration-recommended
    
    # If you would like to add tools to your agents, you can learn more about it here:
    # https://docs.crewai.com/concepts/agents#agent-tools

    def __init__(self, timestamp, project_name: str = "default_project"):
        self.project_name = project_name
        llm_kwargs = {
            "model": os.getenv("MODEL") or os.getenv("ISOFTDEVAGENTS_LLM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4.1-mini-2025-04-14"),
            "seed": int(os.getenv("SEED", 42)),
            "api_key": os.getenv("ISOFTDEVAGENTS_LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
            "base_url": os.getenv("BASE_URL") or os.getenv("ISOFTDEVAGENTS_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
        }
        request_timeout = _llm_request_timeout_seconds()
        if request_timeout is not None:
            llm_kwargs["timeout"] = request_timeout
        # 原因注释：
        # 架构 Agent 之前只把 api_key 放在进程环境里，实际创建 LLM 时却没有显式传入。
        # 这样不同版本的底层 SDK 是否会自动读取环境变量就变得不稳定，
        # 一旦这里没读到，就会出现“别的 Agent 正常，只有架构 Agent 401”的问题。
        self.arch_llm = LLMWithCache(**llm_kwargs)
        
        if not timestamp:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        self.timestamp = timestamp
        self.output_dir = os.path.join("data", "output", f"{timestamp}_{project_name}")

    
    
    @agent
    def unified_agent(self) -> Agent:
        # Configure LLM with a fixed seed and temperature for deterministic output
        # Respect model from config or env
        config = self.agents_config['unified_agent']
        return Agent(
            config=config,  # Assuming a unified config exists
            verbose=True,
            llm=self.arch_llm
        )

    def _generate_output_path(self, task_name: str) -> str:
        """Generate output path for a task based on the current date, time, and project name."""
        os.makedirs(self.output_dir, exist_ok=True)
        return os.path.join(self.output_dir, f"{task_name}_output.txt")

    # To learn more about structured task outputs,
    # task dependencies, and task callbacks, check out the documentation:
    # https://docs.crewai.com/concepts/tasks#overview-of-a-task
    @task
    def analysis_task(self) -> Task:
        return Task(
            config=self.tasks_config['analysis_task'], # type: ignore[index]
            output_file=self._generate_output_path("analysis_task")
        )

    # region - detailed modeling tasks
    @task
    def tech_stack_selection(self) -> Task:
        return Task(
            config=self.tasks_config['tech_stack_selection'],  # Add this to tasks.yaml
            output_file=self._generate_output_path("modeling-1.tech_stack_selection")
        )

    @task
    def architectural_style_selection(self) -> Task:
        return Task(
            config=self.tasks_config['architectural_style_selection'],  # Add this to tasks.yaml
            output_file=self._generate_output_path("modeling-2.architectural_style_selection"),
            verbose=True
        )

    @task
    def static_design(self) -> Task:
        return Task(
            config=self.tasks_config['static_design'],  # Add this to tasks.yaml
            output_file=self._generate_output_path("modeling-3.static_design")
        )

    @task
    def dynamic_design(self) -> Task:
        return Task(
            config=self.tasks_config['dynamic_design'],  # Add this to tasks.yaml
            output_file=self._generate_output_path("modeling-4.dynamic_design")
        )

    @task
    def deployment_design(self) -> Task:
        return Task(
            config=self.tasks_config['deployment_design'],  # Add this to tasks.yaml
            output_file=self._generate_output_path("modeling-5.deployment_design")
        )
    '''
    Designer
    '''
    @task
    def module_design(self) -> Task:
        return Task(
            config=self.tasks_config['module_design'],  # Add this to tasks.yaml
            output_file=self._generate_output_path("modeling-6.module_design")
        )
    @task
    def interface_design(self) -> Task:
        return Task(
            config=self.tasks_config['interface_design'],  # Add this to tasks.yaml
            output_file=self._generate_output_path("modeling-7.interface_design")
        )
    @task
    def interaction_model_development(self) -> Task:
        return Task(
            config=self.tasks_config['interaction_model_development'],  # Add this to tasks.yaml
            output_file=self._generate_output_path("modeling-8.interaction_model_development")
        )
    @task
    def deployment_and_resource_allocation(self) -> Task:
        return Task(
            config=self.tasks_config['deployment_and_resource_allocation'],  # Add this to tasks.yaml
            output_file=self._generate_output_path("modeling-9.deployment_and_resource_allocation")
        )
    '''
    Evaluator
    '''
    @task
    def architectural_mismatch_analysis(self) -> Task:
        return Task(
            config=self.tasks_config['architectural_mismatch_analysis'],  # Add this to tasks.yaml
            output_file=self._generate_output_path("modeling-10.architectural_mismatch_analysis")
        )
    @task
    def architectural_root_cause_analysis(self) -> Task:
        return Task(
            config=self.tasks_config['architectural_root_cause_analysis'],  # Add this to tasks.yaml
            output_file=self._generate_output_path("modeling-11.architectural_root_cause_analysis")
        )
    @task
    def refinement_suggestion(self) -> Task:
        return Task(
            config=self.tasks_config['refinement_suggestion'],  # Add this to tasks.yaml
            output_file=self._generate_output_path("modeling-12.refinement_suggestion")
        )
    @task
    def extractor(self) -> Task:
        return Task(
            config=self.tasks_config['extractor'],  # Add this to tasks.yaml
            output_file=self._generate_output_path("extractor")
        )
    @task
    def component_parser(self) -> Task:
        return Task(
            config=self.tasks_config['component_parser'],  # Add this to tasks.yaml
            output_file=self._generate_output_path("component_parser")
        )
    @task
    def class_design_parser(self) -> Task:
        return Task(
            config=self.tasks_config['class_design_parser'],
            output_file=self._generate_output_path("class_design_parser")
        )
    # endregion - detailed modeling tasks

    # @task
    # def design_task(self) -> Task:
    #     return Task(
    #         config=self.tasks_config['design_task'], # type: ignore[index]
    #         output_file=self._generate_output_path("design_task")
    #     )

    @crew
    def crew(self) -> Crew:
        """Creates the ArchAgent crew with a single unified agent."""
        return Crew(
            agents=[self.unified_agent()],  # Use the single unified agent
            tasks=self.tasks,  # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
            # memory=True
        )

# process to be changed
# memory 
# page 11
# new branch


# Step 1:
# - Fix 
