export type TaskRoundStatus = "running" | "waiting_user" | "completed" | "failed" | "cancelled";
export type LogCardStatus = "running" | "completed" | "failed";

const PHASE_ORDER: Record<string, number> = {
  queued: 10,
  reading_context: 20,
  requirements_analysis: 30,
  modules_ready: 40,
  waiting_for_module_confirmation: 50,
  requirements_feedback_required: 55,
  requirements_drafts_started: 60,
  waiting_for_requirements_artifact_review: 65,
  architecture_generation_started: 70,
  runtime_input_required: 95,
  // 设计注释：
  // 这里的顺序必须和真实工作流一致。
  // “等待架构稿确认”发生在 UI / 代码 / 测试之前，
  // 如果把它排到后面，前端就会误以为旧日志还没被当前阶段越过，
  // 从而把早就过去的架构评审卡片继续显示成 Running。
  waiting_for_artifact_review: 78,
  ui_generation_started: 80,
  artifact_generation_started: 80,
  ui_generation_completed: 85,
  artifact_generated: 90,
  code_generation_started: 100,
  code_generation_completed: 110,
  test_generation_started: 120,
  test_generation_completed: 130,
  waiting_for_overwrite_confirmation: 150,
  artifact_review_completed: 160,
  modification_started: 170,
  task_completed: 180,
  task_failed: 190,
};

type CurrentTaskLike = {
  id: string;
  parentTaskId?: string | null;
  status: "idle" | "running" | "waiting_user" | "completed" | "failed" | "cancelled";
} | null;

type TimelineMessageLike = {
  metadata?: Record<string, unknown> | null;
};

export function inferTaskRoundStatus({
  taskId,
  currentTask,
  logs,
  statusMessage,
}: {
  taskId: string;
  currentTask: CurrentTaskLike;
  logs: Array<{ message: TimelineMessageLike }>;
  statusMessage?: TimelineMessageLike | null;
}): TaskRoundStatus {
  // 设计注释：
  // 原始任务失败后，如果用户基于它发起了重试子任务，
  // 那么这张“原始轮次卡片”展示的应该是最新重试链路的真实状态。
  // 之前这里只覆盖了 idle/running/waiting_user，导致“重试已经成功完成”
  // 时又退回去显示旧失败状态，前端就会一直挂着红色报错。
  const isCurrentRoundTask =
    currentTask?.id === taskId ||
    (currentTask?.parentTaskId === taskId &&
      (currentTask.status === "idle" ||
        currentTask.status === "running" ||
        currentTask.status === "waiting_user" ||
        currentTask.status === "completed"));

  if (isCurrentRoundTask) {
    return currentTask.status === "idle" ? "running" : currentTask.status;
  }

  const foldedTaskStatus =
    typeof statusMessage?.metadata?.taskStatus === "string" ? statusMessage.metadata.taskStatus : null;
  if (foldedTaskStatus === "failed") {
    return "failed";
  }
  if (foldedTaskStatus === "cancelled") {
    return "cancelled";
  }
  if (foldedTaskStatus === "waiting_user") {
    return "waiting_user";
  }
  if (foldedTaskStatus === "completed") {
    return "completed";
  }

  const lastLog = logs[logs.length - 1]?.message;
  const status = typeof lastLog?.metadata?.status === "string" ? lastLog.metadata.status : "completed";

  if (status === "failed") {
    return "failed";
  }
  if (status === "cancelled") {
    return "cancelled";
  }
  if (status === "waiting_user") {
    return "waiting_user";
  }
  if (status === "running") {
    return "running";
  }
  return "completed";
}

export function resolveLogCardStatus({
  logStatus,
  logPhase,
  currentActivePhase,
  taskRoundStatus,
}: {
  logStatus?: string | null;
  logPhase?: string | null;
  currentActivePhase?: string | null;
  taskRoundStatus: TaskRoundStatus;
}): LogCardStatus {
  if (taskRoundStatus === "failed" && logStatus !== "completed") {
    return "failed";
  }
  if (taskRoundStatus === "cancelled" && logStatus !== "completed") {
    return "failed";
  }
  // 设计注释：
  // 当前任务已经推进到后续阶段时，前面那几张旧日志卡片不能继续显示“执行中”。
  // 这里用统一的阶段顺序判断“当前阶段是不是已经越过这条日志所在阶段”，
  // 一旦越过，就把旧卡片视为已完成。
  const currentOrder =
    typeof currentActivePhase === "string" && currentActivePhase.trim()
      ? PHASE_ORDER[currentActivePhase] ?? null
      : null;
  const logOrder =
    typeof logPhase === "string" && logPhase.trim()
      ? PHASE_ORDER[logPhase] ?? null
      : null;
  if (
    currentOrder !== null &&
    logOrder !== null &&
    currentOrder > logOrder &&
    taskRoundStatus !== "failed" &&
    taskRoundStatus !== "cancelled"
  ) {
    return "completed";
  }
  if (logStatus === "completed") {
    return "completed";
  }
  if (logStatus === "failed") {
    return "failed";
  }
  return "running";
}

export function defaultCardExpanded(): boolean {
  return false;
}
