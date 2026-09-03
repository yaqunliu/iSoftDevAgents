import type { AgentArtifactRecord } from "@/hooks/use-api";

export const REQUIREMENTS_OUTPUT_PRIORITY = [
  "feature_tree.md",
  "survey.md",
  "draft_event_list.md",
  "draft_context_diagram.md",
] as const;

export type AgentOutputItem = {
  key: string;
  agent: string;
  artifact: AgentArtifactRecord;
};

export type AgentOutputGroup = {
  agent: string;
  items: AgentOutputItem[];
};

function priorityIndex(fileName: string, preferredFileNames: readonly string[]): number {
  const normalized = fileName.trim().toLowerCase();
  const index = preferredFileNames.findIndex((item) => item.trim().toLowerCase() === normalized);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

export function buildAgentOutputItems(
  artifactsByAgent: Record<string, AgentArtifactRecord[]> | undefined,
  agentName: string,
  preferredFileNames: readonly string[] = [],
): AgentOutputItem[] {
  const items = artifactsByAgent?.[agentName] ?? [];
  return [...items]
    .sort((left, right) => {
      const priorityDelta =
        priorityIndex(left.fileName, preferredFileNames) - priorityIndex(right.fileName, preferredFileNames);
      if (priorityDelta !== 0) {
        return priorityDelta;
      }
      return left.fileName.localeCompare(right.fileName);
    })
    .map((artifact) => ({
      key: `${agentName}:${artifact.fileName}`,
      agent: agentName,
      artifact,
    }));
}

export function findPreferredAgentOutput(
  artifactsByAgent: Record<string, AgentArtifactRecord[]> | undefined,
  agentName: string,
  preferredFileNames: readonly string[] = [],
): AgentOutputItem | null {
  return buildAgentOutputItems(artifactsByAgent, agentName, preferredFileNames)[0] ?? null;
}

export function buildArtifactPanelDocGroups(
  artifactsByAgent: Record<string, AgentArtifactRecord[]> | undefined,
): AgentOutputGroup[] {
  const requirements = buildAgentOutputItems(artifactsByAgent, "requirements_agent", REQUIREMENTS_OUTPUT_PRIORITY);
  const architecture = buildAgentOutputItems(artifactsByAgent, "architecture_agent");
  return [
    ...(requirements.length ? [{ agent: "requirements_agent", items: requirements }] : []),
    ...(architecture.length ? [{ agent: "architecture_agent", items: architecture }] : []),
  ];
}
