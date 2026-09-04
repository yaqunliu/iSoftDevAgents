from __future__ import annotations

import os

from crewai import Agent
from crewai import LLM


def _runtime_llm() -> LLM:
    model = os.getenv("ISOFTDEVAGENTS_LLM_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5"
    base_url = os.getenv("ISOFTDEVAGENTS_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("ISOFTDEVAGENTS_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    max_completion_tokens = int(os.getenv("ISOFTDEVAGENTS_CODING_MAX_TOKENS", "16384"))
    return LLM(
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_completion_tokens=max_completion_tokens,
    )


def create_codegen_agent():
    return Agent(
        role="Senior Software Engineer",
        goal="Generate real executable code for each file.",
        backstory="Expert in scalable backend and frontend engineering.",
        llm=_runtime_llm(),
    )


def create_analysis_agent():
    return Agent(
        role="Code Analysis and Generation Expert",
        goal="Analyze SRS and architecture to generate semantic models.",
        backstory="Expert in domain-driven analysis.",
        llm=_runtime_llm(),
    )
