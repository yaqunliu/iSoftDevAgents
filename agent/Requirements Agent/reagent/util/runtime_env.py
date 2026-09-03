from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


RUNTIME_OBSERVABILITY_DEFAULTS = {
    "CREWAI_TRACING_ENABLED": "false",
    "OTEL_SDK_DISABLED": "true",
    "CREWAI_DISABLE_TELEMETRY": "true",
    "CREWAI_DISABLE_TRACKING": "true",
}


def _set_default_env(name: str, value: str) -> None:
    if not os.getenv(name):
        os.environ[name] = value


def apply_runtime_observability_defaults(*, force: bool = False) -> dict[str, str]:
    """
    统一关闭 CrewAI tracing 与 OpenTelemetry 遥测。

    接口注释：
    这个函数只处理“观测与追踪”这一类环境变量，目的是避免
    Requirements Agent 在平台测试和本地联调时，额外向外部遥测地址发请求，
    从而制造 401、网络重试、DNS 失败这类噪音日志。
    """

    applied: dict[str, str] = {}
    for name, value in RUNTIME_OBSERVABILITY_DEFAULTS.items():
        # 设计注释：
        # force=False 用在普通初始化阶段，只补默认值，保留开发者显式配置。
        # force=True 用在平台桥梁真正启动 Agent 前，哪怕外部环境开过 tracing，
        # 这里也要强制压成关闭，确保本轮运行绝不再打 telemetry.crewai.com。
        if force or not os.getenv(name):
            os.environ[name] = value
        applied[name] = os.environ[name]
    return applied


def _normalize_model_name(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized.startswith("openai/"):
        return normalized
    return f"openai/{normalized}"


def _repo_root(project_root: Path) -> Path:
    return project_root.resolve().parents[2]


def _load_env_with_precedence(path: Path, *, original_env_keys: set[str], allow_override_loaded: bool) -> None:
    if not path.exists():
        return
    values = dotenv_values(path)
    for key, value in values.items():
        if value is None or key in original_env_keys:
            continue
        if allow_override_loaded or key not in os.environ:
            os.environ[key] = value


def load_runtime_env(project_root: str | Path) -> dict[str, str]:
    project_path = Path(project_root).resolve()
    repo_root = _repo_root(project_path)
    runtime_home = project_path / ".runtime-home"
    runtime_home.mkdir(parents=True, exist_ok=True)
    (runtime_home / "crewai-storage").mkdir(parents=True, exist_ok=True)
    original_env_keys = set(os.environ)

    _set_default_env("HOME", str(runtime_home))
    _set_default_env("CREWAI_STORAGE_DIR", str(runtime_home / "crewai-storage"))

    repo_env = repo_root / ".env"
    if repo_env.exists():
        load_dotenv(repo_env, override=False)
    _load_env_with_precedence(repo_root / ".env.local", original_env_keys=original_env_keys, allow_override_loaded=True)
    _load_env_with_precedence(project_path / ".env", original_env_keys=original_env_keys, allow_override_loaded=False)

    api_key = os.getenv("ISOFTDEVAGENTS_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("ISOFTDEVAGENTS_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model = _normalize_model_name(os.getenv("ISOFTDEVAGENTS_LLM_MODEL") or os.getenv("OPENAI_MODEL"))

    if api_key:
        os.environ["ISOFTDEVAGENTS_LLM_API_KEY"] = api_key
        os.environ["OPENAI_API_KEY"] = api_key
    if base_url:
        os.environ["ISOFTDEVAGENTS_LLM_BASE_URL"] = base_url
        os.environ["OPENAI_BASE_URL"] = base_url
    if model:
        os.environ["ISOFTDEVAGENTS_LLM_MODEL"] = model
        os.environ["OPENAI_MODEL"] = model

    # 教学注释：
    # 这里放在 dotenv 读取之后，是为了实现“默认关闭，但允许开发者手工开启”的策略。
    # 如果项目环境里没有显式声明，就补成关闭；如果开发者真的想本地打开 tracing，
    # 仍然可以在外部环境或 .env 里自己设置。
    observability_env = apply_runtime_observability_defaults(force=False)

    return {
        key: value
        for key, value in {
            "HOME": os.environ.get("HOME"),
            "CREWAI_STORAGE_DIR": os.environ.get("CREWAI_STORAGE_DIR"),
            "ISOFTDEVAGENTS_LLM_API_KEY": os.environ.get("ISOFTDEVAGENTS_LLM_API_KEY"),
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
            "ISOFTDEVAGENTS_LLM_BASE_URL": os.environ.get("ISOFTDEVAGENTS_LLM_BASE_URL"),
            "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL"),
            "ISOFTDEVAGENTS_LLM_MODEL": os.environ.get("ISOFTDEVAGENTS_LLM_MODEL"),
            "OPENAI_MODEL": os.environ.get("OPENAI_MODEL"),
            **observability_env,
        }.items()
        if value is not None
    }
