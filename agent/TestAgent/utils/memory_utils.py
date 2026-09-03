from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Iterator, Optional


# ---------- 基础数据结构 ----------

@dataclass
class ExecutionStatus:
    """
    记录模块的执行状态
    stage: 0=STAGE_PLAN, 1=STAGE_DESIGN, 2=STAGE_REVIEW(跳过), 3=STAGE_DEV, 4=STAGE_RUN
    completed: 该阶段是否已完成
    """
    current_module_index: int = 0  # 当前执行到第几个模块（从0开始）
    current_stage: int = 1  # 当前阶段（从STAGE_DESIGN=1开始，因为STAGE_PLAN=0在加载前就完成了）
    module_stages: Dict[str, int] = None  # 每个模块已完成的阶段 module_id -> completed_stage
    
    def __post_init__(self):
        if self.module_stages is None:
            self.module_stages = {}
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ExecutionStatus':
        return cls(
            current_module_index=data.get('current_module_index', 0),
            current_stage=data.get('current_stage', 1),
            module_stages=data.get('module_stages', {})
        )
    
    def is_module_completed(self, module_id: str) -> bool:
        """检查模块是否已完全执行完成（STAGE_RUN=4 完成）"""
        return self.module_stages.get(module_id, 0) >= 4
    
    def get_module_stage(self, module_id: str) -> int:
        """获取模块当前已完成的阶段"""
        return self.module_stages.get(module_id, 0)
    
    def mark_stage_completed(self, module_id: str, stage: int):
        """标记某个模块的某个阶段已完成"""
        self.module_stages[module_id] = stage
        
    def get_next_stage(self, module_id: str) -> Optional[int]:
        """
        获取模块的下一个待执行阶段
        返回 None 表示该模块已完成所有阶段
        注意：STAGE_REVIEW=2 自动跳过
        """
        current = self.get_module_stage(module_id)
        # 阶段顺序: 1(DESIGN) -> 3(DEV) -> 4(RUN)，跳过2(REVIEW)
        if current < 1:
            return 1  # STAGE_DESIGN
        elif current == 1:
            return 3  # STAGE_DEV (跳过REVIEW)
        elif current == 3:
            return 4  # STAGE_RUN
        else:
            return None  # 已完成


@dataclass(frozen=True)
class Feature:
    feature_id: str
    name: str
    description: str
    methods: List[Dict[str, str]]  # [{signature: ..., description: ...}, ...]
    reqs: List[Dict[str, Any]]  # 需求列表
    dependencies: List[Dict[str, str]]  # 依赖列表

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "feature_name": self.name,
            "description": self.description,
            "methods": self.methods,
            "reqs": self.reqs,
            "dependencies": self.dependencies
        }


@dataclass(frozen=True)
class Module:
    module_id: str
    name: str
    classes: List[str]
    description: str
    features: List[Feature]

    def iter_methods(self) -> Iterator[Dict[str, str]]:
        """遍历该模块下所有方法（返回方法对象，包含 signature 和 description）"""
        for feature in self.features:
            for method in feature.methods:
                yield method

    def to_dict(self) -> Dict[str, Any]:
        """
        返回 Module 的 dict 表示（可 JSON 序列化）
        """
        return {
            "module_id": self.module_id,
            "module_name": self.name,
            "classes": self.classes,
            "description": self.description,
            "features": [f.to_dict() for f in self.features],
        }

    def to_json(self, *, indent: int = 2, ensure_ascii: bool = False) -> str:
        """
        返回 Module 的 JSON 字符串表示
        """
        return json.dumps(
            self.to_dict(),
            indent=indent,
            ensure_ascii=ensure_ascii,
        )

    def __str__(self) -> str:
        """
        类似 Java 的 toString()
        """
        return self.to_json()

# ---------- Memory 管理类 ----------

class Memory:
    """
    管理 modules.json 的内存表示
    支持：
      - 纯 JSON 文件
      - Markdown 文件（自动提取 ```json ... ``` 中的内容）
      - 执行状态持久化
    """

    def __init__(self, json_path: str|Path):
        self.json_path = Path(json_path).resolve()
        self.status_path = self.json_path.parent / "execution_status.json"
        self._modules: List[Module] = []
        self._raw_data: Dict[str, Any] = {}  # 保存原始数据用于写回
        self.execution_status: ExecutionStatus = ExecutionStatus()

        self._load()
        self._load_status()

    def _load(self) -> None:
        if not self.json_path.exists():
            raise FileNotFoundError(f"JSON file not found: {self.json_path}")

        # 读取整个文件内容为字符串
        text = self.json_path.read_text(encoding="utf-8")

        # 尝试 1：直接解析为 JSON（适用于纯 JSON 文件）
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            # 尝试 2：从 Markdown 的 ```json ... ``` 中提取 JSON
            match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
            if not match:
                raise ValueError(
                    f"File is not valid JSON and does not contain a ```json code block: {self.json_path}"
                )
            json_str = match.group(1).strip()
            if not json_str:
                raise ValueError(f"Empty JSON code block in file: {self.json_path}")
            try:
                raw = json.loads(json_str)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON inside ```json block in {self.json_path}: {e}") from e

        self._raw_data = raw
        
        # 验证结构
        modules_raw = raw.get("modules", [])
        if not isinstance(modules_raw, list):
            raise ValueError(f'"modules" must be a list in {self.json_path}')

        self._modules = [self._parse_module(m) for m in modules_raw]
    
    def _load_status(self) -> None:
        """加载执行状态"""
        if self.status_path.exists():
            try:
                status_data = json.loads(self.status_path.read_text(encoding="utf-8"))
                self.execution_status = ExecutionStatus.from_dict(status_data)
            except (json.JSONDecodeError, Exception) as e:
                print(f"Warning: Failed to load execution status: {e}. Using default status.")
                self.execution_status = ExecutionStatus()
        else:
            # 初始化状态
            self.execution_status = ExecutionStatus()
    
    def save_status(self) -> None:
        """保存执行状态到文件"""
        self.status_path.write_text(
            json.dumps(self.execution_status.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def _parse_module(self, data: Dict[str, Any]) -> Module:
        features = [
            Feature(
                feature_id=f.get("feature_id", ""),
                name=f.get("feature_name", ""),
                description=f.get("description", ""),
                methods=f.get("methods", []),
                reqs=f.get("reqs", []),
                dependencies=f.get("dependencies", [])
            )
            for f in data.get("features", [])
        ]

        return Module(
            module_id=data.get("module_id", ""),
            name=data.get("module_name", data.get("name", "")),  # 兼容旧字段 name
            classes=data.get("classes", []),
            description=data.get("description", data.get("responsibility_summary", "")),  # 兼容旧字段
            features=features
        )

    # ---------- 对外接口 ----------

    @property
    def modules(self) -> List[Module]:
        return self._modules

    def get_module_by_id(self, module_id: str) -> Module | None:
        return next((m for m in self._modules if m.module_id == module_id), None)

    def iter_modules(self) -> Iterator[Module]:
        return iter(self._modules)

    def iter_all_features(self) -> Iterator[Feature]:
        for module in self._modules:
            for feature in module.features:
                yield feature

    def iter_all_methods(self) -> Iterator[Dict[str, str]]:
        """遍历所有模块的所有方法（返回方法对象，包含 signature 和 description）"""
        for module in self._modules:
            yield from module.iter_methods()
    
    # ---------- 状态管理接口 ----------
    
    def mark_stage_completed(self, module_id: str, stage: int) -> None:
        """标记某个模块的某个阶段已完成并保存"""
        self.execution_status.mark_stage_completed(module_id, stage)
        self.save_status()
    
    def get_next_pending_module(self) -> Optional[tuple[int, Module, int]]:
        """
        获取下一个待执行的模块及其待执行阶段
        返回: (module_index, module, next_stage) 或 None（全部完成）
        """
        for idx, module in enumerate(self._modules):
            next_stage = self.execution_status.get_next_stage(module.module_id)
            if next_stage is not None:
                return (idx, module, next_stage)
        return None
    
    def is_all_completed(self) -> bool:
        """检查所有模块是否都已完成"""
        return self.get_next_pending_module() is None
    
    def reset_status(self) -> None:
        """重置执行状态（重新开始）"""
        self.execution_status = ExecutionStatus()
        self.save_status()
    
    def get_progress_summary(self) -> Dict[str, Any]:
        """获取执行进度摘要"""
        total_modules = len(self._modules)
        completed_modules = sum(
            1 for m in self._modules 
            if self.execution_status.is_module_completed(m.module_id)
        )
        
        return {
            "total_modules": total_modules,
            "completed_modules": completed_modules,
            "progress_percentage": (completed_modules / total_modules * 100) if total_modules > 0 else 0,
            "module_statuses": [
                {
                    "module_id": m.module_id,
                    "module_name": m.name,
                    "completed_stage": self.execution_status.get_module_stage(m.module_id),
                    "is_completed": self.execution_status.is_module_completed(m.module_id)
                }
                for m in self._modules
            ]
        }


if __name__ == '__main__':
    memory = Memory('/home/mgh/dev/projects/python_projects/mate/memory/working_memory/test_plan.json')
    modules = memory.modules
    for module in modules:
        print(module.__str__())

