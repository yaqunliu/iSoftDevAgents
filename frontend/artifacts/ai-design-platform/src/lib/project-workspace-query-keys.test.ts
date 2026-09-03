import test from "node:test";
import assert from "node:assert/strict";

import { projectWorkspaceQueryKeys } from "./project-workspace-query-keys.ts";

test("projectWorkspaceQueryKeys includes both document and code queries so workspace lists refresh together", () => {
  assert.deepEqual(projectWorkspaceQueryKeys("demo-project"), [
    ["project-files", "demo-project"],
    ["project-file", "demo-project"],
    ["code-tree", "demo-project"],
    ["code-file", "demo-project"],
    ["code-modules", "demo-project"],
    ["project-drafts", "demo-project"],
  ]);
});
