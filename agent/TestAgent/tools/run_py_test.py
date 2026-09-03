import json
import os
import sys
import subprocess
import traceback
import datetime
from pathlib import Path
from typing import Type, Dict, Any, Optional, ClassVar

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

# 假设你的配置文件在这里，如果没有可以移除相关引用
try:
    from config.config import config

    CONDA_ENV_PATH = config.get('conda', {}).get('env_path')
except ImportError:
    CONDA_ENV_PATH = None


class RunProjectTestsInput(BaseModel):
    """
    精简后的测试运行参数。
    Agent 只需要决定“在哪跑”和“跑什么”。
    """
    project_root: str = Field(..., description="项目的根目录路径（作为当前工作目录 cwd 和 PYTHONPATH 基准）。")
    target_path: str = Field(..., description="要运行的测试文件或测试目录（相对 project_root路径）。")
    timeout_sec: int = Field(60, description="超时时间（秒），默认 60 秒。")


class RunProjectGeneratedTestsTool(BaseTool):
    name: str = "run_project_generated_tests"
    description: str = (
        "Run Python tests using pytest. "
        "Automatically sets up PYTHONPATH to include project root and 'src'. "
        "Returns pass/fail status and analyzed error logs."
    )
    args_schema: Type[BaseModel] = RunProjectTestsInput

    # 解释器路径逻辑
    TARGET_PYTHON_EXECUTABLE: str = sys.executable
    if CONDA_ENV_PATH and isinstance(CONDA_ENV_PATH, str) and os.path.isfile(CONDA_ENV_PATH):
        TARGET_PYTHON_EXECUTABLE = CONDA_ENV_PATH

    def _get_log_path(self) -> str:
        """获取日志文件的绝对路径，确保不因 cwd 变化而丢失日志"""
        # 获取当前工具文件所在的目录
        base_dir = os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(base_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        return os.path.join(log_dir, f"{self.name}.log")

    def _log_transaction(self, inputs: Dict[str, Any], result: Dict[str, Any]):
        """记录详细日志到文件"""
        try:
            log_file = self._get_log_path()
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            status = "SUCCESS" if result.get("ok") else "FAIL"

            log_entry = (
                f"[{timestamp}] STATUS: {status}\n"
                f"INPUTS: {json.dumps(inputs, ensure_ascii=False)}\n"
                f"SUMMARY: {result.get('summary')}\n"
                f"EXIT CODE: {result.get('exit_code')}\n"
                f"{'-' * 40}\n"
            )

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception as e:
            # 打印到控制台作为最后防线
            print(f"[RunProjectGeneratedTestsTool] Logging failed: {e}")

    def _prepare_env(self, project_root: str) -> Dict[str, str]:
        """构建鲁棒的环境变量，解决导入问题"""
        env = os.environ.copy()
        root_abs = os.path.abspath(project_root)

        # 策略：根目录 + src目录（如果存在） + 原有PYTHONPATH
        paths = [root_abs]
        src_path = os.path.join(root_abs, "src")
        if os.path.isdir(src_path):
            paths.append(src_path)

        # 保留原有的 PYTHONPATH
        if "PYTHONPATH" in env:
            paths.append(env["PYTHONPATH"])

        env["PYTHONPATH"] = os.pathsep.join(paths)
        return env

    def _run(self, project_root: str, target_path: str, timeout_sec: int = 60) -> str:
        inputs = {"project_root": project_root, "target_path": target_path}
        res = {
            "ok": False,
            "exit_code": None,
            "summary": "",
            "output_tail": "",
            "error_type": None
        }

        try:
            # 1. 路径解析与校验
            p_root = Path(project_root).resolve()

            # 处理 target_path：如果是绝对路径则直接用，如果是相对路径则拼接到 root 后
            t_path = Path(target_path)
            if not t_path.is_absolute():
                t_path = p_root / t_path

            t_path = t_path.resolve()

            # 校验存在性
            if not p_root.exists():
                res["summary"] = f"Project root does not exist: {p_root}"
                res["error_type"] = "PathError"
                self._log_transaction(inputs, res)
                return json.dumps(res, ensure_ascii=False)

            if not t_path.exists():
                res["summary"] = f"Target path does not exist: {t_path}"
                res["error_type"] = "PathError"
                self._log_transaction(inputs, res)
                return json.dumps(res, ensure_ascii=False)

            # 2. 构建 Pytest 命令
            # -q: 减少输出
            # --tb=short: 报错时只显示关键行，节省 Token
            # --showlocals: 报错时显示变量值，帮助 Agent 调试
            # --disable-warnings: 减少噪音
            cmd = [
                self.TARGET_PYTHON_EXECUTABLE, "-m", "pytest",
                str(t_path),
                "-q",
                "--tb=short",
                "--showlocals",
                "--disable-warnings"
            ]

            # 3. 执行测试
            env = self._prepare_env(str(p_root))

            # 关键：cwd 设置为项目根目录
            proc = subprocess.run(
                cmd,
                cwd=str(p_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_sec
            )

            res["exit_code"] = proc.returncode
            combined_output = (proc.stdout + "\n" + proc.stderr).strip()

            # 4. 结果分析
            if proc.returncode == 0:
                res["ok"] = True
                res["summary"] = "All tests passed successfully."
                # 成功时不需要返回太多日志
                res["output_tail"] = combined_output[-500:]
            else:
                res["ok"] = False
                # 失败时提取最后 2000 个字符（通常包含 Traceback）
                res["output_tail"] = combined_output[-2000:]

                # 简单的错误分类，帮助 Agent 快速定位
                lower_out = combined_output.lower()
                if "modulenotfounderror" in lower_out or "importerror" in lower_out:
                    res["summary"] = "Import Error detected. Check PYTHONPATH or installed packages."
                    res["error_type"] = "ImportError"
                elif "assertionerror" in lower_out:
                    res["summary"] = "Assertion failed. Logic error in code or test."
                    res["error_type"] = "AssertionError"
                elif "syntaxerror" in lower_out:
                    res["summary"] = "Syntax Error. Code cannot be parsed."
                    res["error_type"] = "SyntaxError"
                else:
                    res["summary"] = "Tests failed during execution."
                    res["error_type"] = "RuntimeError"

        except subprocess.TimeoutExpired:
            res["ok"] = False
            res["summary"] = f"Execution timed out after {timeout_sec} seconds."
            res["error_type"] = "Timeout"
        except Exception as e:
            res["ok"] = False
            res["summary"] = f"Tool internal error: {str(e)}"
            res["error_type"] = "ToolError"
            res["output_tail"] = traceback.format_exc()

        # 5. 记录日志并返回
        self._log_transaction(inputs, res)
        return json.dumps(res, ensure_ascii=False, indent=2)