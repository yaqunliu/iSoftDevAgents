export function projectWorkspaceQueryKeys(projectId: string): unknown[][] {
  return [
    ["project-files", projectId],
    ["project-file", projectId],
    ["code-tree", projectId],
    ["code-file", projectId],
    ["code-modules", projectId],
    ["project-drafts", projectId],
  ];
}
