import test from "node:test";
import assert from "node:assert/strict";

import {
  buildAgentUsageBreakdown,
  buildExecutionStatsMeta,
  buildExecutionStatsSummary,
  buildTokenDisplay,
  buildStepUsageMeta,
  formatCompactTokenCount,
  resolveDisplayedDurationSeconds,
} from "./execution-stats.ts";

test("formatCompactTokenCount keeps values below one thousand unchanged", () => {
  assert.equal(formatCompactTokenCount(999), "999");
});

test("formatCompactTokenCount shortens thousands with k", () => {
  assert.equal(formatCompactTokenCount(1_000), "1k");
  assert.equal(formatCompactTokenCount(1_500), "1.5k");
});

test("formatCompactTokenCount shortens millions with M", () => {
  assert.equal(formatCompactTokenCount(1_000_000), "1M");
  assert.equal(formatCompactTokenCount(1_066_931), "1.1M");
});

test("formatCompactTokenCount caps large values at B", () => {
  assert.equal(formatCompactTokenCount(1_000_000_000), "1B");
  assert.equal(formatCompactTokenCount(1_500_000_000), "1.5B");
});

test("buildExecutionStatsMeta exposes model and directional token counts", () => {
  const meta = buildExecutionStatsMeta({
    totalDuration: 6.4,
    stepsCount: 3,
    itemsRead: 2,
    tokens: {
      input: 321,
      output: 654,
      total: 975,
    },
    cost: 0.12,
    model: "moonshot/kimi-k2.5",
    usageStatus: "reported",
    reportedSteps: 3,
    unreportedSteps: 0,
    agentUsage: [],
    startedAt: "2026-03-27T00:00:00Z",
    completedAt: "2026-03-27T00:00:06Z",
  });

  assert.deepEqual(meta, [
    { id: "model", value: "moonshot/kimi-k2.5" },
    { id: "inputTokens", value: "321", reason: null },
    { id: "outputTokens", value: "654", reason: null },
  ]);
});

test("buildExecutionStatsMeta shortens large directional token counts", () => {
  const meta = buildExecutionStatsMeta({
    totalDuration: 8.1,
    stepsCount: 4,
    itemsRead: 2,
    tokens: {
      input: 1_500,
      output: 1_066_931,
      total: 1_068_431,
    },
    cost: 0.24,
    model: "moonshot/kimi-k2.5",
    usageStatus: "reported",
    reportedSteps: 4,
    unreportedSteps: 0,
    agentUsage: [],
    startedAt: "2026-03-27T00:00:00Z",
    completedAt: "2026-03-27T00:00:08Z",
  });

  assert.deepEqual(meta, [
    { id: "model", value: "moonshot/kimi-k2.5" },
    { id: "inputTokens", value: "1.5k", reason: null },
    { id: "outputTokens", value: "1.1M", reason: null },
  ]);
});

test("buildTokenDisplay shows pending token usage as an explicit processing state", () => {
  const token = buildTokenDisplay({
    totalDuration: 80.7,
    stepsCount: 1,
    itemsRead: 1,
    tokens: {
      input: 0,
      output: 0,
      total: 0,
    },
    cost: 0,
    model: "moonshot/kimi-k2.5",
    usageStatus: "pending",
    reportedSteps: 0,
    unreportedSteps: 0,
    agentUsage: [],
    startedAt: "2026-03-31T00:00:00Z",
    completedAt: null,
  });

  assert.deepEqual(token, {
    value: "Processing",
    reason: "usage_pending",
  });
});

test("buildExecutionStatsMeta labels unreported token usage explicitly", () => {
  const meta = buildExecutionStatsMeta({
    totalDuration: 80.7,
    stepsCount: 1,
    itemsRead: 1,
    tokens: {
      input: 0,
      output: 0,
      total: 0,
    },
    cost: 0,
    model: "moonshot/kimi-k2.5",
    usageStatus: "unreported",
    reportedSteps: 0,
    unreportedSteps: 1,
    agentUsage: [],
    startedAt: "2026-03-31T00:00:00Z",
    completedAt: "2026-03-31T00:01:20Z",
  });

  assert.deepEqual(meta, [
    { id: "model", value: "moonshot/kimi-k2.5" },
    { id: "inputTokens", value: "Unreported", reason: "usage_unreported" },
    { id: "outputTokens", value: "Unreported", reason: "usage_unreported" },
  ]);
});

test("buildExecutionStatsSummary keeps total tokens visible in the collapsed card state", () => {
  const summary = buildExecutionStatsSummary({
    totalDuration: 378.7,
    stepsCount: 1,
    itemsRead: 1,
    tokens: {
      input: 0,
      output: 0,
      total: 0,
    },
    cost: 0,
    model: "MiniMax-M2.7-highspeed",
    usageStatus: "unreported",
    reportedSteps: 0,
    unreportedSteps: 1,
    agentUsage: [],
    startedAt: "2026-04-02T04:51:41Z",
    completedAt: null,
  });

  assert.deepEqual(summary, {
    duration: "378.7s",
    steps: "1",
    items: "1",
    tokens: {
      value: "Unreported",
      reason: "usage_unreported",
    },
  });
});

test("resolveDisplayedDurationSeconds keeps growing while the task is still running", () => {
  const duration = resolveDisplayedDurationSeconds(
    {
      totalDuration: 27.9,
      stepsCount: 1,
      itemsRead: 1,
      tokens: {
        input: 0,
        output: 0,
        total: 0,
      },
      cost: 0,
      model: "moonshot/kimi-k2.5",
      usageStatus: "pending",
      reportedSteps: 0,
      unreportedSteps: 1,
      agentUsage: [],
      startedAt: "2026-04-09T08:00:00.000Z",
      completedAt: null,
    },
    Date.parse("2026-04-09T08:00:32.400Z"),
  );

  assert.equal(duration, 32.4);
});

test("buildTokenDisplay keeps streamed token counts visible even before final usage reconciliation", () => {
  const token = buildTokenDisplay({
    totalDuration: 42.3,
    stepsCount: 2,
    itemsRead: 1,
    tokens: {
      input: 120,
      output: 88,
      total: 208,
    },
    cost: 0.03,
    model: "moonshot/kimi-k2.5",
    usageStatus: "unreported",
    reportedSteps: 0,
    unreportedSteps: 1,
    agentUsage: [],
    startedAt: "2026-04-07T00:00:00Z",
    completedAt: null,
  });

  assert.deepEqual(token, {
    value: "208",
    reason: null,
  });
});

test("buildTokenDisplay shortens large streamed token counts", () => {
  const token = buildTokenDisplay({
    totalDuration: 42.3,
    stepsCount: 2,
    itemsRead: 1,
    tokens: {
      input: 500_000,
      output: 566_931,
      total: 1_066_931,
    },
    cost: 0.03,
    model: "moonshot/kimi-k2.5",
    usageStatus: "unreported",
    reportedSteps: 0,
    unreportedSteps: 1,
    agentUsage: [],
    startedAt: "2026-04-07T00:00:00Z",
    completedAt: null,
  });

  assert.deepEqual(token, {
    value: "1.1M",
    reason: null,
  });
});

test("buildAgentUsageBreakdown keeps per-agent reported and pending token states visible", () => {
  const breakdown = buildAgentUsageBreakdown({
    agentUsage: [
      {
        agent: "requirements_agent",
        totalTokens: 12_345,
        cost: 0.12,
        model: "moonshot/kimi-k2.5",
        usageStatus: "reported",
      },
      {
        agent: "test_agent",
        totalTokens: 0,
        cost: 0,
        model: "moonshot/kimi-k2.5",
        usageStatus: "pending",
      },
    ],
  });

  assert.deepEqual(breakdown, [
    {
      agent: "requirements_agent",
      token: {
        value: "12.3k",
        reason: null,
      },
      cost: 0.12,
      model: "moonshot/kimi-k2.5",
      usageStatus: "reported",
    },
    {
      agent: "test_agent",
      token: {
        value: "Processing",
        reason: "usage_pending",
      },
      cost: 0,
      model: "moonshot/kimi-k2.5",
      usageStatus: "pending",
    },
  ]);
});

test("buildStepUsageMeta exposes per-step token status, model, and source agent", () => {
  const step = buildStepUsageMeta({
    id: "step-1",
    stepName: "Generate code workspace",
    stepType: "generation",
    duration: 12.5,
    tokensUsed: 0,
    cost: 0,
    status: "completed",
    createdAt: "2026-03-31T00:00:20Z",
    metadata: {
      usageStatus: "unreported",
      model: "moonshot/kimi-k2.5",
      sourceAgent: "coding_agent",
    },
  });

  assert.deepEqual(step, {
    token: {
      value: "Unreported",
      reason: "usage_unreported",
    },
    model: "moonshot/kimi-k2.5",
    sourceAgent: "coding_agent",
    usageStatus: "unreported",
    outputFiles: [],
  });
});

test("buildStepUsageMeta prefers concrete step tokens over stale unreported metadata", () => {
  const step = buildStepUsageMeta({
    id: "step-2",
    stepName: "Generate requirements drafts",
    stepType: "generation",
    duration: 55.2,
    tokensUsed: 512,
    cost: 0.07,
    status: "completed",
    createdAt: "2026-04-07T00:05:20Z",
    metadata: {
      usageStatus: "unreported",
      model: "moonshot/kimi-k2.5",
      sourceAgent: "requirements_agent",
    },
  });

  assert.deepEqual(step, {
    token: {
      value: "512",
      reason: null,
    },
    model: "moonshot/kimi-k2.5",
    sourceAgent: "requirements_agent",
    usageStatus: "reported",
    outputFiles: [],
  });
});

test("buildStepUsageMeta shortens large per-step token counts", () => {
  const step = buildStepUsageMeta({
    id: "step-3",
    stepName: "Generate architecture draft",
    stepType: "generation",
    duration: 89.2,
    tokensUsed: 1_000_000_000,
    cost: 0.27,
    status: "completed",
    createdAt: "2026-04-07T00:10:20Z",
    metadata: {
      usageStatus: "reported",
      model: "moonshot/kimi-k2.5",
      sourceAgent: "architecture_agent",
    },
  });

  assert.deepEqual(step, {
    token: {
      value: "1B",
      reason: null,
    },
    model: "moonshot/kimi-k2.5",
    sourceAgent: "architecture_agent",
    usageStatus: "reported",
    outputFiles: [],
  });
});
