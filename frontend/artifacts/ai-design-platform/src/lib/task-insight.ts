import type { CurrentTask } from "@/hooks/use-api";

type ArtifactSourceEntry = {
  source?: string;
  status?: string;
  model?: string;
};

export type TaskInsightModel = {
  analysisSource: string | null;
  analysisReason: string | null;
  artifactSources: Array<{
    artifactType: "prd" | "ui" | "architecture" | "api_spec";
    source: string;
    status: string | null;
    model: string | null;
  }>;
  contextStats: Array<{
    id: "references" | "modules" | "existingArtifacts";
    value: number;
  }>;
};

const ARTIFACT_ORDER = ["prd", "ui", "architecture", "api_spec"] as const;

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function asCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function buildTaskInsightModel(task: CurrentTask | null | undefined): TaskInsightModel {
  const outputData = asRecord(task?.outputData);
  const artifactSourceRecord = asRecord(outputData?.artifactSources);
  const contextSummary = asRecord(outputData?.contextSummary);

  const artifactSources = ARTIFACT_ORDER.flatMap((artifactType) => {
    const entry = asRecord(artifactSourceRecord?.[artifactType]) as ArtifactSourceEntry | null;
    if (!entry?.source || typeof entry.source !== "string") {
      return [];
    }
    return [
      {
        artifactType,
        source: entry.source,
        status: typeof entry.status === "string" ? entry.status : null,
        model: typeof entry.model === "string" ? entry.model : null,
      },
    ];
  });

  return {
    analysisSource: typeof outputData?.analysisSource === "string" ? outputData.analysisSource : null,
    analysisReason: typeof outputData?.analysisReason === "string" ? outputData.analysisReason : null,
    artifactSources,
    contextStats: [
      { id: "references", value: asCount(contextSummary?.referenceFileCount) },
      { id: "modules", value: asCount(contextSummary?.selectedModuleCount) },
      { id: "existingArtifacts", value: asCount(contextSummary?.existingArtifactCount) },
    ],
  };
}
