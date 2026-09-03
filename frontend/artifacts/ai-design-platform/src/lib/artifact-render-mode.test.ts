import test from "node:test";
import assert from "node:assert/strict";

import {
  getDefaultArtifactRenderMode,
  isMarkdownArtifactTab,
  isYamlArtifactTab,
} from "./artifact-render-mode.ts";

test("markdown artifacts default to preview mode", () => {
  assert.equal(getDefaultArtifactRenderMode("prd"), "preview");
  assert.equal(getDefaultArtifactRenderMode("ui"), "preview");
  assert.equal(getDefaultArtifactRenderMode("arch"), "preview");
});

test("yaml artifact defaults to yaml mode", () => {
  assert.equal(getDefaultArtifactRenderMode("api"), "yaml");
});

test("markdown and yaml artifact type guards stay mutually exclusive", () => {
  assert.equal(isMarkdownArtifactTab("prd"), true);
  assert.equal(isMarkdownArtifactTab("api"), false);
  assert.equal(isYamlArtifactTab("api"), true);
  assert.equal(isYamlArtifactTab("ui"), false);
});
