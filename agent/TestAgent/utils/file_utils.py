from openai import OpenAI
from pathlib import Path
from typing import Union, Iterable, Optional, List


def read_file(path: Union[str, Path], encoding: str = "utf-8") -> str:
    # 自动将字符串转为 Path，方便后续处理
    file_path = Path(path)

    # 判断文件是否存在
    if not file_path.is_file():
        raise FileNotFoundError(f"未找到文件: {file_path.resolve()}")

    # 读取并返回
    return file_path.read_text(encoding=encoding)


def write_file(
    path: Union[str, Path],
    content: str,
    *,
    encoding: str = "utf-8",
    overwrite: bool = True,
    create_parent: bool = True,
) -> None:
    """
    将内容写入指定文件

    :param path: 文件路径（str 或 Path）
    :param content: 要写入的内容
    :param encoding: 文件编码
    :param overwrite: 是否覆盖已有文件（True=覆盖，False=追加）
    :param create_parent: 是否自动创建父目录
    """
    file_path = Path(path)

    # 创建父目录
    if create_parent:
        file_path.parent.mkdir(parents=True, exist_ok=True)

    # 写入模式
    mode = "w" if overwrite else "a"

    file_path.write_text(content, encoding=encoding) if mode == "w" else \
        file_path.open(mode, encoding=encoding).__enter__().write(content)