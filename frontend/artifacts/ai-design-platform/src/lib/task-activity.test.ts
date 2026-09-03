import test from "node:test";
import assert from "node:assert/strict";

import {
  getDisplayLiveActivityItems,
  getPrimaryLiveActivityItem,
  mergeLiveActivityItems,
  reduceLiveActivityEvent,
} from "./task-activity.ts";

test("reduceLiveActivityEvent turns agent_progress websocket payloads into activity rows", () => {
  const items = reduceLiveActivityEvent([], {
    type: "agent_progress",
    data: {
      id: "task-1:requirements_analysis:running",
      taskId: "task-1",
      phase: "requirements_analysis",
      status: "running",
      progress: 45,
      createdAt: "2026-03-30T10:00:00Z",
    },
  });

  assert.equal(items.length, 1);
  assert.deepEqual(items[0], {
    id: "task-1:requirements_analysis:running",
    taskId: "task-1",
    phase: "requirements_analysis",
    status: "running",
    progress: 45,
    createdAt: "2026-03-30T10:00:00Z",
    artifactType: null,
    agentName: null,
    outputHint: null,
    rawFileName: null,
    moduleCount: 0,
    referenceCount: 0,
  });
});

test("mergeLiveActivityItems de-duplicates by id and keeps the newest entries first", () => {
  const merged = mergeLiveActivityItems(
    [
      {
        id: "task-1:queued:running",
        taskId: "task-1",
        phase: "queued",
        status: "running",
        progress: 5,
        createdAt: "2026-03-30T10:00:00Z",
        artifactType: null,
        agentName: null,
        outputHint: null,
        rawFileName: null,
        moduleCount: 0,
        referenceCount: 0,
      },
    ],
    {
      id: "task-1:modules_ready:completed",
      taskId: "task-1",
      phase: "modules_ready",
      status: "completed",
      progress: 100,
      createdAt: "2026-03-30T10:00:05Z",
      artifactType: null,
      agentName: null,
      outputHint: null,
      rawFileName: null,
      moduleCount: 3,
      referenceCount: 1,
    },
  );

  const deduped = mergeLiveActivityItems(merged, {
    id: "task-1:queued:running",
    taskId: "task-1",
    phase: "queued",
    status: "running",
    progress: 5,
    createdAt: "2026-03-30T10:00:00Z",
    artifactType: null,
    agentName: null,
    outputHint: null,
    rawFileName: null,
    moduleCount: 0,
    referenceCount: 0,
  });

  assert.deepEqual(
    deduped.map((item) => item.id),
    ["task-1:modules_ready:completed", "task-1:queued:running"],
  );
});

test("reduceLiveActivityEvent completes earlier running phases when a newer phase arrives", () => {
  let items = reduceLiveActivityEvent([], {
    type: "agent_progress",
    data: {
      id: "task-1:queued:running",
      taskId: "task-1",
      phase: "queued",
      status: "running",
      progress: 5,
      createdAt: "2026-03-31T10:00:00Z",
    },
  });

  items = reduceLiveActivityEvent(items, {
    type: "agent_progress",
    data: {
      id: "task-1:reading_context:running",
      taskId: "task-1",
      phase: "reading_context",
      status: "running",
      progress: 15,
      createdAt: "2026-03-31T10:00:01Z",
    },
  });

  items = reduceLiveActivityEvent(items, {
    type: "agent_progress",
    data: {
      id: "task-1:requirements_analysis:running",
      taskId: "task-1",
      phase: "requirements_analysis",
      status: "running",
      progress: 35,
      createdAt: "2026-03-31T10:00:02Z",
    },
  });

  assert.deepEqual(
    items.map((item) => [item.phase, item.status, item.progress]),
    [
      ["requirements_analysis", "running", 35],
      ["reading_context", "completed", 100],
      ["queued", "completed", 100],
    ],
  );
});

test("reduceLiveActivityEvent treats requirements drafts and architecture generation as distinct later phases", () => {
  let items = reduceLiveActivityEvent([], {
    type: "agent_progress",
    data: {
      id: "task-1:requirements_drafts_started:running",
      taskId: "task-1",
      phase: "requirements_drafts_started",
      status: "running",
      progress: 48,
      createdAt: "2026-03-31T10:00:03Z",
    },
  });

  items = reduceLiveActivityEvent(items, {
    type: "agent_progress",
    data: {
      id: "task-1:architecture_generation_started:running",
      taskId: "task-1",
      phase: "architecture_generation_started",
      status: "running",
      progress: 72,
      createdAt: "2026-03-31T10:00:05Z",
    },
  });

  assert.deepEqual(
    items.map((item) => [item.phase, item.status]),
    [
      ["architecture_generation_started", "running"],
      ["requirements_drafts_started", "completed"],
    ],
  );
});

test("reduceLiveActivityEvent keeps the requirements review waiting phase between requirements and architecture", () => {
  let items = reduceLiveActivityEvent([], {
    type: "agent_progress",
    data: {
      id: "task-1:requirements_drafts_started:running",
      taskId: "task-1",
      phase: "requirements_drafts_started",
      status: "running",
      progress: 48,
      createdAt: "2026-04-02T10:00:03Z",
    },
  });

  items = reduceLiveActivityEvent(items, {
    type: "agent_progress",
    data: {
      id: "task-1:waiting_for_requirements_artifact_review:waiting",
      taskId: "task-1",
      phase: "waiting_for_requirements_artifact_review",
      status: "waiting",
      progress: 100,
      createdAt: "2026-04-02T10:00:04Z",
    },
  });

  assert.deepEqual(
    items.map((item) => [item.phase, item.status]),
    [
      ["waiting_for_requirements_artifact_review", "waiting"],
      ["requirements_drafts_started", "completed"],
    ],
  );
});

test("mergeLiveActivityItems drops bootstrap placeholders once real agent progress arrives", () => {
  const merged = mergeLiveActivityItems(
    [
      {
        id: "bootstrap:project-1:reading_context",
        taskId: "bootstrap:project-1",
        phase: "reading_context",
        status: "running",
        progress: 10,
        createdAt: "2026-03-31T10:00:00Z",
        artifactType: null,
        agentName: null,
        outputHint: null,
        rawFileName: null,
        moduleCount: 0,
        referenceCount: 0,
      },
      {
        id: "bootstrap:project-1:queued",
        taskId: "bootstrap:project-1",
        phase: "queued",
        status: "completed",
        progress: 0,
        createdAt: "2026-03-31T10:00:00Z",
        artifactType: null,
        agentName: null,
        outputHint: null,
        rawFileName: null,
        moduleCount: 0,
        referenceCount: 0,
      },
    ],
    {
      id: "task-1:queued:running",
      taskId: "task-1",
      phase: "queued",
      status: "running",
      progress: 5,
      createdAt: "2026-03-31T10:00:01Z",
      artifactType: null,
      agentName: null,
      outputHint: null,
      rawFileName: null,
      moduleCount: 0,
      referenceCount: 0,
    },
  );

  assert.deepEqual(
    merged.map((item) => item.id),
    ["task-1:queued:running"],
  );
});

test("getPrimaryLiveActivityItem prefers the latest active phase for the running banner", () => {
  const primary = getPrimaryLiveActivityItem([
    {
      id: "task-1:queued:running",
      taskId: "task-1",
      phase: "queued",
      status: "completed",
      progress: 100,
      createdAt: "2026-03-31T10:00:00Z",
      artifactType: null,
      agentName: null,
      outputHint: null,
      rawFileName: null,
      moduleCount: 0,
      referenceCount: 0,
    },
    {
      id: "task-1:requirements_analysis:running",
      taskId: "task-1",
      phase: "requirements_analysis",
      status: "running",
      progress: 54,
      createdAt: "2026-03-31T10:00:04Z",
      artifactType: null,
      agentName: null,
      outputHint: null,
      rawFileName: null,
      moduleCount: 0,
      referenceCount: 0,
    },
  ]);

  assert.equal(primary?.phase, "requirements_analysis");
  assert.equal(primary?.progress, 54);
});

test("getDisplayLiveActivityItems keeps the active step at the bottom of the timeline", () => {
  const ordered = getDisplayLiveActivityItems([
    {
      id: "task-1:requirements_analysis:running",
      taskId: "task-1",
      phase: "requirements_analysis",
      status: "running",
      progress: 54,
      createdAt: "2026-03-31T10:00:04Z",
      artifactType: null,
      agentName: null,
      outputHint: null,
      rawFileName: null,
      moduleCount: 0,
      referenceCount: 0,
    },
    {
      id: "task-1:queued:completed",
      taskId: "task-1",
      phase: "queued",
      status: "completed",
      progress: 100,
      createdAt: "2026-03-31T10:00:00Z",
      artifactType: null,
      agentName: null,
      outputHint: null,
      rawFileName: null,
      moduleCount: 0,
      referenceCount: 0,
    },
    {
      id: "task-1:reading_context:completed",
      taskId: "task-1",
      phase: "reading_context",
      status: "completed",
      progress: 100,
      createdAt: "2026-03-31T10:00:02Z",
      artifactType: null,
      agentName: null,
      outputHint: null,
      rawFileName: null,
      moduleCount: 0,
      referenceCount: 0,
    },
  ]);

  assert.deepEqual(
    ordered.map((item) => item.phase),
    ["queued", "reading_context", "requirements_analysis"],
  );
});
