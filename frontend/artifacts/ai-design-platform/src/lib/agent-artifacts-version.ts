export function resolveAgentArtifactsVersion(
  requestedVersion: number | null | undefined,
  currentVersion: number | null | undefined,
  pendingVersion: number | null | undefined,
): number | undefined {
  if (
    typeof requestedVersion === "number" &&
    typeof currentVersion === "number" &&
    requestedVersion === currentVersion &&
    typeof pendingVersion === "number" &&
    pendingVersion > currentVersion
  ) {
    return pendingVersion;
  }
  if (typeof requestedVersion !== "number") {
    if (
      typeof currentVersion === "number" &&
      typeof pendingVersion === "number" &&
      pendingVersion > currentVersion
    ) {
      return pendingVersion;
    }
    return undefined;
  }
  if (typeof currentVersion === "number" && requestedVersion !== currentVersion) {
    return requestedVersion;
  }
  return undefined;
}
