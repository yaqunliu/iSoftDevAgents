import type { AgentArtifactRecord, Message, StepRecord } from "@/hooks/use-api";

export type StepOutputFile = {
  id: string;
  fileName: string;
  agent: string;
  fileType: string;
  contentType: string;
  content: string;
  isPrimarySource: boolean;
  mappedArtifactTypes: string[];
};

export type StepOutputGroup = {
  stepId: string;
  stepName: string;
  sourceAgent: string | null;
  files: StepOutputFile[];
  primaryFile: StepOutputFile | null;
};

function normalizeLabel(value: string | null | undefined): string {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function tokenSet(value: string | null | undefined): Set<string> {
  return new Set(
    normalizeLabel(value)
      .split(/\s+/)
      .filter((token) => token.length > 1),
  );
}

function scoreNameSimilarity(left: string | null | undefined, right: string | null | undefined): number {
  const leftTokens = tokenSet(left);
  const rightTokens = tokenSet(right);
  if (!leftTokens.size || !rightTokens.size) {
    return 0;
  }
  let score = 0;
  for (const token of leftTokens) {
    if (rightTokens.has(token)) {
      score += 1;
    }
  }
  return score;
}

function flattenArtifacts(artifactsByAgent: Record<string, AgentArtifactRecord[]> | undefined): AgentArtifactRecord[] {
  if (!artifactsByAgent) {
    return [];
  }
  return Object.values(artifactsByAgent).flatMap((items) => items ?? []);
}

function metadataOutputFiles(metadata: Record<string, unknown>): string[] {
  const explicitFiles = Array.isArray(metadata.outputFiles)
    ? metadata.outputFiles.map((file) => String(file).trim()).filter((file) => file.length > 0)
    : [];
  if (explicitFiles.length) {
    return explicitFiles;
  }
  const rawFileName = typeof metadata.rawFileName === "string" ? metadata.rawFileName.trim() : "";
  return rawFileName ? [rawFileName] : [];
}

function preferredFileScore(file: StepOutputFile): number {
  let score = 0;
  if (file.fileName === "feature_tree.md") {
    score += 100;
  }
  if (file.isPrimarySource) {
    score += 20;
  }
  if (file.fileName.endsWith(".md")) {
    score += 10;
  }
  if (file.fileName.endsWith(".json") || file.fileName.endsWith(".yaml") || file.fileName.endsWith(".yml")) {
    score += 5;
  }
  score -= file.fileName.length / 1000;
  return score;
}

function buildOutputFiles(step: StepRecord, artifacts: AgentArtifactRecord[]): StepOutputFile[] {
  const metadata = step.metadata ?? {};
  const sourceAgent = typeof metadata.sourceAgent === "string" ? metadata.sourceAgent : null;
  const outputFiles = Array.isArray(metadata.outputFiles)
    ? metadata.outputFiles.filter((file): file is string => typeof file === "string" && file.trim().length > 0)
    : [];

  const byAgent = sourceAgent ? artifacts.filter((artifact) => artifact.agent === sourceAgent) : artifacts;
  const resolved: StepOutputFile[] = outputFiles.map((fileName, index) => {
    const matched =
      byAgent.find((artifact) => artifact.fileName === fileName) ??
      artifacts.find((artifact) => artifact.fileName === fileName);
    return {
      id: matched?.id ?? `${step.id}:${fileName}:${index}`,
      fileName,
      agent: matched?.agent ?? sourceAgent ?? "unknown",
      fileType: matched?.fileType ?? "text",
      contentType: matched?.contentType ?? "text/plain",
      content: typeof matched?.content === "string" ? matched.content : "",
      isPrimarySource: Boolean(matched?.isPrimarySource),
      mappedArtifactTypes: Array.isArray(matched?.mappedArtifactTypes) ? matched.mappedArtifactTypes : [],
    };
  });

  return resolved.sort((left, right) => preferredFileScore(right) - preferredFileScore(left));
}

function resolveOutputFiles(
  fileNames: string[],
  artifacts: AgentArtifactRecord[],
  sourceAgent: string | null,
  scopeId: string,
): StepOutputFile[] {
  const byAgent = sourceAgent ? artifacts.filter((artifact) => artifact.agent === sourceAgent) : artifacts;
  const resolved: StepOutputFile[] = fileNames.map((fileName, index) => {
    const matched =
      byAgent.find((artifact) => artifact.fileName === fileName) ??
      artifacts.find((artifact) => artifact.fileName === fileName);
    return {
      id: matched?.id ?? `${scopeId}:${fileName}:${index}`,
      fileName,
      agent: matched?.agent ?? sourceAgent ?? "unknown",
      fileType: matched?.fileType ?? "text",
      contentType: matched?.contentType ?? "text/plain",
      content: typeof matched?.content === "string" ? matched.content : "",
      isPrimarySource: Boolean(matched?.isPrimarySource),
      mappedArtifactTypes: Array.isArray(matched?.mappedArtifactTypes) ? matched.mappedArtifactTypes : [],
    };
  });

  return resolved.sort((left, right) => preferredFileScore(right) - preferredFileScore(left));
}

function primaryFileFor(files: StepOutputFile[]): StepOutputFile | null {
  return files[0] ?? null;
}

function messageSourceAgent(metadata: Record<string, unknown>): string | null {
  const sourceAgent =
    (typeof metadata.sourceAgent === "string" && metadata.sourceAgent) ||
    (typeof metadata.agentName === "string" && metadata.agentName) ||
    "";
  return sourceAgent || null;
}

function phaseScopedSourceAgent(phase: string): string | null {
  if (phase === "architecture_generation_started") {
    return "architecture_agent";
  }
  if (phase.startsWith("ui_generation")) {
    return "ui_agent";
  }
  if (phase.startsWith("code_generation")) {
    return "coding_agent";
  }
  if (phase.startsWith("test_generation")) {
    return "test_agent";
  }
  return null;
}

export function buildStepOutputGroups(
  steps: StepRecord[],
  artifactsByAgent: Record<string, AgentArtifactRecord[]> | undefined,
): StepOutputGroup[] {
  const artifacts = flattenArtifacts(artifactsByAgent);

  return steps
    .map((step) => {
      const metadata = step.metadata ?? {};
      const files = buildOutputFiles(step, artifacts);
      return {
        stepId: step.id,
        stepName: step.stepName,
        sourceAgent: typeof metadata.sourceAgent === "string" ? metadata.sourceAgent : null,
        files,
        primaryFile: primaryFileFor(files),
      } satisfies StepOutputGroup;
    })
    .filter((group) => group.files.length > 0);
}

function phaseHintForMessage(message: Message): ((group: StepOutputGroup) => boolean) | null {
  const metadata = (message.metadata ?? {}) as Record<string, unknown>;
  const phase = typeof metadata.phase === "string" ? metadata.phase : "";
  const scopedSourceAgent = phaseScopedSourceAgent(phase);
  if (scopedSourceAgent) {
    // 设计注释：
    // 一旦实时日志已经进入明确的 Agent 阶段，就只能展示这个 Agent 自己的产物。
    // 这样架构阶段不会再把 requirements 的 feature_tree.md 借过来挂在自己头上。
    return (group) => group.sourceAgent === scopedSourceAgent;
  }

  if (phase === "requirements_analysis") {
    return (group) =>
      group.files.some((file) => file.fileName === "feature_tree.md") ||
      normalizeLabel(group.stepName).includes("analyze requirements");
  }
  return null;
}

function buildMessageOutputGroup(
  message: Message,
  artifactsByAgent: Record<string, AgentArtifactRecord[]> | undefined,
): StepOutputGroup | null {
  const metadata = (message.metadata ?? {}) as Record<string, unknown>;
  // 设计注释：
  // 这里必须保留当前实时日志自己声明的完整 outputFiles。
  // 用户看到的“任务进度产物”应该和右侧真实目录树尽量一致，
  // 不能因为这些文件在更早步骤里出现过，就在当前日志卡片里把它们删掉。
  const outputFiles = metadataOutputFiles(metadata);
  if (!outputFiles.length) {
    return null;
  }
  const artifacts = flattenArtifacts(artifactsByAgent);
  const sourceAgent =
    (typeof metadata.sourceAgent === "string" && metadata.sourceAgent) ||
    (typeof metadata.agentName === "string" && metadata.agentName) ||
    null;
  const files = resolveOutputFiles(outputFiles, artifacts, sourceAgent, `log:${message.id}`);
  if (!files.length) {
    return null;
  }
  return {
    stepId: `log:${message.id}`,
    stepName:
      (typeof metadata.taskName === "string" && metadata.taskName) ||
      message.content ||
      "Live outputs",
    sourceAgent,
    files,
    primaryFile: primaryFileFor(files),
  };
}

export function findStepOutputGroupForLog(
  message: Message,
  steps: StepRecord[],
  artifactsByAgent: Record<string, AgentArtifactRecord[]> | undefined,
): StepOutputGroup | null {
  const messageOutputGroup = buildMessageOutputGroup(message, artifactsByAgent);
  if (messageOutputGroup) {
    return messageOutputGroup;
  }

  const groups = buildStepOutputGroups(steps, artifactsByAgent);
  if (!groups.length) {
    return null;
  }

  const phaseHint = phaseHintForMessage(message);
  if (phaseHint) {
    const phaseMatched = groups.find(phaseHint);
    if (phaseMatched) {
      return phaseMatched;
    }
  }

  const metadata = (message.metadata ?? {}) as Record<string, unknown>;
  const taskName = typeof metadata.taskName === "string" ? metadata.taskName : "";
  const candidates = [taskName, message.content];
  const scopedSourceAgent = phaseScopedSourceAgent(typeof metadata.phase === "string" ? metadata.phase : "");
  const explicitSourceAgent = messageSourceAgent(metadata);
  const requiredSourceAgent = scopedSourceAgent || explicitSourceAgent;
  const candidateGroups = requiredSourceAgent
    ? groups.filter((group) => group.sourceAgent === requiredSourceAgent)
    : groups;

  // 教学注释：
  // 如果当前日志已经带了 sourceAgent / phase，但历史步骤里一个同 Agent 的组都没有，
  // 这里宁可返回空，也不要错误回退到别的 Agent 历史文件。
  if (requiredSourceAgent && !candidateGroups.length) {
    return null;
  }

  let bestGroup: StepOutputGroup | null = null;
  let bestScore = 0;
  for (const group of candidateGroups) {
    const score = Math.max(...candidates.map((candidate) => scoreNameSimilarity(candidate, group.stepName)), 0);
    if (score > bestScore) {
      bestGroup = group;
      bestScore = score;
    }
  }

  return bestGroup;
}
