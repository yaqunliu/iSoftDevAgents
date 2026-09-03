from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
from typing import Any

from litellm import completion

from app.config import load_local_env_files

load_local_env_files()


def _image_summary_base_url() -> str:
    return (os.getenv("ISOFTDEVAGENTS_IMAGE_LLM_BASE_URL") or "").rstrip("/")


def _image_summary_api_key() -> str:
    return os.getenv("ISOFTDEVAGENTS_IMAGE_LLM_API_KEY") or ""


def _image_summary_model() -> str:
    return os.getenv("ISOFTDEVAGENTS_IMAGE_LLM_MODEL") or ""


def _detect_image_mime_type(file_name: str) -> str:
    guessed, _ = mimetypes.guess_type(file_name)
    if guessed and guessed.startswith("image/"):
        return guessed
    return "image/png"


def _image_summary_prompt(file_name: str) -> str:
    return (
        f"请阅读这张需求参考图片 `{file_name}`，并输出一份面向软件需求分析的结构化中文摘要。\n"
        "必须严格包含下面 5 个标题，并按这个顺序输出：\n"
        "1. 主题\n"
        "2. 可见文字\n"
        "3. 关键界面元素或页面区域\n"
        "4. 可推断的业务流程/角色/状态\n"
        "5. 对需求分析有帮助的要点\n\n"
        "要求：\n"
        "- 不要编造图片里看不见的细节。\n"
        "- 如果某一项看不清，请明确写“未识别清楚”。\n"
        "- 保持简洁，但每一项都至少给出一句完整内容。\n"
        "- 不要输出额外前言。\n"
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
            if isinstance(item.get("text"), str):
                text_chunks.append(str(item["text"]))
                continue
            if item.get("type") in {"text", "output_text"} and isinstance(item.get("text"), str):
                text_chunks.append(str(item["text"]))
        return "\n".join(chunk.strip() for chunk in text_chunks if chunk and chunk.strip()).strip()

    return ""


async def summarize_image_reference(*, file_name: str, content: bytes) -> str:
    # 接口注释：
    # 这个服务只负责“把单张图片转成需求分析摘要文本”，不关心上传记录、任务流程和缓存策略。
    # 这样 workflow 层就能单独决定什么时候调用、失败后如何降级、以及结果要不要复用。
    model = _image_summary_model().strip()
    api_key = _image_summary_api_key().strip()
    if not model:
        raise RuntimeError("Image summary model is not configured.")
    if not api_key:
        raise RuntimeError("Image summary API key is not configured.")

    mime_type = _detect_image_mime_type(file_name)
    encoded_content = base64.b64encode(content).decode("ascii")
    image_url = f"data:{mime_type};base64,{encoded_content}"

    def _run_completion() -> str:
        completion_kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _image_summary_prompt(file_name)},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            "temperature": 0,
        }
        base_url = _image_summary_base_url()
        if base_url:
            completion_kwargs["base_url"] = base_url
        response = completion(**completion_kwargs)
        text = _extract_completion_text(response)
        if not text:
            raise RuntimeError("Image summary model returned an empty response.")
        if text.startswith("[Image Summary]"):
            return text.strip()
        return f"[Image Summary]\n{text.strip()}"

    return await asyncio.to_thread(_run_completion)
