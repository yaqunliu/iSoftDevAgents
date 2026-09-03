import test from "node:test";
import assert from "node:assert/strict";

import { resolveAgentArtifactsVersion } from "./agent-artifacts-version.ts";

test("resolveAgentArtifactsVersion uses latest docs for the live workspace version", () => {
  assert.equal(resolveAgentArtifactsVersion(3, 3, undefined), undefined);
});

test("resolveAgentArtifactsVersion preserves an explicitly selected historical version", () => {
  assert.equal(resolveAgentArtifactsVersion(2, 3, undefined), 2);
});

test("resolveAgentArtifactsVersion falls back to latest when no version is selected", () => {
  assert.equal(resolveAgentArtifactsVersion(null, 3, undefined), undefined);
});

test("resolveAgentArtifactsVersion prefers the pending live output version while the current version is still old", () => {
  assert.equal(resolveAgentArtifactsVersion(3, 3, 4), 4);
});
