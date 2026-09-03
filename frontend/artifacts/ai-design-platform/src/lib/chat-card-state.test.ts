import test from "node:test";
import assert from "node:assert/strict";

import { defaultCardExpanded, inferTaskRoundStatus, resolveLogCardStatus } from "./chat-card-state.ts";

test("inferTaskRoundStatus prefers the current task state", () => {
  const status = inferTaskRoundStatus({
    taskId: "task-1",
    currentTask: {
      id: "task-1",
      status: "failed",
    },
    logs: [
      {
        message: {
          metadata: {
            status: "running",
          },
        },
      },
    ],
  });

  assert.equal(status, "failed");
});

test("resolveLogCardStatus marks unfinished logs as failed when the task round failed", () => {
  const status = resolveLogCardStatus({
    logStatus: "running",
    taskRoundStatus: "failed",
  });

  assert.equal(status, "failed");
});

test("resolveLogCardStatus marks an older waiting phase as completed after the task moves into architecture", () => {
  const status = resolveLogCardStatus({
    logStatus: "waiting_user",
    logPhase: "waiting_for_requirements_artifact_review",
    currentActivePhase: "architecture_generation_started",
    taskRoundStatus: "running",
  });

  assert.equal(status, "completed");
});

test("resolveLogCardStatus marks an older running requirements phase as completed after the task advances", () => {
  const status = resolveLogCardStatus({
    logStatus: "running",
    logPhase: "requirements_drafts_started",
    currentActivePhase: "architecture_generation_started",
    taskRoundStatus: "running",
  });

  assert.equal(status, "completed");
});

test("resolveLogCardStatus keeps the current waiting phase active before the user confirms", () => {
  const status = resolveLogCardStatus({
    logStatus: "waiting_user",
    logPhase: "waiting_for_requirements_artifact_review",
    currentActivePhase: "waiting_for_requirements_artifact_review",
    taskRoundStatus: "waiting_user",
  });

  assert.equal(status, "running");
});

test("resolveLogCardStatus marks architecture review logs as completed after the task moves into test generation", () => {
  const status = resolveLogCardStatus({
    logStatus: "running",
    logPhase: "waiting_for_artifact_review",
    currentActivePhase: "test_generation_started",
    taskRoundStatus: "running",
  });

  assert.equal(status, "completed");
});

test("inferTaskRoundStatus uses the folded task status message when the current task is no longer active", () => {
  const status = inferTaskRoundStatus({
    taskId: "task-1",
    currentTask: null,
    logs: [
      {
        message: {
          metadata: {
            status: "running",
          },
        },
      },
    ],
    statusMessage: {
      metadata: {
        taskStatus: "failed",
      },
    },
  });

  assert.equal(status, "failed");
});

test("inferTaskRoundStatus treats a retry child task as the active running round for the original card", () => {
  const status = inferTaskRoundStatus({
    taskId: "task-cancelled",
    currentTask: {
      id: "task-retry",
      parentTaskId: "task-cancelled",
      status: "running",
    },
    logs: [
      {
        message: {
          metadata: {
            status: "failed",
          },
        },
      },
    ],
    statusMessage: {
      metadata: {
        taskStatus: "cancelled",
      },
    },
  });

  assert.equal(status, "running");
});

test("inferTaskRoundStatus treats a completed retry child task as the final status for the original card", () => {
  const status = inferTaskRoundStatus({
    taskId: "task-failed",
    currentTask: {
      id: "task-retry-success",
      parentTaskId: "task-failed",
      status: "completed",
    },
    logs: [
      {
        message: {
          metadata: {
            status: "failed",
          },
        },
      },
    ],
    statusMessage: {
      metadata: {
        taskStatus: "failed",
      },
    },
  });

  assert.equal(status, "completed");
});

test("default chat cards start collapsed", () => {
  assert.equal(defaultCardExpanded(), false);
});
