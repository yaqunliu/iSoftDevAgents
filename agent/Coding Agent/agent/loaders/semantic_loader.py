from .file_loader import load_json


class SemanticModel:

    def __init__(self, path: str):
        self.model = load_json(path)

    def resolve(self, ref_path: str):
        parts = ref_path.split(".")
        node = self.model

        try:
            for p in parts:
                if isinstance(node, dict):
                    node = node[p]
                elif isinstance(node, list):
                    node = next(x for x in node if x.get("name") == p)
                else:
                    raise KeyError
        except Exception:
            return None

        return node
