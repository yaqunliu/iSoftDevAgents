import test from "node:test";
import assert from "node:assert/strict";

import { buildInteractionGuidance } from "./interaction-guidance.ts";

test("buildInteractionGuidance explains requirements feedback as a current draft revision instead of a whole-project rewrite", () => {
  const guidance = buildInteractionGuidance(
    {
      confirmationKind: "requirements_feedback",
      outputFiles: ["feature_tree.md", "business_scope.md"],
    },
    "zh",
  );

  assert.ok(guidance);
  assert.match(guidance?.scopeHint ?? "", /当前这批需求草稿文件/);
  assert.match(guidance?.scopeHint ?? "", /feature_tree\.md/);
  assert.match(guidance?.submitHint ?? "", /需求 Agent/);
  assert.match(guidance?.skipHint ?? "", /接受当前这批需求文件/);
});

test("buildInteractionGuidance explains requirements review as the gate before architecture", () => {
  const guidance = buildInteractionGuidance(
    {
      confirmationKind: "artifact_review",
      activePhase: "waiting_for_requirements_artifact_review",
      outputFiles: ["feature_tree.md", "business_scope.md", "use_case.md"],
    },
    "zh",
  );

  assert.ok(guidance);
  assert.match(guidance?.reviewHint ?? "", /架构阶段/);
  assert.match(guidance?.reviewHint ?? "", /feature_tree\.md/);
  assert.match(guidance?.reviewHint ?? "", /business_scope\.md/);
  assert.match(guidance?.submitHint ?? "", /Architecture Agent/);
});

test("buildInteractionGuidance explains full artifact review as the gate before ui coding and testing", () => {
  const guidance = buildInteractionGuidance(
    {
      confirmationKind: "artifact_review",
      activePhase: "waiting_for_artifact_review",
    },
    "en",
  );

  assert.ok(guidance);
  assert.match(guidance?.scopeHint ?? "", /architecture/i);
  assert.match(guidance?.submitHint ?? "", /UI, coding, and testing/i);
});

test("buildInteractionGuidance explains runtime variables as current-step execution input", () => {
  const guidance = buildInteractionGuidance(
    {
      confirmationKind: "input_variables",
      variables: [{ id: "api_key" }],
    },
    "zh",
  );

  assert.ok(guidance);
  assert.match(guidance?.scopeHint ?? "", /当前这一步继续执行/);
  assert.match(guidance?.reviewHint ?? "", /不是在补需求文档/);
});

test("buildInteractionGuidance explains module confirmation as accepting the current feature tree", () => {
  const guidance = buildInteractionGuidance(
    {
      options: [{ id: "module-a" }, { id: "module-b" }],
    },
    "en",
  );

  assert.ok(guidance);
  assert.match(guidance?.reviewHint ?? "", /current feature tree/i);
  assert.match(guidance?.reviewHint ?? "", /feature_tree\.md/i);
  assert.match(guidance?.submitHint ?? "", /accept the current feature tree/i);
  assert.match(guidance?.skipHint ?? "", /Regenerate Feature Tree/i);
});

test("buildInteractionGuidance tells the user which requirements files to review before submitting feedback", () => {
  const guidance = buildInteractionGuidance(
    {
      confirmationKind: "requirements_feedback",
      outputFiles: ["BRD.md", "BRD_modify.md", "BusinessRequirementDocument.pkl"],
    },
    "zh",
  );

  assert.ok(guidance);
  assert.match(guidance?.reviewHint ?? "", /BRD\.md/);
  assert.doesNotMatch(guidance?.reviewHint ?? "", /BRD_modify\.md/);
  assert.doesNotMatch(guidance?.reviewHint ?? "", /\.pkl/);
  assert.match(guidance?.scopeHint ?? "", /BRD\.md/);
  assert.match(guidance?.submitHint ?? "", /重新生成|修改/);
});

test("buildInteractionGuidance uses locale-specific copy instead of falling back to english for japanese", () => {
  const guidance = buildInteractionGuidance(
    {
      confirmationKind: "input_variables",
      variables: [{ id: "api_key" }],
    },
    "ja",
  );

  assert.ok(guidance);
  assert.match(guidance?.reviewHint ?? "", /実行|要件/);
  assert.doesNotMatch(guidance?.reviewHint ?? "", /Only enter the runtime variables/i);
});
