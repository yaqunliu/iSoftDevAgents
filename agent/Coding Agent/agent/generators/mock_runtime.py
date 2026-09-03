# generators/mock_runtime.py

import importlib.util
import traceback
from types import ModuleType


class MockResult:
    def __init__(self, ok: bool, errors=None):
        self.ok = ok
        self.errors = errors or []

    def __repr__(self):
        return f"MockResult(ok={self.ok}, errors={self.errors})"


def load_module_safely(module_path: str) -> MockResult:
    """
    Try to import a module from a path.
    This catches:
        - syntax errors
        - invalid import paths
        - missing dependency imports
    but DOES NOT check:
        - business logic
        - DTO correctness
        - semantic model consistency
    """

    try:
        spec = importlib.util.spec_from_file_location("mock_module", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return MockResult(ok=True)
    except Exception as e:
        tb = traceback.format_exc()
        return MockResult(ok=False, errors=[str(e), tb])


def simple_mock_validate(file_path: str):
    """
    High-level wrapper to validate a generated file.
    """

    result = load_module_safely(file_path)

    return result
