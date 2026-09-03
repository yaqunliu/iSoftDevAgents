export type LiveActivityStatus = "running" | "completed" | "waiting" | "failed";

export type LiveActivityPhase =
  | "queued"
  | "reading_context"
  | "requirements_analysis"
  | "modules_ready"
  | "waiting_for_module_confirmation"
  | "requirements_drafts_started"
  | "waiting_for_requirements_artifact_review"
  | "architecture_generation_started"
  | "artifact_generation_started"
  | "artifact_generated"
  | "runtime_input_required"
  | "ui_generation_started"
  | "ui_generation_completed"
  | "code_generation_started"
  | "code_generation_completed"
  | "test_generation_started"
  | "test_generation_completed"
  | "waiting_for_artifact_review"
  | "waiting_for_overwrite_confirmation"
  | "artifact_review_completed"
  | "modification_started"
  | "task_completed"
  | "task_failed";

export type LiveActivityItem = {
  id: string;
  taskId: string;
  phase: LiveActivityPhase;
  status: LiveActivityStatus;
  progress: number | null;
  createdAt: string;
  artifactType: string | null;
  agentName: string | null;
  outputHint: string | null;
  rawFileName: string | null;
  moduleCount: number;
  referenceCount: number;
};

type SocketEventPayload = {
  type?: string;
  data?: Record<string, unknown>;
};

const PHASE_ORDER: Record<LiveActivityPhase, number> = {
  queued: 10,
  reading_context: 20,
  requirements_analysis: 30,
  modules_ready: 40,
  waiting_for_module_confirmation: 50,
  requirements_drafts_started: 60,
  waiting_for_requirements_artifact_review: 65,
  architecture_generation_started: 70,
  artifact_generation_started: 60,
  artifact_generated: 80,
  runtime_input_required: 75,
  ui_generation_started: 85,
  ui_generation_completed: 86,
  code_generation_started: 90,
  code_generation_completed: 100,
  test_generation_started: 105,
  test_generation_completed: 106,
  waiting_for_artifact_review: 110,
  waiting_for_overwrite_confirmation: 120,
  artifact_review_completed: 130,
  modification_started: 140,
  task_completed: 150,
  task_failed: 160,
};

function activityIdentity(item: LiveActivityItem): string {
  const artifactSuffix = item.artifactType ? `:${item.artifactType}` : "";
  return `${item.taskId}:${item.phase}${artifactSuffix}`;
}

function isBootstrapTask(taskId: string): boolean {
  return taskId.startsWith("bootstrap:");
}

function shouldAutoComplete(previous: LiveActivityItem, incoming: LiveActivityItem): boolean {
  if (previous.taskId !== incoming.taskId || previous.status !== "running") {
    return false;
  }

  const previousOrder = PHASE_ORDER[previous.phase] ?? 0;
  const incomingOrder = PHASE_ORDER[incoming.phase] ?? 0;

  return incomingOrder > previousOrder;
}

function completeSupersededActivities(current: LiveActivityItem[], incoming: LiveActivityItem): LiveActivityItem[] {
  return current.map((item) => {
    if (!shouldAutoComplete(item, incoming)) {
      return item;
    }

    return {
      ...item,
      status: "completed",
      progress: 100,
      createdAt: incoming.createdAt,
    };
  });
}

function normalizeLiveActivityEvent(payload: SocketEventPayload): LiveActivityItem | null {
  if (payload.type !== "agent_progress" || !payload.data) {
    return null;
  }

  const id = typeof payload.data.id === "string" ? payload.data.id : null;
  const taskId = typeof payload.data.taskId === "string" ? payload.data.taskId : null;
  const phase = typeof payload.data.phase === "string" ? (payload.data.phase as LiveActivityPhase) : null;
  const status = typeof payload.data.status === "string" ? (payload.data.status as LiveActivityStatus) : null;
  const createdAt = typeof payload.data.createdAt === "string" ? payload.data.createdAt : null;

  if (!id || !taskId || !phase || !status || !createdAt) {
    return null;
  }

  return {
    id,
    taskId,
    phase,
    status,
    progress: typeof payload.data.progress === "number" ? payload.data.progress : null,
    createdAt,
    artifactType: typeof payload.data.artifactType === "string" ? payload.data.artifactType : null,
    agentName: typeof payload.data.agentName === "string" ? payload.data.agentName : null,
    outputHint: typeof payload.data.outputHint === "string" ? payload.data.outputHint : null,
    rawFileName: typeof payload.data.rawFileName === "string" ? payload.data.rawFileName : null,
    moduleCount: typeof payload.data.moduleCount === "number" ? payload.data.moduleCount : 0,
    referenceCount: typeof payload.data.referenceCount === "number" ? payload.data.referenceCount : 0,
  };
}

export function getPrimaryLiveActivityItem(items: LiveActivityItem[]): LiveActivityItem | null {
  const active = items.find((item) => item.status === "running" || item.status === "waiting");
  return active ?? items[0] ?? null;
}

export function getDisplayLiveActivityItems(items: LiveActivityItem[]): LiveActivityItem[] {
  return [...items].sort((left, right) => {
    const timeDelta = new Date(left.createdAt).getTime() - new Date(right.createdAt).getTime();
    if (timeDelta !== 0) {
      return timeDelta;
    }

    const leftActive = left.status === "running" || left.status === "waiting";
    const rightActive = right.status === "running" || right.status === "waiting";
    if (leftActive === rightActive) {
      return 0;
    }
    return leftActive ? 1 : -1;
  });
}

export function mergeLiveActivityItems(current: LiveActivityItem[], incoming: LiveActivityItem): LiveActivityItem[] {
  const withoutBootstrap =
    !isBootstrapTask(incoming.taskId) ? current.filter((item) => !isBootstrapTask(item.taskId)) : current;
  const completed = completeSupersededActivities(withoutBootstrap, incoming);
  const incomingIdentity = activityIdentity(incoming);
  const deduped = completed.filter((item) => activityIdentity(item) !== incomingIdentity && item.id !== incoming.id);

  return [incoming, ...deduped]
    .sort((left, right) => new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime())
    .slice(0, 12);
}

export function reduceLiveActivityEvent(current: LiveActivityItem[], payload: SocketEventPayload): LiveActivityItem[] {
  const normalized = normalizeLiveActivityEvent(payload);
  if (!normalized) {
    return current;
  }
  return mergeLiveActivityItems(current, normalized);
}
