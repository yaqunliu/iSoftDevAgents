from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from openai import OpenAI

from ui_runtime import ensure_single_page_contract


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate DAR model from page descriptions and use cases.")
    parser.add_argument("--project-name", default="generated-project")
    parser.add_argument("--page-description-file", type=Path, required=True)
    parser.add_argument("--use-case-file", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    return parser.parse_args()


def _client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("ISOFTDEVAGENTS_LLM_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("ISOFTDEVAGENTS_LLM_BASE_URL")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY or ISOFTDEVAGENTS_LLM_API_KEY is required for UI Agent.")
    return OpenAI(api_key=api_key, base_url=base_url)


def _extract_json(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def build_prompt(project_name: str, page_payload: dict, use_case_markdown: str) -> str:
    return f"""
You are generating a Display-Action-Response model for the main single-page UI prototype of a software project.

Project name: {project_name}

Output JSON only:
{{
  "dar_models": [
    {{
      "page_id": "string",
      "page_name": "string",
      "behaviors": [
        {{
          "precondition": "string",
          "user_action": "string",
          "system_response": "string"
        }}
      ]
    }}
  ]
}}

Generate behaviors only from the supplied page description and use cases.
Focus on the main user flows, validation feedback, and the most important system responses.

Page Description JSON:
{json.dumps(page_payload, indent=2, ensure_ascii=False)}

Use Case Markdown:
{use_case_markdown}
""".strip()


def render_markdown(payload: dict) -> str:
    lines = ["# DAR Model", ""]
    for page in payload.get("dar_models", []):
        lines.append(f"## {page['page_name']}")
        lines.append("")
        lines.append("| Precondition | User Action | System Response |")
        lines.append("| --- | --- | --- |")
        for behavior in page.get("behaviors", []):
            lines.append(
                f"| {behavior['precondition']} | {behavior['user_action']} | {behavior['system_response']} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    page_payload = json.loads(args.page_description_file.read_text(encoding="utf-8"))
    ensure_single_page_contract(page_payload)
    use_case_markdown = args.use_case_file.read_text(encoding="utf-8")

    response = _client().chat.completions.create(
        model=os.getenv("OPENAI_MODEL") or os.getenv("ISOFTDEVAGENTS_LLM_MODEL") or "gpt-5.1",
        messages=[
            {
                "role": "system",
                "content": "You generate compact DAR models for web applications.",
            },
            {
                "role": "user",
                "content": build_prompt(args.project_name, page_payload, use_case_markdown),
            },
        ],
        temperature=0.1,
    )
    payload = _extract_json(response.choices[0].message.content or "")
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path = args.output_file.with_suffix(".md")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    print(args.output_file.resolve())
    print(markdown_path.resolve())


if __name__ == "__main__":
    main()
