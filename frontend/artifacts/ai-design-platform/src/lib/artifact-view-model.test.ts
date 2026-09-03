import test from "node:test";
import assert from "node:assert/strict";

import {
  buildArtifactSections,
  buildArtifactSourceSummary,
  buildMessageTimeline,
  buildMessageTimelineWithPending,
  moveActiveConfirmationEntryToTail,
  buildArtifactEditPrompt,
  supportsDirectArtifactSave,
} from "./artifact-view-model.ts";

test("buildMessageTimeline nests artifact cards under their process log parent", () => {
  const timeline = buildMessageTimeline([
    {
      id: "m1",
      projectId: "p1",
      role: "agent",
      type: "process_log",
      content: "Generating the PRD draft...",
      createdAt: "2026-03-27T10:00:00Z",
    },
    {
      id: "m2",
      projectId: "p1",
      role: "agent",
      type: "artifact_card",
      content: "System PRD",
      parentId: "m1",
      createdAt: "2026-03-27T10:00:01Z",
      metadata: {
        artifactId: "a1",
        artifactType: "prd",
        title: "System PRD",
      },
    },
    {
      id: "m3",
      projectId: "p1",
      role: "user",
      type: "text",
      content: "Looks good",
      createdAt: "2026-03-27T10:00:02Z",
    },
  ]);

  assert.equal(timeline.length, 2);
  assert.equal(timeline[0]?.kind, "message");
  assert.equal(timeline[0]?.message.id, "m1");
  assert.equal(timeline[0]?.children.length, 1);
  assert.equal(timeline[0]?.children[0]?.id, "m2");
  assert.equal(timeline[1]?.kind, "message");
  assert.equal(timeline[1]?.message.id, "m3");
});

test("buildMessageTimeline keeps task rounds at the tail and groups process logs under them", () => {
  const timeline = buildMessageTimeline([
    {
      id: "u1",
      projectId: "p1",
      role: "user",
      type: "text",
      content: "Build a snake game",
      createdAt: "2026-03-31T10:00:00Z",
      metadata: {
        taskId: "task-1",
        taskRoundRole: "anchor",
      },
    },
    {
      id: "p1",
      projectId: "p1",
      role: "agent",
      type: "process_log",
      content: "Analyzing the requirement...",
      createdAt: "2026-03-31T10:00:01Z",
      metadata: {
        taskId: "task-1",
        taskName: "Analyzing requirements",
        status: "running",
      },
    },
    {
      id: "a1",
      projectId: "p1",
      role: "agent",
      type: "artifact_card",
      content: "PRD Draft",
      createdAt: "2026-03-31T10:00:02Z",
      parentId: "p1",
      metadata: {
        artifactId: "artifact-1",
        artifactType: "prd",
        title: "PRD Draft",
      },
    },
    {
      id: "c1",
      projectId: "p1",
      role: "agent",
      type: "select_options",
      content: "Please confirm the feature modules.",
      createdAt: "2026-03-31T10:00:03Z",
      metadata: {
        taskId: "task-1",
      },
    },
  ]);

  assert.equal(timeline.length, 3);
  assert.equal(timeline[0]?.kind, "message");
  assert.equal(timeline[0]?.message.id, "u1");
  assert.equal(timeline[1]?.kind, "message");
  assert.equal(timeline[1]?.message.id, "c1");
  assert.equal(timeline[2]?.kind, "task_round");
  assert.equal(timeline[2]?.taskId, "task-1");
  assert.equal(timeline[2]?.anchorMessage.id, "u1");
  assert.equal(timeline[2]?.logs.length, 1);
  assert.equal(timeline[2]?.logs[0]?.message.id, "p1");
  assert.equal(timeline[2]?.logs[0]?.children[0]?.id, "a1");
});

test("buildMessageTimelineWithPending inserts a provisional task round while the first backend logs are still missing", () => {
  const timeline = buildMessageTimelineWithPending([], {
    taskId: "task-1",
    prompt: "Build a snake game",
    createdAt: "2026-03-31T10:00:00Z",
  });

  assert.equal(timeline.length, 2);
  assert.equal(timeline[0]?.kind, "message");
  assert.equal(timeline[0]?.message.content, "Build a snake game");
  assert.equal(timeline[1]?.kind, "task_round");
  assert.equal(timeline[1]?.taskId, "task-1");
  assert.equal(timeline[1]?.logs.length, 1);
  assert.equal(timeline[1]?.logs[0]?.message.content, "Starting the task and preparing the first process log.");
});

test("buildMessageTimeline keeps a task round at the end even when newer messages arrive", () => {
  const timeline = buildMessageTimeline([
    {
      id: "u1",
      projectId: "p1",
      role: "user",
      type: "text",
      content: "Build a snake game",
      createdAt: "2026-03-31T10:00:00Z",
      metadata: {
        taskId: "task-1",
        taskRoundRole: "anchor",
      },
    },
    {
      id: "p1",
      projectId: "p1",
      role: "agent",
      type: "process_log",
      content: "Analyzing the requirement...",
      createdAt: "2026-03-31T10:00:01Z",
      metadata: {
        taskId: "task-1",
        taskName: "Analyzing requirements",
        status: "running",
      },
    },
    {
      id: "m2",
      projectId: "p1",
      role: "agent",
      type: "text",
      content: "Feature modules submitted.",
      createdAt: "2026-03-31T10:00:02Z",
    },
    {
      id: "m3",
      projectId: "p1",
      role: "system",
      type: "text",
      content: "Background generation continues.",
      createdAt: "2026-03-31T10:00:03Z",
    },
  ]);

  assert.equal(timeline.at(-1)?.kind, "task_round");
  assert.equal(timeline.at(-1)?.taskId, "task-1");
  assert.equal(timeline[1]?.kind, "message");
  assert.equal(timeline[1]?.message.id, "m2");
  assert.equal(timeline[2]?.kind, "message");
  assert.equal(timeline[2]?.message.id, "m3");
});

test("buildMessageTimeline normalizes out-of-order messages before pinning the task round to the end", () => {
  const timeline = buildMessageTimeline([
    {
      id: "m3",
      projectId: "p1",
      role: "system",
      type: "text",
      content: "Background generation continues.",
      createdAt: "2026-03-31T10:00:03Z",
    },
    {
      id: "p1",
      projectId: "p1",
      role: "agent",
      type: "process_log",
      content: "Analyzing the requirement...",
      createdAt: "2026-03-31T10:00:01Z",
      metadata: {
        taskId: "task-1",
        taskName: "Analyzing requirements",
        status: "running",
      },
    },
    {
      id: "u1",
      projectId: "p1",
      role: "user",
      type: "text",
      content: "Build a snake game",
      createdAt: "2026-03-31T10:00:00Z",
      metadata: {
        taskId: "task-1",
        taskRoundRole: "anchor",
      },
    },
    {
      id: "m2",
      projectId: "p1",
      role: "agent",
      type: "text",
      content: "Feature modules submitted.",
      createdAt: "2026-03-31T10:00:02Z",
    },
  ]);

  assert.equal(timeline[0]?.kind, "message");
  assert.equal(timeline[0]?.message.id, "u1");
  assert.equal(timeline[1]?.kind, "message");
  assert.equal(timeline[1]?.message.id, "m2");
  assert.equal(timeline[2]?.kind, "message");
  assert.equal(timeline[2]?.message.id, "m3");
  assert.equal(timeline[3]?.kind, "task_round");
  assert.equal(timeline[3]?.taskId, "task-1");
});

test("buildMessageTimeline folds failed system task messages into the matching task round", () => {
  const timeline = buildMessageTimeline([
    {
      id: "u1",
      projectId: "p1",
      role: "user",
      type: "text",
      content: "Build a sokoban game",
      createdAt: "2026-04-02T10:00:00Z",
      metadata: {
        taskId: "task-1",
        taskRoundRole: "anchor",
      },
    },
    {
      id: "p1",
      projectId: "p1",
      role: "agent",
      type: "process_log",
      content: "Analyzing the requirement...",
      createdAt: "2026-04-02T10:00:01Z",
      metadata: {
        taskId: "task-1",
        taskName: "Analyzing requirements",
        status: "running",
      },
    },
    {
      id: "s1",
      projectId: "p1",
      role: "system",
      type: "text",
      content: "Requirements Agent did not return a usable analysis result.",
      createdAt: "2026-04-02T10:00:02Z",
      metadata: {
        taskId: "task-1",
        taskStatus: "failed",
      },
    },
  ]);

  assert.equal(timeline.length, 2);
  assert.equal(timeline[0]?.kind, "message");
  assert.equal(timeline[1]?.kind, "task_round");
  assert.equal(timeline[1]?.statusMessage?.id, "s1");
});

test("buildMessageTimeline keeps only the newest log for the same task phase", () => {
  const timeline = buildMessageTimeline([
    {
      id: "u1",
      projectId: "p1",
      role: "user",
      type: "text",
      content: "Build gomoku",
      createdAt: "2026-04-07T09:30:00Z",
      metadata: {
        taskId: "task-1",
        taskRoundRole: "anchor",
      },
    },
    {
      id: "w1",
      projectId: "p1",
      role: "agent",
      type: "process_log",
      content: "Requirements drafts are ready.",
      createdAt: "2026-04-07T09:33:14Z",
      metadata: {
        taskId: "task-1",
        taskName: "Waiting for requirements draft review",
        phase: "waiting_for_requirements_artifact_review",
        status: "running",
      },
    },
    {
      id: "w2",
      projectId: "p1",
      role: "agent",
      type: "process_log",
      content: "Requirements drafts are ready again.",
      createdAt: "2026-04-07T09:34:13Z",
      metadata: {
        taskId: "task-1",
        taskName: "Waiting for requirements draft review",
        phase: "waiting_for_requirements_artifact_review",
        status: "running",
      },
    },
    {
      id: "a1",
      projectId: "p1",
      role: "agent",
      type: "process_log",
      content: "Generating use_case.md.",
      createdAt: "2026-04-07T09:37:14Z",
      metadata: {
        taskId: "task-1",
        taskName: "Generating architecture draft",
        phase: "architecture_generation_started",
        status: "running",
      },
    },
    {
      id: "a2",
      projectId: "p1",
      role: "agent",
      type: "process_log",
      content: "Generating analysis_task_output.txt.",
      createdAt: "2026-04-07T10:01:16Z",
      metadata: {
        taskId: "task-1",
        taskName: "Generating architecture draft",
        phase: "architecture_generation_started",
        status: "running",
      },
    },
  ]);

  const taskRound = timeline.at(-1);
  assert.equal(taskRound?.kind, "task_round");
  assert.equal(taskRound?.logs.length, 2);
  assert.equal(taskRound?.logs[0]?.message.id, "w2");
  assert.equal(taskRound?.logs[1]?.message.id, "a2");
});

test("buildMessageTimeline keeps different task phases even when their titles look similar", () => {
  const timeline = buildMessageTimeline([
    {
      id: "u1",
      projectId: "p1",
      role: "user",
      type: "text",
      content: "Build gomoku",
      createdAt: "2026-04-07T09:30:00Z",
      metadata: {
        taskId: "task-1",
        taskRoundRole: "anchor",
      },
    },
    {
      id: "r1",
      projectId: "p1",
      role: "agent",
      type: "process_log",
      content: "Requirements drafts are ready.",
      createdAt: "2026-04-07T09:33:14Z",
      metadata: {
        taskId: "task-1",
        taskName: "Waiting for requirements draft review",
        phase: "waiting_for_requirements_artifact_review",
        status: "running",
      },
    },
    {
      id: "r2",
      projectId: "p1",
      role: "agent",
      type: "process_log",
      content: "Generating architecture draft.",
      createdAt: "2026-04-07T09:37:14Z",
      metadata: {
        taskId: "task-1",
        taskName: "Generating architecture draft",
        phase: "architecture_generation_started",
        status: "running",
      },
    },
  ]);

  const taskRound = timeline.at(-1);
  assert.equal(taskRound?.kind, "task_round");
  assert.equal(taskRound?.logs.length, 2);
  assert.equal(taskRound?.logs[0]?.message.id, "r1");
  assert.equal(taskRound?.logs[1]?.message.id, "r2");
});

test("buildMessageTimelineWithPending keeps a retried pending round after the older failed round", () => {
  const timeline = buildMessageTimelineWithPending(
    [
      {
        id: "u1",
        projectId: "p1",
        role: "user",
        type: "text",
        content: "Build a sokoban game",
        createdAt: "2026-04-02T10:00:00Z",
        metadata: {
          taskId: "task-1",
          taskRoundRole: "anchor",
        },
      },
      {
        id: "p1",
        projectId: "p1",
        role: "agent",
        type: "process_log",
        content: "Analyzing the requirement...",
        createdAt: "2026-04-02T10:00:01Z",
        metadata: {
          taskId: "task-1",
          taskName: "Analyzing requirements",
          status: "running",
        },
      },
      {
        id: "s1",
        projectId: "p1",
        role: "system",
        type: "text",
        content: "Requirements Agent did not return a usable analysis result.",
        createdAt: "2026-04-02T10:00:02Z",
        metadata: {
          taskId: "task-1",
          taskStatus: "failed",
        },
      },
    ],
    {
      taskId: "task-2",
      prompt: "Build a sokoban game",
      createdAt: "2026-04-02T10:00:03Z",
    },
  );

  const taskRounds = timeline.filter((entry) => entry.kind === "task_round");
  assert.equal(taskRounds.length, 2);
  assert.equal(taskRounds[0]?.taskId, "task-1");
  assert.equal(taskRounds[1]?.taskId, "task-2");
});

test("moveActiveConfirmationEntryToTail keeps the current retry confirmation visible at the bottom", () => {
  const timeline = buildMessageTimelineWithPending(
    [
      {
        id: "u1",
        projectId: "p1",
        role: "user",
        type: "text",
        content: "开发一个五子棋游戏",
        createdAt: "2026-04-12T07:02:27.459198Z",
        metadata: {
          taskId: "task-1",
          taskRoundRole: "anchor",
        },
      },
      {
        id: "p1",
        projectId: "p1",
        role: "agent",
        type: "process_log",
        content: "正在分析需求并提取建议的功能模块。",
        createdAt: "2026-04-12T07:02:27.464420Z",
        metadata: {
          taskId: "task-1",
          taskName: "Analyzing requirements",
          status: "running",
        },
      },
      {
        id: "s1",
        projectId: "p1",
        role: "system",
        type: "text",
        content: "Requirements Agent did not return a usable analysis result.",
        createdAt: "2026-04-12T07:09:00.153348Z",
        metadata: {
          taskId: "task-1",
          taskStatus: "failed",
        },
      },
      {
        id: "u2",
        projectId: "p1",
        role: "user",
        type: "text",
        content: "开发一个五子棋游戏",
        createdAt: "2026-04-12T07:10:28.518045Z",
        metadata: {
          taskId: "task-2",
          taskRoundRole: "anchor",
        },
      },
      {
        id: "p2",
        projectId: "p1",
        role: "agent",
        type: "process_log",
        content: "已完成需求分析，并提取出建议的功能模块。",
        createdAt: "2026-04-12T07:10:28.521027Z",
        metadata: {
          taskId: "task-2",
          taskName: "Analyzing requirements",
          status: "running",
        },
      },
      {
        id: "confirm-2",
        projectId: "p1",
        role: "agent",
        type: "select_options",
        content: "请确认功能模块后继续。",
        createdAt: "2026-04-12T07:10:43.330371Z",
        metadata: {
          taskId: "task-2",
          taskStatus: "waiting_user",
          activePhase: "waiting_for_module_confirmation",
        },
      },
    ],
    null,
  );

  const reordered = moveActiveConfirmationEntryToTail(timeline, "confirm-2");

  assert.equal(reordered.at(-1)?.kind, "message");
  assert.equal(reordered.at(-1)?.message.id, "confirm-2");
  assert.deepEqual(
    reordered
      .filter((entry) => entry.kind === "task_round")
      .map((entry) => entry.taskId),
    ["task-1", "task-2"],
  );
});

test("buildArtifactSections returns no file sections while generation is still running and no agent file exists yet", () => {
  const sections = buildArtifactSections({
    tab: "prd",
    artifact: null,
    taskStatus: "running",
    progress: 20,
  });

  assert.equal(sections.length, 0);
});

test("buildArtifactSections ignores synthesized artifact records when no real agent file is available", () => {
  const sections = buildArtifactSections({
    tab: "prd",
    artifact: {
      id: "a1",
      projectId: "p1",
      version: 2,
      type: "prd",
      title: "PRD Draft",
      content: "# PRD Draft\n\n## Product Goal\nBuild a dashboard.\n\n## Core Modules\n- User System\n- Admin Console\n",
      sourceFiles: ["business_scope.md", "feature_tree.md"],
      sourceAgent: "requirements_agent",
      sourceStatus: "completed",
      createdAt: "2026-03-27T10:00:00Z",
    },
    taskStatus: "completed",
    progress: 100,
  });

  assert.deepEqual(sections, []);
});

test("buildArtifactSourceSummary exposes the real backend source metadata", () => {
  const source = buildArtifactSourceSummary({
    id: "a1",
    projectId: "p1",
    version: 2,
    type: "architecture",
    title: "Architecture Draft",
    content: "# Architecture",
    sourceFiles: ["component_design.json", "class_design_raw.md"],
    sourceAgent: "architecture_agent",
    sourceStatus: "completed",
    createdAt: "2026-03-27T10:00:00Z",
  });

  assert.deepEqual(source, {
    sourceAgent: "architecture_agent",
    sourceStatus: "completed",
    sourceFiles: ["component_design.json", "class_design_raw.md"],
    artifactKind: "synthesized",
    displayPath: "",
    rawSourceAvailable: false,
  });
});

test("buildArtifactSections keeps UI Pages empty even if older requirement docs still carry ui mappings", () => {
  const sections = buildArtifactSections({
    tab: "ui",
    artifact: null,
    taskStatus: "completed",
    progress: 100,
    rawArtifactsByAgent: {
      requirements_agent: [
        {
          id: "ui-1",
          projectId: "p1",
          version: 3,
          agent: "requirements_agent",
          fileName: "use_case.md",
          fileType: "markdown",
          contentType: "text/markdown",
          content: "# Use Case",
          isPrimarySource: true,
          mappedArtifactTypes: ["ui"],
          createdAt: "2026-03-31T10:00:00Z",
        },
      ],
    },
  });

  assert.deepEqual(sections, []);
});

test("buildArtifactSections ignores non-ui-agent planned files inside the UI tab", () => {
  const sections = buildArtifactSections({
    tab: "ui",
    artifact: null,
    taskStatus: "completed",
    progress: 100,
    plannedFiles: [
      {
        fileName: "feature_tree.md",
        label: "功能树",
        agent: "requirements_agent",
        mappedArtifactTypes: ["ui"],
        status: "completed",
        contentAvailable: true,
      },
      {
        fileName: "use_case.md",
        label: "用例文档",
        agent: "requirements_agent",
        mappedArtifactTypes: ["ui"],
        status: "completed",
        contentAvailable: true,
      },
    ],
    rawArtifactsByAgent: {
      requirements_agent: [
        {
          id: "ui-fallback-1",
          projectId: "p1",
          version: 3,
          agent: "requirements_agent",
          fileName: "feature_tree.md",
          fileType: "markdown",
          contentType: "text/markdown",
          content: "# Feature Tree",
          isPrimarySource: true,
          mappedArtifactTypes: ["ui"],
          createdAt: "2026-03-31T10:00:00Z",
        },
      ],
    },
  });

  assert.deepEqual(sections, []);
});

test("buildArtifactSections keeps planned PRD files visible before raw content is ready", () => {
  const sections = buildArtifactSections({
    tab: "prd",
    artifact: {
      id: "a1",
      projectId: "p1",
      version: 2,
      type: "prd",
      title: "PRD Draft",
      content: "# PRD Draft",
      sourceFiles: ["feature_tree.md", "SRS.md"],
      sourceAgent: "requirements_agent",
      sourceStatus: "completed",
      displayPath: "docs/PRD.md",
      rawSourceAvailable: true,
      createdAt: "2026-04-02T10:00:00Z",
    },
    taskStatus: "waiting_user",
    progress: 100,
    plannedFiles: [
      {
        fileName: "feature_tree.md",
        label: "功能树",
        agent: "requirements_agent",
        mappedArtifactTypes: ["prd"],
        status: "completed",
        contentAvailable: true,
      },
      {
        fileName: "SRS.md",
        label: "软件需求规格说明书",
        agent: "requirements_agent",
        mappedArtifactTypes: ["prd"],
        status: "completed",
        contentAvailable: true,
      },
      {
        fileName: "business_scope.md",
        label: "业务范围",
        agent: "requirements_agent",
        mappedArtifactTypes: ["prd"],
        status: "pending",
        contentAvailable: false,
      },
    ],
    rawArtifactsByAgent: {
      requirements_agent: [
        {
          id: "r1",
          projectId: "p1",
          version: 2,
          agent: "requirements_agent",
          fileName: "feature_tree.md",
          fileType: "markdown",
          contentType: "text/markdown",
          content: "# Feature Tree",
          isPrimarySource: true,
          mappedArtifactTypes: ["prd", "ui", "api_spec"],
          createdAt: "2026-04-02T10:00:01Z",
        },
        {
          id: "r2",
          projectId: "p1",
          version: 2,
          agent: "requirements_agent",
          fileName: "SRS.md",
          fileType: "markdown",
          contentType: "text/markdown",
          content: "# SRS",
          isPrimarySource: true,
          mappedArtifactTypes: ["prd"],
          createdAt: "2026-04-02T10:00:02Z",
        },
      ],
    },
  });

  assert.deepEqual(sections.map((section) => section.fileName), ["feature_tree.md", "SRS.md", "business_scope.md"]);
  assert.equal(sections[0]?.status, "completed");
  assert.equal(sections[1]?.content, "# SRS");
  assert.equal(sections[2]?.status, "pending");
  assert.equal(sections[2]?.content, "");
});

test("buildArtifactSections shows planned architecture files with pending status before content exists", () => {
  const sections = buildArtifactSections({
    tab: "arch",
    artifact: null,
    taskStatus: "waiting_user",
    progress: 100,
    plannedFiles: [
      {
        fileName: "component_design.json",
        label: "组件设计",
        agent: "architecture_agent",
        mappedArtifactTypes: ["architecture"],
        status: "pending",
        contentAvailable: false,
      },
      {
        fileName: "class_design_raw.md",
        label: "类设计",
        agent: "architecture_agent",
        mappedArtifactTypes: ["architecture"],
        status: "pending",
        contentAvailable: false,
      },
    ],
    rawArtifactsByAgent: {},
  });

  assert.deepEqual(sections.map((section) => section.fileName), ["component_design.json", "class_design_raw.md"]);
  assert.equal(sections[0]?.status, "pending");
  assert.equal(sections[1]?.status, "pending");
});

test("buildArtifactSections shows planned UI files instead of hiding the whole tab", () => {
  const sections = buildArtifactSections({
    tab: "ui",
    artifact: null,
    taskStatus: "completed",
    progress: 100,
    plannedFiles: [
      {
        fileName: "page_descriptions.md",
        label: "页面描述文档",
        agent: "ui_agent",
        mappedArtifactTypes: ["ui"],
        status: "completed",
        contentAvailable: true,
      },
    ],
    rawArtifactsByAgent: {
      ui_agent: [
        {
          id: "ui-doc-1",
          projectId: "p1",
          version: 1,
          agent: "ui_agent",
          fileName: "page_descriptions.md",
          fileType: "markdown",
          contentType: "text/markdown",
          content: "# 页面描述",
          isPrimarySource: true,
          mappedArtifactTypes: ["ui"],
          createdAt: "2026-04-02T10:00:00Z",
        },
      ],
    },
  });

  assert.deepEqual(sections.map((section) => section.fileName), ["page_descriptions.md"]);
  assert.equal(sections[0]?.status, "completed");
  assert.equal(sections[0]?.content, "# 页面描述");
});

test("buildArtifactSections keeps API tab focused on API files only", () => {
  const sections = buildArtifactSections({
    tab: "api",
    artifact: null,
    taskStatus: "completed",
    progress: 100,
    plannedFiles: [
      {
        fileName: "docs/API.yaml",
        label: "API 规格",
        agent: "coding_agent",
        mappedArtifactTypes: ["api_spec"],
        status: "completed",
        contentAvailable: true,
      },
      {
        fileName: "feature_tree.md",
        label: "功能树",
        agent: "requirements_agent",
        mappedArtifactTypes: ["api_spec"],
        status: "completed",
        contentAvailable: true,
      },
    ],
    rawArtifactsByAgent: {
      coding_agent: [
        {
          id: "api-1",
          projectId: "p1",
          version: 1,
          agent: "coding_agent",
          fileName: "docs/API.yaml",
          fileType: "yaml",
          contentType: "text/yaml",
          content: "openapi: 3.0.0\npaths: {}\n",
          isPrimarySource: false,
          mappedArtifactTypes: [],
          createdAt: "2026-04-02T10:00:00Z",
        },
      ],
      requirements_agent: [
        {
          id: "req-1",
          projectId: "p1",
          version: 1,
          agent: "requirements_agent",
          fileName: "feature_tree.md",
          fileType: "markdown",
          contentType: "text/markdown",
          content: "# Feature Tree",
          isPrimarySource: true,
          mappedArtifactTypes: ["api_spec"],
          createdAt: "2026-04-02T10:00:01Z",
        },
      ],
    },
  });

  assert.deepEqual(sections.map((section) => section.fileName), ["docs/API.yaml"]);
  assert.equal(sections[0]?.content, "openapi: 3.0.0\npaths: {}\n");
});

test("buildArtifactSections only returns real agent files when no synthesized artifact exists", () => {
  const sections = buildArtifactSections({
    tab: "prd",
    artifact: null,
    taskStatus: "waiting_user",
    progress: 100,
    plannedFiles: [
      {
        fileName: "survey.md",
        label: "需求背景调研",
        agent: "requirements_agent",
        mappedArtifactTypes: ["prd"],
        status: "completed",
        contentAvailable: true,
      },
      {
        fileName: "feature_tree.md",
        label: "功能树",
        agent: "requirements_agent",
        mappedArtifactTypes: ["prd"],
        status: "completed",
        contentAvailable: true,
      },
    ],
    rawArtifactsByAgent: {
      requirements_agent: [
        {
          id: "r1",
          projectId: "p1",
          version: 1,
          agent: "requirements_agent",
          fileName: "survey.md",
          fileType: "markdown",
          contentType: "text/markdown",
          content: "# Survey",
          isPrimarySource: true,
          mappedArtifactTypes: ["prd"],
          createdAt: "2026-04-02T10:00:00Z",
        },
        {
          id: "r2",
          projectId: "p1",
          version: 1,
          agent: "requirements_agent",
          fileName: "feature_tree.md",
          fileType: "markdown",
          contentType: "text/markdown",
          content: "# Feature Tree",
          isPrimarySource: true,
          mappedArtifactTypes: ["prd"],
          createdAt: "2026-04-02T10:00:01Z",
        },
      ],
    },
  });

  assert.deepEqual(sections.map((section) => section.fileName), ["survey.md", "feature_tree.md"]);
  assert.equal(sections[0]?.content, "# Survey");
  assert.equal(sections[1]?.content, "# Feature Tree");
});

test("buildArtifactSections preserves running and failed states from the backend plan", () => {
  const sections = buildArtifactSections({
    tab: "arch",
    artifact: null,
    taskStatus: "running",
    progress: 40,
    plannedFiles: [
      {
        fileName: "component_design.json",
        label: "组件设计",
        agent: "architecture_agent",
        mappedArtifactTypes: ["architecture"],
        status: "running",
        contentAvailable: false,
      },
      {
        fileName: "class_design_raw.md",
        label: "类设计",
        agent: "architecture_agent",
        mappedArtifactTypes: ["architecture"],
        status: "failed",
        contentAvailable: false,
      },
    ],
    rawArtifactsByAgent: {},
  });

  assert.equal(sections[0]?.status, "running");
  assert.equal(sections[1]?.status, "failed");
});

test("buildArtifactEditPrompt packages selected section edits into a modify request", () => {
  const prompt = buildArtifactEditPrompt({
    artifactLabel: "PRD",
    sectionLabel: "User Stories",
    originalContent: "## User Stories\nAs a manager, I want to create tasks.",
    editedContent: "## User Stories\nAs a manager, I want to create tasks with deadlines.",
  });

  assert.equal(prompt.includes("Update the PRD section `User Stories`"), true);
  assert.equal(prompt.includes("Original content"), true);
  assert.equal(prompt.includes("Updated content"), true);
  assert.equal(prompt.includes("deadlines"), true);
});

test("supportsDirectArtifactSave keeps all artifact edits on the modify flow", () => {
  assert.equal(supportsDirectArtifactSave("prd"), false);
  assert.equal(supportsDirectArtifactSave("ui"), false);
  assert.equal(supportsDirectArtifactSave("arch"), false);
  assert.equal(supportsDirectArtifactSave("api"), false);
});
