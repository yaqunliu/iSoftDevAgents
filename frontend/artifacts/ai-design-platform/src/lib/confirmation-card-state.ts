export type ConfirmationTaskStatus = "idle" | "running" | "waiting_user" | "completed" | "failed" | "cancelled";

export type ConfirmationCardPhase =
  | "waiting"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "inactive";

const CONFIRMATION_PHASE_ORDER: Record<string, number> = {
  waiting_for_module_confirmation: 50,
  requirements_feedback_required: 55,
  requirements_drafts_started: 60,
  waiting_for_requirements_artifact_review: 65,
  architecture_generation_started: 70,
  runtime_input_required: 75,
  waiting_for_artifact_review: 78,
  ui_generation_started: 80,
  artifact_generation_started: 80,
  code_generation_started: 90,
  code_generation_completed: 100,
  test_generation_started: 110,
  test_generation_completed: 120,
  waiting_for_overwrite_confirmation: 140,
  artifact_review_completed: 150,
  modification_started: 160,
  task_completed: 170,
  task_failed: 180,
};

// 接口注释：
// 这个函数专门把确认卡消息里的元数据还原成“它当时卡在什么阶段”。
// 这样调用方只要传消息 metadata，就不用每个组件都手写一遍确认类型到阶段的映射。
export function resolveConfirmationMessagePhase(metadata?: Record<string, unknown> | null): string | null {
  const explicitPhase = typeof metadata?.activePhase === "string" ? metadata.activePhase.trim() : "";
  if (explicitPhase) {
    return explicitPhase;
  }

  const confirmationKind = typeof metadata?.confirmationKind === "string" ? metadata.confirmationKind : null;
  if (confirmationKind === "requirements_feedback") {
    return "requirements_feedback_required";
  }
  if (confirmationKind === "input_variables") {
    return "runtime_input_required";
  }
  if (confirmationKind === "artifact_review") {
    return "waiting_for_artifact_review";
  }
  if (confirmationKind === "coverage_conflict") {
    return "waiting_for_overwrite_confirmation";
  }
  if (confirmationKind) {
    return "waiting_for_module_confirmation";
  }
  return null;
}

function hasPhaseAdvancedBeyondConfirmation(
  currentActivePhase?: string | null,
  confirmationActivePhase?: string | null,
): boolean {
  const currentOrder =
    typeof currentActivePhase === "string" && currentActivePhase.trim()
      ? (CONFIRMATION_PHASE_ORDER[currentActivePhase] ?? null)
      : null;
  const confirmationOrder =
    typeof confirmationActivePhase === "string" && confirmationActivePhase.trim()
      ? (CONFIRMATION_PHASE_ORDER[confirmationActivePhase] ?? null)
      : null;

  return currentOrder !== null && confirmationOrder !== null && currentOrder > confirmationOrder;
}

// 这里统一约束交互卡片在折叠态下什么时候还要露出按钮。
// 只有还在等待用户操作时，才应该在折叠态继续露出操作入口；
// 一旦已经提交、进入运行中、完成、失败或取消，就不再额外占空间。
export function shouldShowCollapsedInteractionActions({
  phase,
  expanded,
}: {
  phase: ConfirmationCardPhase;
  expanded: boolean;
}): boolean {
  return phase === "waiting" && !expanded;
}

// 接口注释：
// 这个函数专门判断“某个交互卡片自己是不是仍在提交中”。
// 设计原因是页面里可能连续出现多张确认卡，如果直接共用全局 mutation.isPending，
// 后一张新卡会被前一张旧提交误伤，一直显示转圈。
export function isInteractionCardMutationPending({
  mutationPending,
  submittedMessageId,
  messageId,
  optimisticMessageId,
}: {
  mutationPending: boolean;
  submittedMessageId?: string | null;
  messageId: string;
  optimisticMessageId?: string | null;
}): boolean {
  if (optimisticMessageId && optimisticMessageId === messageId) {
    return true;
  }
  return mutationPending && !!submittedMessageId && submittedMessageId === messageId;
}

export function resolveConfirmationCardPhase({
  messageId,
  activeMessageId,
  taskStatus,
  currentActivePhase,
  confirmationActivePhase,
}: {
  messageId: string;
  activeMessageId?: string | null;
  taskStatus?: ConfirmationTaskStatus | null;
  currentActivePhase?: string | null;
  confirmationActivePhase?: string | null;
}): ConfirmationCardPhase {
  if (!activeMessageId || activeMessageId !== messageId) {
    return "inactive";
  }

  // 设计注释：
  // 用户提交确认后，当前任务会继续往后跑，但最后一张确认卡的 message id 并不会变化。
  // 如果这里只看 “activeMessageId 命中 + taskStatus=running”，旧确认卡就会一直显示“运行中”。
  // 所以这里再补一层阶段顺序判断：只要当前阶段已经越过这张卡所在阶段，就把它视为已完成。
  if (
    taskStatus === "running" &&
    hasPhaseAdvancedBeyondConfirmation(currentActivePhase, confirmationActivePhase)
  ) {
    return "completed";
  }

  if (taskStatus === "waiting_user") {
    return "waiting";
  }
  if (taskStatus === "running") {
    return "running";
  }
  if (taskStatus === "completed") {
    return "completed";
  }
  if (taskStatus === "failed") {
    return "failed";
  }
  if (taskStatus === "cancelled") {
    return "cancelled";
  }
  return "inactive";
}
