export type WorkspaceVersionState = {
  version: number | null;
  isPendingPreview: boolean;
};

export function resolveWorkspaceVersionState(
  displayedVersion: number | null | undefined,
  currentVersion: number | null | undefined,
  pendingVersion: number | null | undefined,
): WorkspaceVersionState {
  const normalizedVersion = typeof displayedVersion === "number" ? displayedVersion : null;
  const isPendingPreview =
    typeof normalizedVersion === "number" &&
    typeof currentVersion === "number" &&
    typeof pendingVersion === "number" &&
    pendingVersion > currentVersion &&
    normalizedVersion === pendingVersion;

  return {
    version: normalizedVersion,
    isPendingPreview,
  };
}

export function resolveHistoryEmptyPendingPreview(
  pendingVersion: number | null | undefined,
  currentVersion: number | null | undefined,
): number | null {
  if (
    typeof pendingVersion === "number" &&
    typeof currentVersion === "number" &&
    pendingVersion > currentVersion
  ) {
    return pendingVersion;
  }
  return null;
}
