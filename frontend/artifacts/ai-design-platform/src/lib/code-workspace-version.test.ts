import test from "node:test";
import assert from "node:assert/strict";

import { resolveCodeWorkspaceVersion } from "./code-workspace-version.ts";

test("resolveCodeWorkspaceVersion prefers the pending preview when the user is looking at the current round", () => {
  assert.equal(resolveCodeWorkspaceVersion(3, 3, 4), 4);
});

test("resolveCodeWorkspaceVersion keeps an explicitly selected historical version", () => {
  assert.equal(resolveCodeWorkspaceVersion(2, 3, 4), 2);
});

test("resolveCodeWorkspaceVersion falls back to current latest snapshot when there is no pending version", () => {
  assert.equal(resolveCodeWorkspaceVersion(3, 3, undefined), undefined);
});

test("resolveCodeWorkspaceVersion uses the pending preview when there is no explicit version yet", () => {
  assert.equal(resolveCodeWorkspaceVersion(undefined, 3, 4), 4);
});
