import test from "node:test";
import assert from "node:assert/strict";

import { buildProcessLogFrameModel, buildRuntimeMonitorDisplay } from "./process-log-frame.ts";

test("buildProcessLogFrameModel shows the next architecture step after requirements review is waiting", () => {
  const frame = buildProcessLogFrameModel({
    taskName: "等待需求草稿确认",
    content: "需求草稿已全部生成，确认后将进入架构阶段。",
    metadata: {
      phase: "waiting_for_requirements_artifact_review",
      rawFileName: "SRS.md",
      outputFiles: ["survey.md", "SRS.md"],
    },
  });

  assert.equal(frame.phaseTranslationKey, "chat.activity.waiting_for_requirements_artifact_review");
  assert.equal(frame.recentFile, "SRS.md");
  assert.equal(frame.nextStepTranslationKey, "chat.logFrame.next.waiting_for_requirements_artifact_review");
});

test("buildProcessLogFrameModel keeps the latest generated file while requirements drafts are still running", () => {
  const frame = buildProcessLogFrameModel({
    taskName: "生成需求草稿文件",
    content: "正在生成 PRD、UI、API 所需的需求草稿文件。",
    metadata: {
      phase: "requirements_drafts_started",
      rawFileName: "survey.md",
    },
  });

  assert.equal(frame.phaseTranslationKey, "chat.activity.requirements_drafts_started");
  assert.equal(frame.recentFile, "survey.md");
  assert.equal(frame.nextStepTranslationKey, "chat.logFrame.next.requirements_drafts_started");
});

test("buildProcessLogFrameModel exposes runtime monitor details when the agent is still alive", () => {
  const frame = buildProcessLogFrameModel({
    taskName: "Generating architecture draft",
    content: "Generating analysis_task_output.txt.",
    metadata: {
      phase: "architecture_generation_started",
      rawFileName: "modeling-3.static_design_output.txt",
      runtimePid: 43210,
      runtimeState: "running",
      secondsSinceLastOutput: 7,
      elapsedSeconds: 145,
    },
  });

  assert.equal(frame.recentFile, "modeling-3.static_design_output.txt");
  assert.deepEqual(frame.runtimeMonitor, {
    pid: 43210,
    state: "running",
    secondsSinceLastOutput: 7,
    elapsedSeconds: 145,
  });
});

test("buildProcessLogFrameModel can fall back to the runtime heartbeat file when no raw file is attached yet", () => {
  const frame = buildProcessLogFrameModel({
    taskName: "Generating architecture draft",
    content: "Generating architecture draft.",
    metadata: {
      phase: "architecture_generation_started",
      latestOutputFile: "modeling-2.architectural_style_selection_output.txt",
      runtimeState: "running",
    },
  });

  assert.equal(frame.recentFile, "modeling-2.architectural_style_selection_output.txt");
  assert.deepEqual(frame.runtimeMonitor, {
    pid: null,
    state: "running",
    secondsSinceLastOutput: null,
    elapsedSeconds: null,
  });
});

test("buildRuntimeMonitorDisplay only keeps elapsed time for the frontend", () => {
  const display = buildRuntimeMonitorDisplay({
    pid: 43210,
    state: "running",
    secondsSinceLastOutput: 36,
    elapsedSeconds: 8820,
  });

  assert.deepEqual(display, {
    elapsedSeconds: 8820,
  });
});

test("buildRuntimeMonitorDisplay hides runtime monitor when elapsed time is missing", () => {
  const display = buildRuntimeMonitorDisplay({
    pid: 43210,
    state: "running",
    secondsSinceLastOutput: 36,
    elapsedSeconds: null,
  });

  assert.equal(display, null);
});
