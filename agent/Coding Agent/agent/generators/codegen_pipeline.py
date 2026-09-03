import os
from generators.dependency_manager import (
    collect_files,
    sort_files_by_priority,
    read_context
)
from generators.code_generator import generate_file_using_llm
from generators.mock_runtime import simple_mock_validate
from generators.file_classifier import FileClassifier

def unwrap_code_block(s: str) -> str:
    s = s.strip()
    if s.startswith("```") and s.endswith("```"):
        lines = s.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1])
    return s

class CodeGenPipeline:
    def __init__(self, *, project, working_memory, semantic_model,
                 code_desc, agent, output_root):
        self.project = project
        self.working_memory = working_memory
        self.semantic_model = semantic_model
        self.code_desc = code_desc
        self.agent = agent
        self.output_root = output_root
        
        self.classifier = FileClassifier()

        self.files = collect_files(project["backend"], prefix="backend")
        # self.files = collect_files(project["frontend"], prefix="frontend")
        self.ordered_files = sort_files_by_priority(self.files)


    def select_prompt_for_file(self, file_path: str):
        file_type = self.classifier.classify(file_path)
        return self.code_desc.get(file_type, self.code_desc["general"])

    def run(self):
        print("\n=== Code Generation Pipeline START ===\n")

        for file_path, meta in self.ordered_files:
            # print(file_path)
            # continue

            if self.working_memory.is_generated(file_path):
                print(f"Skip: {file_path}")
                continue

            real_path = self.output_root + file_path
            os.makedirs(os.path.dirname(real_path), exist_ok=True)
            print(f"- real_path: {real_path}")

            dep_paths = [self.output_root + "backend/" + d for d in meta.get("depends_on", [])]
            dep_context = read_context(dep_paths)
            # '''
            # dep_paths = []
            # for d in meta.get("depends_on", []):
            #     tmp_path = self.output_root + d
            #     classification = self.classifier.classify(tmp_path)
            #     if "backend" in classification.lower():
            #         real_path = self.output_root + "backend/" + d
            #     else:
            #         real_path = self.output_root + "frontend/" + d
            #     dep_paths.append(real_path)
            # dep_context = read_context(dep_paths)

            # real_path = self.output_root + file_path
            # os.makedirs(os.path.dirname(real_path), exist_ok=True)
            # print(f"- real_path: {real_path}")
            # '''
            print(f"→ Generating {file_path} (priority {meta['priority']})\n")
            file_type = self.classifier.classify(file_path)
            print(f"- The file type is: {file_type}\n")


            code = generate_file_using_llm(
                agent=self.agent,
                file_path=file_path,
                meta=meta,
                context=dep_context,
                semantic_model=self.semantic_model,
                code_desc=self.code_desc[file_type]
            )

            with open(real_path, "w", encoding="utf-8") as f:
                f.write(unwrap_code_block(code))


            self.working_memory.mark_generated(file_path)
            print(f"✔ Saved: {file_path}")
            # exit(0)      


        print("\n=== Code Generation Pipeline COMPLETE ===\n")

