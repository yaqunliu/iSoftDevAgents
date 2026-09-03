import test from "node:test";
import assert from "node:assert/strict";

import {
  buildAgentOutputItems,
  buildArtifactPanelDocGroups,
  findPreferredAgentOutput,
  REQUIREMENTS_OUTPUT_PRIORITY,
} from "./agent-output-view.ts";

test("buildAgentOutputItems prioritizes key requirements outputs before the remaining files", () => {
  const items = buildAgentOutputItems(
    {
      requirements_agent: [
        {
          id: "a3",
          projectId: "p1",
          version: 1,
          agent: "requirements_agent",
          fileName: "draft_context_diagram.md",
          fileType: "markdown",
          contentType: "text/markdown",
          content: "# Context",
          isPrimarySource: false,
          mappedArtifactTypes: [],
          createdAt: "2026-04-01T10:00:03Z",
        },
        {
          id: "a2",
          projectId: "p1",
          version: 1,
          agent: "requirements_agent",
          fileName: "survey.md",
          fileType: "markdown",
          contentType: "text/markdown",
          content: "# Survey",
          isPrimarySource: false,
          mappedArtifactTypes: [],
          createdAt: "2026-04-01T10:00:02Z",
        },
        {
          id: "a1",
          projectId: "p1",
          version: 1,
          agent: "requirements_agent",
          fileName: "feature_tree.md",
          fileType: "markdown",
          contentType: "text/markdown",
          content: "# Feature Tree",
          isPrimarySource: true,
          mappedArtifactTypes: ["prd"],
          createdAt: "2026-04-01T10:00:01Z",
        },
        {
          id: "a4",
          projectId: "p1",
          version: 1,
          agent: "requirements_agent",
          fileName: "use_case.md",
          fileType: "markdown",
          contentType: "text/markdown",
          content: "# Use Case",
          isPrimarySource: true,
          mappedArtifactTypes: ["prd", "ui"],
          createdAt: "2026-04-01T10:00:04Z",
        },
      ],
    },
    "requirements_agent",
    REQUIREMENTS_OUTPUT_PRIORITY,
  );

  assert.deepEqual(
    items.map((item) => item.artifact.fileName),
    ["feature_tree.md", "survey.md", "draft_context_diagram.md", "use_case.md"],
  );
});

test("findPreferredAgentOutput returns the top prioritized requirements file", () => {
  const item = findPreferredAgentOutput(
    {
      requirements_agent: [
        {
          id: "a1",
          projectId: "p1",
          version: 1,
          agent: "requirements_agent",
          fileName: "survey.md",
          fileType: "markdown",
          contentType: "text/markdown",
          content: "# Survey",
          isPrimarySource: false,
          mappedArtifactTypes: [],
          createdAt: "2026-04-01T10:00:01Z",
        },
        {
          id: "a2",
          projectId: "p1",
          version: 1,
          agent: "requirements_agent",
          fileName: "feature_tree.md",
          fileType: "markdown",
          contentType: "text/markdown",
          content: "# Feature Tree",
          isPrimarySource: true,
          mappedArtifactTypes: ["prd"],
          createdAt: "2026-04-01T10:00:02Z",
        },
      ],
    },
    "requirements_agent",
    REQUIREMENTS_OUTPUT_PRIORITY,
  );

  assert.equal(item?.artifact.fileName, "feature_tree.md");
});

test("buildArtifactPanelDocGroups keeps requirements and architecture docs visible for the artifact panel", () => {
  const groups = buildArtifactPanelDocGroups({
    coding_agent: [
      {
        id: "c1",
        projectId: "p1",
        version: 1,
        agent: "coding_agent",
        fileName: "frontend/App.tsx",
        fileType: "tsx",
        contentType: "text/plain",
        content: "export function App() {}",
        isPrimarySource: false,
        mappedArtifactTypes: [],
        createdAt: "2026-04-01T10:00:05Z",
      },
    ],
    architecture_agent: [
      {
        id: "a1",
        projectId: "p1",
        version: 1,
        agent: "architecture_agent",
        fileName: "class_design_raw.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Classes",
        isPrimarySource: true,
        mappedArtifactTypes: ["architecture"],
        createdAt: "2026-04-01T10:00:04Z",
      },
    ],
    requirements_agent: [
      {
        id: "r2",
        projectId: "p1",
        version: 1,
        agent: "requirements_agent",
        fileName: "survey.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Survey",
        isPrimarySource: false,
        mappedArtifactTypes: [],
        createdAt: "2026-04-01T10:00:02Z",
      },
      {
        id: "r1",
        projectId: "p1",
        version: 1,
        agent: "requirements_agent",
        fileName: "feature_tree.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Feature Tree",
        isPrimarySource: true,
        mappedArtifactTypes: ["prd"],
        createdAt: "2026-04-01T10:00:01Z",
      },
    ],
  });

  assert.deepEqual(groups.map((group) => group.agent), ["requirements_agent", "architecture_agent"]);
  assert.deepEqual(groups[0]?.items.map((item) => item.artifact.fileName), ["feature_tree.md", "survey.md"]);
  assert.deepEqual(groups[1]?.items.map((item) => item.artifact.fileName), ["class_design_raw.md"]);
});
