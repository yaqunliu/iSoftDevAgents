# import json
# from crewai import Crew, Task

# from generators.dependency_manager import extract_source_details


# def generate_file_using_llm(
#     agent,
#     file_path,
#     meta,
#     context,
#     semantic_model,
#     code_desc
# ):

#     description = meta.get("description", "")
#     source_ref = meta.get("source_ref", [])


#     source_details = extract_source_details(source_ref, semantic_model)

#     prompt = f"""
#     You are generating the file: **{file_path}**

#     ============================================================
#     FILE PURPOSE
#     ============================================================
#     {description}

#     ============================================================
#     SOURCE REFERENCES (Resolved from semantic_model)
#     ============================================================
#     {json.dumps(source_details, indent=2)}

#     ============================================================
#     RAW SOURCE_REF PATHS
#     ============================================================
#     {json.dumps(source_ref, indent=2)}

#     ============================================================
#     DEPENDENCIES CONTEXT
#     ============================================================
#     {context}

#     ============================================================
#     CODE GENERATION RULES
#     ============================================================
#     {code_desc}
#     """


#     task = Task(
#         description=prompt,
#         expected_output="Valid runnable code",
#         agent=agent
#     )

#     crew = Crew(
#         agents=[agent],
#         tasks=[task],
#         verbose=True
#     )

#     crew.kickoff()

#     return task.output.raw

import json
from crewai import Crew, Task

from generators.dependency_manager import extract_source_details


def _section(title: str, body: str | None):
    """Return a formatted section only if body is not empty."""
    if not body:
        return ""
    clean_body = body.strip()
    if clean_body == "":
        return ""
    return f"""
    ============================================================
    {title}
    ============================================================
    {clean_body}
    """


def generate_file_using_llm(
    agent,
    file_path,
    meta,
    context,
    semantic_model,
    code_desc
):

    description = meta.get("description") or ""
    source_ref = meta.get("source_ref") or []

    # Build optional parts
    source_details = ""
    raw_source_ref = ""
    context_section = ""

    if source_ref:
        resolved = extract_source_details(source_ref, semantic_model)
        source_details = _section(
            "SOURCE REFERENCES",
            json.dumps(resolved, indent=2, ensure_ascii=False)
        )

    if context and str(context).strip():
        context_section = _section("DEPENDENCIES CONTEXT", str(context))

    # Always include FILE PURPOSE + CODE RULES
    file_purpose_section = _section("FILE PURPOSE", description)
    code_rules_section = _section("CODE GENERATION RULES", code_desc)

    # Final prompt assembly (clean & safe)
    prompt = f"""
        You are generating the file: **{file_path}**
        {file_purpose_section}
        {source_details}
        {raw_source_ref}
        {context_section}
        {code_rules_section}
        """.strip()

    task = Task(
        description=prompt,
        expected_output="Valid runnable code",
        agent=agent
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        verbose=True
    )

    crew.kickoff()

    return task.output.raw
