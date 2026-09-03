import test from "node:test";
import assert from "node:assert/strict";

import { findRequirementsFeatureTreePreview, looksLikeMarkdown } from "./confirmation-preview.ts";

test("findRequirementsFeatureTreePreview returns the feature_tree markdown content when available", () => {
  const preview = findRequirementsFeatureTreePreview({
    requirements_agent: [
      {
        id: "a1",
        projectId: "p1",
        version: 1,
        taskId: "t1",
        agent: "requirements_agent",
        fileName: "feature_tree.md",
        fileType: "markdown",
        contentType: "text/markdown",
        content: "# Feature Tree\n\n- **L1: Core Gameplay Engine**",
        isPrimarySource: true,
        mappedArtifactTypes: ["prd", "ui"],
        createdAt: "2026-04-01T00:00:00Z",
      },
    ],
  });

  assert.equal(preview?.fileName, "feature_tree.md");
  assert.equal(preview?.content.includes("Core Gameplay Engine"), true);
});

test("looksLikeMarkdown detects formatted option labels", () => {
  assert.equal(looksLikeMarkdown("**L1: Core Gameplay Engine**"), true);
  assert.equal(looksLikeMarkdown("- item 1\n- item 2"), true);
  assert.equal(looksLikeMarkdown("Plain text"), false);
});
