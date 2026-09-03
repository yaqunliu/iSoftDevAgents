import datetime
import os
from pathlib import Path
from typing import Optional, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


ALLOWED_WRITE_ROOTS_ENV = "ISOFTDEVAGENTS_TEST_AGENT_ALLOWED_WRITE_ROOTS"


class WriteFileInput(BaseModel):
    """输入 schema: 要写入的文件路径和内容。"""
    path: str = Field(..., description="目标文件绝对路径")
    code: str = Field(..., description="要写入的代码内容")
    overwrite: Optional[bool] = Field(False, description="是否覆盖已有文件 (True = 覆盖, False = 追加)")


class WriteCodeFileTool(BaseTool):
    name: str = "write_code_file"
    description: str = "Write given code to the specified file path."
    args_schema: Type[BaseModel] = WriteFileInput

    # 接口注释：
    # 这个工具只允许把测试阶段产物写入运行时临时目录。
    # 这样平台才能在阶段结束后统一把文件同步进数据库，并保持版本记录一致。
    def _load_allowed_roots(self) -> list[Path]:
        raw_roots = str(os.environ.get(ALLOWED_WRITE_ROOTS_ENV) or "").strip()
        if not raw_roots:
            return []

        allowed_roots: list[Path] = []
        for item in raw_roots.split(os.pathsep):
            candidate = item.strip()
            if not candidate:
                continue
            allowed_roots.append(Path(candidate).expanduser().resolve(strict=False))
        return allowed_roots

    # 设计注释：
    # 必须用“目标路径是否位于白名单根目录内”来判断是否放行，
    # 不能只做字符串前缀比较，否则很容易被类似 /tmp/a 和 /tmp/ab 这种路径绕过。
    def _is_path_inside_allowed_roots(self, target_path: Path, allowed_roots: list[Path]) -> bool:
        return any(target_path == root or root in target_path.parents for root in allowed_roots)

    def _format_allowed_roots(self, allowed_roots: list[Path]) -> str:
        if not allowed_roots:
            return "(none)"
        return ", ".join(str(item) for item in allowed_roots)

    # 原因注释：
    # 这里统一打印明确告警，避免以后再把“工具写盘成功”误判成“数据库和版本也已经记账”。
    def _emit_rejection_log(self, *, abs_path: Path, allowed_roots: list[Path], reason: str) -> str:
        allowed_roots_text = self._format_allowed_roots(allowed_roots)
        message = (
            f"{reason} Path: {abs_path}. Allowed roots: {allowed_roots_text}. "
            "This write was blocked, so it was not stored in the database and no version record was created."
        )
        print("[WARN] Test Agent 文件写入被拒绝")
        print(f"[WARN] 被拒绝的绝对路径: {abs_path}")
        print(f"[WARN] 当前允许的根目录: {allowed_roots_text}")
        print("[WARN] 这次写入没有进入数据库，也没有版本记录。")
        print(f"[WARN] 拒绝原因: {reason}")
        return message

    def _memory_root_from_allowed_roots(self, allowed_roots: list[Path]) -> Path | None:
        for root in allowed_roots:
            if root.name == "memory":
                return root
        return None

    def _append_runtime_log(
        self,
        *,
        abs_path: Path,
        overwrite: bool,
        code_length: int,
        allowed_roots: list[Path],
    ) -> None:
        memory_root = self._memory_root_from_allowed_roots(allowed_roots)
        if memory_root is None:
            return

        try:
            log_dir = memory_root / "working_memory"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "write_code_file.log"
            log_entry = (
                f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"File: {abs_path} | Overwrite: {overwrite} | Size: {code_length}\n"
            )
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(log_entry)
        except Exception as error:
            print(f"[DEBUG] 写运行时日志失败 (但不影响主流程): {error}")

    def _record_generated_file(self, *, path: str, allowed_roots: list[Path]) -> None:
        file_name = os.path.basename(path)
        if not (file_name.endswith(".java") or file_name.endswith(".py")):
            return

        memory_root = self._memory_root_from_allowed_roots(allowed_roots)
        if memory_root is None:
            return

        try:
            memory_dir = memory_root / "working_memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            memory_file = memory_dir / "generatedTest.txt"
            with memory_file.open("a", encoding="utf-8") as mem_file:
                mem_file.write(file_name + "\n")
        except Exception as error:
            print(f"[DEBUG] 写生成文件索引失败 (但不影响主流程): {error}")

    def _run(self, path: str, code: str, overwrite: bool = False) -> str:
        allowed_roots = self._load_allowed_roots()

        # --- DEBUG 信息 ---
        abs_path = Path(path).expanduser().resolve(strict=False)
        print(f"--------------------------------------------------")
        print(f"[DEBUG] 工具被触发")
        print(f"[DEBUG] 目标路径 (相对): {path}")
        print(f"[DEBUG] 目标路径 (绝对): {abs_path}")
        print(f"[DEBUG] 写入模式: {'覆写 (w)' if overwrite else '追加 (a)'}")
        print(f"[DEBUG] 代码长度: {len(code)} 字符")
        print(f"[DEBUG] 允许写入根目录: {self._format_allowed_roots(allowed_roots)}")
        if len(code) < 10:
            print(f"[DEBUG] 警告: 代码内容似乎为空或过短: '{code}'")
        # ------------------

        if overwrite and not str(code).strip():
            return self._emit_rejection_log(
                abs_path=abs_path,
                allowed_roots=allowed_roots,
                reason="Refused to overwrite with empty content.",
            )

        if not allowed_roots:
            return self._emit_rejection_log(
                abs_path=abs_path,
                allowed_roots=allowed_roots,
                reason=f"Refused to write because {ALLOWED_WRITE_ROOTS_ENV} is not configured.",
            )

        if not self._is_path_inside_allowed_roots(abs_path, allowed_roots):
            return self._emit_rejection_log(
                abs_path=abs_path,
                allowed_roots=allowed_roots,
                reason="Refused to write because the target path is outside the allowed runtime roots.",
            )

        # 1. 确保目标文件目录存在
        dir_name = abs_path.parent
        if str(dir_name) and not dir_name.exists():
            try:
                dir_name.mkdir(parents=True, exist_ok=True)
                print(f"[DEBUG] 创建目录成功: {dir_name}")
            except Exception as error:
                return f"Error creating directory {dir_name}: {error}"

        # 2. 写入文件
        try:
            mode = "w" if overwrite else "a"
            with abs_path.open(mode, encoding="utf-8") as f:
                f.write(code)
                if code and not code.endswith("\n"):
                    f.write("\n")
                # 强制刷新缓冲区，确保写入磁盘
                f.flush()
                os.fsync(f.fileno())
            print(f"[DEBUG] 文件写入操作完成。")
        except Exception as error:
            print(f"[DEBUG] 写入文件失败: {error}")
            return f"Error writing to file: {error}"

        # 教学注释：
        # 下面两个辅助记录文件不属于真实业务产物，但也必须跟着运行时目录走，
        # 否则测试阶段虽然主文件被限制住了，辅助日志还是会污染真实工程目录。
        self._append_runtime_log(
            abs_path=abs_path,
            overwrite=overwrite,
            code_length=len(code),
            allowed_roots=allowed_roots,
        )
        self._record_generated_file(path=str(abs_path), allowed_roots=allowed_roots)

        return f"Successfully wrote code to {abs_path}"

