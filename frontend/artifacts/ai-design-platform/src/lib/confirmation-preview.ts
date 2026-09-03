import type { AgentArtifactRecord } from "@/hooks/use-api";

export function looksLikeMarkdown(value: string | null | undefined): boolean {
  const text = String(value ?? "").trim();
  if (!text) {
    return false;
  }
  return /(\*\*|__|`|^#\s|^- |\n- |\n\d+\. |\[.+\]\(.+\))/m.test(text);
}

export function findRequirementsFeatureTreePreview(
  artifactsByAgent: Record<string, AgentArtifactRecord[]> | undefined,
): AgentArtifactRecord | null {
  const requirementsArtifacts = artifactsByAgent?.requirements_agent ?? [];
  return (
    requirementsArtifacts.find((artifact) => artifact.fileName === "feature_tree.md") ??
    requirementsArtifacts.find((artifact) => artifact.fileName.endsWith("feature_tree.md")) ??
    null
  );
}
