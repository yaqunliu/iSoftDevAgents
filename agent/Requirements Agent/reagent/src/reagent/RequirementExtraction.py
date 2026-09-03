from landingai_ade import LandingAIADE
import os
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import WebsiteSearchTool
from util.SoftwareManager import SoftwareManagerCrew
from util.util import store_path
from util import *
import json
from pathlib import Path

    

class RequirementsExtractionDevCrew(SoftwareManagerCrew):
    pass

@CrewBase
class OfficeDocumentCrew(RequirementsExtractionDevCrew):
    @task
    def doc_summary_task(self) -> Task:
        return Task(
            config=self.tasks_config["doc_summary_task"],
            output_file=f"{store_path}/information_summary.md",
            agent = self.SoftwareManager()
        )

class RequirementsExtractionRun():
    def __init__(self, project_name, Description, data_path):
        self.project_name = project_name
        self.Description = Description
        self.data_path = data_path
        self.data_summary = {}

    def _post_process(self):
        result = read_markdown(f"{store_path}/information_summary.md")
        if len(result) < 100:
            raise ValueError("数据总结结果过短，可能是提取失败了，请检查数据文件是否符合要求，或者调整提取的参数")
        return result
    
    def run(self):
        data_dict = parse_folder_into_md(self.data_path)
        for key,value in data_dict.items():
            _inputs = {
                    'key': key,
                    'value': value,
                    'project_name': self.project_name,
                    'Description' : self.Description, 
                }
            self.data_summary[key] = run_with_retry(OfficeDocumentCrew, 
                                    _inputs, 
                                    name="OfficeDocumentCrew",
                                    post_process_callable=self._post_process,)
        output_root = Path(store_path)
        output_root.mkdir(parents=True, exist_ok=True)
        with open(output_root / "project_data_summary.md", "w", encoding="utf-8") as f:
            json.dump(
                self.data_summary, f, ensure_ascii=False, indent=2            
            )
        with open(output_root / "total_project_data.md", "w", encoding="utf-8") as f:
            json.dump(
                data_dict, f, ensure_ascii=False, indent=2            
            )
            

    

PERMITTED_EXT = {
    ".jpeg", ".jpg", ".png", ".pdf",
    ".doc", ".docx",
    ".ppt", ".pptx",
    ".csv", ".xlsx"
}

TEXT_EXT = {".txt", ".md"}

def parse_folder_into_md(root_dir: str):
    result = {}

    for root, _, files in os.walk(root_dir):
        
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            full_path = os.path.join(root, file)

            # ---------- 纯文本：直接读 ----------
            if ext in TEXT_EXT:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    result[full_path] = f.read()
                continue

            # ---------- 文档 / 图片：走 LandingAI ----------
            if ext in PERMITTED_EXT:
                
                try:
                    response = LandingAIADE().parse(
                        document_url=full_path,
                        model="dpt-2-latest"
                    )
                    result[full_path] = response.markdown
                except Exception as e:
                    result[full_path] = f"[ERROR] {str(e)}"

    return result

                
