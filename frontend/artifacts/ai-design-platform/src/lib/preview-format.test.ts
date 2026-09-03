import test from "node:test";
import assert from "node:assert/strict";

import { detectPreviewLanguage, highlightCodeLine, isMarkdownFileName } from "./preview-format.ts";

test("detectPreviewLanguage resolves common frontend and docs file types", () => {
  assert.equal(detectPreviewLanguage("src/App.tsx"), "tsx");
  assert.equal(detectPreviewLanguage("src/lib/gomoku.ts"), "ts");
  assert.equal(detectPreviewLanguage("openapi.yaml"), "yaml");
  assert.equal(detectPreviewLanguage("component_design.json"), "json");
  assert.equal(detectPreviewLanguage("docs/feature_tree.md"), "markdown");
  assert.equal(detectPreviewLanguage("public/index.html"), "html");
  assert.equal(detectPreviewLanguage("styles/index.css"), "css");
  assert.equal(detectPreviewLanguage("notes.txt"), "text");
});

test("isMarkdownFileName detects markdown artifacts", () => {
  assert.equal(isMarkdownFileName("feature_tree.md"), true);
  assert.equal(isMarkdownFileName("notes.markdown"), true);
  assert.equal(isMarkdownFileName("component_design.json"), false);
});

test("highlightCodeLine marks ts keywords and strings", () => {
  const tokens = highlightCodeLine("export const title = \"Gomoku\";", "ts");

  assert.equal(tokens.some((token) => token.type === "keyword" && token.text === "export"), true);
  assert.equal(tokens.some((token) => token.type === "keyword" && token.text === "const"), true);
  assert.equal(tokens.some((token) => token.type === "string" && token.text === "\"Gomoku\""), true);
});

test("highlightCodeLine marks json keys and values", () => {
  const tokens = highlightCodeLine("\"title\": \"Gomoku\",", "json");

  assert.equal(tokens.some((token) => token.type === "property" && token.text === "\"title\""), true);
  assert.equal(tokens.some((token) => token.type === "string" && token.text === "\"Gomoku\""), true);
});
