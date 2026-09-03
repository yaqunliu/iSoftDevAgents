from __future__ import annotations

import json
import re
from pathlib import Path

from agents.test_agent import (
    create_test_architect,
    create_test_designer,
    create_test_reviewer,
)
from config.config import config as loaded_config
from piplines.core import PipelineStep
from utils.dataset_utils import load_dataset
from utils.file_utils import read_file, write_file
from utils.memory_utils import Memory


class TestAgentApp:
    DEBUG_RUN = {1, 2, 3}
    MAX_REVIEW_ITERATIONS = 3

    def __init__(
        self,
        *,
        dataset_name: str,
        dataset_root: str | Path | None = None,
        output_root: str | Path | None = None,
        memory_root: str | Path | None = None,
        usage_callback=None,
    ) -> None:
        self.base_dir = Path(__file__).resolve().parent
        self.dataset_name = dataset_name
        if dataset_root is not None:
            loaded_config["dataset"]["root_path"] = str(dataset_root)
        self.data = load_dataset(dataset_name, strict=False)
        self.output_root = Path(output_root) if output_root is not None else self.base_dir / "output"
        self.memory_root = Path(memory_root) if memory_root is not None else self.base_dir / "memory"
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.memory_root.mkdir(parents=True, exist_ok=True)
        self.usage_callback = usage_callback
        self.usage_summary = {
            "inputTokens": 0,
            "outputTokens": 0,
            "totalTokens": 0,
        }

        self.test_architect = create_test_architect()
        self.test_designer = create_test_designer()
        self.test_reviewer = create_test_reviewer()
        self.cot1_desc = read_file(self.base_dir / "prompt" / "test_plan" / "test_plan.md")
        self.cot1_out = read_file(self.base_dir / "prompt" / "test_plan" / "test_plan_out.md")
        self.cot2_desc = read_file(self.base_dir / "prompt" / "test_design" / "test_design.md")
        self.cot2_out = read_file(self.base_dir / "prompt" / "test_design" / "test_design_out.md")
        self.cot3_desc = read_file(self.base_dir / "prompt" / "test_review" / "test_review.md")
        self.cot3_out = read_file(self.base_dir / "prompt" / "test_review" / "test_review_out.md")

    def _record_usage(self, usage_payload: dict | None) -> None:
        if not usage_payload:
            return
        self.usage_summary["inputTokens"] += int(usage_payload.get("inputTokens") or 0)
        self.usage_summary["outputTokens"] += int(usage_payload.get("outputTokens") or 0)
        self.usage_summary["totalTokens"] += int(usage_payload.get("totalTokens") or 0)
        if self.usage_callback is not None:
            self.usage_callback(dict(self.usage_summary))

    def _memory_file(self) -> Path:
        return self.memory_root / "test_plan.json"

    def _test_plan_output(self) -> Path:
        return self.output_root / f"{self.dataset_name}_test_plan.md"

    def _testcase_output(self) -> Path:
        return self.output_root / f"{self.dataset_name}_testcase.md"

    def run(self) -> None:
        print("\nStarting TestAgent Pipeline...\n")
        dataset = self.data

        if 1 in self.DEBUG_RUN:
            print("Step 1: Test planning...")
            step1 = PipelineStep(
                agent=self.test_architect,
                template_text=self.cot1_desc,
                expected_output=self.cot1_out,
                output_file=str(self._test_plan_output()),
                usage_callback=self._record_usage,
            )
            test_plan_raw = step1.run(
                srs=dataset.srs,
                add=dataset.architecture_design,
                class_diagram=dataset.uml_class,
                sequence_diagram=dataset.uml_sequence,
            )
            print(test_plan_raw)
            self._persist_test_plan(test_plan_raw)
            print("\nStep 1: Test planning completed\n")

        if 2 in self.DEBUG_RUN:
            memory_file = self._memory_file()
            if not memory_file.exists():
                print(f"\nError: {memory_file} not found!")
                return

            print("Step 2: Test design with review...")
            memory = Memory(str(memory_file))
            modules = memory.modules
            if not modules:
                print("Warning: No modules found in test plan. Nothing to test.")
                return

            step2 = PipelineStep(
                agent=self.test_designer,
                template_text=self.cot2_desc,
                expected_output=self.cot2_out,
                output_file="",
                usage_callback=self._record_usage,
            )
            step3 = PipelineStep(
                agent=self.test_reviewer,
                template_text=self.cot3_desc,
                expected_output=self.cot3_out,
                output_file="",
                usage_callback=self._record_usage,
            )

            testcase_file = self._testcase_output()
            for module_idx, module in enumerate(modules):
                print(f"\n{'=' * 60}")
                print(f"Processing Module {module_idx + 1}/{len(modules)}")
                print(f"{'=' * 60}\n")
                iteration = 0
                approved = False
                current_test_code = ""
                review_feedback = None

                while iteration < self.MAX_REVIEW_ITERATIONS and not approved:
                    iteration += 1
                    print(f"\n--- Iteration {iteration} ---")
                    designer_input = {"sut": module.to_json()}
                    if review_feedback:
                        designer_input["review_feedback"] = review_feedback
                        designer_input["previous_code"] = current_test_code

                    current_test_code = step2.run(**designer_input)
                    print("\n[Test Code Output]:")
                    print(current_test_code)

                    review_result_raw = step3.run(
                        sut=module.to_json(),
                        test_code=current_test_code,
                    )
                    print("\n[Review Result]:")
                    print(review_result_raw)

                    try:
                        review_result = self._parse_review(review_result_raw)
                    except json.JSONDecodeError:
                        write_file(path=testcase_file, content=current_test_code, overwrite=False)
                        break

                    status = review_result.get("status", "rejected")
                    modification_required = review_result.get("modification_required", True)
                    if status == "approved" and not modification_required:
                        approved = True
                        write_file(path=testcase_file, content=current_test_code, overwrite=False)
                    else:
                        review_feedback = review_result_raw
                        if iteration >= self.MAX_REVIEW_ITERATIONS:
                            write_file(path=testcase_file, content=current_test_code, overwrite=False)

            print("\n" + "=" * 60)
            print("Cot2 — Test design with review completed")
            print("=" * 60)

    def _persist_test_plan(self, test_plan_raw: str) -> None:
        memory_file = self._memory_file()
        try:
            payload = json.loads(test_plan_raw)
        except json.JSONDecodeError:
            match = re.search(r"```json\s*(.*?)\s*```", test_plan_raw, re.DOTALL)
            if match:
                payload = json.loads(match.group(1).strip())
            else:
                memory_file.write_text(test_plan_raw, encoding="utf-8")
                return
        memory_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _parse_review(self, raw_text: str) -> dict:
        match = re.search(r"\{[\s\S]*\}", raw_text)
        if match:
            return json.loads(match.group())
        return json.loads(raw_text)
