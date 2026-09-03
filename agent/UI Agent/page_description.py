from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from openai import OpenAI

from ui_runtime import ensure_single_page_contract


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate UI page descriptions from upstream artifacts.")
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--dialog-map-file", type=Path, required=True)
    parser.add_argument("--api-methods-file", type=Path, required=True)
    parser.add_argument("--use-case-file", type=Path, required=False)
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


def build_prompt(project_name: str, api_methods: dict, dialog_map: str, use_case_markdown: str) -> str:
    return f"""
You are a senior product designer preparing a single-page UI description for a browser-based project.

Project name: {project_name}

You must output VALID JSON ONLY with this shape:
{{
  "pages": [
    {{
      "page_id": "string",
      "page_name": "string",
      "purpose": "string",
      "navigation": {{
        "entry_points": ["string"],
        "exit_points": ["string"]
      }},
      "layout": {{
        "page_type": "string",
        "structure_notes": "string"
      }},
      "artifacts": ["string"]
    }}
  ]
}}

Hard constraints:
- Generate exactly one page.
- The page must be the main product workspace for this project.
- Keep navigation minimal and truthful for a single-page app.
- The artifacts must come from the real use cases and dialog map below.
- Do not invent unrelated pages, dashboards, login flows, or admin portals unless the provided inputs explicitly require them.

API Methods JSON:
{json.dumps(api_methods, indent=2, ensure_ascii=False)}

Use Cases:
{use_case_markdown}

Dialog Map:
{dialog_map}
""".strip()


def render_markdown(payload: dict) -> str:
    page = payload["pages"][0]
    lines = [
        "# Page Descriptions",
        "",
        f"## {page['page_name']}",
        "",
        f"- Page ID: `{page['page_id']}`",
        f"- Purpose: {page['purpose']}",
        f"- Entry Points: {', '.join(page['navigation']['entry_points']) or '(none)'}",
        f"- Exit Points: {', '.join(page['navigation']['exit_points']) or '(none)'}",
        f"- Layout: {page['layout']['page_type']}",
        f"- Structure Notes: {page['layout']['structure_notes']}",
        "",
        "### Artifacts",
    ]
    lines.extend(f"- {artifact}" for artifact in page["artifacts"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    api_methods = json.loads(args.api_methods_file.read_text(encoding="utf-8"))
    dialog_map = args.dialog_map_file.read_text(encoding="utf-8")
    use_case_markdown = ""
    if args.use_case_file and args.use_case_file.exists():
        use_case_markdown = args.use_case_file.read_text(encoding="utf-8")

    response = _client().chat.completions.create(
        model=os.getenv("OPENAI_MODEL") or os.getenv("ISOFTDEVAGENTS_LLM_MODEL") or "gpt-5.1",
        messages=[
            {
                "role": "system",
                "content": "You generate concise structured page descriptions for software projects.",
            },
            {
                "role": "user",
                "content": build_prompt(args.project_name, api_methods, dialog_map, use_case_markdown),
            },
        ],
        temperature=0.1,
    )
    payload = _extract_json(response.choices[0].message.content or "")
    ensure_single_page_contract(payload)

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path = args.output_file.with_suffix(".md")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    print(args.output_file.resolve())
    print(markdown_path.resolve())


if __name__ == "__main__":
    main()
