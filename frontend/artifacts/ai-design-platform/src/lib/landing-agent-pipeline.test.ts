import test from "node:test";
import assert from "node:assert/strict";

import {
  nextActiveIndex,
  PIPELINE_STAGE_COUNT,
  PIPELINE_STAGES,
  pipelineProgressPercent,
  resolveStageState,
} from "./landing-agent-pipeline.ts";

test("PIPELINE_STAGES describes the five delivery stages in execution order", () => {
  assert.deepEqual(
    PIPELINE_STAGES.map((stage) => stage.id),
    ["requirements", "architecture", "ui", "coding", "testing"],
  );
  assert.deepEqual(
    PIPELINE_STAGES.map((stage) => stage.index),
    [1, 2, 3, 4, 5],
  );
  assert.equal(PIPELINE_STAGE_COUNT, 5);
});

test("every stage declares at least one artifact so the section never renders an empty list", () => {
  for (const stage of PIPELINE_STAGES) {
    assert.ok(stage.artifactKeys.length > 0, `stage ${stage.id} has no artifacts`);
  }
});

test("resolveStageState marks earlier stages done, the current one running, later ones pending", () => {
  assert.equal(resolveStageState(1, 3), "done");
  assert.equal(resolveStageState(2, 3), "done");
  assert.equal(resolveStageState(3, 3), "running");
  assert.equal(resolveStageState(4, 3), "pending");
  assert.equal(resolveStageState(5, 3), "pending");
});

test("nextActiveIndex advances the demo loop and wraps back to the first stage", () => {
  assert.equal(nextActiveIndex(1), 2);
  assert.equal(nextActiveIndex(4), 5);
  assert.equal(nextActiveIndex(5), 1);
});

// 边界回归：阶段数为 0 时不能返回 0 或 NaN，否则演示动画会卡死在无效索引上。
test("nextActiveIndex stays on a valid index for degenerate stage counts", () => {
  assert.equal(nextActiveIndex(1, 0), 1);
  assert.equal(nextActiveIndex(1, 1), 1);
  assert.equal(nextActiveIndex(0, 5), 1);
});

test("pipelineProgressPercent reports completion and clamps out-of-range input", () => {
  assert.equal(pipelineProgressPercent(0), 0);
  assert.equal(pipelineProgressPercent(5), 100);
  assert.equal(pipelineProgressPercent(9), 100);
  assert.equal(pipelineProgressPercent(-3), 0);
  assert.equal(pipelineProgressPercent(2, 4), 50);
  assert.equal(pipelineProgressPercent(1, 0), 0);
});
