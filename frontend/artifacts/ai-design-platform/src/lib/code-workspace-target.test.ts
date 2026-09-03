import test from "node:test";
import assert from "node:assert/strict";

import { buildWorkspaceDocKey, resolveWorkspaceDocSelection } from "./code-workspace-target.ts";

test("resolveWorkspaceDocSelection prefers the requested agent document when it exists", () => {
  const selected = resolveWorkspaceDocSelection(
    [
      { key: buildWorkspaceDocKey("requirements_agent", "feature_tree.md") },
      { key: buildWorkspaceDocKey("requirements_agent", "survey.md") },
    ],
    {
      kind: "doc",
      agent: "requirements_agent",
      fileName: "survey.md",
    },
  );

  assert.equal(selected, buildWorkspaceDocKey("requirements_agent", "survey.md"));
});

test("resolveWorkspaceDocSelection falls back to the first document when the requested file is missing", () => {
  const selected = resolveWorkspaceDocSelection(
    [
      { key: buildWorkspaceDocKey("requirements_agent", "feature_tree.md") },
      { key: buildWorkspaceDocKey("requirements_agent", "survey.md") },
    ],
    {
      kind: "doc",
      agent: "requirements_agent",
      fileName: "draft_event_list.md",
    },
  );

  assert.equal(selected, buildWorkspaceDocKey("requirements_agent", "feature_tree.md"));
});
