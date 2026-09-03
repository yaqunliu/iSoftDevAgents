import test from "node:test";
import assert from "node:assert/strict";

import { shouldAutoSwitchWorkspaceMode } from "./code-workspace-mode.ts";

test("shouldAutoSwitchWorkspaceMode does not switch away from docs while project files are still loading", () => {
  assert.equal(shouldAutoSwitchWorkspaceMode("docs", true, 0), false);
});

test("shouldAutoSwitchWorkspaceMode switches to code only after docs finished loading and are truly empty", () => {
  assert.equal(shouldAutoSwitchWorkspaceMode("docs", false, 0), true);
});

test("shouldAutoSwitchWorkspaceMode leaves code mode unchanged", () => {
  assert.equal(shouldAutoSwitchWorkspaceMode("code", false, 0), false);
});
