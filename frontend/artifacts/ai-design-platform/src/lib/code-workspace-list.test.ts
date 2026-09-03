import test from "node:test";
import assert from "node:assert/strict";

import {
  buildWorkspaceDocFolders,
  expandCodeTreeFoldersForSelection,
  groupWorkspaceDocItems,
  humanizeAgentSourceName,
  syncCodeTreeExpandedState,
  syncWorkspaceDocGroupExpandedState,
} from "./code-workspace-list.ts";

test("groupWorkspaceDocItems keeps agent order and preserves file names inside each group", () => {
  const groups = groupWorkspaceDocItems([
    { key: "requirements_agent:survey.md", agent: "requirements_agent", fileName: "survey.md" },
    { key: "architecture_agent:system.md", agent: "architecture_agent", fileName: "system.md" },
    { key: "requirements_agent:flow.md", agent: "requirements_agent", fileName: "flow.md" },
  ]);

  assert.deepEqual(groups, [
    {
      agent: "requirements_agent",
      items: [
        { key: "requirements_agent:survey.md", agent: "requirements_agent", fileName: "survey.md" },
        { key: "requirements_agent:flow.md", agent: "requirements_agent", fileName: "flow.md" },
      ],
    },
    {
      agent: "architecture_agent",
      items: [{ key: "architecture_agent:system.md", agent: "architecture_agent", fileName: "system.md" }],
    },
  ]);
});

test("buildWorkspaceDocFolders turns grouped docs into folder rows for the left tree", () => {
  const folders = buildWorkspaceDocFolders([
    { key: "requirements_agent:survey.md", agent: "requirements_agent", fileName: "survey.md" },
    { key: "requirements_agent:flow.md", agent: "requirements_agent", fileName: "flow.md" },
    { key: "architecture_agent:system.md", agent: "architecture_agent", fileName: "system.md" },
  ]);

  assert.deepEqual(folders, [
    {
      id: "requirements_agent",
      agent: "requirements_agent",
      fileNames: ["survey.md", "flow.md"],
    },
    {
      id: "architecture_agent",
      agent: "architecture_agent",
      fileNames: ["system.md"],
    },
  ]);
});

test("humanizeAgentSourceName turns snake case agent ids into readable names", () => {
  assert.equal(humanizeAgentSourceName("requirements_agent"), "Requirements Agent");
  assert.equal(humanizeAgentSourceName("architecture_agent"), "Architecture Agent");
  assert.equal(humanizeAgentSourceName("unknown"), "Unknown");
});

test("syncWorkspaceDocGroupExpandedState keeps current collapse choices and expands new groups by default", () => {
  const groups = groupWorkspaceDocItems([
    { key: "requirements_agent:survey.md", agent: "requirements_agent", fileName: "survey.md" },
    { key: "architecture_agent:system.md", agent: "architecture_agent", fileName: "system.md" },
  ]);

  assert.deepEqual(syncWorkspaceDocGroupExpandedState(groups, { requirements_agent: false }), {
    requirements_agent: false,
    architecture_agent: true,
  });
});

test("syncCodeTreeExpandedState keeps current folder choices and expands new folders by default", () => {
  const nodes = [
    {
      name: "backend",
      type: "folder" as const,
      children: [
        {
          name: "app",
          type: "folder" as const,
          children: [{ name: "run.py", type: "file" as const, path: "backend/app/run.py" }],
        },
      ],
    },
    {
      name: "frontend",
      type: "folder" as const,
      children: [{ name: "index.html", type: "file" as const, path: "frontend/index.html" }],
    },
  ];

  assert.deepEqual(syncCodeTreeExpandedState(nodes, { backend: false }), {
    backend: false,
    "backend/app": true,
    frontend: true,
  });
});

test("expandCodeTreeFoldersForSelection expands every ancestor folder for the selected file", () => {
  const nextState = expandCodeTreeFoldersForSelection("backend/app/api/module_1.py", {
    backend: false,
    "backend/app": false,
    "backend/app/api": false,
  });

  assert.deepEqual(nextState, {
    backend: true,
    "backend/app": true,
    "backend/app/api": true,
  });
});
