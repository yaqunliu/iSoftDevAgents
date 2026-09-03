import type { LiveActivityItem } from "./task-activity.ts";

export type PendingProjectGeneration = {
  projectId: string;
  prompt: string;
  uploadedFileIds: string[];
  createdAt: string;
};

function storageKey(projectId: string): string {
  return `isoftdevagents.pendingProjectGeneration.${projectId}`;
}

export function savePendingProjectGeneration(
  storage: Pick<Storage, "setItem">,
  pending: PendingProjectGeneration,
): void {
  storage.setItem(storageKey(pending.projectId), JSON.stringify(pending));
}

export function readPendingProjectGeneration(
  storage: Pick<Storage, "getItem">,
  projectId: string,
): PendingProjectGeneration | null {
  const raw = storage.getItem(storageKey(projectId));
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as PendingProjectGeneration;
    if (
      typeof parsed.projectId !== "string" ||
      typeof parsed.prompt !== "string" ||
      !Array.isArray(parsed.uploadedFileIds) ||
      typeof parsed.createdAt !== "string"
    ) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function clearPendingProjectGeneration(
  storage: Pick<Storage, "removeItem">,
  projectId: string,
): void {
  storage.removeItem(storageKey(projectId));
}

export function buildPendingGenerationActivityItems(projectId: string, createdAt: string): LiveActivityItem[] {
  return [
    {
      id: `bootstrap:${projectId}:reading_context`,
      taskId: `bootstrap:${projectId}`,
      phase: "reading_context",
      status: "running",
      progress: 10,
      createdAt,
      artifactType: null,
      agentName: null,
      outputHint: null,
      rawFileName: null,
      moduleCount: 0,
      referenceCount: 0,
    },
    {
      id: `bootstrap:${projectId}:queued`,
      taskId: `bootstrap:${projectId}`,
      phase: "queued",
      status: "completed",
      progress: 0,
      createdAt,
      artifactType: null,
      agentName: null,
      outputHint: null,
      rawFileName: null,
      moduleCount: 0,
      referenceCount: 0,
    },
  ];
}
