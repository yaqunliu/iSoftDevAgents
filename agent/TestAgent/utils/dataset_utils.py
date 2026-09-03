from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from config.config import config


@dataclass(frozen=True)
class DatasetLoader:
    dataset_name: str
    dataset_root: Path
    sut_root: str
    srs: str
    uml_class: str
    uml_sequence: str
    architecture_design: str
    language: str
    conda_env: str


def load_dataset(
        dataset_name: str,
        *,
        encoding: str = "utf-8",
        strict: bool = True,
) -> DatasetLoader:
    """
    读取 <global_prefix>/<dataset_name>/config.json，并加载 PRD、UML_class 文件内容。

    参数:
      - dataset_name: 数据集目录名（例如 "dior", "rsod"）
      - global_prefix: 所有数据集所在的根目录（全局前缀）
      - encoding: 文件编码
      - strict: True 时，缺失 key / 文件不存在会抛异常；False 时会用空字符串兜底

    返回:
      DatasetDocs: 包含 prd/uml_class 的文本内容、实际路径、以及完整 config
    """
    global_prefix = Path(config['dataset']['root_path'])
    dataset_root = Path(global_prefix).expanduser().resolve() / dataset_name
    config_path = dataset_root / "config.json"

    if strict and not config_path.exists():
        raise FileNotFoundError(f"config.json not found: {config_path}")

    # 读取并解析 config.json
    try:
        config_obj: Dict[str, Any] = json.loads(config_path.read_text(encoding=encoding))
    except FileNotFoundError:
        if strict:
            raise
        config_obj = {}
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {config_path}: {e}") from e

    # 取 srs / UML_class 的相对路径
    srs_rel = config_obj.get("srs")
    uml_class_rel = config_obj.get("uml_class")
    uml_sequence_rel = config_obj.get("uml_sequence")
    architecture_design_rel = config_obj.get("architecture_design")
    sut_root=config_obj.get("sut_root")
    language = config_obj.get("language")
    conda_env = config_obj.get("conda_env")

    if strict:
        if not srs_rel:
            raise KeyError(f'Missing or empty key "PRD" in {config_path}')
        if not uml_class_rel:
            raise KeyError(f'Missing or empty key "UML_class" in {config_path}')
        if not uml_sequence_rel:
            raise KeyError(f'Missing or empty key "UML_sequence" in {config_path}')
        if not architecture_design_rel:
            raise KeyError(f'Missing or empty key "architecture_design" in {config_path}')

    srs_path = (dataset_root / srs_rel).resolve() if srs_rel else (dataset_root / "MISSING_PRD")
    uml_class_path = (dataset_root / uml_class_rel).resolve() if uml_class_rel else (dataset_root / "MISSING_UML_class")
    uml_sequence_path = (dataset_root / uml_sequence_rel).resolve() if uml_sequence_rel else (
            dataset_root / "MISSING_UML_class")
    architecture_design_path = (dataset_root / architecture_design_rel).resolve() if architecture_design_rel else (
            dataset_root / "MISSING_Architecture_Design")

    # 读取文件内容
    def _read_text(p: Path) -> str:
        if p.exists():
            return p.read_text(encoding=encoding)
        if strict:
            raise FileNotFoundError(f"File not found: {p}")
        return ""

    srs_text = _read_text(srs_path)
    uml_class_text = _read_text(uml_class_path)
    uml_sequence_text = _read_text(uml_sequence_path)
    architecture_design_text = _read_text(architecture_design_path)

    return DatasetLoader(
        dataset_name=dataset_name,
        dataset_root=dataset_root,
        srs=srs_text,
        uml_class=uml_class_text,
        uml_sequence=uml_sequence_text,
        architecture_design=architecture_design_text,
        sut_root=sut_root,
        language=language,
        conda_env=conda_env
    )


# ---- 使用示例 ----
if __name__ == "__main__":
    docs = load_dataset(
        "hone",
        strict=True,
    )

    print("PRD content preview:", docs.uml_class)
