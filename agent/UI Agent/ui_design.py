from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from openai import OpenAI

from ui_runtime import ensure_single_page_contract


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate runnable UI code from page descriptions.")
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--page-description-file", type=Path, required=True)
    parser.add_argument("--api-methods-file", type=Path, required=True)
    parser.add_argument("--use-case-file", type=Path, required=False)
    parser.add_argument("--dialog-map-file", type=Path, required=False)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("ISOFTDEVAGENTS_LLM_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("ISOFTDEVAGENTS_LLM_BASE_URL")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY or ISOFTDEVAGENTS_LLM_API_KEY is required for UI Agent.")
    return OpenAI(api_key=api_key, base_url=base_url)


def extract_block(content: str, languages: list[str]) -> str:
    for language in languages:
        pattern = re.compile(rf"```{language}\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
        match = pattern.search(content)
        if match:
            return match.group(1).strip()
    return ""


def build_api_service(api_methods: dict) -> str:
    methods = []
    for service in api_methods.values():
        for method_name, method in (service.get("methods") or {}).items():
            verb = method.get("http", {}).get("verb", "GET").upper()
            route = method.get("http", {}).get("route", "/")
            methods.append(
                "\n".join(
                    [
                        f"  async {method_name}(payload = null) {{",
                        f"    const response = await fetch(`${{API_BASE_URL}}{route}`, {{",
                        f"      method: '{verb}',",
                        "      headers: { 'Content-Type': 'application/json' },",
                        "      body: payload ? JSON.stringify(payload) : undefined,",
                        "    });",
                        "    if (!response.ok) throw new Error('API request failed');",
                        "    return response.status === 204 ? null : response.json();",
                        "  }},",
                    ]
                )
            )
    method_block = "\n".join(methods)
    return "\n".join(
        [
            "const API_BASE_URL = '';",
            "",
            "export const api = {",
            method_block,
            "};",
            "",
            "export async function loadInitialState() {",
            "  return null;",
            "}",
        ]
    )


def build_prompt(
    project_name: str,
    page: dict,
    api_methods: dict,
    use_case_markdown: str,
    dialog_map_markdown: str,
) -> str:
    return f"""
Generate runnable UI code for a single-page web application prototype.

Project name: {project_name}

Requirements:
- Output exactly three fenced code blocks: html, css, javascript.
- Build the main page described in the JSON below.
- Keep the design clean and usable.
- Use vanilla JS only.
- The JavaScript must work even if API methods are empty and should initialize a local fallback state in that case.

Page JSON:
{json.dumps(page, indent=2, ensure_ascii=False)}

Use Cases:
{use_case_markdown}

Dialog Map:
{dialog_map_markdown}

API Methods:
{json.dumps(api_methods, indent=2, ensure_ascii=False)}
""".strip()


def write_ui_files(output_dir: Path, html: str, css: str, js: str, api_service: str) -> None:
    (output_dir / "css").mkdir(parents=True, exist_ok=True)
    (output_dir / "js").mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text(html, encoding="utf-8")
    (output_dir / "css" / "style.css").write_text(css, encoding="utf-8")
    (output_dir / "js" / "index.js").write_text(js, encoding="utf-8")
    (output_dir / "js" / "api.js").write_text(api_service, encoding="utf-8")
    (output_dir / "README.md").write_text(
        "Run with a local web server, for example: `python3 -m http.server 8000`.\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    page_payload = json.loads(args.page_description_file.read_text(encoding="utf-8"))
    ensure_single_page_contract(page_payload)
    page = page_payload["pages"][0]
    api_methods = json.loads(args.api_methods_file.read_text(encoding="utf-8"))
    use_case_markdown = args.use_case_file.read_text(encoding="utf-8") if args.use_case_file and args.use_case_file.exists() else ""
    dialog_map_markdown = (
        args.dialog_map_file.read_text(encoding="utf-8") if args.dialog_map_file and args.dialog_map_file.exists() else ""
    )

    response = _client().chat.completions.create(
        model=os.getenv("OPENAI_MODEL") or os.getenv("ISOFTDEVAGENTS_LLM_MODEL") or "gpt-5.1",
        messages=[
            {
                "role": "system",
                "content": "You are a senior front-end engineer who produces concise runnable single-page apps.",
            },
            {
                "role": "user",
                "content": build_prompt(args.project_name, page, api_methods, use_case_markdown, dialog_map_markdown),
            },
        ],
        temperature=0.1,
    )
    raw_content = response.choices[0].message.content or ""
    html = extract_block(raw_content, ["html"])
    css = extract_block(raw_content, ["css"])
    js = extract_block(raw_content, ["javascript", "js"])
    if not html or not css or not js:
        raise RuntimeError("UI Agent did not return all required code blocks.")
    write_ui_files(args.output_dir, html, css, js, build_api_service(api_methods))
    print(args.output_dir.resolve())


if __name__ == "__main__":
    main()
