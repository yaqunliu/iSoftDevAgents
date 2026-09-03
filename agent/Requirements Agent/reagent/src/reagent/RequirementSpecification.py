from util.SoftwareManager import SoftwareManagerCrew
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task, before_kickoff, after_kickoff
from crewai_tools import WebsiteSearchTool
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List
from util.util import store_path

class RequirementsSpecificationDevCrew(SoftwareManagerCrew):
    @agent
    def SoftwareManager(self) -> Agent:
        return Agent(
            config=self.agents_config["SoftwareManager"], # Gets injected by subclasses
            use_agent_data=False,
            llm = self.llm
            # memory = True,
        )

@CrewBase
class SRSev(RequirementsSpecificationDevCrew):
    @task
    def software_requirements_specification_chapter(self) -> Task:
        return Task(
            config=self.tasks_config["SRS_draft_task"],
            output_file=f"{store_path}/software_requirements_specification_chapter.md",
            agent = self.SoftwareManager()
        )
   
@CrewBase
class SRSplaningCrew(RequirementsSpecificationDevCrew):
    @task
    def srs_planning_task(self) -> Task:
        return Task(
            config=self.tasks_config["SRS_planning_task"],
            output_file=f"{store_path}/srs_planning.md",
            agent = self.SoftwareManager()
        )


    
    
