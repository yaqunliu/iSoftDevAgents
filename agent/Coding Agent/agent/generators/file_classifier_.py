import re

class FileClassifier:

    # ---------------------------------------------------------
    # L1: Exact pattern rules (strongest)
    # ---------------------------------------------------------
    EXACT_RULES = {
        r".*entity\.py$": "entity",
        r".*entities\.py$": "entity",
        r".*_dto\.py$": "dto",
        r".*_repository_impl\.py$": "repository_impl",
        r".*repositories\.py$": "repository",
        r".*service\.py$": "service",
        r".*controller\.py$": "controller",
        r".*routes\.py$": "route",
        r".*model\.py$": "model",
        r".*/models/__init__\.py$": "general"
    }

    # ---------------------------------------------------------
    # L2: Directory-based rules
    # ---------------------------------------------------------
    PATH_RULES = {
        r".*/entities/.*": "entity",
        r".*/dto/.*": "dto",
        r".*/repositories/impl/.*": "repository_impl",
        r".*/repositories/.*": "repository",
        r".*/services/.*": "service",
        r".*/controllers/.*": "controller",
        r".*/infra/.*": "infra",
        r".*/models/.*": "model",
        r".*/schemas/.*": "schema",
    }

    # ---------------------------------------------------------
    # L3: Semantic token rules (fallback)
    # ---------------------------------------------------------
    SEMANTIC_RULES = {
        r".*(request|response|dto).*": "dto",
        r".*(repository).*": "repository",
        r".*(impl|implementation).*": "repository_impl",
        r".*(entity|model).*": "entity",
        r".*(service).*": "service",
        r".*(controller|handler).*": "controller",
        r".*(schema).*": "schema",
    }

    # ---------------------------------------------------------
    # MASTER API
    # ---------------------------------------------------------
    def classify(self, file_path: str) -> str:

        # --- Level 1: exact match
        for pattern, label in self.EXACT_RULES.items():
            if re.match(pattern, file_path):
                return label

        # --- Level 2: directory-based
        for pattern, label in self.PATH_RULES.items():
            if re.match(pattern, file_path):
                return label

        # --- Level 3: semantic
        filename = file_path.replace("\\", "/").split("/")[-1].lower()
        for pattern, label in self.SEMANTIC_RULES.items():
            if re.match(pattern, filename):
                return label

        # --- default fallback
        return "general"
