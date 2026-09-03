import importlib.util
import sys
import tempfile
import types
from pathlib import Path


def _load_pipeline_core_module():
    module_path = Path(__file__).resolve().parents[1] / "agent" / "TestAgent" / "piplines" / "core.py"

    fake_crewai = types.ModuleType("crewai")
    fake_crewai.Task = object
    fake_crewai.Crew = object

    fake_jinja2 = types.ModuleType("jinja2")

    class FakeTemplate:
        def __init__(self, text: str) -> None:
            self.text = text

        def render(self, **kwargs):
            return self.text.format(**kwargs)

    fake_jinja2.Template = FakeTemplate

    module_name = "test_agent_pipeline_core_under_test"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    old_crewai = sys.modules.get("crewai")
    old_jinja2 = sys.modules.get("jinja2")
    sys.modules["crewai"] = fake_crewai
    sys.modules["jinja2"] = fake_jinja2
    try:
        spec.loader.exec_module(module)
    finally:
        if old_crewai is not None:
            sys.modules["crewai"] = old_crewai
        else:
            sys.modules.pop("crewai", None)
        if old_jinja2 is not None:
            sys.modules["jinja2"] = old_jinja2
        else:
            sys.modules.pop("jinja2", None)
    return module


def test_pipeline_step_run_returns_final_text_for_streaming_output():
    module = _load_pipeline_core_module()
    PipelineStep = module.PipelineStep

    class FakeStreamingOutput:
        def __init__(self) -> None:
            self.is_completed = False
            self._chunks = ["{\"modules\":", " []}"]
            self.result = None

        def __iter__(self):
            for chunk in self._chunks:
                yield chunk
            self.result = types.SimpleNamespace(raw='{"modules": []}')
            self.is_completed = True

        def get_full_text(self) -> str:
            return "".join(self._chunks)

    class FakeCrew:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def kickoff(self):
            return FakeStreamingOutput()

        def calculate_usage_metrics(self):
            return types.SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20)

    class FakeTask:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    module.Crew = FakeCrew
    module.Task = FakeTask

    usage_events = []
    step = PipelineStep(
        agent=object(),
        template_text="{name}",
        expected_output="json",
        output_file="",
        usage_callback=usage_events.append,
    )

    result = step.run(name="demo")

    assert result == '{"modules": []}'
    assert usage_events == [{"inputTokens": 12, "outputTokens": 8, "totalTokens": 20}]


def test_pipeline_step_run_falls_back_to_streamed_text_when_result_raw_is_missing():
    module = _load_pipeline_core_module()
    PipelineStep = module.PipelineStep

    class FakeStreamingOutput:
        def __init__(self) -> None:
            self.is_completed = False
            self._chunks = ["# Test", " Plan"]
            self.result = None

        def __iter__(self):
            for chunk in self._chunks:
                yield chunk
            self.result = types.SimpleNamespace(raw="")
            self.is_completed = True

        def get_full_text(self) -> str:
            return "".join(self._chunks)

    class FakeCrew:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def kickoff(self):
            return FakeStreamingOutput()

    class FakeTask:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    module.Crew = FakeCrew
    module.Task = FakeTask

    step = PipelineStep(
        agent=object(),
        template_text="{name}",
        expected_output="markdown",
        output_file="",
    )

    result = step.run(name="demo")

    assert result == "# Test Plan"


def test_pipeline_step_run_persists_output_file_with_normalized_text():
    module = _load_pipeline_core_module()
    PipelineStep = module.PipelineStep

    class FakeStreamingOutput:
        def __init__(self) -> None:
            self.is_completed = False
            self.result = None

        def __iter__(self):
            yield '{"modules": []}'
            self.result = types.SimpleNamespace(raw='{"modules": []}')
            self.is_completed = True

        def get_full_text(self) -> str:
            return '{"modules": []}'

    class FakeCrew:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def kickoff(self):
            return FakeStreamingOutput()

    class FakeTask:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    module.Crew = FakeCrew
    module.Task = FakeTask

    with tempfile.TemporaryDirectory() as temp_dir:
        output_path = Path(temp_dir) / "generated-project_test_plan.md"
        step = PipelineStep(
            agent=object(),
            template_text="{name}",
            expected_output="markdown",
            output_file=str(output_path),
        )

        result = step.run(name="demo")

        assert result == '{"modules": []}'
        assert output_path.read_text(encoding="utf-8") == '{"modules": []}'
