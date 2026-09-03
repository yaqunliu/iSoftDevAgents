export type ProjectWebSocketQueryPlan = {
  invalidateChat: boolean;
  invalidateCurrentTask: boolean;
  refetchChatNow: boolean;
  refetchCurrentTaskNow: boolean;
};

type ProjectWebSocketMessagePayload = {
  type?: unknown;
  metadata?: Record<string, unknown> | null;
};

function isInteractionCardMessage(payload: ProjectWebSocketMessagePayload | null | undefined): boolean {
  if (!payload || typeof payload !== "object") {
    return false;
  }
  const messageType = typeof payload.type === "string" ? payload.type.trim() : "";
  if (messageType !== "select_options" && messageType !== "input_form") {
    return false;
  }
  const confirmationKind =
    payload.metadata && typeof payload.metadata.confirmationKind === "string"
      ? payload.metadata.confirmationKind.trim()
      : "";
  return confirmationKind.length > 0;
}

// 接口注释：
// 把 WebSocket 事件要触发哪些查询刷新，统一收口在这里。
// 前端收到事件后只需要照这个结果执行，不用把判断条件散落在 use-api 里。
export function buildProjectWebSocketQueryPlan(
  eventType: string | undefined | null,
  payload?: ProjectWebSocketMessagePayload | null,
): ProjectWebSocketQueryPlan {
  const type = typeof eventType === "string" ? eventType.trim() : "";
  const interactionCardMessage = type === "message" && isInteractionCardMessage(payload);
  // task_log_updated 是 Agent 运行期间最高频的事件（每几秒一次），
  // 它只更新进度日志内容，不需要重新拉取整个消息列表。
  // 移除后靠 10 秒兜底轮询补上，大幅减少请求量。
  const shouldRefreshChat =
    type === "message" ||
    type === "message_update" ||
    type === "task_round_started" ||
    type === "task_log_started" ||
    type === "task_log_completed" ||
    type === "task_artifact_attached" ||
    type === "task_waiting_for_user" ||
    type === "task_round_finished" ||
    type === "agent_require_action" ||
    type === "agent_require_input";
  const shouldRefreshCurrentTask =
    type === "status_change" ||
    type === "agent_waiting" ||
    type === "task_round_started" ||
    type === "task_waiting_for_user" ||
    type === "task_round_finished" ||
    type === "agent_require_action" ||
    type === "agent_require_input" ||
    interactionCardMessage;

  // 原因注释：
  // “等待用户确认”的卡片属于必须立刻出现的界面，不适合只做 invalidate。
  // 如果这里只标记缓存过期，某些情况下确认卡会等到下一次轮询或整页刷新才出现。
  const shouldRefetchNow =
    type === "task_waiting_for_user" ||
    type === "agent_require_action" ||
    type === "agent_require_input" ||
    interactionCardMessage;

  return {
    invalidateChat: shouldRefreshChat,
    invalidateCurrentTask: shouldRefreshCurrentTask,
    refetchChatNow: shouldRefreshChat && shouldRefetchNow,
    refetchCurrentTaskNow: shouldRefreshCurrentTask && shouldRefetchNow,
  };
}
