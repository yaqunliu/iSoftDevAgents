from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _response_usage_payload(response: Any, *, fallback_model: str) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
    if total_tokens <= 0 and (input_tokens > 0 or output_tokens > 0):
        total_tokens = input_tokens + output_tokens
    if total_tokens <= 0:
        return None
    return {
        "model": fallback_model,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
    }


def _merge_usage_payloads(*payloads: dict[str, Any] | None, fallback_model: str) -> dict[str, Any] | None:
    resolved = [payload for payload in payloads if payload]
    if not resolved:
        return None
    return {
        "model": str(resolved[-1].get("model") or fallback_model),
        "inputTokens": sum(int(payload.get("inputTokens") or 0) for payload in resolved),
        "outputTokens": sum(int(payload.get("outputTokens") or 0) for payload in resolved),
        "totalTokens": sum(int(payload.get("totalTokens") or 0) for payload in resolved),
    }


def run_ui_agent(
    *,
    project_name: str,
    use_case_path: str | Path,
    dialog_map_path: str | Path,
    api_methods_path: str | Path,
    output_dir: str | Path,
    usage_callback: Any = None,
) -> dict[str, Any]:
    """
    UI Agent 的真实函数入口。

    这里不走 shell 脚本，也不走三个脚本各自的 main。
    我们直接按真实顺序复用它们的内部函数，保证后端可以直接函数调用。
    """

    import dar_model
    import page_description
    import ui_design

    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    use_case_file = Path(use_case_path)
    dialog_map_file = Path(dialog_map_path)
    api_methods_file = Path(api_methods_path)
    api_methods = json.loads(api_methods_file.read_text(encoding="utf-8"))
    dialog_map_text = dialog_map_file.read_text(encoding="utf-8")
    use_case_text = use_case_file.read_text(encoding="utf-8")

    model_name = os.getenv("OPENAI_MODEL") or os.getenv("ISOFTDEVAGENTS_LLM_MODEL") or "gpt-5.1"

    print("Generating page_descriptions.json")
    page_response = page_description._client().chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": "You generate concise structured page descriptions for software projects.",
            },
            {
                "role": "user",
                "content": page_description.build_prompt(project_name, api_methods, dialog_map_text, use_case_text),
            },
        ],
        temperature=0.1,
    )
    if usage_callback is not None:
        page_usage = _response_usage_payload(page_response, fallback_model=model_name)
        if page_usage is not None:
            usage_callback({"stage": "page_descriptions", **page_usage})
    page_payload = page_description._extract_json(page_response.choices[0].message.content or "")
    page_description.ensure_single_page_contract(page_payload)
    page_json_path = output_root / "page_descriptions.json"
    page_md_path = output_root / "page_descriptions.md"
    page_json_path.write_text(json.dumps(page_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    page_md_path.write_text(page_description.render_markdown(page_payload), encoding="utf-8")

    print("Generating dar_model.json")
    dar_response = dar_model._client().chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": "You generate compact DAR models for web applications.",
            },
            {
                "role": "user",
                "content": dar_model.build_prompt(project_name, page_payload, use_case_text),
            },
        ],
        temperature=0.1,
    )
    if usage_callback is not None:
        dar_usage = _response_usage_payload(dar_response, fallback_model=model_name)
        if dar_usage is not None:
            usage_callback({"stage": "dar_model", **dar_usage})
    dar_payload = dar_model._extract_json(dar_response.choices[0].message.content or "")
    dar_json_path = output_root / "dar_model.json"
    dar_md_path = output_root / "dar_model.md"
    dar_json_path.write_text(json.dumps(dar_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    dar_md_path.write_text(dar_model.render_markdown(dar_payload), encoding="utf-8")

    print("Generating app/index.html")
    page = page_payload["pages"][0]
    ui_response = ui_design._client().chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": "You are a senior front-end engineer who produces concise runnable single-page apps.",
            },
            {
                "role": "user",
                "content": ui_design.build_prompt(project_name, page, api_methods, use_case_text, dialog_map_text),
            },
        ],
        temperature=0.1,
    )
    if usage_callback is not None:
        ui_usage = _response_usage_payload(ui_response, fallback_model=model_name)
        if ui_usage is not None:
            usage_callback({"stage": "ui_design", **ui_usage})
    raw_content = ui_response.choices[0].message.content or ""
    html = ui_design.extract_block(raw_content, ["html"])
    css = ui_design.extract_block(raw_content, ["css"])
    js = ui_design.extract_block(raw_content, ["javascript", "js"])
    if not html or not css or not js:
        raise RuntimeError("UI Agent did not return all required code blocks.")
    ui_design.write_ui_files(output_root / "app", html, css, js, ui_design.build_api_service(api_methods))

    usage = _merge_usage_payloads(
        _response_usage_payload(page_response, fallback_model=model_name),
        _response_usage_payload(dar_response, fallback_model=model_name),
        _response_usage_payload(ui_response, fallback_model=model_name),
        fallback_model=model_name,
    )
    return {
        "output_dir": str(output_root),
        "usage": usage,
    }
