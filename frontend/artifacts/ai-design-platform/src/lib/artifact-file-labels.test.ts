import test from "node:test";
import assert from "node:assert/strict";

import i18n from "@/i18n";
import { artifactFileLabelKey, localizeArtifactFileLabel } from "./artifact-file-labels.ts";

test("artifactFileLabelKey returns the i18n key for planned requirement files", () => {
  assert.equal(artifactFileLabelKey("feature_tree.md"), "artifact.fileLabel.feature_tree");
  assert.equal(artifactFileLabelKey("user_introduction.md"), "artifact.fileLabel.user_introduction");
  assert.equal(artifactFileLabelKey("business_scope.md"), "artifact.fileLabel.business_scope");
});

test("localizeArtifactFileLabel follows the active frontend language", async () => {
  await i18n.changeLanguage("en");
  assert.equal(localizeArtifactFileLabel(i18n.t.bind(i18n), "feature_tree.md", "功能树"), "Feature Tree");

  await i18n.changeLanguage("zh");
  assert.equal(localizeArtifactFileLabel(i18n.t.bind(i18n), "feature_tree.md", "功能树"), "功能树");

  await i18n.changeLanguage("ja");
  assert.equal(localizeArtifactFileLabel(i18n.t.bind(i18n), "feature_tree.md", "功能树"), "機能ツリー");

  await i18n.changeLanguage("en");
});

test("localizeArtifactFileLabel falls back to the backend label for unknown files", () => {
  const fakeTranslate = (key: string, options?: Record<string, unknown>) =>
    typeof options?.defaultValue === "string" ? String(options.defaultValue) : key;

  assert.equal(localizeArtifactFileLabel(fakeTranslate, "unknown.md", "自定义标签"), "自定义标签");
  assert.equal(localizeArtifactFileLabel(fakeTranslate, "unknown.md"), "unknown.md");
});
