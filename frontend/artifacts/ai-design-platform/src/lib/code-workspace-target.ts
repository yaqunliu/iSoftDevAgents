export type CodeWorkspaceOpenTarget =
  | {
      kind: "doc";
      agent: string;
      fileName: string;
    }
  | {
      kind: "code";
      filePath: string;
    };

export type CodeWorkspaceSelectionRequest = CodeWorkspaceOpenTarget & {
  requestId: number;
};

type WorkspaceDocKeyItem = {
  key: string;
};

export function buildWorkspaceDocKey(agent: string, fileName: string): string {
  return `${agent}:${fileName}`;
}

export function resolveWorkspaceDocSelection(
  items: WorkspaceDocKeyItem[],
  requestedTarget: Extract<CodeWorkspaceOpenTarget, { kind: "doc" }>,
): string | null {
  const requestedKey = buildWorkspaceDocKey(requestedTarget.agent, requestedTarget.fileName);
  if (items.some((item) => item.key === requestedKey)) {
    return requestedKey;
  }
  return items[0]?.key ?? null;
}
