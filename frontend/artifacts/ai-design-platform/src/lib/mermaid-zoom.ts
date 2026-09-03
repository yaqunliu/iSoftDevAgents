const MIN_MERMAID_ZOOM = 0.5;
const MAX_MERMAID_ZOOM = 4;
const MERMAID_ZOOM_STEP = 0.25;

/**
 * 接口注释：
 * 统一限制 Mermaid 图表的缩放范围，避免一口气放得太大或缩得太小。
 */
export function clampMermaidZoom(value: number): number {
  if (!Number.isFinite(value)) {
    return 1;
  }
  return Math.min(MAX_MERMAID_ZOOM, Math.max(MIN_MERMAID_ZOOM, value));
}

/**
 * 教学注释：
 * 图表缩放只做固定步长，交互更稳定，也方便后续把当前倍率显示给用户。
 */
export function nextMermaidZoom(currentZoom: number, direction: "in" | "out"): number {
  const delta = direction === "in" ? MERMAID_ZOOM_STEP : -MERMAID_ZOOM_STEP;
  return clampMermaidZoom(Number((currentZoom + delta).toFixed(2)));
}

export const DEFAULT_MERMAID_ZOOM = 1;
