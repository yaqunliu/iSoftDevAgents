const MERMAID_BLOCK_FENCE = /^```(?:mermaid|mmd)\s*\n([\s\S]*?)\n```$/i;

const MERMAID_DIAGRAM_PREFIXES = [
  "flowchart",
  "graph",
  "sequenceDiagram",
  "classDiagram",
  "stateDiagram",
  "erDiagram",
  "journey",
  "gantt",
  "pie",
  "mindmap",
  "timeline",
  "gitGraph",
  "requirementDiagram",
  "quadrantChart",
  "xychart-beta",
  "C4Context",
  "C4Container",
  "C4Component",
  "C4Dynamic",
  "C4Deployment",
];

function normalizeContentLines(content: string): string[] {
  return content
    .trim()
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function isMermaidDiagramHeader(line: string): boolean {
  return MERMAID_DIAGRAM_PREFIXES.some((prefix) => line === prefix || line.startsWith(`${prefix} `));
}

/**
 * 接口注释：
 * 从一段文本里提取可以直接交给 mermaid 渲染器的源码。
 *
 * 兼容两种输入：
 * 1. 标准 markdown 围栏：```mermaid
 * 2. 需求 Agent / 架构 Agent 直接产出的“裸 mermaid 文本”
 */
export function extractMermaidSource(content: string): string | null {
  const trimmed = content.trim();
  if (!trimmed) {
    return null;
  }

  const fencedMatch = trimmed.match(MERMAID_BLOCK_FENCE);
  if (fencedMatch) {
    return fencedMatch[1]?.trim() || null;
  }

  const normalizedLines = normalizeContentLines(trimmed);
  if (!normalizedLines.length) {
    return null;
  }

  const firstMeaningfulLine = normalizedLines.find((line) => !line.startsWith("%%"));
  if (!firstMeaningfulLine) {
    return null;
  }

  return isMermaidDiagramHeader(firstMeaningfulLine) ? trimmed : null;
}

/**
 * 教学注释：
 * 这个布尔判断给前端展示层用，避免每个组件自己重复猜“这段 markdown 像不像 mermaid”。
 */
export function isLikelyMermaidDiagram(content: string): boolean {
  return extractMermaidSource(content) !== null;
}
