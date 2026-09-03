import test from "node:test";
import assert from "node:assert/strict";

import { clampMermaidZoom, nextMermaidZoom } from "./mermaid-zoom.ts";

test("clampMermaidZoom keeps zoom inside the supported range", () => {
  assert.equal(clampMermaidZoom(0.1), 0.5);
  assert.equal(clampMermaidZoom(1.25), 1.25);
  assert.equal(clampMermaidZoom(9), 4);
});

test("nextMermaidZoom moves zoom by fixed steps and still respects bounds", () => {
  assert.equal(nextMermaidZoom(1, "in"), 1.25);
  assert.equal(nextMermaidZoom(1, "out"), 0.75);
  assert.equal(nextMermaidZoom(4, "in"), 4);
  assert.equal(nextMermaidZoom(0.5, "out"), 0.5);
});
