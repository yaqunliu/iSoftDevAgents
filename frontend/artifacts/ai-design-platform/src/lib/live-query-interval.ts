type LiveQueryStatus = "idle" | "running" | "waiting_user" | "completed" | "failed" | "cancelled" | null | undefined;

// 接口注释：
// 统一决定前端在任务进行中时，哪些查询要用兜底轮询。
// 这样即使某次 WebSocket 事件丢了，聊天消息和步骤区也能在短时间内自己补上最新状态。
export function resolveLiveQueryRefetchInterval(status: LiveQueryStatus): number | false {
  if (status === "running" || status === "waiting_user") {
    return 10_000;
  }
  return false;
}
