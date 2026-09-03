import type { AgentArtifactRecord, PlannedArtifactFile } from "@/hooks/use-api";

export type TimelineMessage = {
  id: string;
  projectId: string;
  role: "user" | "agent" | "system";
  type: "text" | "process_log" | "artifact_card" | "select_options" | "input_form" | "user_response";
  content: string;
  metadata?: Record<string, unknown> | null;
  parentId?: string | null;
  createdAt: string;
};

export type TimelineGroup = {
  message: TimelineMessage;
  children: TimelineMessage[];
};

export type TimelineEntry =
  | {
      kind: "message";
      message: TimelineMessage;
      children: TimelineMessage[];
    }
  | {
      kind: "task_round";
      taskId: string;
      anchorMessage: TimelineMessage;
      logs: TimelineGroup[];
      statusMessage?: TimelineMessage;
    };

type TaskRoundEntry = Extract<TimelineEntry, { kind: "task_round" }>;

export type PendingTaskRoundSeed = {
  taskId: string;
  prompt: string;
  createdAt: string;
};

export type ArtifactContentRecord = {
  id: string;
  projectId: string;
  version: number;
  type: "prd" | "ui" | "architecture" | "api_spec";
  title: string;
  content: string;
  sourceFiles?: string[];
  sourceAgent?: string;
  sourceStatus?: string;
  artifactKind?: string;
  displayPath?: string;
  rawSourceAvailable?: boolean;
  metadata?: Record<string, unknown> | null;
  createdAt: string;
};

export type ArtifactPanelTab = "prd" | "ui" | "arch" | "api";
export type ArtifactSectionStatus = "pending" | "running" | "completed" | "failed";

export type ArtifactSection = {
  id: string;
  label: string;
  fileName: string;
  status: ArtifactSectionStatus;
  content: string;
  sourceKind?: "document" | "raw";
  sourceAgent?: string | null;
};

export type ArtifactSourceSummary = {
  sourceAgent: string;
  sourceStatus: string;
  sourceFiles: string[];
  artifactKind: string;
  displayPath: string;
  rawSourceAvailable: boolean;
};

const DOCUMENT_SECTION_ID = "document";

export function getArtifactSectionIds(tab: ArtifactPanelTab): string[] {
  return [DOCUMENT_SECTION_ID];
}

function taskIdFromMetadata(message: TimelineMessage): string | null {
  const taskId = message.metadata?.taskId;
  return typeof taskId === "string" ? taskId : null;
}

function isTaskStatusMessage(message: TimelineMessage): boolean {
  return (
    message.role === "system" &&
    message.type === "text" &&
    typeof message.metadata?.taskId === "string" &&
    typeof message.metadata?.taskStatus === "string"
  );
}

function messageTimestamp(message: TimelineMessage | undefined): number {
  if (!message) {
    return 0;
  }
  return new Date(message.createdAt).getTime();
}

function isTaskAnchorMessage(message: TimelineMessage): boolean {
  return message.role === "user" && message.type === "text" && message.metadata?.taskRoundRole === "anchor";
}

function processLogPhaseIdentity(message: TimelineMessage): string | null {
  const phase = typeof message.metadata?.phase === "string" ? message.metadata.phase.trim() : "";
  if (phase) {
    return `phase:${phase}`;
  }
  const taskName = typeof message.metadata?.taskName === "string" ? message.metadata.taskName.trim() : "";
  if (taskName) {
    return `task:${taskName.toLowerCase()}`;
  }
  const content = message.content.trim();
  return content ? `content:${content.toLowerCase()}` : null;
}

function keepNewestProcessLogsPerPhase(logs: TimelineGroup[]): TimelineGroup[] {
  // 设计注释：
  // 同一条任务在“恢复后重试”时，会留下多条历史 process_log。
  // 这里按阶段身份去重，只保留每个阶段最新的一条，让界面默认展示“当前这轮最新现场”。
  const newestIndexByIdentity = new Map<string, number>();

  for (let index = 0; index < logs.length; index += 1) {
    const identity = processLogPhaseIdentity(logs[index]?.message);
    if (!identity) {
      continue;
    }
    newestIndexByIdentity.set(identity, index);
  }

  return logs.filter((group, index) => {
    const identity = processLogPhaseIdentity(group.message);
    if (!identity) {
      return true;
    }
    return newestIndexByIdentity.get(identity) === index;
  });
}

function compareMessagesChronologically(left: TimelineMessage, right: TimelineMessage): number {
  const leftTime = new Date(left.createdAt).getTime();
  const rightTime = new Date(right.createdAt).getTime();
  if (leftTime !== rightTime) {
    return leftTime - rightTime;
  }
  return left.id.localeCompare(right.id);
}

export function buildMessageTimeline(messages: TimelineMessage[]): TimelineEntry[] {
  return buildMessageTimelineWithPending(messages);
}

export function buildMessageTimelineWithPending(
  messages: TimelineMessage[],
  pendingTaskRound?: PendingTaskRoundSeed | null,
): TimelineEntry[] {
  const orderedMessages = [...messages].sort(compareMessagesChronologically);
  const messageIds = new Set(orderedMessages.map((message) => message.id));
  const childrenByParent = new Map<string, TimelineMessage[]>();
  const logsByTaskId = new Map<string, TimelineGroup[]>();
  const statusMessageByTaskId = new Map<string, TimelineMessage>();
  const groupedLogIds = new Set<string>();
  const groupedArtifactIds = new Set<string>();
  const groupedStatusMessageIds = new Set<string>();

  for (const message of orderedMessages) {
    if (message.type === "artifact_card" && message.parentId && messageIds.has(message.parentId)) {
      const current = childrenByParent.get(message.parentId) ?? [];
      current.push(message);
      childrenByParent.set(message.parentId, current);
    }
  }

  for (const children of childrenByParent.values()) {
    for (const child of children) {
      groupedArtifactIds.add(child.id);
    }
  }

  for (const message of orderedMessages) {
    if (isTaskStatusMessage(message)) {
      const taskId = taskIdFromMetadata(message);
      if (!taskId) {
        continue;
      }
      statusMessageByTaskId.set(taskId, message);
      groupedStatusMessageIds.add(message.id);
      continue;
    }
    if (message.type !== "process_log") {
      continue;
    }
    const taskId = taskIdFromMetadata(message);
    if (!taskId) {
      continue;
    }
    const group = {
      message,
      children: childrenByParent.get(message.id) ?? [],
    };
    const current = logsByTaskId.get(taskId) ?? [];
    current.push(group);
    logsByTaskId.set(taskId, keepNewestProcessLogsPerPhase(current));
    groupedLogIds.add(message.id);
  }

  const entries: TimelineEntry[] = [];
  const insertedTaskRounds = new Set<string>();
  const deferredTaskRounds: TaskRoundEntry[] = [];

  for (const message of orderedMessages) {
    if (groupedArtifactIds.has(message.id) || groupedLogIds.has(message.id) || groupedStatusMessageIds.has(message.id)) {
      continue;
    }

    entries.push({
      kind: "message",
      message,
      children: childrenByParent.get(message.id) ?? [],
    });

    if (!isTaskAnchorMessage(message)) {
      continue;
    }

    const taskId = taskIdFromMetadata(message);
    if (!taskId || insertedTaskRounds.has(taskId)) {
      continue;
    }
    const logs = logsByTaskId.get(taskId) ?? [];
    if (!logs.length) {
      continue;
    }
    deferredTaskRounds.push({
      kind: "task_round",
      taskId,
      anchorMessage: message,
      logs,
      statusMessage: statusMessageByTaskId.get(taskId),
    });
    insertedTaskRounds.add(taskId);
  }

  if (
    pendingTaskRound &&
    !insertedTaskRounds.has(pendingTaskRound.taskId) &&
    !orderedMessages.some((message) => taskIdFromMetadata(message) === pendingTaskRound.taskId)
  ) {
    const anchorMessage: TimelineMessage = {
      id: `pending:${pendingTaskRound.taskId}:anchor`,
      projectId: orderedMessages[0]?.projectId ?? "",
      role: "user",
      type: "text",
      content: pendingTaskRound.prompt,
      createdAt: pendingTaskRound.createdAt,
      metadata: {
        taskId: pendingTaskRound.taskId,
        taskRoundRole: "anchor",
        pending: true,
      },
    };
    const processLog: TimelineMessage = {
      id: `pending:${pendingTaskRound.taskId}:log`,
      projectId: anchorMessage.projectId,
      role: "agent",
      type: "process_log",
      content: "Starting the task and preparing the first process log.",
      createdAt: pendingTaskRound.createdAt,
      metadata: {
        taskId: pendingTaskRound.taskId,
        taskName: "Starting task",
        status: "running",
        pending: true,
      },
    };
    entries.push({
      kind: "message",
      message: anchorMessage,
      children: [],
    });
    deferredTaskRounds.push({
      kind: "task_round",
      taskId: pendingTaskRound.taskId,
      anchorMessage,
      logs: [{ message: processLog, children: [] }],
    });
  }

  deferredTaskRounds.sort((left, right) => {
    const leftTime = Math.max(
      messageTimestamp(left.anchorMessage),
      messageTimestamp(left.logs[left.logs.length - 1]?.message),
      messageTimestamp(left.statusMessage),
    );
    const rightTime = Math.max(
      messageTimestamp(right.anchorMessage),
      messageTimestamp(right.logs[right.logs.length - 1]?.message),
      messageTimestamp(right.statusMessage),
    );
    if (leftTime !== rightTime) {
      return leftTime - rightTime;
    }
    return left.taskId.localeCompare(right.taskId);
  });

  return [...entries, ...deferredTaskRounds];
}

export function moveActiveConfirmationEntryToTail(
  entries: TimelineEntry[],
  activeMessageId: string | null | undefined,
): TimelineEntry[] {
  if (!activeMessageId) {
    return entries;
  }

  const activeIndex = entries.findIndex(
    (entry) => entry.kind === "message" && entry.message.id === activeMessageId,
  );
  if (activeIndex < 0 || activeIndex === entries.length - 1) {
    return entries;
  }

  // 设计注释：
  // 当前任务进入等待确认时，聊天区会自动滚动到底部。
  // 任务轮卡片又固定被放在时间线末尾，结果确认卡可能被压到上方看不见。
  // 这里仅把“当前这一张活动确认卡”移到最后，确保用户一滚到底就能看到确认按钮，
  // 同时不去改动其他历史消息和旧任务轮次的顺序。
  const reordered = [...entries];
  const [activeEntry] = reordered.splice(activeIndex, 1);
  reordered.push(activeEntry);
  return reordered;
}

export function getDefaultSectionId(tab: ArtifactPanelTab): string {
  return getArtifactSectionIds(tab)[0] ?? DOCUMENT_SECTION_ID;
}

export function supportsDirectArtifactSave(tab: ArtifactPanelTab): boolean {
  return false;
}

export function buildArtifactEditPrompt({
  artifactLabel,
  sectionLabel,
  originalContent,
  editedContent,
}: {
  artifactLabel: string;
  sectionLabel: string;
  originalContent: string;
  editedContent: string;
}): string {
  return [
    `Update the ${artifactLabel} section \`${sectionLabel}\` based on the edited content below.`,
    "",
    "Original content:",
    originalContent,
    "",
    "Updated content:",
    editedContent,
    "",
    "Apply this change to the project artifacts and keep the rest of the project consistent.",
  ].join("\n");
}

export function buildArtifactSourceSummary(artifact: ArtifactContentRecord | null): ArtifactSourceSummary {
  return {
    sourceAgent: artifact?.sourceAgent ?? "unknown",
    sourceStatus: artifact?.sourceStatus ?? "unknown",
    sourceFiles: Array.isArray(artifact?.sourceFiles) ? artifact.sourceFiles : [],
    artifactKind: artifact?.artifactKind ?? "synthesized",
    displayPath: artifact?.displayPath ?? "",
    rawSourceAvailable: Boolean(artifact?.rawSourceAvailable),
  };
}

export function buildArtifactSections({
  tab,
  artifact,
  taskStatus,
  progress: _progress,
  plannedFiles = [],
  rawArtifactsByAgent,
}: {
  tab: ArtifactPanelTab;
  artifact: ArtifactContentRecord | null;
  taskStatus: "idle" | "running" | "waiting_user" | "completed" | "failed" | "cancelled";
  progress: number;
  plannedFiles?: PlannedArtifactFile[];
  rawArtifactsByAgent?: Record<string, AgentArtifactRecord[]> | undefined;
}): ArtifactSection[] {
  // 设计注释：
  // 主产物面板要按“谁真正产出了这个标签页里的正式文件”来收口。
  // API 标签页这里明确只认 coding_agent 的 `docs/API.yaml`，
  // 避免把 requirements 阶段的 `feature_tree.md`、`use_case.md` 再兜底挂进来。
  const allowedAgentsForTab =
    tab === "ui"
      ? new Set(["ui_agent"])
      : tab === "api"
        ? new Set(["coding_agent"])
      : tab === "arch"
        ? new Set(["architecture_agent"])
        : null;

  const rawArtifactLookup = new Map<string, AgentArtifactRecord>();
  for (const items of Object.values(rawArtifactsByAgent ?? {})) {
    for (const item of items ?? []) {
      rawArtifactLookup.set(`${item.agent}:${item.fileName}`, item);
    }
  }

  // 这里直接以后端 planned files 为准。
  // 这样用户在文件还没写出来之前，也能先看到“待生成 / 生成中 / 已生成 / 失败”。
  // 设计注释：
  // 主面板的文件归类规则统一由后端维护，前端这里只消费结果。
  // 不要在这里根据文件名再做一轮“看起来像 PRD / API / UI”的猜测，
  // 否则后端刚整理好的边界又会在前端被打乱。
  const matchedSections: ArtifactSection[] = [];
  const consumedRawKeys = new Set<string>();

  for (const file of plannedFiles) {
    if (allowedAgentsForTab && !allowedAgentsForTab.has(file.agent)) {
      continue;
    }
    const rawKey = `${file.agent}:${file.fileName}`;
    const matched = rawArtifactLookup.get(rawKey);
    if (matched) {
      consumedRawKeys.add(rawKey);
    }
    const normalizedStatus =
      file.status === "running" || file.status === "completed" || file.status === "failed" ? file.status : "pending";
    matchedSections.push({
      id: `raw:${file.agent}:${file.fileName}`,
      label: file.label,
      fileName: file.fileName,
      status: matched ? "completed" : normalizedStatus,
      content: typeof matched?.content === "string" ? matched.content : "",
      sourceKind: "raw",
      sourceAgent: file.agent,
    });
  }

  // 教学注释：
  // 历史版本或者旧任务有时拿不到 plannedFiles，这时退回到 mappedArtifactTypes 做兜底，
  // 依然保证展示的是“真实产物”，只是顺序退化为文件名字典序。
  // 这条兜底逻辑只能作为旧数据兼容，不能反过来当成新的归类规则来源。
  const backendArtifactType = tab === "arch" ? "architecture" : tab === "api" ? "api_spec" : tab;
  const fallbackSections = Array.from(rawArtifactLookup.values())
    .filter((item) => !consumedRawKeys.has(`${item.agent}:${item.fileName}`))
    .filter((item) => !allowedAgentsForTab || allowedAgentsForTab.has(item.agent))
    .filter((item) => item.mappedArtifactTypes.includes(backendArtifactType))
    .sort((left, right) => left.fileName.localeCompare(right.fileName))
    .map((item) => ({
      id: `raw:${item.agent}:${item.fileName}`,
      label: item.fileName,
      fileName: item.fileName,
      status: "completed" as const,
      content: typeof item.content === "string" ? item.content : "",
      sourceKind: "raw" as const,
      sourceAgent: item.agent,
    }));

  return [...matchedSections, ...fallbackSections];
}
