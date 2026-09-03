import test from "node:test";
import assert from "node:assert/strict";

import {
  buildPendingGenerationActivityItems,
  clearPendingProjectGeneration,
  readPendingProjectGeneration,
  savePendingProjectGeneration,
  type PendingProjectGeneration,
} from "./pending-project-generation.ts";

function createMemoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem(key: string) {
      return values.get(key) ?? null;
    },
    setItem(key: string, value: string) {
      values.set(key, value);
    },
    removeItem(key: string) {
      values.delete(key);
    },
  };
}

test("pending project generation round-trips through storage and can be cleared", () => {
  const storage = createMemoryStorage();
  const pending: PendingProjectGeneration = {
    projectId: "project-1",
    prompt: "Build a snake game",
    uploadedFileIds: ["file-1"],
    createdAt: "2026-03-31T10:00:00Z",
  };

  savePendingProjectGeneration(storage, pending);
  assert.deepEqual(readPendingProjectGeneration(storage, "project-1"), pending);

  clearPendingProjectGeneration(storage, "project-1");
  assert.equal(readPendingProjectGeneration(storage, "project-1"), null);
});

test("buildPendingGenerationActivityItems creates immediate running feedback for a new project", () => {
  const items = buildPendingGenerationActivityItems("project-1", "2026-03-31T10:00:00Z");

  assert.deepEqual(
    items.map((item) => [item.phase, item.status, item.progress]),
    [
      ["reading_context", "running", 10],
      ["queued", "completed", 0],
    ],
  );
});
