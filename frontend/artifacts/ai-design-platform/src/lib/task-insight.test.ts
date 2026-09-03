import test from "node:test";
import assert from "node:assert/strict";

import { buildTaskInsightModel } from "./task-insight.ts";

test("buildTaskInsightModel exposes analysis source, artifact sources, and context counts", () => {
  const model = buildTaskInsightModel({
    id: "task-1",
    projectId: "project-1",
    taskType: "modify",
    status: "completed",
    inputData: {},
    outputData: {
      analysisSource: "requirements_agent",
      artifactSources: {
        prd: { source: "requirements_agent", status: "completed" },
        ui: { source: "requirements_agent", status: "completed" },
        architecture: { source: "architecture_agent", status: "completed" },
        api_spec: { source: "requirements_agent", status: "completed", model: "moonshot/kimi-k2.5" },
      },
      contextSummary: {
        referenceFileCount: 2,
        selectedModuleCount: 3,
        existingArtifactCount: 4,
      },
    },
    parentTaskId: null,
    createdAt: "2026-03-30T00:00:00Z",
    startedAt: "2026-03-30T00:00:01Z",
    completedAt: "2026-03-30T00:00:10Z",
  });

  assert.equal(model.analysisSource, "requirements_agent");
  assert.equal(model.analysisReason, null);
  assert.equal(model.artifactSources.length, 4);
  assert.deepEqual(model.contextStats, [
    { id: "references", value: 2 },
    { id: "modules", value: 3 },
    { id: "existingArtifacts", value: 4 },
  ]);
});

test("buildTaskInsightModel falls back to empty values when task output is missing", () => {
  const model = buildTaskInsightModel(null);

  assert.equal(model.analysisSource, null);
  assert.equal(model.analysisReason, null);
  assert.deepEqual(model.artifactSources, []);
  assert.deepEqual(model.contextStats, [
    { id: "references", value: 0 },
    { id: "modules", value: 0 },
    { id: "existingArtifacts", value: 0 },
  ]);
});
