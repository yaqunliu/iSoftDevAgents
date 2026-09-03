import { useEffect, useMemo } from "react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Braces,
  CheckCircle2,
  Circle,
  FileCode2,
  FileText,
  History,
  LayoutTemplate,
  Loader2,
  Network,
  XCircle,
} from "lucide-react";
import { Badge, Button } from "@/components/ui";
import { MermaidDiagram } from "@/components/MermaidDiagram";
import {
  formatArtifactTypeLabel,
  useAgentArtifacts,
  useCurrentTask,
} from "@/hooks/use-api";
import {
  buildArtifactSections,
  type ArtifactPanelTab,
  type ArtifactSection,
} from "@/lib/artifact-view-model";
import { localizeArtifactFileLabel } from "@/lib/artifact-file-labels";
import {
} from "@/lib/artifact-render-mode";
import { resolveAgentArtifactsVersion } from "@/lib/agent-artifacts-version";
import { extractMermaidSource } from "@/lib/mermaid-detection";
import { getArtifactVersionHighlight } from "@/lib/version-history-link";
import { cn } from "@/lib/utils";

const TABS = [
  { id: "prd", labelKey: "artifact.tab.prd", icon: FileText },
  { id: "ui", labelKey: "artifact.tab.ui", icon: LayoutTemplate },
  { id: "arch", labelKey: "artifact.tab.arch", icon: Network },
  { id: "api", labelKey: "artifact.tab.api", icon: Braces },
] as const;

function renderYamlValue(value: string) {
  if (!value) {
    return null;
  }

  return (
    <span className="text-emerald-200">
      {value}
    </span>
  );
}

function renderYamlContent(content: string) {
  const lines = content.split("\n");
  return (
    <pre className="overflow-x-auto rounded-2xl border border-cyan-500/15 bg-[#071118] p-5 font-mono text-sm leading-7 text-slate-200 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)]">
      {lines.map((line, index) => {
        const commentMatch = line.match(/^(\s*#.*)$/);
        if (commentMatch) {
          return (
            <div key={`${index}-${line}`} className="text-slate-500">
              {commentMatch[1]}
            </div>
          );
        }

        const mappingMatch = line.match(/^(\s*-?\s*)([A-Za-z0-9_.-]+)(\s*:\s*)(.*)$/);
        if (!mappingMatch) {
          return (
            <div key={`${index}-${line}`} className="text-slate-300">
              {line || " "}
            </div>
          );
        }

        const [, indent, key, separator, value] = mappingMatch;
        return (
          <div key={`${index}-${line}`}>
            <span className="text-slate-500">{indent}</span>
            <span className="text-sky-300">{key}</span>
            <span className="text-slate-500">{separator}</span>
            {renderYamlValue(value)}
          </div>
        );
      })}
    </pre>
  );
}

function renderMarkdownPreview(content: string) {
  const bareMermaidSource = extractMermaidSource(content);
  if (bareMermaidSource) {
    return <MermaidDiagram chart={bareMermaidSource} />;
  }

  return (
    <div className="max-w-none text-[15px] leading-7 text-slate-200">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="text-3xl font-semibold tracking-tight text-slate-50">{children}</h1>,
          h2: ({ children }) => <h2 className="mt-10 border-t border-white/10 pt-6 text-2xl font-semibold text-slate-50">{children}</h2>,
          h3: ({ children }) => <h3 className="mt-8 text-lg font-semibold text-slate-100">{children}</h3>,
          p: ({ children }) => <p className="mt-4 text-slate-300">{children}</p>,
          ul: ({ children }) => <ul className="mt-4 list-disc space-y-2 pl-6 text-slate-300">{children}</ul>,
          ol: ({ children }) => <ol className="mt-4 list-decimal space-y-2 pl-6 text-slate-300">{children}</ol>,
          li: ({ children }) => <li className="pl-1">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="mt-6 rounded-r-2xl border-l-4 border-cyan-400/60 bg-cyan-500/5 px-5 py-4 text-slate-200">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="my-8 border-white/10" />,
          table: ({ children }) => (
            <div className="mt-6 overflow-x-auto rounded-2xl border border-white/10 bg-black/30">
              <table className="min-w-full border-collapse text-left text-sm">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-white/5 text-slate-100">{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr className="border-t border-white/10">{children}</tr>,
          th: ({ children }) => <th className="px-4 py-3 font-semibold">{children}</th>,
          td: ({ children }) => <td className="px-4 py-3 align-top text-slate-300">{children}</td>,
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-cyan-200 underline decoration-cyan-500/40 underline-offset-4 hover:text-cyan-100"
            >
              {children}
            </a>
          ),
          code: ({ className, children }) => {
            const content = String(children);
            const isInlineCode = !className && !content.includes("\n");
            if (isInlineCode) {
              return (
                <code className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[0.9em] text-cyan-200">
                  {children}
                </code>
              );
            }
            const language = className?.replace("language-", "") ?? "";
            const isMermaid = language === "mermaid";
            if (isMermaid) {
              return <MermaidDiagram chart={content.trim()} />;
            }
            return (
              <div className={cn("mt-6 overflow-hidden rounded-2xl border border-white/10 bg-[#05080d]")}>
                <div className={cn("border-b border-white/10 px-4 py-2 text-[11px] uppercase tracking-[0.2em] text-slate-400")}>
                  {language || "Code Block"}
                </div>
                <pre className="overflow-x-auto p-5 text-sm leading-7 text-slate-200">
                  <code className={className}>{children}</code>
                </pre>
              </div>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function SectionStatusIcon({ status }: { status: ArtifactSection["status"] }) {
  if (status === "completed") {
    return <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />;
  }
  if (status === "running") {
    return <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />;
  }
  if (status === "failed") {
    return <XCircle className="w-3.5 h-3.5 text-rose-400" />;
  }
  return <Circle className="w-3.5 h-3.5 text-muted-foreground/50" />;
}

function renderRawSourceContent(fileName: string, content: string) {
  const normalized = fileName.toLowerCase();
  if (normalized.endsWith(".md") || normalized.endsWith(".markdown")) {
    return renderMarkdownPreview(content);
  }
  if (normalized.endsWith(".yaml") || normalized.endsWith(".yml")) {
    return renderYamlContent(content);
  }
  return (
    <pre className="max-h-[48vh] overflow-auto rounded-2xl border border-white/10 bg-[#05080d] p-5 text-sm leading-7 text-slate-200">
      {content}
    </pre>
  );
}

export function ArtifactViewer({
  projectId,
  activeTab,
  activeSectionId,
  selectedVersion,
  highlightedChanges,
  currentVersion,
  onVersionChange,
  onTabChange,
  onSectionChange,
  onOpenCodeWorkspace,
  onOpenHistory,
}: {
  projectId: string;
  activeTab: string;
  activeSectionId: string | null;
  selectedVersion: number | null;
  highlightedChanges: Array<{ file: string; status: "Modified" | "Added" | "Deleted" }>;
  currentVersion?: number;
  onVersionChange: (version: number | null) => void;
  onTabChange: (t: string) => void;
  onSectionChange: (sectionId: string | null) => void;
  onOpenCodeWorkspace: () => void;
  onOpenHistory: () => void;
}) {
  const { t } = useTranslation();
  const artifactTab = (activeTab === "ui" || activeTab === "arch" || activeTab === "api" ? activeTab : "prd") as ArtifactPanelTab;
  const { data: currentTask } = useCurrentTask(projectId);
  const plannedFilesByArtifact = currentTask?.plannedArtifactFiles ?? {};
  const plannedFilesForTab = useMemo(() => {
    if (artifactTab === "arch") {
      return plannedFilesByArtifact.architecture ?? [];
    }
    if (artifactTab === "api") {
      return plannedFilesByArtifact.api_spec ?? [];
    }
    return plannedFilesByArtifact[artifactTab] ?? [];
  }, [artifactTab, plannedFilesByArtifact]);
  const displayedVersion = selectedVersion ?? currentVersion ?? null;
  const isHistoricalVersion =
    typeof displayedVersion === "number" &&
    typeof currentVersion === "number" &&
    displayedVersion !== currentVersion;
  const rawAgentArtifactsVersion = resolveAgentArtifactsVersion(
    displayedVersion,
    currentVersion,
    currentTask?.pendingAgentArtifactsVersion,
  );
  const { data: rawAgentArtifacts, isLoading, isError } = useAgentArtifacts(projectId, rawAgentArtifactsVersion, projectId !== "new");

  const sections = useMemo(
    () =>
      buildArtifactSections({
        tab: artifactTab,
        artifact: null,
        taskStatus: currentTask?.status ?? "idle",
        progress: 0,
        plannedFiles: plannedFilesForTab,
        rawArtifactsByAgent: rawAgentArtifacts?.artifactsByAgent,
      }),
    [artifactTab, currentTask?.status, plannedFilesForTab, rawAgentArtifacts?.artifactsByAgent],
  );

  useEffect(() => {
    if (!sections.length) {
      if (activeSectionId !== null) {
        onSectionChange(null);
      }
      return;
    }
    const currentExists = activeSectionId ? sections.some((section) => section.id === activeSectionId) : false;
    if (!currentExists) {
      onSectionChange(sections[0]?.id ?? null);
    }
  }, [activeSectionId, onSectionChange, sections]);

  const selectedSection =
    sections.find((section) => section.id === activeSectionId) ??
    sections[0] ??
    null;
  const localizedSelectedSectionLabel = selectedSection
    ? localizeArtifactFileLabel(t, selectedSection.fileName, selectedSection.label)
    : null;
  const versionHighlight = useMemo(() => {
    if (selectedVersion === null) {
      return { changed: false, sectionIds: [] as string[] };
    }
    const baseHighlight = getArtifactVersionHighlight(artifactTab, highlightedChanges);
    return {
      changed: baseHighlight.changed,
      // 设计注释：
      // 现在每个标签页只展示真实文件，所以历史高亮需要落到“当前可见文件”，
      // 不能再落到旧的 document 占位 section。
      sectionIds: baseHighlight.changed ? sections.map((section) => section.id) : [],
    };
  }, [artifactTab, highlightedChanges, sections, selectedVersion]);
  const showGeneratingState = currentTask?.status === "running" && !sections.length;
  const showSelectedSectionGeneratingState =
    selectedSection?.status === "running" &&
    !selectedSection.content;
  const showArtifactLoadingSpinner = isLoading && !sections.length && !showGeneratingState;
  const renderArtifactBody = () => {
    if (!selectedSection) {
      return null;
    }

    return renderRawSourceContent(selectedSection.fileName, selectedSection.content);
  };

  return (
    <div className="flex flex-col h-full bg-[#0d0d0d] relative overflow-hidden">
      <div className="flex items-center justify-between px-6 h-14 border-b border-white/10 bg-background/50 backdrop-blur-md z-10">
        <div className="flex gap-6 h-full">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => onTabChange(tab.id)}
                className={cn(
                  "flex items-center gap-2 h-full text-sm font-medium transition-colors relative",
                  isActive ? "text-primary" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <tab.icon className="w-4 h-4" />
                {t(tab.labelKey)}
                {isActive ? <motion.div layoutId="active-tab" className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary" /> : null}
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-3">
          {displayedVersion ? <Badge variant="outline" className="bg-secondary text-muted-foreground">v{displayedVersion}</Badge> : null}
          <Button variant="ghost" size="sm" onClick={onOpenCodeWorkspace} className="text-muted-foreground hover:text-foreground">
            <FileCode2 className="w-4 h-4 mr-2" />
            {t("code.title")}
          </Button>
          <Button variant="ghost" size="sm" onClick={onOpenHistory} className="text-muted-foreground hover:text-foreground">
            <History className="w-4 h-4 mr-2" />
            {t("artifact.history")}
          </Button>
        </div>
      </div>

      <div className="border-b border-white/10 bg-black/30 px-6 py-3">
        {isHistoricalVersion ? (
          <div className="mb-3 rounded-xl border border-cyan-500/20 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-100">
            {t("artifact.historicalVersionNotice", {
              defaultValue: "当前看到的是历史版本 v{{version}}。如果在这里继续编辑，系统会创建一个新版本，不会覆盖旧记录。",
              version: displayedVersion,
            })}
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          {sections.length > 1 ? (
            sections.map((section) => {
              const isActive = selectedSection?.id === section.id;
              return (
                <button
                  key={section.id}
                  onClick={() => onSectionChange(section.id)}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors whitespace-nowrap",
                    isActive
                      ? "border-primary/40 bg-primary/10 text-foreground"
                      : "border-white/10 bg-black/20 text-muted-foreground hover:text-foreground hover:bg-white/5",
                    versionHighlight.sectionIds.includes(section.id) && "border-emerald-400/40 bg-emerald-500/10 text-emerald-100",
                  )}
                >
                  <SectionStatusIcon status={section.status} />
                  <span>{section.fileName}</span>
                </button>
              );
            })
          ) : selectedSection ? (
            <div className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-muted-foreground">
              <SectionStatusIcon status={selectedSection.status} />
              <span>{selectedSection.fileName}</span>
            </div>
          ) : null}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-8 relative">
        {showArtifactLoadingSpinner ? (
          <div className="h-full flex items-center justify-center">
            <div className="flex flex-col items-center gap-4 text-muted-foreground">
              <div className="w-10 h-10 border-4 border-primary/20 border-t-primary rounded-full animate-spin" />
              {t("artifact.loading")}
            </div>
          </div>
        ) : isError && !sections.length ? (
          <div className="h-full flex items-center justify-center">
            <div className="max-w-md rounded-2xl border border-white/10 bg-card/50 px-6 py-8 text-center text-muted-foreground">
              {t("artifact.empty")}
            </div>
          </div>
        ) : selectedSection ? (
          <motion.div
            key={`${activeTab}-${selectedSection.id}`}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
            className="max-w-4xl mx-auto space-y-4"
          >
            {versionHighlight.changed ? (
              <div className="rounded-2xl border border-emerald-400/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">
                {t("history.artifactHighlight", { version: displayedVersion ?? selectedVersion })}
              </div>
            ) : null}
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{formatArtifactTypeLabel(artifactTab === "arch" ? "architecture" : artifactTab === "api" ? "api_spec" : artifactTab)}</div>
                <h2 className="text-2xl font-semibold text-foreground mt-1">{localizedSelectedSectionLabel}</h2>
              </div>
              <Badge
                variant="outline"
                className={cn(
                  "border-white/10",
                  selectedSection.status === "completed" && "border-green-500/30 bg-green-500/10 text-green-200",
                  selectedSection.status === "running" && "border-primary/30 bg-primary/10 text-primary",
                  selectedSection.status === "pending" && "bg-black/20 text-muted-foreground",
                  selectedSection.status === "failed" && "border-rose-500/30 bg-rose-500/10 text-rose-200",
                )}
              >
                {selectedSection.status === "completed"
                  ? t("artifact.sectionCompleted")
                  : selectedSection.status === "running"
                    ? t("artifact.sectionGenerating")
                    : selectedSection.status === "failed"
                      ? t("artifact.sectionFailed")
                  : t("artifact.sectionPending")}
              </Badge>
            </div>

            {selectedSection.sourceKind === "raw" ? (
              <div className="rounded-3xl border border-white/10 bg-black/20 p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className="border-white/10 bg-white/5 text-slate-200">
                    {t("artifact.sourceAgent")}: {t(`chat.source.${selectedSection.sourceAgent}`, { defaultValue: selectedSection.sourceAgent ?? "unknown" })}
                  </Badge>
                  <Badge variant="outline" className="border-white/10 bg-white/5 font-mono text-slate-300">
                    {selectedSection.fileName}
                  </Badge>
                </div>
              </div>
            ) : null}

            {selectedSection.content ? (
              <div
                className={cn(
                  versionHighlight.sectionIds.includes(selectedSection.id) &&
                    "rounded-3xl border border-emerald-400/35 bg-emerald-500/5 p-5",
                )}
              >
                {renderArtifactBody()}
              </div>
            ) : showGeneratingState || showSelectedSectionGeneratingState ? (
              <div className="rounded-2xl border border-primary/20 bg-primary/5 p-8">
                <div className="flex items-center gap-3 text-primary">
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span className="text-sm font-medium">{t("artifact.generatingPanel")}</span>
                </div>
              </div>
            ) : (
              <div className="rounded-2xl border border-white/10 bg-card/50 px-6 py-8 text-center text-muted-foreground">
                {t("artifact.empty")}
              </div>
            )}
          </motion.div>
        ) : (
          <div className="h-full flex items-center justify-center">
            <div className="max-w-md rounded-2xl border border-white/10 bg-card/50 px-6 py-8 text-center text-muted-foreground">
              {t("artifact.empty")}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
