import json
from pathlib import Path

IMPLEMENTATION_SPEC_PATH = Path("/Users/lxx/Desktop/CodeAgent/agent/output_latest/step4_test.md")
BACKEND_PATH = Path("/Users/lxx/Desktop/CodeAgent/agent/output_latest/step3_test.md")
OUTPUT_PATH = Path("/Users/lxx/Desktop/CodeAgent/agent/output_latest/step3_4_test.md")

def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(data, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def merge_method_fields(backend, impl):
    impl_modules = impl.get("implementation_spec", {}).get("modules", {})
    backend_modules = backend.get("modules", {})

    for module_name, impl_module in impl_modules.items():
        if module_name not in backend_modules:
            continue

        impl_methods = impl_module.get("methods", {})
        backend_methods = backend_modules[module_name].get("methods", {})

        for impl_method in impl_methods.values():
            impl_method_name = impl_method.get("method_name")

            for backend_method in backend_methods.values():
                if backend_method.get("method_name") != impl_method_name:
                    continue

                if "trigger" in impl_method:
                    backend_method["trigger"] = impl_method["trigger"]

                if "steps" in impl_method:
                    backend_method["steps"] = impl_method["steps"]

                if "invoked_methods" in impl_method:
                    backend_method["invoked_methods"] = impl_method["invoked_methods"]
                
                if "key_functional_points" in impl_method:
                    backend_method["key_functional_points"] = impl_method["key_functional_points"]

    return backend

def main():
    impl = load_json(IMPLEMENTATION_SPEC_PATH)
    backend = load_json(BACKEND_PATH)

    merged = merge_method_fields(backend, impl)

    save_json(merged, OUTPUT_PATH)

if __name__ == "__main__":
    main()
