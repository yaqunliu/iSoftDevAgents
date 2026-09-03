type ProcessLogFrameInput = {
  taskName?: string | null;
  content?: string | null;
  metadata?: Record<string, unknown> | null;
};

export type ProcessLogRuntimeMonitor = {
  pid: number | null;
  state: string | null;
  secondsSinceLastOutput: number | null;
  elapsedSeconds: number | null;
};

export type ProcessLogFrameModel = {
  phaseTranslationKey: string | null;
  recentFile: string | null;
  nextStepTranslationKey: string | null;
  runtimeMonitor: ProcessLogRuntimeMonitor | null;
};

export type ProcessLogRuntimeDisplay = {
  elapsedSeconds: number;
};

function recentFileFromMetadata(metadata: Record<string, unknown> | null | undefined): string | null {
  if (!metadata) {
    return null;
  }
  const rawFileName = typeof metadata.rawFileName === "string" ? metadata.rawFileName.trim() : "";
  if (rawFileName) {
    return rawFileName;
  }
  const latestOutputFile = typeof metadata.latestOutputFile === "string" ? metadata.latestOutputFile.trim() : "";
  if (latestOutputFile) {
    return latestOutputFile;
  }
  const outputFiles = Array.isArray(metadata.outputFiles) ? metadata.outputFiles : [];
  for (let index = outputFiles.length - 1; index >= 0; index -= 1) {
    const candidate = String(outputFiles[index] ?? "").trim();
    if (candidate) {
      return candidate;
    }
  }
  return null;
}

function nextStepTranslationKeyForPhase(phase: string | null): string | null {
  if (!phase) {
    return null;
  }
  const keys: Record<string, string> = {
    requirements_drafts_started: "chat.logFrame.next.requirements_drafts_started",
    waiting_for_requirements_artifact_review: "chat.logFrame.next.waiting_for_requirements_artifact_review",
    architecture_generation_started: "chat.logFrame.next.architecture_generation_started",
    waiting_for_artifact_review: "chat.logFrame.next.waiting_for_artifact_review",
    runtime_input_required: "chat.logFrame.next.runtime_input_required",
    code_generation_started: "chat.logFrame.next.code_generation_started",
    test_generation_started: "chat.logFrame.next.test_generation_started",
    task_completed: "chat.logFrame.next.task_completed",
    task_failed: "chat.logFrame.next.task_failed",
  };
  return keys[phase] ?? null;
}

function numericMetadataValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function runtimeMonitorFromMetadata(
  metadata: Record<string, unknown> | null | undefined,
): ProcessLogRuntimeMonitor | null {
  if (!metadata) {
    return null;
  }

  // 设计注释：
  // 这里故意把“运行监控”单独抽出来，而不是混进普通文案里。
  // 因为日志内容可能长时间不刷新，但心跳字段仍然会变化。
  // 前端只要拿到这个对象，就能明确告诉用户进程是不是还活着。
  const state = typeof metadata.runtimeState === "string" ? metadata.runtimeState.trim() : "";
  const pid = numericMetadataValue(metadata.runtimePid);
  const secondsSinceLastOutput = numericMetadataValue(metadata.secondsSinceLastOutput);
  const elapsedSeconds = numericMetadataValue(metadata.elapsedSeconds);

  if (!state && pid === null && secondsSinceLastOutput === null && elapsedSeconds === null) {
    return null;
  }

  return {
    pid,
    state: state || null,
    secondsSinceLastOutput,
    elapsedSeconds,
  };
}

export function buildRuntimeMonitorDisplay(
  runtimeMonitor: ProcessLogRuntimeMonitor | null,
): ProcessLogRuntimeDisplay | null {
  // 接口注释：
  // 前端最终只展示“已经运行了多久”这一条信息。
  // 这样用户能快速判断任务是不是跑了太久，又不会被 PID、状态名、无输出时长这些噪音打扰。
  const elapsedSeconds = runtimeMonitor?.elapsedSeconds;
  if (elapsedSeconds === null || elapsedSeconds === undefined || !Number.isFinite(elapsedSeconds) || elapsedSeconds < 0) {
    return null;
  }
  return {
    elapsedSeconds,
  };
}

export function buildProcessLogFrameModel(input: ProcessLogFrameInput): ProcessLogFrameModel {
  const metadata = (input.metadata ?? {}) as Record<string, unknown>;
  const phase = typeof metadata.phase === "string" ? metadata.phase : null;

  return {
    phaseTranslationKey: phase ? `chat.activity.${phase}` : null,
    recentFile: recentFileFromMetadata(metadata),
    nextStepTranslationKey: nextStepTranslationKeyForPhase(phase),
    runtimeMonitor: runtimeMonitorFromMetadata(metadata),
  };
}
