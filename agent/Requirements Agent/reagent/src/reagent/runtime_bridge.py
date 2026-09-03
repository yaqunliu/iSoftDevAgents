from __future__ import annotations

import argparse
import io
import json
import os
import pickle
import site
import sys
import warnings
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable, Iterator


warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

CURRENT = Path(__file__).resolve()
PACKAGE_ROOT = CURRENT.parent
SRC_ROOT = CURRENT.parents[1]
REQUIREMENTS_ROOT = CURRENT.parents[2]


def _normalize_model_name(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("openai/"):
        return normalized
    return f"openai/{normalized}"


def _managed_module_names() -> tuple[str, ...]:
    """
    这里只清理需求 Agent 自己这一条链路会碰到的模块。

    这样做是为了避免后端多次调用时，复用到上一次残留的全局状态。
    """

    return (
        "main",
        "StandardProcess",
        "NonStandardProcess",
        "RequirementExtraction",
        "BusinessRequirements",
        "MetaAnalysis",
        "RequirementAnalysis",
        "RequirementElicitation",
        "RequirementSpecification",
        "util",
        "util.runtime_env",
        "util.util",
        "util.DAG",
        "util.Artifacts",
        "util.validate_format",
        "util.user_case",
    )


def _apply_run_with_retry_override(
    *,
    run_with_retry_override: Any,
    util_module: Any,
    standard_process_module: Any,
) -> None:
    """
    接口注释：
    把平台注入的 `run_with_retry` 覆盖到需求 Agent 已加载的各个模块。

    设计注释：
    需求 Agent 里不少文件都用了 `from util import *`。
    这种写法会把 `run_with_retry` 在导入那一刻复制成模块自己的全局变量。
    如果我们只改 `util.run_with_retry`，那些已经导入完成的模块仍然会继续调用旧函数，
    结果就是 token usage 根本不会经过平台的统计回调。
    所以这里要把“当前已经加载到内存里的模块”一起补丁掉。
    """

    util_module.run_with_retry = run_with_retry_override
    standard_process_module.run_with_retry = run_with_retry_override

    for module_name in _managed_module_names():
        module = sys.modules.get(module_name)
        if module is None:
            continue
        if hasattr(module, "run_with_retry"):
            setattr(module, "run_with_retry", run_with_retry_override)


@contextmanager
def _prepared_runtime(
    *,
    runtime_home: str | Path,
    output_root: str | Path,
    tasks_config_path: str | Path | None,
    api_key: str,
    base_url: str,
    model: str,
    site_packages_dir: str | None,
    stdin_text: str,
    run_with_retry_override: Any = None,
    prompt_input_provider: Any = None,
    setup_logging: Callable[[], None] | None = None,
) -> Iterator[dict[str, Any]]:
    saved_modules = {name: sys.modules.get(name) for name in _managed_module_names()}
    for name in _managed_module_names():
        sys.modules.pop(name, None)

    original_sys_path = list(sys.path)
    original_cwd = Path.cwd()
    original_stdin = sys.stdin

    managed_env_keys = (
        "HOME",
        "CREWAI_STORAGE_DIR",
        "CREWAI_TRACING_ENABLED",
        "OTEL_SDK_DISABLED",
        "CREWAI_DISABLE_TELEMETRY",
        "CREWAI_DISABLE_TRACKING",
        "REAGENT_STORE_PATH",
        "ISOFTDEVAGENTS_REAGENT_NONINTERACTIVE",
        "ISOFTDEVAGENTS_REAGENT_ENABLE_WEB_TOOLS",
        "ISOFTDEVAGENTS_REAGENT_TASKS_CONFIG",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "ISOFTDEVAGENTS_LLM_API_KEY",
        "ISOFTDEVAGENTS_LLM_BASE_URL",
        "ISOFTDEVAGENTS_LLM_MODEL",
    )
    saved_env = {key: os.environ.get(key) for key in managed_env_keys}

    runtime_home_path = Path(runtime_home)
    output_root_path = Path(output_root)
    runtime_home_path.mkdir(parents=True, exist_ok=True)
    (runtime_home_path / "crewai-storage").mkdir(parents=True, exist_ok=True)
    output_root_path.mkdir(parents=True, exist_ok=True)

    try:
        sys.path.insert(0, str(PACKAGE_ROOT))
        sys.path.insert(0, str(SRC_ROOT))
        sys.path.insert(0, str(REQUIREMENTS_ROOT))
        if site_packages_dir:
            site.addsitedir(str(site_packages_dir))

        if setup_logging is not None:
            setup_logging()

        litellm_model = _normalize_model_name(model)
        os.environ["HOME"] = str(runtime_home_path)
        os.environ["CREWAI_STORAGE_DIR"] = str(runtime_home_path / "crewai-storage")
        os.environ["REAGENT_STORE_PATH"] = str(output_root_path)
        if prompt_input_provider is None:
            os.environ["ISOFTDEVAGENTS_REAGENT_NONINTERACTIVE"] = "1"
        else:
            os.environ.pop("ISOFTDEVAGENTS_REAGENT_NONINTERACTIVE", None)
        os.environ["ISOFTDEVAGENTS_REAGENT_ENABLE_WEB_TOOLS"] = "0"
        if tasks_config_path:
            os.environ["ISOFTDEVAGENTS_REAGENT_TASKS_CONFIG"] = str(tasks_config_path)
        else:
            os.environ.pop("ISOFTDEVAGENTS_REAGENT_TASKS_CONFIG", None)
        os.environ["OPENAI_API_KEY"] = api_key
        os.environ["OPENAI_BASE_URL"] = base_url
        os.environ["OPENAI_MODEL"] = litellm_model
        os.environ["ISOFTDEVAGENTS_LLM_API_KEY"] = api_key
        os.environ["ISOFTDEVAGENTS_LLM_BASE_URL"] = base_url
        os.environ["ISOFTDEVAGENTS_LLM_MODEL"] = litellm_model

        os.chdir(REQUIREMENTS_ROOT)
        sys.stdin = io.StringIO(stdin_text)

        from util.runtime_env import apply_runtime_observability_defaults, load_runtime_env

        load_runtime_env(REQUIREMENTS_ROOT)
        # 设计注释：
        # load_runtime_env 只负责“默认关闭”。
        # 真正进入平台桥梁运行时，这里再强制覆盖一次，避免外部 shell、
        # 用户本机残留配置、或者 CrewAI 之前记住的 tracing 偏好把噪音日志重新打开。
        apply_runtime_observability_defaults(force=True)

        import StandardProcess
        import util
        from util.prompt_input_bridge import clear_prompt_input_provider, set_prompt_input_provider

        import sys as _sys
        print(f"[runtime_bridge] run_with_retry_override={run_with_retry_override}", file=_sys.__stderr__, flush=True)
        if run_with_retry_override is not None:
            _apply_run_with_retry_override(
                run_with_retry_override=run_with_retry_override,
                util_module=util,
                standard_process_module=StandardProcess,
            )
            print(f"[runtime_bridge] patched run_with_retry in {len(list(_managed_module_names()))} modules", file=_sys.__stderr__, flush=True)

        set_prompt_input_provider(prompt_input_provider)

        yield {
            "StandardProcess": StandardProcess,
            "util": util,
            "model": litellm_model,
            "output_root": output_root_path,
            "tasks_config_path": Path(tasks_config_path) if tasks_config_path else None,
        }
    finally:
        try:
            from util.prompt_input_bridge import clear_prompt_input_provider

            clear_prompt_input_provider()
        except Exception:
            pass
        sys.stdin = original_stdin
        os.chdir(original_cwd)
        sys.path[:] = original_sys_path
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def RequirementSpecificationrun(
    document_template: Any,
    document_skeleton: Any,
    doc_content: Any,
    chapter_dependence: Any,
    SRS_Reference: Any,
    srs_example_path: str | None,
) -> None:
    from RequirementSpecification import SRSev, SRSplaningCrew
    from StandardProcess import load_json_payload_from_markdown as _parse_json
    from util import (
        get_SRS_chapter,
        get_SRS_planning,
        get_dependence_appendix,
        get_reference,
        parse_skeleton_to_document_template,
        print_doc_content,
        read_markdown,
        run_with_retry,
        store_path,
        split_markdown_by_h2,
        topological_sort,
    )

    chapter_sequence = topological_sort(chapter_dependence)
    SRS_initial_template = document_template
    SRS = parse_skeleton_to_document_template(
        skeleton_json=document_skeleton,
        authors="csl-gpt4.1",
    )

    def post_process() -> None:
        chapter = get_SRS_chapter()
        try:
            parsed_chapter = _parse_json(chapter)
        except (json.JSONDecodeError, ValueError):
            try:
                from json_repair import repair_json
                parsed_chapter = json.loads(repair_json(chapter))
            except Exception:
                parsed_chapter = json.loads(chapter)
        chapter = _normalize_srs_chapter_payload(parsed_chapter)
        # 设计注释：
        # 这里把归一化后的章节结果写回调试文件，方便后面排查模型到底输出了什么、
        # 以及桥梁层最后交给 document.py 的真实结构是什么。
        with open(f"{store_path}/software_requirements_specification_chapter.md", "w", encoding="utf-8") as handle:
            handle.write(json.dumps(chapter, ensure_ascii=False, indent=2))
        SRS.write_file(chapter)
        with open(f"{store_path}/SRS.pkl", "wb") as handle:
            pickle.dump(SRS, handle)
        with open(f"{store_path}/SRS.md", "w", encoding="utf-8") as handle:
            handle.write(f"{SRS.get_whole_document(only_show_written=True)}{get_dependence_appendix(SRS_Reference)}")

    if srs_example_path:
        SRS_example = split_markdown_by_h2(read_markdown(srs_example_path))
    else:
        SRS_example = None

    SRS_chapter_dict: dict[str, str] = {}
    for index, chapter in enumerate(chapter_sequence):
        dependency_chapter_list = [item for item in chapter_dependence[chapter]]
        if SRS_example is not None:
            SRS_exmaple_inputs = {
                "SRS_example": SRS_example[index + 1],
                "SRS_reference": get_reference(SRS_Reference[index], artifact=False),
                "dependence_chapter_content": "".join(
                    [
                        print_doc_content(doc_content[item])
                        for item in range(len(doc_content))
                        if doc_content[item]["chapter_index"] in dependency_chapter_list
                    ]
                ),
            }
            run_with_retry(
                SRSplaningCrew,
                inputs=SRS_exmaple_inputs,
                name=f"SRS Chapter planning {index}",
            )
            prompt = get_SRS_planning()
        else:
            prompt = SRS_initial_template.SUBCHAPTERS[index].get_all_content(introduction=True)

        SRS_inputs = {
            "SRS_chapter_structure": SRS_initial_template.SUBCHAPTERS[index].get_all_content(introduction=True),
            "reference": get_reference(SRS_Reference[index]),
            "chapter_reference": "".join([SRS_chapter_dict[item] for item in dependency_chapter_list]),
            "prompt": prompt,
            "chapter_index": index,
        }
        run_with_retry(
            SRSev,
            inputs=SRS_inputs,
            name=f"SRS Chapter {index + 1}",
            post_process_callable=post_process,
        )
        try:
            srs_chapter_raw = _parse_json(get_SRS_chapter())
        except (json.JSONDecodeError, ValueError):
            try:
                from json_repair import repair_json
                srs_chapter_raw = json.loads(repair_json(get_SRS_chapter()))
            except Exception:
                srs_chapter_raw = json.loads(get_SRS_chapter())
        SRS_chapter_dict[chapter] = json.dumps(
            _normalize_srs_chapter_payload(srs_chapter_raw),
            ensure_ascii=False,
        )

    from util import get_dependence_appendix

    with open(f"{store_path}/SRS.md", "w", encoding="utf-8") as handle:
        handle.write(f"{SRS.get_whole_document(only_show_written=True)}{get_dependence_appendix(SRS_Reference)}")


def _run_with_optional_redirects(
    *,
    stdout_writer: io.TextIOBase | None,
    stderr_writer: io.TextIOBase | None,
    runner: Callable[[], None],
) -> None:
    if stdout_writer is None and stderr_writer is None:
        runner()
        return
    with redirect_stdout(stdout_writer or sys.stdout), redirect_stderr(stderr_writer or sys.stderr):
        runner()


def _merge_usage_payloads(
    usage_payloads: list[dict[str, Any]],
    *,
    model: str,
) -> dict[str, Any] | None:
    if not usage_payloads:
        return None

    return {
        "model": _normalize_model_name(model),
        "inputTokens": sum(int(item.get("inputTokens") or 0) for item in usage_payloads),
        "outputTokens": sum(int(item.get("outputTokens") or 0) for item in usage_payloads),
        "totalTokens": sum(int(item.get("totalTokens") or 0) for item in usage_payloads),
    }


def _build_tracked_run_with_retry(
    run_with_retry_override: Any,
    usage_payloads: list[dict[str, Any]],
    usage_callback: Any = None,
    cancel_event: Any = None,
) -> Any:
    """
    需求 Agent 内部很多步骤都会经过 run_with_retry。

    这里统一包一层，是为了把每一次 LLM 调用的 usage 都拦下来，
    最后再合并回后端项目的总 token 统计。
    """

    if run_with_retry_override is None:
        return None

    def record_usage(payload: dict[str, Any]) -> None:
        usage_payloads.append(payload)
        if usage_callback is not None:
            usage_callback(payload)

    def tracked_run_with_retry(*args, **kwargs):
        return run_with_retry_override(
            *args,
            **kwargs,
            usage_callback=record_usage,
            cancel_event=cancel_event,
        )

    return tracked_run_with_retry


def _build_runtime_result(
    *,
    output_root: str | Path,
    tasks_config_path: str | Path | None,
    model: str,
    usage_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    """统一整理桥梁层返回结果，避免 analysis/full 各自拼一遍。"""

    return {
        "output_root": str(output_root),
        "tasks_config_path": str(tasks_config_path) if tasks_config_path else None,
        "model": _normalize_model_name(model),
        "seededFiles": [],
        "usage": _merge_usage_payloads(usage_payloads, model=model),
    }


def _stringify_srs_structure_value(value: Any) -> str:
    """
    把零散字段整理成可放进 SRS `structure` 的文本。

    教学注释：
    `document.py` 只认识 `structure/subchapter` 这套形状。
    但模型偶尔会输出 `content/requirements/chapters` 这种旧格式，
    所以这里先把内容尽量保留下来，再统一映射到新格式。
    """

    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            if isinstance(item, dict):
                lines.append(json.dumps(item, ensure_ascii=False))
            else:
                normalized = str(item).strip()
                if normalized:
                    lines.append(f"- {normalized}")
        return "\n".join(lines).strip()
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value).strip()


def _legacy_srs_structure_items(chapter_payload: dict[str, Any]) -> list[dict[str, str]]:
    """
    把旧式章节字段折叠成 `structure` 列表。

    设计注释：
    这里不是去“美化”模型输出，而是为了保证：
    1. 旧字段不会直接把 SRS 落盘阶段打崩
    2. 已经生成出来的正文、需求点、补充字段尽量不丢
    """

    structure_items: list[dict[str, str]] = []

    introduction = _stringify_srs_structure_value(chapter_payload.get("introduction"))
    if introduction:
        structure_items.append({"introduction": introduction})

    content = _stringify_srs_structure_value(chapter_payload.get("content"))
    if content:
        structure_items.append({"content": content})

    requirements = chapter_payload.get("requirements")
    if isinstance(requirements, list) and requirements:
        requirement_lines: list[str] = []
        for item in requirements:
            if isinstance(item, dict):
                requirement_index = str(item.get("index") or "").strip()
                requirement_content = str(item.get("content") or "").strip()
                if requirement_index and requirement_content:
                    requirement_lines.append(f"- {requirement_index}: {requirement_content}")
                elif requirement_content:
                    requirement_lines.append(f"- {requirement_content}")
                elif requirement_index:
                    requirement_lines.append(f"- {requirement_index}")
            else:
                normalized = str(item).strip()
                if normalized:
                    requirement_lines.append(f"- {normalized}")
        if requirement_lines:
            structure_items.append({"requirements": "\n".join(requirement_lines)})

    reserved_keys = {
        "chapter_index",
        "title",
        "structure",
        "subchapter",
        "chapters",
        "content",
        "introduction",
        "requirements",
    }
    for key, value in chapter_payload.items():
        if key in reserved_keys:
            continue
        normalized_value = _stringify_srs_structure_value(value)
        if normalized_value:
            structure_items.append({str(key): normalized_value})

    if not structure_items:
        structure_items.append({"content": ""})
    return structure_items


def _normalize_srs_chapter_payload(chapter_payload: Any) -> dict[str, Any]:
    """
    把 SRS 单章结果归一化成 `document.py` 能稳定消费的结构。

    目前兼容两类输入：
    - 新格式：`chapter_index/title/structure/subchapter`
    - 旧格式：`chapter_index/title/content/requirements/chapters`
    """

    if not isinstance(chapter_payload, dict):
        raise ValueError("SRS chapter payload must be a dictionary.")

    raw_chapter_index = chapter_payload.get("chapter_index")
    # 注意：chapter_index 可能是整数 0，而 0 是 falsy，
    # 不能用 `x or ""` 做默认值兜底，否则 0 会被吞掉变成空字符串。
    chapter_index_str = str(raw_chapter_index).strip() if raw_chapter_index is not None else ""

    normalized_payload: dict[str, Any] = {
        "chapter_index": chapter_index_str,
        "title": str(chapter_payload.get("title") or "").strip() or "Untitled Section",
    }

    structure = chapter_payload.get("structure")
    if isinstance(structure, list):
        normalized_payload["structure"] = structure
    else:
        normalized_payload["structure"] = _legacy_srs_structure_items(chapter_payload)

    raw_subchapters = chapter_payload.get("subchapter")
    if not isinstance(raw_subchapters, list):
        raw_subchapters = chapter_payload.get("chapters")
    if not isinstance(raw_subchapters, list):
        raw_subchapters = []

    normalized_payload["subchapter"] = [
        _normalize_srs_chapter_payload(subchapter)
        for subchapter in raw_subchapters
        if isinstance(subchapter, dict)
    ]

    return normalized_payload


def run_requirements_agent_analysis(
    *,
    project_name: str,
    description_text: str,
    runtime_home: str | Path,
    output_root: str | Path,
    tasks_config_path: str | Path | None,
    api_key: str,
    base_url: str,
    model: str,
    site_packages_dir: str | None = None,
    stdout_writer: io.TextIOBase | None = None,
    stderr_writer: io.TextIOBase | None = None,
    run_with_retry_override: Any = None,
    prompt_input_provider: Any = None,
    task_id: str | None = None,
    usage_callback: Any = None,
    setup_logging: Callable[[], None] | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    del task_id
    usage_payloads: list[dict[str, Any]] = []
    tracked_run_with_retry = _build_tracked_run_with_retry(
        run_with_retry_override,
        usage_payloads,
        usage_callback=usage_callback,
        cancel_event=cancel_event,
    )

    def runner() -> None:
        with _prepared_runtime(
            runtime_home=runtime_home,
            output_root=output_root,
            tasks_config_path=tasks_config_path,
            api_key=api_key,
            base_url=base_url,
            model=model,
            site_packages_dir=site_packages_dir,
            stdin_text="" if prompt_input_provider is not None else "no\n" * 16,
            run_with_retry_override=tracked_run_with_retry,
            prompt_input_provider=prompt_input_provider,
            setup_logging=setup_logging,
        ) as runtime:
            standard_process = runtime["StandardProcess"]
            prompt_analysis_run = getattr(standard_process, "PromptAnalysisRun", None)
            if prompt_analysis_run is not None:
                prompt_analysis_run(
                    project_name=project_name,
                    Description=description_text,
                )
                return

            from BusinessRequirements import FeatureTreeRun

            # 老需求 Agent 缺少稳定的 PromptAnalysisRun 时，
            # 这里不要再退回整条 BRD 草稿链路。
            # 因为那样会把 survey / business_scope / BRD 等后续阶段文件提前产出，
            # 直接污染“第一步只做模块分析”的运行边界。
            #
            # analysis 阶段的平台合同只有 feature_tree.md，
            # 所以这里改成只调用真实的 FeatureTree 生成能力。
            feature_tree_run = FeatureTreeRun(
                project_name=project_name,
                Description=description_text,
            )
            feature_tree_run.run(
                "本轮没有人类意见",
                {"all": ""},
                description_text,
            )

    _run_with_optional_redirects(
        stdout_writer=stdout_writer,
        stderr_writer=stderr_writer,
        runner=runner,
    )

    return _build_runtime_result(
        output_root=output_root,
        tasks_config_path=tasks_config_path,
        model=model,
        usage_payloads=usage_payloads,
    )


def run_requirements_agent_full(
    *,
    project_name: str,
    description_text: str,
    runtime_home: str | Path,
    output_root: str | Path,
    tasks_config_path: str | Path | None,
    api_key: str,
    base_url: str,
    model: str,
    site_packages_dir: str | None = None,
    stdout_writer: io.TextIOBase | None = None,
    stderr_writer: io.TextIOBase | None = None,
    run_with_retry_override: Any = None,
    prompt_input_provider: Any = None,
    task_id: str | None = None,
    srs_example_path: str | None = None,
    srs_template: str | None = None,
    data_path: str | None = None,
    usage_callback: Any = None,
    setup_logging: Callable[[], None] | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    del task_id
    usage_payloads: list[dict[str, Any]] = []
    tracked_run_with_retry = _build_tracked_run_with_retry(
        run_with_retry_override,
        usage_payloads,
        usage_callback=usage_callback,
        cancel_event=cancel_event,
    )

    def runner() -> None:
        with _prepared_runtime(
            runtime_home=runtime_home,
            output_root=output_root,
            tasks_config_path=tasks_config_path,
            api_key=api_key,
            base_url=base_url,
            model=model,
            site_packages_dir=site_packages_dir,
            stdin_text="" if prompt_input_provider is not None else "no\n" * 16,
            run_with_retry_override=tracked_run_with_retry,
            prompt_input_provider=prompt_input_provider,
            setup_logging=setup_logging,
        ) as runtime:
            import NonStandardProcess

            standard_process = runtime["StandardProcess"]

            if data_path:
                if not os.path.exists(data_path):
                    raise FileNotFoundError("数据文件未找到")
                # 只有真的传入外部资料路径时，才去加载这个可选模块。
                # 否则 requirements agent 的常规流程不应该被额外依赖卡死。
                import RequirementExtraction

                RequirementExtraction.RequirementsExtractionRun(
                    project_name,
                    description_text,
                    data_path,
                ).run()

            (
                document_template,
                document_skeleton,
                doc_planning,
                chapter_dependence,
                artifact_planing,
            ) = standard_process.StandardProcessrun(
                project_name=project_name,
                Description=description_text,
                srs_example_path=srs_example_path,
                SRS_template=srs_template,
            )
            NonStandardProcess.NonStandardProcessrun(
                project_name=project_name,
                Description=description_text,
                artifact_planing=artifact_planing,
            )
            RequirementSpecificationrun(
                document_template,
                document_skeleton,
                doc_planning,
                chapter_dependence,
                SRS_Reference=artifact_planing,
                srs_example_path=srs_example_path,
            )

    _run_with_optional_redirects(
        stdout_writer=stdout_writer,
        stderr_writer=stderr_writer,
        runner=runner,
    )

    return _build_runtime_result(
        output_root=output_root,
        tasks_config_path=tasks_config_path,
        model=model,
        usage_payloads=usage_payloads,
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run automated requirement engineering pipeline")
    parser.add_argument("--mode", type=str, default="full", choices=["analysis", "full"], help="运行模式")
    parser.add_argument("--project_name", type=str, default="自动化软件源代码审查平台", help="项目名称")
    parser.add_argument("--description_file", type=str, required=True, help="项目描述文本文件路径")
    parser.add_argument("--data_path", type=str, default=None, help="项目数据路径")
    parser.add_argument("--srs_example_path", type=str, default=None, help="SRS 示例模板路径")
    parser.add_argument("--srs_template", type=str, default=None, help="SRS 模板（可选）")
    return parser


def run_cli(argv: list[str] | None = None) -> dict[str, Any]:
    args = build_cli_parser().parse_args(argv)
    with open(args.description_file, "r", encoding="utf-8") as handle:
        description_text = handle.read()

    common_kwargs = {
        "project_name": args.project_name,
        "description_text": description_text,
        "runtime_home": REQUIREMENTS_ROOT / ".runtime-home",
        "output_root": Path(os.getenv("REAGENT_STORE_PATH", "output")),
        "tasks_config_path": os.getenv("ISOFTDEVAGENTS_REAGENT_TASKS_CONFIG"),
        "api_key": os.getenv("ISOFTDEVAGENTS_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "",
        "base_url": os.getenv("ISOFTDEVAGENTS_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "",
        "model": os.getenv("ISOFTDEVAGENTS_LLM_MODEL") or os.getenv("OPENAI_MODEL") or "",
    }

    if args.mode == "analysis":
        return run_requirements_agent_analysis(**common_kwargs)

    return run_requirements_agent_full(
        **common_kwargs,
        srs_example_path=args.srs_example_path,
        srs_template=args.srs_template,
        data_path=args.data_path,
    )
