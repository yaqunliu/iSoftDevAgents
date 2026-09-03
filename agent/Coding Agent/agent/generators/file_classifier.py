import re


class FileClassifier:

    # =========================================================
    # L1: EXACT RULES (Strongest)
    # =========================================================
    EXACT_RULES = {
        # Backend entry
        r".*/run\.py$": "backend_entry",
        r".*/app/__init__\.py$": "backend_entry",

        # Backend API endpoints
        r".*/api/.*_module_api\.py$": "backend_api_module",
        r".*/api/.*_api\.py$": "backend_api_module",

        # Backend services
        r".*/services/.*_service\.py$": "backend_service",

        # Backend repositories
        r".*/repositories/.*_repository\.py$": "backend_repository",

        # Backend models
        r".*/models/.*\.py$": "backend_model",

        # Frontend entries
        r".*/src/main\.jsx$": "frontend_entry",
        r".*/src/App\.jsx$": "frontend_app",
        r".*/index\.html$": "frontend_general",

        # Frontend routes
        r".*/src/routes/.*Routes\.jsx$": "frontend_routes",

        # Frontend pages
        r".*/src/pages/.*\.jsx$": "frontend_pages",

        # Frontend components
        r".*/src/components/.*Component\.jsx$": "frontend_component",
        r".*/src/components/.*Input\.jsx$": "frontend_component",

        # Frontend API clients
        r".*/src/api/.*ModuleApi\.js$": "frontend_api_client",
        r".*/src/api/.*Api\.js$": "frontend_api_client",

        # Frontend utils
        r".*/src/utils/request\.js$": "frontend_http_utils",
    }

    # =========================================================
    # L2: PATH RULES (Folder-based)
    # =========================================================
    PATH_RULES = {
        # Backend
        r".*/app/api/.*": "backend_entry",
        r".*/app/services/.*": "backend_service",
        r".*/app/repositories/.*": "backend_repository",
        r".*/app/models/.*": "backend_model",
        r".*/app/tasks/.*": "backend_tasks",
        r".*/app/utils/.*": "backend_utils",

        # Frontend
        r".*/src/routes/.*": "frontend_routes",
        r".*/src/pages/.*": "frontend_pages",
        r".*/src/components/.*": "frontend_components",
        r".*/src/api/.*": "frontend_api_client",
        r".*/src/utils/.*": "frontend_utils",
    }

    # =========================================================
    # L3: SEMANTIC RULES (Filename-based fallback)
    # =========================================================
    SEMANTIC_RULES = {
        # Backend semantics
        r".*(service).*": "backend_service",
        r".*(repository).*": "backend_repository",
        r".*(model).*": "backend_model",
        r".*(entity).*": "backend_model",
        r".*(config).*": "backend_entry",
        r".*(extension).*": "backend_entry",

        # Frontend semantics
        r".*(route|routes).*": "frontend_routes",
        r".*(page|detail|list|dashboard).*": "frontend_pages",
        r".*(component|input|editor).*": "frontend_component",
        r".*(api).*": "frontend_api_client",
        r".*(request).*": "frontend_http_utils",
    }

    # =========================================================
    # MASTER API
    # =========================================================
    def classify(self, file_path: str) -> str:
        normalized = file_path.replace("\\", "/")

        # ---------- Level 1: Exact rules ----------
        for pattern, label in self.EXACT_RULES.items():
            if re.match(pattern, normalized):
                return label

        # ---------- Level 2: Folder rules ----------
        for pattern, label in self.PATH_RULES.items():
            if re.match(pattern, normalized):
                return label

        # ---------- Level 3: Semantic rules ----------
        filename = normalized.split("/")[-1].lower()
        for pattern, label in self.SEMANTIC_RULES.items():
            if re.match(pattern, filename):
                return label

        # ---------- Default ----------
        return "frontend_general"


# # Example Usage
# if __name__ == "__main__":
#     classifier = FileClassifier()
#     print(classifier.classify("backend/app/services/review_engine_module_service.py"))
#     print(classifier.classify("frontend/src/pages/UserManagement_UpdateUser.jsx"))
#     print(classifier.classify("frontend/src/api/reviewRulesManagementModuleApi.js"))
