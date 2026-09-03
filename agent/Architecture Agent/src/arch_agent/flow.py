from crewai.flow.flow import Flow, listen, start, or_
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from arch_agent.crew import ArchDesign
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from pathlib import Path
from datetime import datetime
import re
import json
import os

class RequirementsExtraction(BaseModel):
    functional_requirements: str = Field(..., description="The functional requirements extracted from the text.")
    non_functional_requirements: str = Field(..., description="The non-functional requirements extracted from the text.")
    constraints_and_assumptions: str = Field(..., description="The constraints and assumptions extracted from the text.")

class TechStackExtraction(BaseModel):
    selected_tech_stack: str = Field(..., description="The selected technical stack including programming languages, frameworks, and key libraries.")

class ArchStyleExtraction(BaseModel):
    selected_architectural_style: str = Field(..., description="The selected architectural style.")

class Component(BaseModel):
    name: str = Field(..., description="Name of the component")
    interfaces: List[str] = Field(..., description="List of interfaces provided or required by the component")
    description: str = Field(..., description="Brief description of the component's responsibility")
    related_functional_requirements: List[str] = Field(..., description="List of functional requirements IDs or descriptions mapped to this component")

class DynamicDesignExtraction(BaseModel):
    component_diagram_code: str = Field(..., description="The UML component diagram code (e.g., PlantUML or Mermaid).")
    components: List[Component] = Field(..., description="List of components identified in the design.")

class ModuleDesignExtraction(BaseModel):
    class_diagram: str = Field(..., description="The UML class diagram code (e.g., PlantUML or Mermaid).")
    class_description: str = Field(..., description="A detailed textual description of the classes designed for the component.")

# For later
class ArchiState(BaseModel):
    user_input: Dict[str, Any] = Field(default_factory=dict)
    output_time : str = ""
    functional_requirement : str = ""
    non_functional_requirement : str = ""
    constraint : str = ""
    tech_stack_selection : str = ""
    architectural_style : str = ""
    uml_diagram : str = ""
    sequence_diagram : str = ""
    data_flow_diagram : str = ""
    infrastructure_topology_diagram : str = ""
    module_design : str = ""
    interface_design : str = ""
    component_diagram : str = ""
    components : List[Component] = Field(default_factory=list)
    structured_module_design : Dict[str, ModuleDesignExtraction] = Field(default_factory=dict)
    deployment_diagram : str = ""
    resource_allocation_plan : str = ""
    mismatch_analysis : str = ""
    root_case_analysis : str = ""
    refinement_suggestion : str = ""

# Main flow
class ArchiFlow(Flow[ArchiState]):
    
    def __init__(self, requirements_path: str = None, project_name: str = None):
        super().__init__()
        self.requirements_path = Path(requirements_path) if requirements_path else None
        self.project_name = project_name
    
    def _build_inputs(self,additional_inputs: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Construct the shared inputs dictionary for crew execution."""
        if not self.requirements_path:
            raise ValueError("Requirements path is not set.")
        requirements_file = self.requirements_path
        if not requirements_file.exists():
            raise FileNotFoundError(
                f"Requirements document not found at {requirements_file}. "
                "Please ensure the SRS file is available before running the agents."
            )

        requirements = requirements_file.read_text(encoding="utf-8")

        if not self.project_name:
            raise ValueError("Project name is not set.")
        inputs: Dict[str, Any] = {
            "project_name": self.project_name,
            "requirements": requirements,
            # "requirements_source": str(requirements_file),
            "current_year": str(datetime.now().year),
        }

        if additional_inputs:
            inputs.update(additional_inputs)

        return inputs

    def _write_usage_snapshot(self) -> None:
        usage_output_path = os.getenv("ISOFTDEVAGENTS_USAGE_OUTPUT", "").strip()
        if not usage_output_path:
            return

        input_tokens = 0
        output_tokens = 0
        total_tokens = 0

        # 优先从 _token_process 读取
        unified_agent = getattr(self, "unified_agent", None)
        token_process = getattr(unified_agent, "_token_process", None)
        if token_process is not None and hasattr(token_process, "get_summary"):
            summary = token_process.get_summary()
            input_tokens = int(getattr(summary, "prompt_tokens", 0) or 0)
            output_tokens = int(getattr(summary, "completion_tokens", 0) or 0)
            total_tokens = int(getattr(summary, "total_tokens", 0) or 0)

        # Fallback: 从 LLM._token_usage 读取
        if total_tokens <= 0 and input_tokens <= 0 and output_tokens <= 0:
            llm = getattr(unified_agent, "llm", None)
            token_usage = getattr(llm, "_token_usage", None)
            if isinstance(token_usage, dict):
                input_tokens = int(token_usage.get("prompt_tokens") or 0)
                output_tokens = int(token_usage.get("completion_tokens") or 0)
                total_tokens = int(token_usage.get("total_tokens") or 0)

        if total_tokens <= 0 and (input_tokens > 0 or output_tokens > 0):
            total_tokens = input_tokens + output_tokens
        if total_tokens <= 0 and input_tokens <= 0 and output_tokens <= 0:
            return

        payload = {
            "model": os.getenv("MODEL") or os.getenv("ISOFTDEVAGENTS_LLM_MODEL") or os.getenv("OPENAI_MODEL") or "",
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": total_tokens,
        }
        Path(usage_output_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _kickoff_with_usage(self, crew: Crew, *, inputs: Dict[str, Any]):
        result = crew.kickoff(inputs=inputs)
        self._write_usage_snapshot()
        return result

    '''
    Analyst
    '''
    
    # Entry point
    @start()
    def task_analysis(self):
        self.state.output_time = datetime.now().strftime('%Y%m%d_%H%M')
        if not self.project_name:
            raise ValueError("Project name is not set.")
        self.crew_class = ArchDesign(timestamp=self.state.output_time, project_name=self.project_name)
        self.base_crew = self.crew_class.crew()
        self.unified_agent = self.base_crew.agents[0]
        self.state.user_input = self._build_inputs()
        task = [i for i in self.base_crew.tasks if i.name == "analysis_task"]
        extract_task = [i for i in self.base_crew.tasks if i.name == "extractor"]
        
        result = self._kickoff_with_usage(Crew(
            agents=[self.unified_agent],  # Use the single unified agent
            tasks=task,  # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=False,
        ), inputs=self.state.user_input)

        # Requirement search using LLM summarizer with structured output
        extraction_task = extract_task[0]
        extraction_task.output_pydantic = RequirementsExtraction
        
        extraction_input = self._build_inputs({
            "term": "Functional Requirements, Non-Functional Requirements, and Constraints and Assumptions",
            "text": result.raw
        })
        
        extraction_result = self._kickoff_with_usage(Crew(
            agents=[self.unified_agent],
            tasks=[extraction_task],
            process=Process.sequential,
            verbose=False,
        ), inputs=extraction_input)
        
        extracted = extraction_result.pydantic
        self.state.functional_requirement = extracted.functional_requirements
        self.state.non_functional_requirement = extracted.non_functional_requirements
        self.state.constraint = extracted.constraints_and_assumptions
        
        result = {"source": "task_analysis", "result": result}
        return result
    
    '''
    Modeler
    '''
    @listen(task_analysis)
    def tech_stack_selection(self, state):
        task = [i for i in self.base_crew.tasks if i.name == "tech_stack_selection"]
        extract_task = [i for i in self.base_crew.tasks if i.name == "extractor"]

        input = self._build_inputs({
                "fr": self.state.functional_requirement,
                "nfr": self.state.non_functional_requirement,
                "con": self.state.constraint
            })
        result = self._kickoff_with_usage(Crew(
            agents=[self.unified_agent],  # Use the single unified agent
            tasks=task,  # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=False,
        ), inputs=input)
        
        extraction_task = extract_task[0]
        extraction_task.output_pydantic = TechStackExtraction
        
        extraction_input = self._build_inputs({
            "term": "Selected Technical Stack",
            "text": result.raw
        })
        
        extraction_result = self._kickoff_with_usage(Crew(
            agents=[self.unified_agent],
            tasks=[extraction_task],
            process=Process.sequential,
            verbose=False,
        ), inputs=extraction_input)

        self.state.tech_stack_selection = extraction_result.pydantic.selected_tech_stack
        result = {"source": "tech_stack_selection", "result": result}
        return result
    
    @listen(tech_stack_selection)
    def architectural_style_selection(self, state):
        task = [i for i in self.base_crew.tasks if i.name == "architectural_style_selection"]
        extract_task = [i for i in self.base_crew.tasks if i.name == "extractor"]
        input = self._build_inputs({
                "fr": self.state.functional_requirement,
                "nfr": self.state.non_functional_requirement,
                "con": self.state.constraint,
                "tech_stack": self.state.tech_stack_selection
            })
        result = self._kickoff_with_usage(Crew(
            agents=[self.unified_agent],  # Use the single unified agent
            tasks=task,  # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=False,
        ), inputs=input)
        
        extraction_task = extract_task[0]
        extraction_task.output_pydantic = ArchStyleExtraction
        
        extraction_input = self._build_inputs({
            "term": "Selected Architectural Style",
            "text": result.raw
        })
        
        extraction_result = self._kickoff_with_usage(Crew(
            agents=[self.unified_agent],
            tasks=[extraction_task],
            process=Process.sequential,
            verbose=False,
        ), inputs=extraction_input)

        self.state.architectural_style = extraction_result.pydantic.selected_architectural_style
        result = {"source": "architectural_style_selection", "result": result}
        return result

    @listen(architectural_style_selection)
    def static_design(self, state):
        task = [i for i in self.base_crew.tasks if i.name == "static_design"]
        input = self._build_inputs({
                "fr": self.state.functional_requirement,
                # "nfr": self.state.non_functional_requirement,
                "con": self.state.constraint,
                "tech_stack": self.state.tech_stack_selection,
                "arch_style": self.state.architectural_style
            })
        result = self._kickoff_with_usage(Crew(
            agents=[self.unified_agent],  # Use the single unified agent
            tasks=task,  # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=False,
        ), inputs=input)
        # This is still raw i think we should put some regex or another summarizer
        self.state.uml_diagram = result.raw
        result = {"source": "static_design", "result": result}
        return result
    
    @listen(static_design)
    def dynamic_design(self, state):
        task = [i for i in self.base_crew.tasks if i.name == "dynamic_design"]
        extract_task = [i for i in self.base_crew.tasks if i.name == "component_parser"]
        input = self._build_inputs({
                "fr": self.state.functional_requirement,
                "tech_stack": self.state.tech_stack_selection,
                "arch_style": self.state.architectural_style,
                "static_design": self.state.uml_diagram,
                "con": self.state.constraint
            })
        result = self._kickoff_with_usage(Crew(
            agents=[self.unified_agent],  # Use the single unified agent
            tasks=task,  # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=False,
        ), inputs=input)
        
        extraction_task = extract_task[0]
        extraction_task.output_pydantic = DynamicDesignExtraction
        
        extraction_input = self._build_inputs({
            "text": result.raw
        })
        
        extraction_result = self._kickoff_with_usage(Crew(
            agents=[self.unified_agent],
            tasks=[extraction_task],
            process=Process.sequential,
            verbose=False,
        ), inputs=extraction_input)

        self.state.component_diagram = extraction_result.pydantic.component_diagram_code
        self.state.components = extraction_result.pydantic.components
        
        file_name_components = f"component_design.json"
        output_dir = self.crew_class.output_dir
        with open(Path(output_dir) / file_name_components, "w", encoding="utf-8") as f:
            json.dump({"component_diagram": self.state.component_diagram, "components": [dict(c) for c in self.state.components]}, f, indent=4, ensure_ascii=False)
        
        
        self.state.sequence_diagram = result.raw
        self.state.interface_design = result.raw
        result = {"source": "dynamic_design", "result": result}
        return result
    
    @listen(dynamic_design)
    def deployment_design(self, state):
        task = [i for i in self.base_crew.tasks if i.name == "deployment_design"]
        input = self._build_inputs({
                "fr": self.state.functional_requirement,
                "nfr": self.state.non_functional_requirement,
                "con": self.state.constraint,
                "tech_stack": self.state.tech_stack_selection,
                "arch_style": self.state.architectural_style
            })
        result = self._kickoff_with_usage(Crew(
            agents=[self.unified_agent],  # Use the single unified agent
            tasks=task,  # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=False,
        ), inputs=input)
        # This is still raw i think we should put some regex or another summarizer
        self.state.infrastructure_topology_diagram = result
        result = {"source": "deployment_design", "result": result}
        return result
    '''
    Designer
    '''
    @listen(deployment_design)
    def module_design(self, state):
        component_designs = []
        component_designs_raw = []
        task_class_design = [i for i in self.base_crew.tasks if i.name == "module_design"][0]
        task_parser = [i for i in self.base_crew.tasks if i.name == "class_design_parser"][0]

        for comp in self.state.components:
            input_data = self._build_inputs({
                "component_name": comp.name,
                "component_description": comp.description,
                "component_interfaces": ", ".join(comp.interfaces),
                "related_frs": ", ".join(comp.related_functional_requirements),
            })
            result = self._kickoff_with_usage(Crew(
                agents=[self.unified_agent],  # Use the single unified agent
                tasks=[task_class_design],  # Automatically created by the @task decorator
                process=Process.sequential,
                verbose=False,
            ), inputs=input_data)
            
            extraction_task = task_parser
            extraction_task.output_pydantic = ModuleDesignExtraction
            extraction_input = self._build_inputs({"text": result.raw})
            
            extraction_result = self._kickoff_with_usage(Crew(
                agents=[self.unified_agent],
                tasks=[extraction_task],
                process=Process.sequential,
                verbose=False
            ), inputs=extraction_input)
            
            component_designs.append({"component_name": comp.name, "class_design": dict(extraction_result.pydantic)})
            component_designs_raw.append(f"## Component: {comp.name}\n\n{result.raw}")
            pass
        
        file_name_structured = f"class_design_structured.json"
        file_name_raw = f"class_design_raw.md"
        output_dir = self.crew_class.output_dir
        with open(Path(output_dir) / file_name_structured, "w", encoding="utf-8") as f:
            json.dump(component_designs, f, indent=4, ensure_ascii=False)
        with open(Path(output_dir) / file_name_raw, "w", encoding="utf-8") as f:
            f.write("\n\n".join(component_designs_raw))

        self.state.module_design = "\n\n".join(component_designs_raw)
        result = {"source": "module_design", "result": self.state.module_design}
        return result
    
    # @listen(module_design)
    # def interface_design(self, state):
    #     self.base_crew = ArchDesign(timestamp=self.state.output_time).crew()
    #     self.unified_agent = self.base_crew.agents[0]
    #     task = [i for i in self.base_crew.tasks if i.name == "interface_design"]
    #     result =  Crew(
    #         agents=[self.unified_agent],  # Use the single unified agent
    #         tasks=task,  # Automatically created by the @task decorator
    #         process=Process.sequential,
    #         verbose=False,
    #     ).kickoff(inputs=self.state.user_input)
    #     result = {"source": "interface_design", "result": result}
    #     return result
    # @listen(interface_design)
    # def interaction_model_development(self, state):
    #     self.base_crew = ArchDesign(timestamp=self.state.output_time).crew()
    #     self.unified_agent = self.base_crew.agents[0]
    #     task = [i for i in self.base_crew.tasks if i.name == "interaction_model_development"]
    #     result =  Crew(
    #         agents=[self.unified_agent],  # Use the single unified agent
    #         tasks=task,  # Automatically created by the @task decorator
    #         process=Process.sequential,
    #         verbose=False,
    #     ).kickoff(inputs=self.state.user_input)
    #     result = {"source": "interaction_model_development", "result": result}
    #     return result
    # @listen(interaction_model_development)
    # def deployment_and_resource_allocation(self, state):
    #     self.base_crew = ArchDesign(timestamp=self.state.output_time).crew()
    #     self.unified_agent = self.base_crew.agents[0]
    #     task = [i for i in self.base_crew.tasks if i.name == "deployment_and_resource_allocation"]
    #     result =  Crew(
    #         agents=[self.unified_agent],  # Use the single unified agent
    #         tasks=task,  # Automatically created by the @task decorator
    #         process=Process.sequential,
    #         verbose=False,
    #     ).kickoff(inputs=self.state.user_input)
    #     result = {"source": "deployment_and_resource_allocation", "result": result}
    #     return result
    # '''
    # Evaluator
    # '''
    # # Note this might be an issue later on passing the input, the potential way to mitigate this is to put the result of the previous step to the state memory
    # # then parse it into the following function and in the task template
    # @listen(deployment_and_resource_allocation)
    # def architectural_mismatch_analysis(self, state):
    #     self.base_crew = ArchDesign(timestamp=self.state.output_time).crew()
    #     self.unified_agent = self.base_crew.agents[0]
    #     task = [i for i in self.base_crew.tasks if i.name == "architectural_mismatch_analysis"]
    #     result =  Crew(
    #         agents=[self.unified_agent],  # Use the single unified agent
    #         tasks=task,  # Automatically created by the @task decorator
    #         process=Process.sequential,
    #         verbose=False,
    #     ).kickoff(inputs=self.state.user_input)
    #     result = {"source": "architectural_mismatch_analysis", "result": result}
    #     return result
    # @listen(architectural_mismatch_analysis)
    # def architectural_root_cause_analysis(self, state):
    #     self.base_crew = ArchDesign(timestamp=self.state.output_time).crew()
    #     self.unified_agent = self.base_crew.agents[0]
    #     task = [i for i in self.base_crew.tasks if i.name == "architectural_root_cause_analysis"]
    #     result =  Crew(
    #         agents=[self.unified_agent],  # Use the single unified agent
    #         tasks=task,  # Automatically created by the @task decorator
    #         process=Process.sequential,
    #         verbose=False,
    #     ).kickoff(inputs=self.state.user_input)
    #     result = {"source": "architectural_root_cause_analysis", "result": result}
    #     return result
    # @listen(architectural_root_cause_analysis)
    # def refinement_suggestion(self, state):
    #     self.base_crew = ArchDesign(timestamp=self.state.output_time).crew()
    #     self.unified_agent = self.base_crew.agents[0]
    #     task = [i for i in self.base_crew.tasks if i.name == "refinement_suggestion"]
    #     result =  Crew(
    #         agents=[self.unified_agent],  # Use the single unified agent
    #         tasks=task,  # Automatically created by the @task decorator
    #         process=Process.sequential,
    #         verbose=False,
    #     ).kickoff(inputs=self.state.user_input)
    #     result = {"source": "refinement_suggestion", "result": result}
    #     return result
    # Template for later
    # Not yet completely tested
    # @listen(or_(architectural_style_selection,task_analysis))
    # def branch_test(self, result):
    #     if result["source"] == "architectural_style_selection":
    #         print("Last state was architectural_style_selection")
    #     elif result["source"] == "task_analysis":
    #         print("Last state was task_analysis")
def plot():
    """Generate a visualization of the flow"""
    flow = ArchiFlow()
    flow.plot("guide_creator_flow")
if __name__ == "__main__":
    flow = ArchiFlow()
    flow.plot("arch_flow")
