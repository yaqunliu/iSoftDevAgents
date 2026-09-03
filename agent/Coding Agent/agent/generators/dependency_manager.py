import os


def collect_files(structure, prefix=""):
    files = {}

    for name, meta in structure.items():
        path = f"{prefix}/{name}" if prefix else name

        if isinstance(meta, dict) and "priority" not in meta:
            files.update(collect_files(meta, path))
        else:
            files[path] = meta

    return files



def sort_files_by_priority(files_dict):
    return sorted(files_dict.items(), key=lambda kv: kv[1]["priority"])



def read_context(dep_files):
    text = ""
    for file in dep_files:
        print(f"dep_file: {file}")
        if os.path.exists(file):
            with open(file, "r", encoding="utf-8") as f:
                text += f"\n\n# ===== {file} =====\n{f.read()}"
    return text



def extract_source_details(ref_paths, semantic_model):
    result = {}

    if not ref_paths:
        return result

    

    for ref in ref_paths:
        print("ref_paths:", ref_paths)
        node = semantic_model.resolve(ref)
        print("node:", node)
        result[ref] = node if node is not None else "[ERROR] Cannot resolve"

    return result
