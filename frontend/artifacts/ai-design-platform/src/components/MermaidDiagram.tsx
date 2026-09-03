import { useEffect, useId, useMemo, useState } from "react";

import { Expand, Minus, Plus, RotateCcw } from "lucide-react";

import { resolveMermaidRuntime, type MermaidRuntime } from "@/lib/mermaid-runtime";
import { Button } from "@/components/ui";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { DEFAULT_MERMAID_ZOOM, nextMermaidZoom } from "@/lib/mermaid-zoom";
import { cn } from "@/lib/utils";

declare global {
  interface Window {
    mermaid?: MermaidRuntime;
    __esbuild_esm_mermaid_nm?: {
      mermaid?: MermaidRuntime | { default?: MermaidRuntime };
    };
  }
}

type MermaidDiagramProps = {
  chart: string;
  className?: string;
};

let mermaidRuntimeLoader: Promise<MermaidRuntime> | null = null;

/**
 * 接口注释：
 * 这里统一从前端静态资源目录加载 Mermaid 浏览器运行时。
 *
 * 之所以不用 npm 依赖直连，是因为当前前端工作区依赖树已经比较复杂，
 * 小范围兼容修复时，直接加载静态运行文件更稳，避免被整个工作区安装流程卡住。
 */
function loadMermaidRuntime(): Promise<MermaidRuntime> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Mermaid runtime can only be loaded in the browser."));
  }

  const loadedRuntime = resolveMermaidRuntime(window);
  if (loadedRuntime) {
    return Promise.resolve(loadedRuntime);
  }

  if (mermaidRuntimeLoader) {
    return mermaidRuntimeLoader;
  }

  mermaidRuntimeLoader = new Promise<MermaidRuntime>((resolve, reject) => {
    const existingScript = document.querySelector<HTMLScriptElement>("script[data-mermaid-runtime='local']");
    const resolveRuntime = () => {
      const runtime = resolveMermaidRuntime(window);
      if (runtime) {
        resolve(runtime);
        return true;
      }
      return false;
    };

    if (resolveRuntime()) {
      return;
    }

    const script = existingScript ?? document.createElement("script");
    script.dataset.mermaidRuntime = "local";
    script.src = `${import.meta.env.BASE_URL}vendor/mermaid.min.js`;
    script.async = true;
    script.onload = () => {
      if (!resolveRuntime()) {
        reject(new Error("Mermaid runtime loaded, but the global API was not found."));
      }
    };
    script.onerror = () => {
      reject(new Error("Failed to load Mermaid runtime script."));
    };

    if (!existingScript) {
      document.head.appendChild(script);
    }
  });

  return mermaidRuntimeLoader;
}

export function MermaidDiagram({ chart, className }: MermaidDiagramProps) {
  const diagramId = useId().replace(/:/g, "-");
  const [svgMarkup, setSvgMarkup] = useState<string>("");
  const [renderError, setRenderError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(DEFAULT_MERMAID_ZOOM);
  const [previewOpen, setPreviewOpen] = useState(false);

  const zoomPercent = useMemo(() => `${Math.round(zoom * 100)}%`, [zoom]);
  const previewZoom = useMemo(() => `${Math.max(zoom * 100, 160)}%`, [zoom]);

  useEffect(() => {
    let active = true;

    async function renderChart() {
      try {
        const mermaid = await loadMermaidRuntime();

        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "loose",
          theme: "dark",
          suppressErrorRendering: true,
        });

        const { svg } = await mermaid.render(`artifact-mermaid-${diagramId}`, chart);
        if (!active) {
          return;
        }
        setSvgMarkup(svg);
        setRenderError(null);
      } catch (error) {
        if (!active) {
          return;
        }
        const message = error instanceof Error ? error.message : "Unknown mermaid render error.";
        setSvgMarkup("");
        setRenderError(message);
      }
    }

    renderChart();
    return () => {
      active = false;
    };
  }, [chart, diagramId]);

  if (renderError) {
    return (
      <div className={cn("mt-6 overflow-hidden rounded-2xl border border-amber-500/20 bg-amber-500/5", className)}>
        <div className="border-b border-amber-500/20 px-4 py-2 text-[11px] uppercase tracking-[0.2em] text-amber-200">
          Mermaid Diagram Source
        </div>
        <div className="px-4 py-3 text-xs text-amber-100/80">
          图表语法暂时无法渲染，下面保留原始 Mermaid 内容，方便继续排查。
        </div>
        <pre className="overflow-x-auto border-t border-amber-500/10 px-5 py-4 text-sm leading-7 text-slate-200">
          <code>{chart}</code>
        </pre>
      </div>
    );
  }

  if (!svgMarkup) {
    return (
      <div className={cn("mt-6 rounded-2xl border border-cyan-500/20 bg-cyan-500/5 px-5 py-8 text-center text-sm text-cyan-100/80", className)}>
        正在渲染 Mermaid 图表…
      </div>
    );
  }

  function renderDiagramCanvas(extraClassName?: string) {
    return (
      <div className={cn("overflow-auto bg-[#05080d] p-4 text-slate-100", extraClassName)}>
        <div
          className="[&_svg]:h-auto [&_svg]:max-w-none [&_svg]:min-w-max"
          style={{
            transform: `scale(${zoom})`,
            transformOrigin: "top left",
            width: previewZoom,
          }}
          dangerouslySetInnerHTML={{ __html: svgMarkup }}
        />
      </div>
    );
  }

  return (
    <>
      <div className={cn("mt-6 overflow-hidden rounded-2xl border border-cyan-500/20 bg-cyan-500/5", className)}>
        <div className="flex items-center justify-between gap-3 border-b border-cyan-500/20 px-4 py-2">
          <div className="text-[11px] uppercase tracking-[0.2em] text-cyan-200">
            Mermaid Diagram
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-cyan-100/70">{zoomPercent}</span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-cyan-100 hover:bg-cyan-500/10"
              onClick={() => setZoom((currentZoom) => nextMermaidZoom(currentZoom, "out"))}
            >
              <Minus className="h-3.5 w-3.5" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-cyan-100 hover:bg-cyan-500/10"
              onClick={() => setZoom(DEFAULT_MERMAID_ZOOM)}
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-cyan-100 hover:bg-cyan-500/10"
              onClick={() => setZoom((currentZoom) => nextMermaidZoom(currentZoom, "in"))}
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-cyan-100 hover:bg-cyan-500/10"
              onClick={() => setPreviewOpen(true)}
            >
              <Expand className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
        {renderDiagramCanvas("max-h-[65vh]")}
      </div>
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-h-[92vh] max-w-[95vw] overflow-hidden border-cyan-500/20 bg-[#071018] p-0 text-slate-100">
          <div className="flex items-center justify-between gap-3 border-b border-cyan-500/20 px-5 py-3">
            <DialogTitle className="text-sm font-medium text-cyan-100">Mermaid Diagram Preview</DialogTitle>
            <span className="pr-8 text-xs text-cyan-100/70">{zoomPercent}</span>
          </div>
          {renderDiagramCanvas("max-h-[calc(92vh-64px)]")}
        </DialogContent>
      </Dialog>
    </>
  );
}
