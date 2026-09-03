import re
import ast
import re
from pathlib import Path
from typing import Type, List, Dict, Any, Literal

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class CodeSearchInput(BaseModel):
    """输入 schema：要检索的符号名/类型、根目录、以及一些检索参数。"""
    root_dir: str = Field(..., description="搜索根目录（相对或绝对）")
    query: str = Field(..., description="要搜索的类名/函数名（支持精确或正则）")
    kind: Literal["function", "class", "any"] = Field(
        "any",
        description="搜索类型：function=函数，class=类，any=两者都搜"
    )
    use_regex: bool = Field(False, description="是否将 query 视为正则表达式")
    case_sensitive: bool = Field(True, description="是否大小写敏感（仅在 use_regex=False 时有效）")
    include_private: bool = Field(True, description="是否包含以下划线开头的符号")
    file_glob: str = Field("**/*.py", description="要扫描的文件模式，默认递归扫描所有 .py")
    max_results: int = Field(10, description="最多返回多少条匹配结果")
    max_file_size_kb: int = Field(1024, description="单文件最大大小（KB），超出则跳过以加速")
    snippet_context_lines: int = Field(0, description="额外返回前后上下文行数（0 表示只返回定义块）")


class CodeSearchTool(BaseTool):
    """
    代码搜索工具：
    - 在指定目录递归扫描 .py 文件
    - 使用 AST 精确定位 class / function 定义
    - 返回：源码片段、所在文件、起止行、模块名（包名）
    """
    name: str = "code_search"
    description: str = (
        "Search for a Python class/function definition by name (or regex) under a directory. "
        "Returns source code and module/package path."
    )
    args_schema: Type[BaseModel] = CodeSearchInput

    def _run(
            self,
            root_dir: str,
            query: str,
            kind: str = "any",
            use_regex: bool = False,
            case_sensitive: bool = True,
            include_private: bool = True,
            file_glob: str = "**/*.py",
            max_results: int = 10,
            max_file_size_kb: int = 1024,
            snippet_context_lines: int = 0,
    ) -> str:
        root = Path(root_dir).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"root_dir 不存在或不是目录: {root}")

        # 准备匹配器
        if use_regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            pattern = re.compile(query, flags=flags)

            def _match(name: str) -> bool:
                return bool(pattern.search(name))
        else:
            q = query if case_sensitive else query.lower()

            def _match(name: str) -> bool:
                n = name if case_sensitive else name.lower()
                return n == q

        # 收集结果
        results: List[Dict[str, Any]] = []

        # 遍历文件
        for py_file in root.glob(file_glob):
            if not py_file.is_file():
                continue

            # 大文件跳过（加速）
            try:
                size_kb = py_file.stat().st_size / 1024.0
                if size_kb > max_file_size_kb:
                    continue
            except OSError:
                continue

            # 读取源码
            try:
                text = py_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                # 尝试宽松编码（可按需扩展）
                try:
                    text = py_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
            except Exception:
                continue

            # 解析 AST
            try:
                tree = ast.parse(text, filename=str(py_file))
            except SyntaxError:
                continue

            # 为 end_lineno 做兼容（py>=3.8 通常都有；缺失则后面降级）
            lines = text.splitlines(keepends=True)

            # 遍历定义
            for node in ast.walk(tree):
                if len(results) >= max_results:
                    break

                # 过滤类型
                is_func = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                is_cls = isinstance(node, ast.ClassDef)

                if kind == "function" and not is_func:
                    continue
                if kind == "class" and not is_cls:
                    continue
                if kind == "any" and not (is_func or is_cls):
                    continue

                name = getattr(node, "name", None)
                if not name:
                    continue

                if not include_private and name.startswith("_"):
                    continue

                if not _match(name):
                    continue

                # 取行号范围（1-based）
                start = getattr(node, "lineno", None)
                end = getattr(node, "end_lineno", None)

                # end_lineno 可能缺失：降级为只取起始行到起始行+1（尽量不炸）
                if start is None:
                    continue
                if end is None:
                    end = start

                # 加上下文
                ctx = max(0, int(snippet_context_lines))
                start_idx = max(1, start - ctx)
                end_idx = min(len(lines), end + ctx)

                snippet = "".join(lines[start_idx - 1: end_idx])

                # 计算模块名（包名）
                module_name = self._infer_module_name(root, py_file)

                results.append(
                    {
                        "symbol": name,
                        "kind": "class" if is_cls else "function",
                        "module": module_name,  # e.g. hone.utils.csv_utils
                        "file": str(py_file),  # 绝对路径
                        "rel_file": str(py_file.relative_to(root)),
                        "start_line": start,
                        "end_line": end,
                        "snippet": snippet,
                    }
                )

        # 输出结果（JSON 字符串，便于下游 Agent 解析）
        import json
        payload = {
            "query": query,
            "kind": kind,
            "root_dir": str(root),
            "count": len(results),
            "results": results,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _infer_module_name(root: Path, file_path: Path) -> str:
        """
        尝试从文件路径推断模块名（包名）：
        - 相对于 root 的相对路径
        - 去掉 .py
        - 将路径分隔符替换成 '.'
        - 如果是 __init__.py，则模块名是目录名（例如 hone/utils/__init__.py -> hone.utils）
        """
        rel = file_path.resolve().relative_to(root.resolve())
        parts = list(rel.parts)

        if parts[-1] == "__init__.py":
            parts = parts[:-1]  # 包本身
        else:
            parts[-1] = parts[-1].removesuffix(".py")

        # 过滤掉空 parts
        parts = [p for p in parts if p]
        return ".".join(parts)


from pydantic import BaseModel, Field


class SearchJavaDefinitionInput(BaseModel):
    root_dir: str = Field(..., description="Java 项目根目录")
    query: str = Field(..., description="类名或方法名")
    search_type: str = Field(..., description="class | method")
    ignore_case: bool = Field(True, description="是否忽略大小写")
    max_results: int = Field(5, description="最大返回结果数")


import os
import re
import json
from typing import Type, Optional
from pydantic import BaseModel
from crewai.tools import BaseTool


class SearchJavaCodeTool(BaseTool):
    name: str = "search_java_definition"
    description: str = (
        "Search Java class or method definitions and return full definitions "
        "in structured JSON format."
    )
    args_schema: Type[BaseModel] = SearchJavaDefinitionInput

    def _run(
        self,
        root_dir: str,
        query: str,
        search_type: str,
        ignore_case: bool = True,
        max_results: int = 5,
    ) -> str:

        response = {
            "success": False,
            "search_type": search_type,
            "target_name": query,
            "results": [],
            "error": None,
        }

        if not os.path.isdir(root_dir):
            response["error"] = f"Directory not found: {root_dir}"
            return json.dumps(response, ensure_ascii=False)

        flags = re.IGNORECASE if ignore_case else 0

        if search_type == "class":
            pattern = rf"\b(class|interface|enum)\s+{re.escape(query)}\b"
        elif search_type == "method":
            pattern = rf"""
                ^\s*
                (public|protected|private|\s)*
                [\w\<\>\[\]]+\s+
                {re.escape(query)}
                \s*\([^;]*\)
                \s*\{{ 
            """
        else:
            response["error"] = "search_type must be 'class' or 'method'"
            return json.dumps(response, ensure_ascii=False)

        regex = re.compile(pattern, flags | re.MULTILINE | re.VERBOSE)

        for root, _, files in os.walk(root_dir):
            for file in files:
                if not file.endswith(".java"):
                    continue

                path = os.path.join(root, file)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except Exception:
                    continue

                for match in regex.finditer(content):
                    block = self._extract_block(content, match.start())
                    if not block:
                        continue

                    info = {
                        "file": path,
                        "code": block,
                    }

                    if search_type == "class":
                        info["class_name"] = query
                    else:
                        info["method_name"] = query
                        info["class_name"] = self._infer_class_name(content, match.start())
                        info["signature"] = block.split("{", 1)[0].strip()

                    response["results"].append(info)

                    if len(response["results"]) >= max_results:
                        response["success"] = True
                        return json.dumps(response, ensure_ascii=False)

        response["success"] = len(response["results"]) > 0
        return json.dumps(response, ensure_ascii=False)

    def _extract_block(self, content: str, start_index: int) -> Optional[str]:
        brace_count = 0
        in_block = False
        buf = []

        for ch in content[start_index:]:
            buf.append(ch)
            if ch == "{":
                brace_count += 1
                in_block = True
            elif ch == "}":
                brace_count -= 1

            if in_block and brace_count == 0:
                return "".join(buf).strip()

        return None

    def _infer_class_name(self, content: str, pos: int) -> Optional[str]:
        """
        从方法位置向前推断所属类名（简单但实用）
        """
        prefix = content[:pos]
        matches = re.findall(r"\bclass\s+(\w+)", prefix)
        return matches[-1] if matches else None



if __name__ == "__main__":
    tool = SearchJavaCodeTool()

    print(tool._run(
        root_dir="/home/mgh/dev/data/dataset/login/backend/",
        query="UserRepository",
        search_type="class"
    ))


