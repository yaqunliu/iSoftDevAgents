import test from "node:test";
import assert from "node:assert/strict";

import {
  resolveHistoryEmptyPendingPreview,
  resolveWorkspaceVersionState,
} from "./workspace-version-state.ts";

test("resolveWorkspaceVersionState marks a newer live snapshot as pending preview", () => {
  assert.deepEqual(resolveWorkspaceVersionState(2, 1, 2), {
    version: 2,
    isPendingPreview: true,
  });
});

test("resolveWorkspaceVersionState keeps a normal committed version badge unchanged", () => {
  assert.deepEqual(resolveWorkspaceVersionState(1, 1, 2), {
    version: 1,
    isPendingPreview: false,
  });
});

test("resolveHistoryEmptyPendingPreview exposes the temporary live snapshot while history is still empty", () => {
  assert.equal(resolveHistoryEmptyPendingPreview(2, 1), 2);
});

test("resolveHistoryEmptyPendingPreview stays empty when no newer pending snapshot exists", () => {
  assert.equal(resolveHistoryEmptyPendingPreview(1, 1), null);
});
