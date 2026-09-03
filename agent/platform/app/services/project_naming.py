from __future__ import annotations

import os
import re
from typing import Any

from litellm import completion

from app.config import load_local_env_files

load_local_env_files()

_DEFAULT_PROJECT_NAME = "New Project"
_MAX_PROJECT_NAME_LENGTH = 48


def _project_name_base_url() -> str:
    return (
        os.getenv("ISOFTDEVAGENTS_PROJECT_NAME_LLM_BASE_URL")
        or os.getenv("ISOFTDEVAGENTS_LLM_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or ""
    ).rstrip("/")


def _project_name_api_key() -> str:
    return (
        os.getenv("ISOFTDEVAGENTS_PROJECT_NAME_LLM_API_KEY")
        or os.getenv("ISOFTDEVAGENTS_LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )


def _project_name_model() -> str:
    return (
        os.getenv("ISOFTDEVAGENTS_PROJECT_NAME_LLM_MODEL")
        or os.getenv("ISOFTDEVAGENTS_LLM_MODEL")
        or os.getenv("OPENAI_MODEL")
        or ""
    )


def _extract_completion_text(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if choices is None and isinstance(response, dict):
        choices = response.get("choices")
    if not choices:
        return ""

    first_choice = choices[0]
    message = getattr(first_choice, "message", None)
    if message is None and isinstance(first_choice, dict):
        message = first_choice.get("message")

    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        text_chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                text_chunks.append(item)
                continue
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                text_chunks.append(text.strip())
        return "\n".join(text_chunks).strip()

    return ""


def _normalize_project_name(raw_name: str) -> str:
    cleaned = raw_name.strip()
    cleaned = re.sub(r"^[#>*`\-\d\.\)\( \t]+", "", cleaned)
    cleaned = cleaned.replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" '\"`“”‘’：:;；，,。.!！?？")
    if not cleaned:
        return ""
    return cleaned[:_MAX_PROJECT_NAME_LENGTH].strip()


def _fallback_project_name(description_text: str) -> str:
    # 教学注释：
    # AI 不可用时，我们退回到一个非常稳定的本地规则：
    # 取第一行有内容的描述，做一次清洗，再限制长度。
    # 这样创建项目不会因为模型配置缺失而卡住。
    for raw_line in description_text.splitlines():
        candidate = _normalize_project_name(raw_line)
        if candidate:
            return candidate
    return _DEFAULT_PROJECT_NAME


def generate_project_name(description_text: str) -> str:
    """
    接口注释：
    根据项目描述生成一个适合展示的项目名；如果模型不可用，就回退到本地规则。

    设计注释：
    这里故意做成“尽力而为”的能力，而不是创建项目的硬依赖。
    因为项目创建属于高频主流程，不能被模型配置、网络状态或额度问题卡住。
    """

    normalized_description = description_text.strip()
    if not normalized_description:
        return _DEFAULT_PROJECT_NAME

    model = _project_name_model().strip()
    api_key = _project_name_api_key().strip()
    if not model or not api_key:
        return _fallback_project_name(normalized_description)

    try:
        completion_kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一个软件项目命名助手。"
                        "请根据用户的项目描述，只输出一个简短项目名。"
                        "要求：不要加引号，不要加序号，不要解释，不要超过 12 个汉字或 6 个英文单词。"
                    ),
                },
                {
                    "role": "user",
                    "content": normalized_description,
                },
            ],
            "temperature": 0.2,
        }
        base_url = _project_name_base_url()
        if base_url:
            completion_kwargs["base_url"] = base_url
        response = completion(**completion_kwargs)
        candidate = _normalize_project_name(_extract_completion_text(response))
        if candidate:
            return candidate
    except Exception:
        pass

    return _fallback_project_name(normalized_description)
