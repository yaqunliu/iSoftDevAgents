import json
import os


def create_structure(base_path: str, structure: dict):
    for name, content in structure.items():
        path = os.path.join(base_path, name)

        if isinstance(content, dict):
            os.makedirs(path, exist_ok=True)
            create_structure(path, content)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content or "")



def extract_file_tree(meta: dict):
    file_tree = {}

    for key, value in meta.items():
        if isinstance(value, dict):
            if "priority" in value:
                file_tree[key] = ""
            else:
                file_tree[key] = extract_file_tree(value)

    return file_tree



def build_from_stepB_json(json_path: str, project_root: str):
    with open(json_path, "r", encoding="utf-8") as f:
        structure = json.load(f)

    tree = extract_file_tree(structure)
    create_structure(project_root, tree)
    print(f"Project structure created → {project_root}")

    return tree
