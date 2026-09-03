import test from "node:test";
import assert from "node:assert/strict";

import { buildProjectWebSocketQueryPlan } from "./project-websocket-events.ts";

test("waiting confirmation events force immediate chat and current-task refetch", () => {
  assert.deepEqual(buildProjectWebSocketQueryPlan("agent_require_action"), {
    invalidateChat: true,
    invalidateCurrentTask: true,
    refetchChatNow: true,
    refetchCurrentTaskNow: true,
  });

  assert.deepEqual(buildProjectWebSocketQueryPlan("task_waiting_for_user"), {
    invalidateChat: true,
    invalidateCurrentTask: true,
    refetchChatNow: true,
    refetchCurrentTaskNow: true,
  });
});

test("ordinary status updates still refresh current task without forced chat refetch", () => {
  assert.deepEqual(buildProjectWebSocketQueryPlan("status_change"), {
    invalidateChat: false,
    invalidateCurrentTask: true,
    refetchChatNow: false,
    refetchCurrentTaskNow: false,
  });
});

test("ordinary chat messages refresh chat without forced current-task refetch", () => {
  assert.deepEqual(buildProjectWebSocketQueryPlan("message"), {
    invalidateChat: true,
    invalidateCurrentTask: false,
    refetchChatNow: false,
    refetchCurrentTaskNow: false,
  });
});

test("interaction card messages also force immediate current-task refetch", () => {
  assert.deepEqual(
    buildProjectWebSocketQueryPlan("message", {
      type: "select_options",
      metadata: {
        confirmationKind: "artifact_review",
      },
    }),
    {
      invalidateChat: true,
      invalidateCurrentTask: true,
      refetchChatNow: true,
      refetchCurrentTaskNow: true,
    },
  );

  assert.deepEqual(
    buildProjectWebSocketQueryPlan("message", {
      type: "input_form",
      metadata: {
        confirmationKind: "requirements_feedback",
      },
    }),
    {
      invalidateChat: true,
      invalidateCurrentTask: true,
      refetchChatNow: true,
      refetchCurrentTaskNow: true,
    },
  );
});
