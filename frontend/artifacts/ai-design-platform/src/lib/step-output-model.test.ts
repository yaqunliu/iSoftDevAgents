import test from "node:test";
import assert from "node:assert/strict";

import { buildStepOutputGroups, findStepOutputGroupForLog } from "./step-output-model.ts";

test("buildStepOutputGroups keeps requirements analysis outputs and prioritizes feature_tree.md", () => {
  const steps = [
    {
      id: "step-1",
      stepName: "Analyze requirements",
      stepType: "process_log" as const,
      duration: 12,
      tokensUsed: 0,
      cost: 0,
      status: "completed" as const,
      createdAt: "2026-04-01T00:00:00Z",
      metadata: {
        sourceAgent: "requirements_agent",
        outputFiles: ["project_description.md", "feature_tree.md"],
      },
    },
  ];

  const artifactsByAgent = {
    requirements_agent: [
      {
        id: "artifact-1",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "requirements_agent",
        fileName: "project_description.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Project Description",
        isPrimarySource: false,
        mappedArtifactTypes: [],
        createdAt: "2026-04-01T00:00:00Z",
      },
      {
        id: "artifact-2",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "requirements_agent",
        fileName: "feature_tree.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Feature Tree\n\n- Board System",
        isPrimarySource: true,
        mappedArtifactTypes: ["prd", "ui"],
        createdAt: "2026-04-01T00:00:01Z",
      },
    ],
  };

  const groups = buildStepOutputGroups(steps, artifactsByAgent);

  assert.equal(groups.length, 1);
  assert.equal(groups[0]?.files.length, 2);
  assert.equal(groups[0]?.primaryFile?.fileName, "feature_tree.md");
  assert.equal(groups[0]?.files[0]?.fileName, "feature_tree.md");
});

test("findStepOutputGroupForLog matches requirements analysis logs to the analysis output group", () => {
  const steps = [
    {
      id: "step-1",
      stepName: "Analyze requirements",
      stepType: "process_log" as const,
      duration: 12,
      tokensUsed: 0,
      cost: 0,
      status: "completed" as const,
      createdAt: "2026-04-01T00:00:00Z",
      metadata: {
        sourceAgent: "requirements_agent",
        outputFiles: ["feature_tree.md"],
      },
    },
  ];

  const artifactsByAgent = {
    requirements_agent: [
      {
        id: "artifact-2",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "requirements_agent",
        fileName: "feature_tree.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Feature Tree\n\n- Board System",
        isPrimarySource: true,
        mappedArtifactTypes: ["prd", "ui"],
        createdAt: "2026-04-01T00:00:01Z",
      },
    ],
  };

  const group = findStepOutputGroupForLog(
    {
      id: "log-1",
      projectId: "project-1",
      role: "agent",
      type: "process_log",
      content: "Analyzed the requirement and extracted the suggested feature modules.",
      createdAt: "2026-04-01T00:00:02Z",
      metadata: {
        taskName: "Analyzing requirements",
        phase: "requirements_analysis",
        status: "completed",
      },
    },
    steps,
    artifactsByAgent,
  );

  assert.ok(group);
  assert.equal(group?.stepId, "step-1");
  assert.equal(group?.primaryFile?.fileName, "feature_tree.md");
});

test("buildStepOutputGroups includes coding agent files for code generation steps", () => {
  const steps = [
    {
      id: "step-2",
      stepName: "Generate code workspace",
      stepType: "generation" as const,
      duration: 45,
      tokensUsed: 0,
      cost: 0,
      status: "completed" as const,
      createdAt: "2026-04-01T00:01:00Z",
      metadata: {
        sourceAgent: "coding_agent",
        outputFiles: ["frontend/src/App.tsx", "frontend/src/lib/gomoku.ts"],
      },
    },
  ];

  const artifactsByAgent = {
    coding_agent: [
      {
        id: "artifact-3",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "coding_agent",
        fileName: "frontend/src/App.tsx",
        fileType: "tsx",
        contentType: "text/plain",
        content: "export function App() { return null; }",
        isPrimarySource: false,
        mappedArtifactTypes: [],
        createdAt: "2026-04-01T00:01:01Z",
      },
      {
        id: "artifact-4",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "coding_agent",
        fileName: "frontend/src/lib/gomoku.ts",
        fileType: "ts",
        contentType: "text/plain",
        content: "export const boardSize = 15;",
        isPrimarySource: false,
        mappedArtifactTypes: [],
        createdAt: "2026-04-01T00:01:02Z",
      },
    ],
  };

  const groups = buildStepOutputGroups(steps, artifactsByAgent);

  assert.equal(groups.length, 1);
  assert.equal(groups[0]?.files.length, 2);
  assert.equal(groups[0]?.primaryFile?.fileName, "frontend/src/App.tsx");
});

test("findStepOutputGroupForLog prefers the process log outputFiles over an earlier unrelated step", () => {
  const steps = [
    {
      id: "step-1",
      stepName: "Analyze requirements",
      stepType: "process_log" as const,
      duration: 12,
      tokensUsed: 0,
      cost: 0,
      status: "completed" as const,
      createdAt: "2026-04-01T00:00:00Z",
      metadata: {
        sourceAgent: "requirements_agent",
        outputFiles: ["feature_tree.md", "project_description.md"],
      },
    },
  ];

  const artifactsByAgent = {
    requirements_agent: [
      {
        id: "artifact-2",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "requirements_agent",
        fileName: "feature_tree.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Feature Tree",
        isPrimarySource: true,
        mappedArtifactTypes: ["prd", "ui"],
        createdAt: "2026-04-01T00:00:01Z",
      },
      {
        id: "artifact-3",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "requirements_agent",
        fileName: "draft_context_diagram.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Context Diagram",
        isPrimarySource: false,
        mappedArtifactTypes: [],
        createdAt: "2026-04-01T00:01:01Z",
      },
      {
        id: "artifact-4",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "requirements_agent",
        fileName: "draft_event_list.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Event List",
        isPrimarySource: false,
        mappedArtifactTypes: [],
        createdAt: "2026-04-01T00:01:02Z",
      },
    ],
  };

  const group = findStepOutputGroupForLog(
    {
      id: "log-2",
      projectId: "project-1",
      role: "agent",
      type: "process_log",
      content: "Generating draft_event_list.md.",
      createdAt: "2026-04-01T00:01:05Z",
      metadata: {
        taskName: "Generating core artifacts",
        phase: "artifact_generation_started",
        status: "running",
        sourceAgent: "requirements_agent",
        outputFiles: ["draft_context_diagram.md", "draft_event_list.md"],
      },
    },
    steps,
    artifactsByAgent,
  );

  assert.ok(group);
  assert.equal(group?.stepId, "log:log-2");
  assert.deepEqual(
    new Set(group?.files.map((file) => file.fileName)),
    new Set(["draft_context_diagram.md", "draft_event_list.md"]),
  );
});

test("findStepOutputGroupForLog keeps the full live output file list for artifact-generation logs", () => {
  const steps = [
    {
      id: "step-1",
      stepName: "Analyze requirements",
      stepType: "process_log" as const,
      duration: 12,
      tokensUsed: 0,
      cost: 0,
      status: "completed" as const,
      createdAt: "2026-04-01T00:00:00Z",
      metadata: {
        sourceAgent: "requirements_agent",
        outputFiles: ["feature_tree.md", "project_description.md"],
      },
    },
  ];

  const artifactsByAgent = {
    requirements_agent: [
      {
        id: "artifact-1",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "requirements_agent",
        fileName: "feature_tree.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Feature Tree",
        isPrimarySource: true,
        mappedArtifactTypes: ["prd"],
        createdAt: "2026-04-01T00:00:01Z",
      },
      {
        id: "artifact-2",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "requirements_agent",
        fileName: "business_scope.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Business Scope",
        isPrimarySource: true,
        mappedArtifactTypes: ["prd"],
        createdAt: "2026-04-01T00:01:01Z",
      },
    ],
  };

  const group = findStepOutputGroupForLog(
    {
      id: "log-3",
      projectId: "project-1",
      role: "agent",
      type: "process_log",
      content: "Generating business_scope.md.",
      createdAt: "2026-04-01T00:01:05Z",
      metadata: {
        taskName: "Generating requirements drafts",
        phase: "requirements_drafts_started",
        status: "running",
        sourceAgent: "requirements_agent",
        outputFiles: ["feature_tree.md", "business_scope.md"],
      },
    },
    steps,
    artifactsByAgent,
  );

  assert.ok(group);
  assert.deepEqual(
    new Set(group?.files.map((file) => file.fileName)),
    new Set(["feature_tree.md", "business_scope.md"]),
  );
});

test("findStepOutputGroupForLog keeps repeated files when the live requirements log grows across the same phase", () => {
  const steps = [
    {
      id: "step-1",
      stepName: "Analyze requirements",
      stepType: "process_log" as const,
      duration: 12,
      tokensUsed: 0,
      cost: 0,
      status: "completed" as const,
      createdAt: "2026-04-01T00:00:00Z",
      metadata: {
        sourceAgent: "requirements_agent",
        outputFiles: ["feature_tree.md"],
      },
    },
  ];

  const artifactsByAgent = {
    requirements_agent: [
      {
        id: "artifact-1",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "requirements_agent",
        fileName: "feature_tree.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Feature Tree",
        isPrimarySource: true,
        mappedArtifactTypes: ["prd"],
        createdAt: "2026-04-01T00:00:01Z",
      },
      {
        id: "artifact-2",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "requirements_agent",
        fileName: "survey.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Survey",
        isPrimarySource: false,
        mappedArtifactTypes: [],
        createdAt: "2026-04-01T00:01:01Z",
      },
      {
        id: "artifact-3",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "requirements_agent",
        fileName: "business_scope.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Business Scope",
        isPrimarySource: true,
        mappedArtifactTypes: ["prd"],
        createdAt: "2026-04-01T00:01:02Z",
      },
      {
        id: "artifact-4",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "requirements_agent",
        fileName: "draft_context_diagram.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Context Diagram",
        isPrimarySource: false,
        mappedArtifactTypes: [],
        createdAt: "2026-04-01T00:01:03Z",
      },
    ],
  };

  const group = findStepOutputGroupForLog(
    {
      id: "log-4",
      projectId: "project-1",
      role: "agent",
      type: "process_log",
      content: "已生成 survey.md。",
      createdAt: "2026-04-01T00:01:05Z",
      metadata: {
        taskName: "生成需求草稿文件",
        phase: "requirements_drafts_started",
        status: "running",
        sourceAgent: "requirements_agent",
        outputFiles: ["feature_tree.md", "survey.md", "business_scope.md", "draft_context_diagram.md"],
      },
    },
    steps,
    artifactsByAgent,
  );

  assert.ok(group);
  assert.deepEqual(
    new Set(group?.files.map((file) => file.fileName)),
    new Set(["feature_tree.md", "survey.md", "business_scope.md", "draft_context_diagram.md"]),
  );
});

test("findStepOutputGroupForLog does not borrow requirements outputs for architecture live logs", () => {
  const steps = [
    {
      id: "step-1",
      stepName: "Generate feature modules",
      stepType: "process_log" as const,
      duration: 12,
      tokensUsed: 0,
      cost: 0,
      status: "completed" as const,
      createdAt: "2026-04-03T00:00:00Z",
      metadata: {
        sourceAgent: "requirements_agent",
        outputFiles: ["feature_tree.md"],
      },
    },
  ];

  const artifactsByAgent = {
    requirements_agent: [
      {
        id: "artifact-feature-tree",
        projectId: "project-1",
        version: 1,
        taskId: "task-1",
        agent: "requirements_agent",
        fileName: "feature_tree.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Feature Tree",
        isPrimarySource: true,
        mappedArtifactTypes: ["prd", "ui"],
        createdAt: "2026-04-03T00:00:01Z",
      },
    ],
  };

  const group = findStepOutputGroupForLog(
    {
      id: "log-architecture",
      projectId: "project-1",
      role: "agent",
      type: "process_log",
      content: "Generating architecture draft.",
      createdAt: "2026-04-03T00:00:05Z",
      metadata: {
        taskName: "Generate architecture draft",
        phase: "architecture_generation_started",
        status: "running",
        sourceAgent: "architecture_agent",
      },
    },
    steps,
    artifactsByAgent,
  );

  assert.equal(group, null);
});
