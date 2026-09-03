export type WorkspaceMode = "docs" | "code";

export function shouldAutoSwitchWorkspaceMode(
  currentMode: WorkspaceMode,
  isDocsLoading: boolean,
  docCount: number,
): boolean {
  return currentMode === "docs" && !isDocsLoading && docCount === 0;
}
