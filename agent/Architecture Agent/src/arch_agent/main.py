#!/usr/bin/env python
import json
import os
import re
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
import argparse



from arch_agent.crew import ArchDesign
from arch_agent.flow import ArchiFlow
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")


def _build_inputs(additional_inputs: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Construct the shared inputs dictionary for crew execution."""
    requirements_file = Path(sys.argv[1])
    if not requirements_file.exists():
        raise FileNotFoundError(
            f"Requirements document not found at {requirements_file}. "
            "Please ensure the SRS file is available before running the agents."
        )

    requirements = requirements_file.read_text(encoding="utf-8")

    inputs: Dict[str, Any] = {
        "project_name": sys.argv[2] if len(sys.argv) > 2 else Path(sys.argv[1]).stem,
        "requirements": requirements,
        # "requirements_source": str(requirements_file),
        "current_year": str(datetime.now().year),
    }

    if additional_inputs:
        inputs.update(additional_inputs)

    return inputs

def run(requirements_path: str = None, project_name: str = None):
    """Run the crew."""
    run_architecture_agent(requirements_path=requirements_path, project_name=project_name)


def _normalize_usage_payload(flow: ArchiFlow) -> dict[str, Any] | None:
    """
    从 Architecture Agent 的 Flow 对象里提取累计用量。

    这里优先读统一 agent 自己累计的 token 进程统计。
    这个 Flow 里虽然会创建很多个 Crew，但它们复用的是同一个 unified agent，
    所以这里拿到的就是整个架构阶段的总用量。
    """

    unified_agent = getattr(flow, "unified_agent", None)
    token_process = getattr(unified_agent, "_token_process", None)
    if token_process is not None and hasattr(token_process, "get_summary"):
        summary = token_process.get_summary()
        input_tokens = int(getattr(summary, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(summary, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(summary, "total_tokens", 0) or 0)
        if total_tokens <= 0 and (input_tokens > 0 or output_tokens > 0):
            total_tokens = input_tokens + output_tokens
        if total_tokens > 0 or input_tokens > 0 or output_tokens > 0:
            model = os.getenv("MODEL") or os.getenv("ISOFTDEVAGENTS_LLM_MODEL") or os.getenv("OPENAI_MODEL") or ""
            return {
                "model": model,
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "totalTokens": total_tokens,
            }

    # Fallback: 从 LLM 实例的 _token_usage 读取（由 install_crewai_llm_debug_logging patch 填充）
    llm = getattr(unified_agent, "llm", None)
    token_usage = getattr(llm, "_token_usage", None)
    if isinstance(token_usage, dict):
        input_tokens = int(token_usage.get("prompt_tokens") or 0)
        output_tokens = int(token_usage.get("completion_tokens") or 0)
        total_tokens = int(token_usage.get("total_tokens") or 0)
        if total_tokens <= 0 and (input_tokens > 0 or output_tokens > 0):
            total_tokens = input_tokens + output_tokens
        if total_tokens > 0 or input_tokens > 0 or output_tokens > 0:
            model = os.getenv("MODEL") or os.getenv("ISOFTDEVAGENTS_LLM_MODEL") or os.getenv("OPENAI_MODEL") or ""
            print(f"[ArchAgent] usage from LLM._token_usage fallback: input={input_tokens} output={output_tokens} total={total_tokens}", flush=True)
            return {
                "model": model,
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "totalTokens": total_tokens,
            }

    print("[ArchAgent] usage: NONE (both _token_process and LLM._token_usage empty)", flush=True)
    return None


def _write_usage_payload_if_needed(usage_payload: dict[str, Any] | None) -> None:
    usage_output_path = os.getenv("ISOFTDEVAGENTS_USAGE_OUTPUT", "").strip()
    if not usage_output_path or usage_payload is None:
        return
    Path(usage_output_path).write_text(
        json.dumps(usage_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_architecture_agent(requirements_path: str = None, project_name: str = None) -> dict[str, Any]:
    try:
        flow = ArchiFlow(requirements_path=requirements_path, project_name=project_name)
        flow.kickoff()
        usage_payload = _normalize_usage_payload(flow)
        _write_usage_payload_if_needed(usage_payload)
        return {
            "usage": usage_payload,
        }
    except Exception as exc:
        raise Exception(f"An error occurred while running the crew: {exc}") from exc

def train():
    """Train the crew for a given number of iterations."""
    if len(sys.argv) < 3:
        raise Exception("train command requires two arguments: <iterations> <output_filename>")

    try:
        ArchDesign().crew().train(
            n_iterations=int(sys.argv[1]),
            filename=sys.argv[2],
            inputs=_build_inputs(),
        )
    except Exception as exc:
        raise Exception(f"An error occurred while training the crew: {exc}") from exc

def replay():
    """Replay the crew execution from a specific task."""
    if len(sys.argv) < 2:
        raise Exception("replay command requires the task_id as an argument")

    try:
        ArchDesign().crew().replay(task_id=sys.argv[1])
    except Exception as exc:
        raise Exception(f"An error occurred while replaying the crew: {exc}") from exc

def test():
    """Test the crew execution and return the results."""
    if len(sys.argv) < 3:
        raise Exception("test command requires two arguments: <iterations> <eval_llm>")

    try:
        ArchDesign().crew().test(
            n_iterations=int(sys.argv[1]),
            eval_llm=sys.argv[2],
            inputs=_build_inputs(),
        )
    except Exception as exc:
        raise Exception(f"An error occurred while testing the crew: {exc}") from exc

def run_with_trigger():
    """Run the crew with a trigger payload provided via CLI."""
    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError as exc:
        raise Exception("Invalid JSON payload provided as argument") from exc

    try:
        inputs = _build_inputs({"crewai_trigger_payload": trigger_payload})
        result = ArchDesign().crew().kickoff(inputs=inputs)
    except Exception as exc:
        raise Exception(f"An error occurred while running the crew with trigger: {exc}") from exc

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the ArchAgent crew.")
    parser.add_argument(
        "requirements_path",
        nargs="?",
        help="Path to the requirements document (e.g., SRS file).",
    )
    parser.add_argument(
        "project_name",
        nargs="?",
        help="Name of the project. If not provided, it will be derived from the requirements file name.",
    )

    args = parser.parse_args()

    if args.requirements_path:
        req_path = args.requirements_path
        proj_name = args.project_name if args.project_name else Path(req_path).stem
        run(req_path, proj_name)
    else:
        parser.print_help()
