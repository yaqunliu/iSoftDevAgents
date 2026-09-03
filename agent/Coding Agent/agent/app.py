from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.code_agent import create_codegen_agent
from config.paths import PATHS
from generators.codegen_pipeline import CodeGenPipeline
from loaders.file_loader import load_json, load_text
from loaders.semantic_loader import SemanticModel


def _load_optional_text(path: str | Path) -> str:
    target = Path(path)
    if not target.exists():
        return ""
    return load_text(str(target))


class WorkingMemory:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._generated_files: set[str] = set()

    def is_generated(self, file_path: str) -> bool:
        return file_path in self._generated_files

    def mark_generated(self, file_path: str) -> None:
        self._generated_files.add(file_path)
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"generated_files": sorted(self._generated_files)}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


class CodeAgentApp:
    def __init__(self, *, paths: dict[str, str] | None = None) -> None:
        self.paths = dict(PATHS)
        if paths:
            self.paths.update({key: str(value) for key, value in paths.items()})

        self.project = load_json(self.paths["project"])
        self.semantic_model = SemanticModel(self.paths["semantic_model"])
        self.memory = WorkingMemory(self.paths.get("memory"))
        self.codegen_agent = create_codegen_agent()
        self.code_desc = self._load_code_descriptions()

    def _load_code_descriptions(self) -> dict[str, str]:
        return {
            "backend_model": _load_optional_text(self.paths["code_desc_model"]),
            "backend_entry": _load_optional_text(self.paths["code_desc_general"]),
            "backend_api_module": _load_optional_text(self.paths["code_desc_route"]),
            "backend_service": _load_optional_text(self.paths["code_desc_service"]),
            "backend_repository": _load_optional_text(self.paths["code_desc_repo"]),
            "frontend_http_utils": _load_optional_text(self.paths["code_desc_front_utils"]),
            "frontend_api_client": _load_optional_text(self.paths["code_desc_front_api"]),
            "frontend_component": _load_optional_text(self.paths["code_desc_front_component"]),
            "frontend_pages": _load_optional_text(self.paths["code_desc_frontend_pages"]),
            "frontend_routes": _load_optional_text(self.paths["code_desc_frontend_routes"]),
            "frontend_app": _load_optional_text(self.paths["code_desc_frontend_app"]),
            "frontend_entry": _load_optional_text(self.paths["code_desc_frontend_entry"]),
            "frontend_general": _load_optional_text(self.paths["code_desc_frontend_general"]),
        }

    def run(self, *, mode: str = "full") -> None:
        if mode != "full":
            raise ValueError("CodeAgentApp currently supports only mode='full'.")

        output_root = self.paths["software"]
        if not output_root.endswith("/"):
            output_root = output_root + "/"

        print("\nStarting CodeAgent Pipeline...\n")
        print("Step 6: Code Generation Pipeline Running...\n")

        project = self.project if "backend" in self.project else {"backend": self.project}

        pipeline = CodeGenPipeline(
            project=project,
            working_memory=self.memory,
            semantic_model=self.semantic_model,
            code_desc=self.code_desc,
            agent=self.codegen_agent,
            output_root=output_root,
        )
        pipeline.run()
