import test from "node:test";
import assert from "node:assert/strict";

import {
  getArtifactVersionHighlight,
  getPrimaryArtifactTabFromHistoryChanges,
  inferArtifactTabFromHistoryFile,
} from "./version-history-link.ts";

test("inferArtifactTabFromHistoryFile maps top-level artifact titles to viewer tabs", () => {
  assert.equal(inferArtifactTabFromHistoryFile("PRD Draft"), "prd");
  assert.equal(inferArtifactTabFromHistoryFile("UI Draft"), "ui");
  assert.equal(inferArtifactTabFromHistoryFile("Architecture Draft"), "arch");
  assert.equal(inferArtifactTabFromHistoryFile("API Design"), "api");
});

test("getPrimaryArtifactTabFromHistoryChanges returns the first changed artifact tab", () => {
  const tab = getPrimaryArtifactTabFromHistoryChanges([
    { file: "UI Draft", status: "Modified" },
    { file: "Architecture Draft", status: "Modified" },
  ]);

  assert.equal(tab, "ui");
});

test("getArtifactVersionHighlight marks all sections in the changed artifact tab", () => {
  const highlight = getArtifactVersionHighlight("api", [
    { file: "PRD Draft", status: "Modified" },
    { file: "API Design", status: "Modified" },
  ]);

  assert.equal(highlight.changed, true);
  assert.deepEqual(highlight.sectionIds, ["overview", "endpoints", "schemas", "errors"]);
});

test("getArtifactVersionHighlight returns no highlighted sections for unchanged tabs", () => {
  const highlight = getArtifactVersionHighlight("arch", [
    { file: "PRD Draft", status: "Modified" },
  ]);

  assert.equal(highlight.changed, false);
  assert.deepEqual(highlight.sectionIds, []);
});
