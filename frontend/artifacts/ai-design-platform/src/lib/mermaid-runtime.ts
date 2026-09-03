type MermaidRuntime = {
  initialize: (config: Record<string, unknown>) => void;
  render: (id: string, chart: string) => Promise<{ svg: string }> | { svg: string };
};

type MermaidWindowLike = {
  mermaid?: MermaidRuntime;
  __esbuild_esm_mermaid_nm?: {
    mermaid?: MermaidRuntime | { default?: MermaidRuntime };
  };
};

/**
 * 接口注释：
 * 统一从浏览器全局对象里解析 Mermaid 运行时。
 *
 * 现在要兼容两种挂载方式：
 * 1. `window.mermaid`
 * 2. `window.__esbuild_esm_mermaid_nm.mermaid.default`
 */
export function resolveMermaidRuntime(windowLike: MermaidWindowLike | undefined | null): MermaidRuntime | null {
  if (!windowLike) {
    return null;
  }

  if (windowLike.mermaid) {
    return windowLike.mermaid;
  }

  const bundledRuntime = windowLike.__esbuild_esm_mermaid_nm?.mermaid;
  if (!bundledRuntime) {
    return null;
  }

  if (typeof (bundledRuntime as MermaidRuntime).render === "function") {
    return bundledRuntime as MermaidRuntime;
  }

  const defaultRuntime = (bundledRuntime as { default?: MermaidRuntime }).default;
  return defaultRuntime ?? null;
}

export type { MermaidRuntime, MermaidWindowLike };
