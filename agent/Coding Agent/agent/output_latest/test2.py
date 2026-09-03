import json
from pathlib import Path

# step4：external_api_analysis
EXTERNAL_API_ANALYSIS_PATH = Path("/Users/lxx/Desktop/CodeAgent/agent/output_latest/step4_5_test.md")

# step3：backend / modules 定义
BACKEND_PATH = Path("/Users/lxx/Desktop/CodeAgent/agent/output_latest/step3_4_test.md")

# 输出
OUTPUT_PATH = Path("/Users/lxx/Desktop/CodeAgent/agent/output_latest/step5_test.md")


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def merge_external_api_calls(backend, external_api_analysis):
    """
    把 external_api_analysis 中的 external_api_calls
    合并进 backend.modules.*.methods.*
    """

    analysis_modules = (
        external_api_analysis
        .get("external_api_analysis", {})
        .get("modules", {})
    )

    backend_modules = backend.get("modules", {})

    for module_name, analysis_module in analysis_modules.items():
        if module_name not in backend_modules:
            continue

        analysis_methods = analysis_module.get("methods", {})
        backend_methods = backend_modules[module_name].get("methods", {})

        for analysis_method in analysis_methods.values():
            method_name = analysis_method.get("method_name")
            external_calls = analysis_method.get("external_api_calls")

            if external_calls is None:
                continue

            for backend_method in backend_methods.values():
                if backend_method.get("method_name") != method_name:
                    continue

                backend_method["external_api_calls"] = external_calls

    return backend


def main():
    external_api_analysis = load_json(EXTERNAL_API_ANALYSIS_PATH)
    backend = load_json(BACKEND_PATH)

    merged = merge_external_api_calls(backend, external_api_analysis)

    save_json(merged, OUTPUT_PATH)


if __name__ == "__main__":
    main()
