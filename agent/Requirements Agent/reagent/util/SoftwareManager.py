from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task, before_kickoff, after_kickoff
from crewai_tools import WebsiteSearchTool
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List
from crewai import LLM
from dotenv import load_dotenv
import os
import pdb
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _resolved_reagent_tasks_config() -> str:
    configured = os.getenv("ISOFTDEVAGENTS_REAGENT_TASKS_CONFIG", "").strip()
    if configured:
        configured_path = Path(configured)
        if configured_path.name == "tasks.runtime.yaml" and not configured_path.exists():
            configured_path.parent.mkdir(parents=True, exist_ok=True)
            base_tasks = yaml.safe_load((PROJECT_ROOT / "src" / "reagent" / "config" / "tasks.yaml").read_text(encoding="utf-8")) or {}
            english_tasks = yaml.safe_load((PROJECT_ROOT / "src" / "reagent" / "config" / "tasks_eng.yaml").read_text(encoding="utf-8")) or {}
            merged_tasks = dict(base_tasks)
            merged_tasks.update(english_tasks)
            configured_path.write_text(yaml.safe_dump(merged_tasks, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return str(configured_path)

    runtime_path = PROJECT_ROOT / ".runtime-home" / "tasks.runtime.yaml"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    base_tasks = yaml.safe_load((PROJECT_ROOT / "src" / "reagent" / "config" / "tasks.yaml").read_text(encoding="utf-8")) or {}
    english_tasks = yaml.safe_load((PROJECT_ROOT / "src" / "reagent" / "config" / "tasks_eng.yaml").read_text(encoding="utf-8")) or {}
    merged_tasks = dict(base_tasks)
    merged_tasks.update(english_tasks)
    runtime_path.write_text(yaml.safe_dump(merged_tasks, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return str(runtime_path)


def _llm_request_timeout_seconds() -> float | None:
    """
    返回单次 LLM 请求超时时间。

    接口注释：
    这里控制的是“单次模型调用最多等多久”，不是整条 Requirements 流程的总超时。
    当提示词很大、模型返回慢、或者网关偶发抖动时，这个值太小就会出现一章反复超时重试。
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

class SoftwareManagerCrew:
    """Base class that provides shared agents and kickoff hooks.
    This class MUST NOT be decorated with @CrewBase."""

    # NOT registered automatically — only type hints
    agents: List[BaseAgent]
    tasks: List[Task]
    agents_config = os.getenv("ISOFTDEVAGENTS_REAGENT_AGENTS_CONFIG", "config/agents.yaml")
    tasks_config = _resolved_reagent_tasks_config()
    _llm_kwargs = {
        "model": os.getenv("ISOFTDEVAGENTS_LLM_MODEL") or os.getenv("OPENAI_MODEL", "o1"),
        "api_key": os.getenv("ISOFTDEVAGENTS_LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        "base_url": os.getenv("ISOFTDEVAGENTS_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
    }
    _request_timeout = _llm_request_timeout_seconds()
    if _request_timeout is not None:
        # 原因注释：
        # Requirements 这条链路经常会带很长的用例、图表、章节参考一起进模型。
        # 如果单次请求超时太短，就会出现“同一章连续超时重试”，日志里看起来像死循环。
        _llm_kwargs["timeout"] = _request_timeout
    llm = LLM(**_llm_kwargs)
    # Shared Agent ---------------------------------------------------
    @agent
    def SoftwareManager(self) -> Agent:
        return Agent(
            config=self.agents_config["SoftwareManager"],
            llm = self.llm,                     # ⭐ 关键
            verbose=True,
            use_agent_data=False
        )

    # Shared lifecycle hooks ----------------------------------------
    @before_kickoff
    def before_kickoff_function(self, inputs):
        return inputs

    @after_kickoff
    def after_kickoff_function(self, result):
        return result

    @crew
    def crew(self) -> Crew:
        """Creates the LatestAiDevelopment crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
