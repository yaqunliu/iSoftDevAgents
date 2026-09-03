import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  BookMarked,
  Braces,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock,
  Cpu,
  FileText,
  FileCode2,
  LayoutTemplate,
  Loader2,
  Network,
  Paperclip,
  Send,
  SquareX,
} from "lucide-react";
import { Badge, Button, Textarea } from "@/components/ui";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  ApiError,
  type ExistingArtifactContext,
  formatArtifactType,
  formatArtifactTypeLabel,
  formatDateDistance,
  type ArtifactCardMetadata,
  type CurrentTaskResponse,
  type CurrentTask,
  type ExecutionStats,
  type InputFormMetadata,
  type AgentArtifactRecord,
  type Message,
  type ProcessLogMetadata,
  type SelectOptionsMetadata,
  type StepRecord,
  type UploadedReference,
  useAgentArtifacts,
  useChat,
} from "@/hooks/use-api";
import { toast } from "@/hooks/use-toast";
import { moduleTranslations } from "@/i18n";
import { moduleTranslationLocaleForLanguage } from "@/lib/locale";
import { buildMessageTimelineWithPending, moveActiveConfirmationEntryToTail } from "@/lib/artifact-view-model";
import { type CodeWorkspaceOpenTarget } from "@/lib/code-workspace-target";
import {
  isInteractionCardMutationPending,
  resolveConfirmationCardPhase,
  resolveConfirmationMessagePhase,
  shouldShowCollapsedInteractionActions,
  type ConfirmationCardPhase,
} from "@/lib/confirmation-card-state";
import { findRequirementsFeatureTreePreview, looksLikeMarkdown } from "@/lib/confirmation-preview";
import {
  buildAgentUsageBreakdown,
  buildExecutionStatsMeta,
  buildExecutionStatsSummary,
  buildStepUsageMeta,
  buildTokenDisplay,
  resolveDisplayedDurationSeconds,
} from "@/lib/execution-stats";
import { buildInteractionGuidance, type InteractionGuidance } from "@/lib/interaction-guidance";
import { buildProcessLogFrameModel, buildRuntimeMonitorDisplay } from "@/lib/process-log-frame";
import { buildStepOutputGroups, findStepOutputGroupForLog, type StepOutputFile, type StepOutputGroup } from "@/lib/step-output-model";
import { buildTaskInsightModel } from "@/lib/task-insight";
import { cn } from "@/lib/utils";
import {
  defaultCardExpanded,
  inferTaskRoundStatus,
  resolveLogCardStatus,
  type TaskRoundStatus,
} from "@/lib/chat-card-state";

function taskErrorMessage(
  t: ReturnType<typeof useTranslation>["t"],
  task: CurrentTask | null | undefined,
) {
  const errorType = task?.errorType;
  if (errorType === "GENERATION_FAILED") return t("chat.error.generation_failed");
  if (errorType === "PARSING_FAILED") return t("chat.error.parsing_failed");
  if (errorType === "FILE_PARSE_FAILED") return t("chat.error.file_parse_failed");
  if (errorType === "COVERAGE_CONFLICT") return t("chat.error.coverage_conflict");
  if (errorType === "ROLLBACK_FAILED") return t("chat.error.rollback_failed");
  if (errorType === "TASK_CANCELLED") return t("chat.error.task_cancelled");
  if (errorType === "CONTEXT_EXPIRED") return t("chat.error.context_expired");
  return task?.errorMessage ?? t("chat.error.unknown");
}

function artifactIcon(type: string) {
  if (type === "prd") return FileText;
  if (type === "ui") return LayoutTemplate;
  if (type === "architecture") return Network;
  return Braces;
}

function sourceLabel(t: ReturnType<typeof useTranslation>["t"], source: string) {
  return t(`chat.source.${source}`, { defaultValue: source });
}

function outputFileIcon(fileName: string) {
  if (fileName.endsWith(".md") || fileName.endsWith(".txt")) {
    return FileText;
  }
  return FileCode2;
}

function formatMappedArtifacts(file: StepOutputFile) {
  if (!file.mappedArtifactTypes.length) {
    return "";
  }
  return file.mappedArtifactTypes.map((artifactType) => formatArtifactTypeLabel(artifactType as never)).join(" / ");
}

function MarkdownContent({
  content,
  inline = false,
  className,
  rich = false,
}: {
  content: string;
  inline?: boolean;
  className?: string;
  rich?: boolean;
}) {
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) =>
            inline ? <span>{children}</span> : <p className={cn("m-0 whitespace-pre-wrap", rich && "text-slate-300")}>{children}</p>,
          strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
          em: ({ children }) => <em className="italic">{children}</em>,
          ul: ({ children }) => <ul className="m-0 list-disc space-y-1 pl-5 text-slate-300">{children}</ul>,
          ol: ({ children }) => <ol className="m-0 list-decimal space-y-1 pl-5 text-slate-300">{children}</ol>,
          li: ({ children }) => <li>{children}</li>,
          code: ({ children }) => (
            <code className="rounded bg-white/5 px-1 py-0.5 font-mono text-[0.95em] text-cyan-100">{children}</code>
          ),
          h1: ({ children }) => <h1 className="m-0 text-xl font-semibold tracking-tight text-slate-50">{children}</h1>,
          h2: ({ children }) => <h2 className="m-0 border-t border-white/10 pt-4 text-lg font-semibold text-slate-100">{children}</h2>,
          h3: ({ children }) => <h3 className="m-0 text-sm font-semibold uppercase tracking-[0.12em] text-slate-200">{children}</h3>,
          blockquote: ({ children }) => (
            <blockquote className="rounded-r-xl border-l-4 border-cyan-400/50 bg-cyan-500/5 px-4 py-3 text-slate-200">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="my-4 border-white/10" />,
          table: ({ children }) => (
            <div className="overflow-x-auto rounded-xl border border-white/10 bg-[#071118]">
              <table className="min-w-full border-collapse text-left text-sm">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-white/5 text-slate-100">{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr className="border-t border-white/10">{children}</tr>,
          th: ({ children }) => <th className="px-3 py-2 font-semibold">{children}</th>,
          td: ({ children }) => <td className="px-3 py-2 align-top text-slate-300">{children}</td>,
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-cyan-200 underline underline-offset-2">
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function CardCollapseToggle({
  expanded,
  onToggle,
}: {
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex items-center justify-center rounded-md p-1 text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground"
    >
      {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
    </button>
  );
}

function InteractionGuidanceCard({
  guidance,
  language,
}: {
  guidance: InteractionGuidance | null;
  language: string;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  if (!guidance) {
    return null;
  }

  const items = [
    guidance.reviewHint
      ? {
          label: t("chat.guidance.reviewLabel"),
          value: guidance.reviewHint,
        }
      : null,
    {
      label: t("chat.guidance.scopeLabel"),
      value: guidance.scopeHint,
    },
    {
      label: t("chat.guidance.submitLabel"),
      value: guidance.submitHint,
    },
    guidance.skipHint
      ? {
          label: t("chat.guidance.skipLabel"),
          value: guidance.skipHint,
        }
      : null,
  ].filter((item): item is { label: string; value: string } => Boolean(item?.value));

  return (
    <div className="mb-4 rounded-xl border border-amber-500/15 bg-amber-500/5 p-4">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <div className="flex min-w-0 items-center gap-2 text-sm font-medium text-amber-100">
          <BookMarked className="h-4 w-4 shrink-0" />
          <span className="truncate">{t("chat.guidance.title")}</span>
        </div>
        <div className="rounded-md p-1 text-amber-100/80 transition-colors hover:bg-white/5 hover:text-amber-50">
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </div>
      </button>
      {expanded ? (
        <div className="mt-3 space-y-2.5">
          {items.map((item) => (
            <div key={item.label} className="rounded-lg border border-white/5 bg-black/20 px-3 py-2.5">
              <div className="text-[11px] uppercase tracking-[0.18em] text-amber-200/80">{item.label}</div>
              <div className="mt-1 text-sm leading-6 text-slate-200">{item.value}</div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}


function StepOutputsCard({
  outputGroup,
  defaultExpanded = true,
  onOpenFile,
}: {
  outputGroup: StepOutputGroup;
  defaultExpanded?: boolean;
  onOpenFile: (file: StepOutputFile) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(defaultExpanded);

  if (!outputGroup.files.length) {
    return null;
  }

  return (
    <div className="mt-4 rounded-xl border border-cyan-500/15 bg-cyan-500/5">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-3 py-3 text-left"
      >
        <div className="flex min-w-0 items-center gap-3">
          <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/10 p-2 text-cyan-100">
            <FileCode2 className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-medium text-foreground">{t("chat.stepOutputs")}</div>
            <div className="text-xs text-muted-foreground">{t("chat.stepOutputsCount", { count: outputGroup.files.length })}</div>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>{expanded ? t("chat.hideOutputs") : t("chat.showOutputs")}</span>
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </div>
      </button>

      {expanded ? (
        <div className="space-y-1.5 border-t border-cyan-500/10 px-3 py-2.5">
          <div className="space-y-1.5">
            {outputGroup.files.map((file) => {
              const Icon = outputFileIcon(file.fileName);
              return (
                <button
                  key={file.id}
                  type="button"
                  onClick={() => onOpenFile(file)}
                  className={cn(
                    "w-full rounded-xl border px-3 py-2.5 text-left transition-colors",
                    "border-white/5 bg-black/20 hover:border-cyan-500/20 hover:bg-black/30",
                  )}
                >
                  <div className="flex items-start justify-between gap-2.5">
                    <div className="flex min-w-0 flex-1 items-start gap-2.5">
                      <div className="rounded-lg bg-background/50 p-1.5 text-cyan-100">
                        <Icon className="h-4 w-4" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-foreground">{file.fileName}</div>
                        <div className="mt-0.5 text-xs text-muted-foreground">{sourceLabel(t, file.agent)}</div>
                        <div className="mt-1.5 flex flex-wrap gap-1.5">
                          {file.isPrimarySource ? (
                            <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-100">
                              {t("chat.outputPrimarySource")}
                            </Badge>
                          ) : null}
                          {file.mappedArtifactTypes.length ? (
                            <Badge variant="outline" className="border-cyan-500/20 bg-cyan-500/10 text-cyan-100">
                              {t("chat.outputMappedArtifacts", { artifacts: formatMappedArtifacts(file) })}
                            </Badge>
                          ) : null}
                        </div>
                      </div>
                    </div>
                    <div className="rounded-lg bg-background/50 p-2 text-cyan-100">
                      <ChevronRight className="h-4 w-4" />
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function usageDisplayLabel(
  t: ReturnType<typeof useTranslation>["t"],
  usage: { value: string; reason?: "usage_pending" | "usage_unreported" | null },
) {
  if (usage.reason === "usage_pending") {
    return t("chat.tokensPendingShort");
  }
  if (usage.reason === "usage_unreported") {
    return t("chat.tokensUnreportedShort");
  }
  return usage.value;
}

function taskRoundStatusLabel(
  t: ReturnType<typeof useTranslation>["t"],
  status: "running" | "waiting_user" | "completed" | "failed" | "cancelled",
) {
  if (status === "waiting_user") return t("chat.confirmationStatus.waiting");
  if (status === "completed") return t("chat.completed");
  if (status === "failed") return t("chat.failed");
  if (status === "cancelled") return t("chat.confirmationStatus.cancelled");
  return t("chat.running");
}

function formatRuntimeDuration(seconds: number | null): string | null {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) {
    return null;
  }
  if (seconds < 60) {
    return `${seconds}s`;
  }

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) {
    return remainingSeconds > 0 ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
  }

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (remainingMinutes > 0) {
    return `${hours}h ${remainingMinutes}m`;
  }
  return `${hours}h`;
}

function TaskRoundCard({
  taskId,
  anchorMessage,
  logs,
  statusMessage,
  currentTask,
  steps,
  agentArtifactsByAgent,
  onSelectArtifact,
  onCancel,
  onRetry,
  isCancelling,
  isRetrying,
  onOpenWorkspaceTarget,
}: {
  taskId: string;
  anchorMessage: Message;
  logs: Array<{ message: Message; children: Message[] }>;
  statusMessage?: Message;
  currentTask: CurrentTask | null;
  steps: StepRecord[];
  agentArtifactsByAgent: Record<string, AgentArtifactRecord[]>;
  onSelectArtifact: (type: string, sectionId?: string | null) => void;
  onCancel: () => void;
  onRetry: () => void;
  isCancelling: boolean;
  isRetrying: boolean;
  onOpenWorkspaceTarget: (target: CodeWorkspaceOpenTarget) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(defaultCardExpanded);
  if (!logs.length) {
    return null;
  }
  const status = inferTaskRoundStatus({ taskId, currentTask, logs, statusMessage });
  const latestLog = logs[logs.length - 1]?.message ?? null;
  const detailedError = statusMessage?.content ?? taskErrorMessage(t, currentTask);
  const summaryTitle =
    ((latestLog?.metadata ?? {}) as ProcessLogMetadata).taskName ??
    anchorMessage.content ??
    latestLog?.content ??
    t("chat.taskRunningFallback");
  const summaryHint =
    status === "waiting_user"
      ? latestLog?.content ?? t("chat.waitingHint")
      : status === "failed"
        ? t("chat.taskFailed")
        : latestLog?.content ?? t("chat.taskRunningFallback");

  return (
    <div className="w-full rounded-2xl border border-primary/20 bg-card/80 p-4 shadow-lg">
      <div className="flex min-h-[72px] items-start gap-3">
        <div className="rounded-xl bg-primary/10 p-2 text-primary">
          {status === "running" ? <Loader2 className="w-4 h-4 animate-spin" /> : <Cpu className="w-4 h-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-h-[56px] items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-foreground">{summaryTitle}</div>
              <div className="text-xs text-muted-foreground mt-1">{summaryHint}</div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Badge
                variant={status === "running" ? "default" : "outline"}
                className={cn(
                  status === "completed" && "border-emerald-500/30 bg-emerald-500/10 text-emerald-100",
                  status === "failed" && "border-destructive/30 bg-destructive/10 text-destructive",
                  status === "cancelled" && "border-white/10 bg-white/5 text-muted-foreground",
                )}
              >
                {taskRoundStatusLabel(t, status)}
              </Badge>
              {status === "failed" && detailedError ? (
                <TooltipProvider delayDuration={0}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        className="flex items-center justify-center rounded-md p-1 text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground"
                        aria-label={t("chat.failed")}
                      >
                        <CircleHelp className="h-4 w-4" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="bottom" className="max-w-sm whitespace-pre-wrap text-left">
                      {detailedError}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              ) : null}
              {currentTask?.id === taskId && status === "running" ? (
                <Button variant="ghost" size="sm" onClick={onCancel} isLoading={isCancelling}>
                  <SquareX className="w-4 h-4 mr-2" />
                  {t("chat.cancel")}
                </Button>
              ) : null}
              {currentTask?.id === taskId && (status === "failed" || status === "cancelled") ? (
                <Button variant="secondary" size="sm" onClick={onRetry} isLoading={isRetrying}>
                  {t("chat.retry")}
                </Button>
              ) : null}
              <CardCollapseToggle expanded={expanded} onToggle={() => setExpanded((value) => !value)} />
            </div>
          </div>
        </div>
      </div>
      {expanded ? (
        <div className="mt-4 space-y-3">
          {logs.map((entry) => (
            <LogMessageCard
              key={entry.message.id}
              taskRoundStatus={status}
              currentActivePhase={
                currentTask?.id === taskId
                  ? (((currentTask.outputData ?? {}) as { activePhase?: string | null }).activePhase ?? null)
                  : null
              }
              message={entry.message}
              childrenMessages={entry.children}
              outputGroup={currentTask?.id === taskId ? findStepOutputGroupForLog(entry.message, steps, agentArtifactsByAgent) : null}
              onSelectArtifact={onSelectArtifact}
              onOpenWorkspaceTarget={onOpenWorkspaceTarget}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function LogMessageCard({
  taskRoundStatus,
  currentActivePhase,
  message,
  childrenMessages,
  outputGroup,
  onSelectArtifact,
  onOpenWorkspaceTarget,
}: {
  taskRoundStatus: TaskRoundStatus;
  currentActivePhase?: string | null;
  message: Message;
  childrenMessages: Message[];
  outputGroup: StepOutputGroup | null;
  onSelectArtifact: (type: string, sectionId?: string | null) => void;
  onOpenWorkspaceTarget: (target: CodeWorkspaceOpenTarget) => void;
}) {
  const { t } = useTranslation();
  const metadata = (message.metadata ?? {}) as ProcessLogMetadata;
  const status = resolveLogCardStatus({
    logStatus: metadata.status,
    logPhase: metadata.phase,
    currentActivePhase,
    taskRoundStatus,
  });
  const frame = buildProcessLogFrameModel({
    taskName: metadata.taskName,
    content: message.content,
    metadata: message.metadata ?? {},
  });
  const [expanded, setExpanded] = useState(defaultCardExpanded);
  const phaseLabel = frame.phaseTranslationKey
    ? t(frame.phaseTranslationKey, { defaultValue: metadata.taskName ?? message.content })
    : metadata.taskName ?? message.content;
  const recentFileLabel = frame.recentFile ?? t("chat.logFrame.none");
  const nextStepLabel = frame.nextStepTranslationKey
    ? t(frame.nextStepTranslationKey, { defaultValue: t("chat.logFrame.none") })
    : t("chat.logFrame.none");
  const runtimeDisplay = buildRuntimeMonitorDisplay(frame.runtimeMonitor);
  const runtimeElapsed = formatRuntimeDuration(runtimeDisplay?.elapsedSeconds ?? null);

  return (
    <div className="w-full bg-card rounded-xl border border-white/5 overflow-hidden shadow-lg">
      <div className="flex items-center justify-between p-3 text-sm font-medium border-b border-white/5 bg-black/20">
        <div className="min-w-0 flex items-center gap-2">
          {status === "completed" ? (
            <CheckCircle2 className="w-4 h-4 text-success shrink-0" />
          ) : status === "failed" ? (
            <SquareX className="w-4 h-4 text-destructive shrink-0" />
          ) : (
            <Loader2 className="w-4 h-4 text-primary shrink-0 animate-spin" />
          )}
          <div className="min-w-0">
            <div className="truncate">{metadata.taskName ?? message.content}</div>
            <div className="mt-1 text-xs font-normal text-muted-foreground">{message.content}</div>
          </div>
        </div>
        <div className="ml-3 flex items-center gap-2">
          <Badge
            variant={status === "running" ? "default" : "outline"}
            className={cn(
              status === "completed" && "border-emerald-500/30 bg-emerald-500/10 text-emerald-100",
              status === "failed" && "border-destructive/30 bg-destructive/10 text-destructive",
            )}
          >
            {status === "completed" ? t("chat.completed") : status === "failed" ? t("chat.failed") : t("chat.running")}
          </Badge>
          <CardCollapseToggle expanded={expanded} onToggle={() => setExpanded((value) => !value)} />
        </div>
      </div>
      {expanded ? (
        <div className="p-4">
          <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-4 font-mono text-xs leading-6 text-cyan-100">
            <div className="text-cyan-300/80">{">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>"}</div>
            <div>
              <span className="text-cyan-300">{t("chat.logFrame.stage")}：</span>
              <span>{phaseLabel}</span>
            </div>
            <div>
              <span className="text-cyan-300">{t("chat.logFrame.action")}：</span>
              <span>{message.content}</span>
            </div>
            <div>
              <span className="text-cyan-300">{t("chat.logFrame.recentFile")}：</span>
              <span>{recentFileLabel}</span>
            </div>
            <div>
              <span className="text-cyan-300">{t("chat.logFrame.next")}：</span>
              <span>{nextStepLabel}</span>
            </div>
            {runtimeElapsed ? (
              <div>
                <span className="text-cyan-300">{t("chat.logFrame.runtime.elapsed")}：</span>
                <span>{runtimeElapsed}</span>
              </div>
            ) : null}
            {metadata.duration ? (
              <div>
                <span className="text-cyan-300">{t("chat.logFrame.duration")}：</span>
                <span>{metadata.duration}</span>
              </div>
            ) : null}
            <div className="text-cyan-300/80">{">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>"}</div>
          </div>
          {childrenMessages.length ? (
            <div className="mt-4 rounded-xl border border-white/5 bg-black/20">
              <div className="flex w-full items-center justify-between px-3 py-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
                <span>{t("chat.intermediateArtifacts")}</span>
              </div>
              <div className="space-y-3 border-t border-white/5 p-3">
                {childrenMessages.map((child) => (
                  <ArtifactCard
                    key={child.id}
                    metadata={(child.metadata ?? {}) as ArtifactCardMetadata}
                    onClick={() =>
                      onSelectArtifact(
                        formatArtifactType(((child.metadata ?? {}) as ArtifactCardMetadata).artifactType),
                        null,
                      )
                    }
                  />
                ))}
              </div>
            </div>
          ) : null}
          {outputGroup ? (
            <StepOutputsCard
              outputGroup={outputGroup}
              defaultExpanded={false}
              onOpenFile={(file) =>
                onOpenWorkspaceTarget(
                  file.agent === "coding_agent"
                    ? { kind: "code", filePath: file.fileName }
                    : { kind: "doc", agent: file.agent, fileName: file.fileName },
                )
              }
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ConfirmationCard({
  metadata,
  currentTask,
  analysisPreviewContent,
  analysisPreviewFileName,
  phase,
  onConfirm,
  onModify,
  onCancel,
  isConfirming,
  isModifying,
  isCancelling,
}: {
  metadata: SelectOptionsMetadata;
  currentTask: CurrentTask | null;
  analysisPreviewContent?: string | null;
  analysisPreviewFileName?: string | null;
  phase: ConfirmationCardPhase;
  onConfirm: () => void;
  onModify: (content: string) => void;
  onCancel: () => void;
  isConfirming: boolean;
  isModifying: boolean;
  isCancelling: boolean;
}) {
  const { t, i18n } = useTranslation();
  const options = metadata.options ?? [];
  const confirmationKind = metadata.confirmationKind ?? "module_selection";
  const isCoverageConflict = confirmationKind === "coverage_conflict";
  const conflicts = metadata.conflicts ?? [];
  const [showModify, setShowModify] = useState(false);
  const [showFullAnalysis, setShowFullAnalysis] = useState(false);
  const [modifyText, setModifyText] = useState("");
  const [expanded, setExpanded] = useState(defaultCardExpanded);

  const locale = moduleTranslationLocaleForLanguage(i18n.language);
  const isActionable = phase === "waiting";
  const isRunning = phase === "running";
  const interactionLocked = isConfirming || isModifying || isCancelling;
  const showCollapsedActions = shouldShowCollapsedInteractionActions({ phase, expanded });
  const interactionGuidance = buildInteractionGuidance(metadata, i18n.language);
  const statusLabel =
    phase === "waiting"
      ? t("chat.confirmationStatus.waiting")
      : phase === "running"
        ? t("chat.confirmationStatus.running")
        : phase === "completed"
          ? t("chat.confirmationStatus.completed")
          : phase === "failed"
            ? t("chat.confirmationStatus.failed")
            : phase === "cancelled"
              ? t("chat.confirmationStatus.cancelled")
              : t("chat.confirmationStatus.inactive");
  const statusHint =
    phase === "waiting"
      ? metadata.message ?? t("chat.confirmMessage")
      : phase === "running"
        ? t("chat.confirmationHint.running")
        : phase === "completed"
          ? t("chat.confirmationHint.completed")
          : phase === "failed"
            ? t("chat.confirmationHint.failed")
            : phase === "cancelled"
              ? t("chat.confirmationHint.cancelled")
              : t("chat.confirmationHint.inactive");

  return (
    <div className="w-full max-w-xl bg-gradient-to-b from-secondary to-card rounded-2xl border border-primary/20 p-5 shadow-[0_10px_40px_rgba(0,0,0,0.5)]">
      <h4 className="font-semibold text-foreground mb-2 flex items-center gap-2">
        <CheckCircle2 className="w-5 h-5 text-primary" />
        <span className="min-w-0 flex-1 truncate">{metadata.title ?? (isCoverageConflict ? t("chat.coverageConflictTitle") : t("chat.confirmTitle"))}</span>
        <Badge
          variant={phase === "running" ? "default" : "outline"}
          className={cn(phase === "completed" && "border-emerald-500/30 bg-emerald-500/10 text-emerald-100", "shrink-0")}
        >
          {statusLabel}
        </Badge>
        <CardCollapseToggle expanded={expanded} onToggle={() => setExpanded((value) => !value)} />
      </h4>
      {looksLikeMarkdown(statusHint) ? (
        <MarkdownContent content={statusHint} className="mb-4 text-sm leading-6 text-muted-foreground" />
      ) : (
        <p className="text-sm text-muted-foreground mb-4">{statusHint}</p>
      )}
      <InteractionGuidanceCard guidance={interactionGuidance} language={i18n.language} />
      {showCollapsedActions ? (
        <div className="mb-4 flex flex-wrap gap-3">
          <Button
            className="flex-1 min-w-[180px]"
            onClick={onConfirm}
            disabled={!isActionable || interactionLocked}
            isLoading={isConfirming}
          >
            {metadata.confirmText ?? t("chat.confirmAndContinue")}
          </Button>
          <Button
            variant="secondary"
            className="flex-1 min-w-[180px]"
            onClick={() => {
              if (isCoverageConflict) {
                onCancel();
                return;
              }
              setExpanded(true);
              setShowModify(true);
            }}
            disabled={!isActionable || interactionLocked}
            isLoading={isModifying || isCancelling}
          >
            {isCoverageConflict ? metadata.cancelText ?? t("chat.cancelTask") : metadata.cancelText ?? t("chat.modify")}
          </Button>
        </div>
      ) : null}
      {expanded ? <div className="text-xs text-muted-foreground uppercase tracking-wider mb-2 px-1">
        {isCoverageConflict ? t("chat.coverageConflictItems") : t("chat.featureModules")}
      </div> : null}
      {expanded ? <div className="space-y-2 mb-5 bg-black/20 p-3 rounded-xl border border-white/5">
        {isCoverageConflict
          ? conflicts.map((conflict) => (
              <div key={`${conflict.type}-${conflict.version ?? "current"}`} className="w-full rounded-xl border border-white/5 bg-black/20 px-3 py-3">
                <div className="flex items-center gap-2 text-sm text-foreground">
                  <CheckCircle2 className="w-4 h-4 text-amber-400" />
                  <span>{conflict.name ?? conflict.type ?? "Artifact"}</span>
                </div>
                <div className="mt-1 pl-6 text-xs text-muted-foreground">
                  {(conflict.type ?? "artifact").toUpperCase()}
                  {typeof conflict.version === "number" ? ` · v${conflict.version}` : ""}
                </div>
              </div>
            ))
          : options.map((option) => {
              const translated = moduleTranslations[option.id as keyof typeof moduleTranslations]?.[locale];
              const label = translated?.label ?? option.label;
              const description = translated?.description ?? option.description;
              return (
                <div
                  key={option.id}
                  className={cn(
                    "w-full text-left rounded-xl border px-3 py-3 transition-colors",
                    "border-white/5 bg-black/20",
                  )}
                >
                  <div className="flex items-center gap-2 text-sm text-foreground">
                    <CheckCircle2 className="w-4 h-4 text-green-500" />
                    {looksLikeMarkdown(label) ? (
                      <MarkdownContent content={label} inline className="flex-1 leading-6" />
                    ) : (
                      <span>{label}</span>
                    )}
                  </div>
                  {description ? (
                    looksLikeMarkdown(description) ? (
                      <MarkdownContent content={description} className="mt-1 pl-6 text-xs leading-6 text-muted-foreground" />
                    ) : (
                      <div className="mt-1 pl-6 text-xs text-muted-foreground">{description}</div>
                    )
                  ) : null}
                </div>
              );
            })}
      </div> : null}
      {expanded && !isCoverageConflict && analysisPreviewContent ? (
        <div className="mb-5 rounded-xl border border-cyan-500/15 bg-cyan-500/5">
          <button
            type="button"
            onClick={() => setShowFullAnalysis((value) => !value)}
            className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
          >
            <div>
              <div className="text-sm font-medium text-foreground">
                {analysisPreviewFileName ?? "feature_tree.md"}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {showFullAnalysis ? t("chat.hideOutputs") : t("chat.showOutputs")}
              </div>
            </div>
            {showFullAnalysis ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
          </button>
          {showFullAnalysis ? (
            <div className="border-t border-cyan-500/10 p-4">
              <div className="max-h-96 overflow-auto rounded-xl border border-white/5 bg-black/20 p-4">
                <MarkdownContent content={analysisPreviewContent} className="text-sm leading-6 text-foreground/90" />
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
      {expanded && !isCoverageConflict && showModify ? (
        <div className="mb-4">
          <Textarea
            value={modifyText}
            onChange={(event) => setModifyText(event.target.value)}
            placeholder={t("chat.regenerateFeatureTreePlaceholder")}
            className="w-full h-24 bg-black/30 border border-white/10 rounded-lg p-3 text-sm"
            disabled={!isActionable || interactionLocked}
          />
        </div>
      ) : null}
      {expanded ? <div className="flex gap-3 flex-wrap">
        <Button
          className="flex-1 min-w-[180px]"
          onClick={onConfirm}
          disabled={!isActionable || interactionLocked}
          isLoading={isConfirming}
        >
          {metadata.confirmText ?? t("chat.confirmAndContinue")}
        </Button>
        <Button
          variant="secondary"
          className="flex-1 min-w-[180px]"
          onClick={() => {
            if (isCoverageConflict) {
              onCancel();
              return;
            }
            if (showModify && modifyText.trim()) {
              onModify(modifyText.trim());
              setModifyText("");
              setShowModify(false);
              return;
            }
            setShowModify((value) => !value);
          }}
          disabled={!isActionable || interactionLocked}
          isLoading={isModifying}
        >
          {isCoverageConflict
            ? metadata.cancelText ?? t("chat.cancelTask")
            : showModify
              ? t("chat.submitFeatureTreeRegeneration")
              : t("chat.regenerateFeatureTree")}
        </Button>
        {!isCoverageConflict && (isActionable || isRunning) ? (
          <Button variant="ghost" className="w-full" onClick={onCancel} disabled={interactionLocked && !isCancelling} isLoading={isCancelling}>
            <SquareX className="w-4 h-4 mr-2" />
            {t("chat.cancelTask")}
          </Button>
        ) : null}
      </div> : null}
    </div>
  );
}

function InputFormCard({
  metadata,
  phase,
  onSubmit,
  onSkip,
  isSubmitting,
  isSkipping,
}: {
  metadata: InputFormMetadata;
  phase: ConfirmationCardPhase;
  onSubmit: (variables: Record<string, string>) => void;
  onSkip: () => void;
  isSubmitting: boolean;
  isSkipping: boolean;
}) {
  const { t, i18n } = useTranslation();
  const variables = metadata.variables ?? [];
  const [values, setValues] = useState<Record<string, string>>({});
  const [expanded, setExpanded] = useState(defaultCardExpanded);
  const isActionable = phase === "waiting";
  const showCollapsedActions = shouldShowCollapsedInteractionActions({ phase, expanded });
  const interactionGuidance = buildInteractionGuidance(metadata, i18n.language);
  const statusLabel =
    phase === "waiting"
      ? t("chat.confirmationStatus.waiting")
      : phase === "running"
        ? t("chat.confirmationStatus.running")
        : phase === "completed"
          ? t("chat.confirmationStatus.completed")
          : phase === "failed"
            ? t("chat.confirmationStatus.failed")
            : phase === "cancelled"
              ? t("chat.confirmationStatus.cancelled")
              : t("chat.confirmationStatus.inactive");
  const statusHint =
    phase === "waiting"
      ? metadata.message ?? t("chat.inputVariablesHint")
      : phase === "running"
        ? t("chat.confirmationHint.running")
        : phase === "completed"
          ? t("chat.confirmationHint.completed")
          : phase === "failed"
            ? t("chat.confirmationHint.failed")
            : phase === "cancelled"
              ? t("chat.confirmationHint.cancelled")
              : t("chat.confirmationHint.inactive");
  const missingRequired = variables.some((field) => field.required && !(values[field.id] ?? "").trim());

  return (
    <div className="w-full max-w-xl bg-gradient-to-b from-secondary to-card rounded-2xl border border-primary/20 p-5 shadow-[0_10px_40px_rgba(0,0,0,0.5)]">
      <h4 className="font-semibold text-foreground mb-2 flex items-center gap-2">
        <Cpu className="w-5 h-5 text-primary" />
        <span className="min-w-0 flex-1 truncate">{metadata.title ?? t("chat.inputVariablesTitle")}</span>
        <Badge
          variant={phase === "running" ? "default" : "outline"}
          className={cn(phase === "completed" && "border-emerald-500/30 bg-emerald-500/10 text-emerald-100", "shrink-0")}
        >
          {statusLabel}
        </Badge>
        <CardCollapseToggle expanded={expanded} onToggle={() => setExpanded((value) => !value)} />
      </h4>
      <p className="text-sm text-muted-foreground mb-4">{statusHint}</p>
      <InteractionGuidanceCard guidance={interactionGuidance} language={i18n.language} />
      {showCollapsedActions ? (
        <div className="mb-4 flex flex-wrap gap-3">
          <Button
            className="flex-1 min-w-[180px]"
            variant="secondary"
            onClick={() => setExpanded(true)}
          >
            {t("chat.inputVariablesOpen")}
          </Button>
          <Button
            variant="ghost"
            className="flex-1 min-w-[180px]"
            onClick={onSkip}
            isLoading={isSkipping}
          >
            {metadata.skipText ?? t("chat.inputVariablesSkip")}
          </Button>
        </div>
      ) : null}
      {expanded ? <div className="space-y-3 mb-5">
        {variables.map((field) => (
          <label key={field.id} className="block">
            <div className="mb-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
              {field.label}
              {field.required ? " *" : ""}
            </div>
            {field.type === "textarea" ? (
              <Textarea
                value={values[field.id] ?? ""}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [field.id]: event.target.value,
                  }))
                }
                disabled={!isActionable}
                placeholder={field.placeholder}
                className="min-h-[140px] rounded-xl border border-white/10 bg-black/30 px-3 py-3 text-sm text-foreground outline-none transition-colors focus-visible:ring-0 focus:border-primary/40 disabled:cursor-default disabled:opacity-70"
              />
            ) : (
              <input
                type={field.type === "password" ? "password" : "text"}
                value={values[field.id] ?? ""}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [field.id]: event.target.value,
                  }))
                }
                disabled={!isActionable}
                placeholder={field.placeholder}
                className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-3 text-sm text-foreground outline-none transition-colors focus:border-primary/40 disabled:cursor-default disabled:opacity-70"
              />
            )}
          </label>
        ))}
      </div> : null}
      {expanded ? <div className="flex gap-3 flex-wrap">
        <Button
          className="flex-1 min-w-[180px]"
          onClick={() => onSubmit(values)}
          disabled={!isActionable || missingRequired}
          isLoading={isSubmitting}
        >
          {metadata.submitText ?? t("chat.inputVariablesSubmit")}
        </Button>
        <Button
          variant="secondary"
          className="flex-1 min-w-[180px]"
          onClick={onSkip}
          disabled={!isActionable}
          isLoading={isSkipping}
        >
          {metadata.skipText ?? t("chat.inputVariablesSkip")}
        </Button>
      </div> : null}
    </div>
  );
}

function ArtifactCard({
  metadata,
  onClick,
}: {
  metadata: ArtifactCardMetadata;
  onClick: () => void;
}) {
  const Icon = artifactIcon(metadata.artifactType);
  const displayType = formatArtifactTypeLabel(metadata.artifactType);

  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 p-4 rounded-xl border border-white/10 bg-secondary/50 hover:bg-secondary hover:border-primary/50 transition-all text-left group"
    >
      <div className="p-2 rounded-lg bg-background/50 text-primary group-hover:scale-110 transition-transform">
        <Icon className="w-4 h-4" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-foreground truncate">{metadata.title}</div>
        <div className="text-xs text-muted-foreground uppercase tracking-wider">{displayType}</div>
        {metadata.preview ? <div className="text-xs text-muted-foreground mt-1 truncate">{metadata.preview}</div> : null}
      </div>
    </button>
  );
}

function ExecutionStatsCard({
  statistics,
  steps,
  stepOutputGroupsById,
  onOpenWorkspaceTarget,
}: {
  statistics: ExecutionStats;
  steps: StepRecord[];
  stepOutputGroupsById: ReadonlyMap<string, StepOutputGroup>;
  onOpenWorkspaceTarget: (target: CodeWorkspaceOpenTarget) => void;
}) {
  const { t } = useTranslation();
  const [durationNowMs, setDurationNowMs] = useState(() => Date.now());
  const metaItems = buildExecutionStatsMeta(statistics);
  const liveDurationSeconds = resolveDisplayedDurationSeconds(statistics, durationNowMs);
  const summaryMeta = buildExecutionStatsSummary({
    ...statistics,
    totalDuration: liveDurationSeconds,
    completedAt: statistics.completedAt,
    startedAt: statistics.startedAt,
  });
  const agentUsageItems = buildAgentUsageBreakdown(statistics);
  const totalToken = summaryMeta.tokens;
  const [expanded, setExpanded] = useState(defaultCardExpanded);
  const summary = `${summaryMeta.steps} ${t("chat.steps")} · ${summaryMeta.duration} · ${t("chat.tokens")}: ${usageDisplayLabel(t, summaryMeta.tokens)}`;

  useEffect(() => {
    if (statistics.completedAt) {
      return;
    }
    const timer = window.setInterval(() => {
      setDurationNowMs(Date.now());
    }, 500);
    return () => window.clearInterval(timer);
  }, [statistics.completedAt]);

  if (!steps.length && statistics.totalDuration <= 0 && statistics.itemsRead <= 0) {
    return null;
  }

  return (
    <div className="w-full bg-secondary/30 p-4 rounded-xl border border-white/5 space-y-4">
      <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-foreground">{t("chat.taskSummary")}</div>
            <div className="mt-1 text-xs text-muted-foreground">{summary}</div>
          </div>
        <CardCollapseToggle expanded={expanded} onToggle={() => setExpanded((value) => !value)} />
      </div>
      {expanded ? <div className="grid grid-cols-4 gap-2">
        <div className="flex flex-col text-center">
          <span className="text-xs text-muted-foreground flex justify-center items-center gap-1 mb-1"><Clock className="w-3 h-3" /> {t("chat.time")}</span>
          <span className="text-sm font-mono text-foreground">{liveDurationSeconds.toFixed(1)}s</span>
        </div>
        <div className="flex flex-col text-center border-l border-white/5">
          <span className="text-xs text-muted-foreground flex justify-center items-center gap-1 mb-1"><Cpu className="w-3 h-3" /> {t("chat.steps")}</span>
          <span className="text-sm font-mono text-foreground">{statistics.stepsCount}</span>
        </div>
        <div className="flex flex-col text-center border-l border-white/5">
          <span className="text-xs text-muted-foreground flex justify-center items-center gap-1 mb-1"><FileText className="w-3 h-3" /> {t("chat.items")}</span>
          <span className="text-sm font-mono text-foreground">{statistics.itemsRead}</span>
        </div>
        <div className="flex flex-col text-center border-l border-white/5">
          <span className="text-xs text-muted-foreground flex justify-center items-center gap-1 mb-1">
            <Cpu className="w-3 h-3" /> {t("chat.tokens")}
            {agentUsageItems.length ? (
              <TooltipProvider delayDuration={0}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className="rounded-full p-0.5 text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground"
                      aria-label={t("chat.tokenBreakdown", { defaultValue: "Token breakdown" })}
                    >
                      <CircleHelp className="h-3 w-3" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-sm text-left">
                    <div className="space-y-2">
                      <div className="text-xs font-medium text-foreground">
                        {t("chat.tokenBreakdown", { defaultValue: "Token breakdown" })}
                      </div>
                      <div className="space-y-1.5 text-xs">
                        {agentUsageItems.map((item) => (
                          <div key={item.agent} className="flex items-start justify-between gap-4">
                            <div className="min-w-0">
                              <div className="truncate text-foreground">{sourceLabel(t, item.agent)}</div>
                              {item.model ? (
                                <div className="text-[11px] text-muted-foreground">{item.model}</div>
                              ) : null}
                            </div>
                            <div className="shrink-0 font-mono text-foreground">
                              {usageDisplayLabel(t, item.token)}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ) : null}
          </span>
          <span className="text-sm font-mono text-foreground">{usageDisplayLabel(t, totalToken)}</span>
        </div>
      </div> : null}
      {expanded ? <div className="grid grid-cols-3 gap-2 border-t border-white/5 pt-3">
        {metaItems.map((item, index) => (
          <div key={item.id} className={cn("flex flex-col text-center", index > 0 && "border-l border-white/5")}>
            <span className="mb-1 text-xs text-muted-foreground">
              {item.id === "model"
                ? t("chat.model")
                : item.id === "inputTokens"
                  ? t("chat.inputTokens")
                  : t("chat.outputTokens")}
            </span>
            <span className="truncate text-xs font-mono text-foreground">{usageDisplayLabel(t, item)}</span>
          </div>
        ))}
      </div> : null}
      {expanded && totalToken.reason === "usage_pending" ? (
        <div className="border-t border-white/5 pt-3 text-center text-xs text-muted-foreground">
          {t("chat.tokensPending")}
        </div>
      ) : null}
      {expanded && totalToken.reason === "usage_unreported" ? (
        <div className="border-t border-white/5 pt-3 text-center text-xs text-muted-foreground">
          {t("chat.tokensNotReported")}
        </div>
      ) : null}
      {expanded && steps.length ? (
        <div className="border-t border-white/5 pt-3">
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">{t("chat.stepDetails")}</div>
          <div className="space-y-2">
            {steps.map((step) => {
              const stepMeta = buildStepUsageMeta(step);
              const outputGroup = stepOutputGroupsById.get(step.id) ?? null;
              return (
                <div key={step.id} className="rounded-xl border border-white/5 bg-black/10 px-3 py-2">
                  <div className="flex items-center justify-between gap-3 text-xs font-mono text-muted-foreground">
                    <span className="truncate">{step.stepName}</span>
                    <span>{step.duration.toFixed(1)}s</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                    <span className="rounded-full border border-white/10 px-2 py-0.5">
                      {t("chat.tokens")}: {usageDisplayLabel(t, stepMeta.token)}
                    </span>
                    {stepMeta.model ? (
                      <span className="rounded-full border border-white/10 px-2 py-0.5">
                        {t("chat.model")}: {stepMeta.model}
                      </span>
                    ) : null}
                    {stepMeta.sourceAgent ? (
                      <span className="rounded-full border border-white/10 px-2 py-0.5">
                        {t("chat.stepSource")}: {sourceLabel(t, stepMeta.sourceAgent)}
                      </span>
                    ) : null}
                    {outputGroup ? (
                      <span className="rounded-full border border-white/10 px-2 py-0.5">
                        {t("chat.stepOutputs", { defaultValue: "Outputs" })}: {outputGroup.files.length}
                      </span>
                    ) : null}
                  </div>
                  {outputGroup ? (
                    <StepOutputsCard
                      outputGroup={outputGroup}
                      defaultExpanded={false}
                      onOpenFile={(file) =>
                        onOpenWorkspaceTarget(
                          file.agent === "coding_agent"
                            ? { kind: "code", filePath: file.fileName }
                            : { kind: "doc", agent: file.agent, fileName: file.fileName },
                        )
                      }
                    />
                  ) : stepMeta.outputFiles.length ? (
                    <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                      {stepMeta.outputFiles.slice(0, 6).map((file) => (
                        <span key={file} className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-2 py-0.5 font-mono text-cyan-100">
                          {file}
                        </span>
                      ))}
                      {stepMeta.outputFiles.length > 6 ? (
                        <span className="rounded-full border border-white/10 px-2 py-0.5">
                          +{stepMeta.outputFiles.length - 6}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ModifyContextCard({
  prompt,
  artifacts,
}: {
  prompt: string | null;
  artifacts: ExistingArtifactContext[];
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(defaultCardExpanded);

  if (!artifacts.length && !prompt) {
    return null;
  }

  return (
    <div className="rounded-2xl border border-cyan-500/20 bg-cyan-500/5 p-4 shadow-lg">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-cyan-500/10 p-2 text-cyan-200">
          <Clock className="w-4 h-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-foreground">{t("chat.modifyContextTitle")}</div>
          <div className="text-xs text-muted-foreground mt-1">{t("chat.modifyContextHint")}</div>
        </div>
        <CardCollapseToggle expanded={expanded} onToggle={() => setExpanded((value) => !value)} />
      </div>
      {expanded && prompt ? (
        <div className="mt-4 rounded-xl border border-white/5 bg-black/20 px-3 py-3">
          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">{t("chat.modifyRequest")}</div>
          <div className="mt-2 text-sm leading-5 text-foreground/90">{prompt}</div>
        </div>
      ) : null}
      {expanded && artifacts.length ? (
        <div className="mt-4 space-y-3">
          {artifacts.map((artifact) => (
            <div key={artifact.id} className="rounded-xl border border-white/5 bg-black/20 px-3 py-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm text-foreground truncate">{artifact.title}</div>
                  <div className="mt-1 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                    {formatArtifactTypeLabel(artifact.type)} · v{artifact.version}
                  </div>
                </div>
              </div>
              <div className="mt-3 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">{t("chat.referencePreview")}</div>
              <div className="mt-1 text-sm leading-5 text-muted-foreground">
                {artifact.content.slice(0, 220)}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TaskInsightCard({
  currentTask,
}: {
  currentTask: CurrentTaskResponse | null;
}) {
  const { t } = useTranslation();
  const insight = useMemo(() => buildTaskInsightModel(currentTask?.task), [currentTask?.task]);
  const [expanded, setExpanded] = useState(defaultCardExpanded);
  const hasArtifactSources = insight.artifactSources.length > 0;
  const hasAnalysisSource = !!insight.analysisSource;
  const hasContextStats = insight.contextStats.some((item) => item.value > 0);
  const activeAgent = typeof currentTask?.activeAgent === "string" ? currentTask.activeAgent : null;
  const activePhase = typeof currentTask?.activePhase === "string" ? currentTask.activePhase : null;
  const agentOutputsReady = Array.isArray(currentTask?.agentOutputsReady) ? currentTask.agentOutputsReady : [];

  if (!hasArtifactSources && !hasAnalysisSource && !hasContextStats && !activeAgent && !agentOutputsReady.length) {
    return null;
  }

  return (
    <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-4 shadow-lg">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-emerald-500/10 p-2 text-emerald-200">
          <Cpu className="w-4 h-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-foreground">{t("chat.taskInsightTitle")}</div>
          <div className="text-xs text-muted-foreground mt-1">{t("chat.taskInsightHint")}</div>
        </div>
        <CardCollapseToggle expanded={expanded} onToggle={() => setExpanded((value) => !value)} />
      </div>

      {expanded && (activeAgent || activePhase || agentOutputsReady.length) ? (
        <div className="mt-4 rounded-xl border border-white/5 bg-black/20 px-3 py-3">
          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">{t("chat.activeAgent", { defaultValue: "Active Agent" })}</div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {activeAgent ? (
              <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-100">
                {sourceLabel(t, activeAgent)}
              </Badge>
            ) : null}
            {activePhase ? (
              <Badge variant="outline" className="border-white/10 bg-white/5 text-muted-foreground">
                {activePhase}
              </Badge>
            ) : null}
            {agentOutputsReady.map((agent) => (
              <Badge key={agent} variant="outline" className="border-cyan-500/20 bg-cyan-500/10 text-cyan-100">
                {sourceLabel(t, agent)}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}

      {expanded && hasAnalysisSource ? (
        <div className="mt-4 rounded-xl border border-white/5 bg-black/20 px-3 py-3">
          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">{t("chat.analysisSource")}</div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-100">
              {sourceLabel(t, insight.analysisSource ?? "unknown")}
            </Badge>
            {insight.analysisReason ? (
              <span className="text-xs text-muted-foreground">{insight.analysisReason}</span>
            ) : null}
          </div>
        </div>
      ) : null}

      {expanded && hasArtifactSources ? (
        <div className="mt-4 rounded-xl border border-white/5 bg-black/20 px-3 py-3">
          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">{t("chat.artifactSources")}</div>
          <div className="mt-3 space-y-2">
            {insight.artifactSources.map((item) => (
              <div key={item.artifactType} className="flex items-center justify-between gap-3 rounded-lg border border-white/5 px-3 py-2">
                <div className="min-w-0">
                  <div className="text-sm text-foreground">{formatArtifactTypeLabel(item.artifactType)}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {sourceLabel(t, item.source)}
                    {item.model ? ` · ${item.model}` : ""}
                  </div>
                </div>
                {item.status ? (
                  <Badge variant="outline" className="border-white/10 bg-white/5 text-muted-foreground">
                    {item.status}
                  </Badge>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {expanded && hasContextStats ? (
        <div className="mt-4 rounded-xl border border-white/5 bg-black/20 px-3 py-3">
          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">{t("chat.contextInputs")}</div>
          <div className="mt-3 grid grid-cols-3 gap-2">
            {insight.contextStats.map((item) => (
              <div key={item.id} className="rounded-lg border border-white/5 px-3 py-3 text-center">
                <div className="text-lg font-mono text-foreground">{item.value}</div>
                <div className="mt-1 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                  {item.id === "references"
                    ? t("chat.context.references")
                    : item.id === "modules"
                      ? t("chat.context.modules")
                      : t("chat.context.existingArtifacts")}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ReferencesCard({
  files,
  title,
  hint,
}: {
  files: UploadedReference[];
  title: string;
  hint: string;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(defaultCardExpanded);

  if (!files.length) {
    return null;
  }

  return (
    <div className="rounded-2xl border border-white/10 bg-card/70 p-4 shadow-lg">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-primary/10 p-2 text-primary">
          <BookMarked className="w-4 h-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-foreground">{title}</div>
          <div className="text-xs text-muted-foreground mt-1">{hint}</div>
        </div>
        <CardCollapseToggle expanded={expanded} onToggle={() => setExpanded((value) => !value)} />
      </div>
      {expanded ? <div className="mt-4 space-y-3">
        {files.map((file) => {
          const preview = file.contentPreview?.trim();
          return (
            <div key={file.id} className="rounded-xl border border-white/5 bg-black/20 px-3 py-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm text-foreground truncate">{file.fileName}</div>
                  <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground mt-1">{file.fileType}</div>
                </div>
                {!preview ? (
                  <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-amber-100">
                    {t("chat.referenceSkipped")}
                  </Badge>
                ) : null}
              </div>
              <div className="mt-3 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">{t("chat.referencePreview")}</div>
              <div className="mt-1 text-sm leading-5 text-muted-foreground">
                {preview || t("chat.referenceSkipped")}
              </div>
            </div>
          );
        })}
      </div> : null}
    </div>
  );
}

export function ChatArea({
  projectId,
  onSelectArtifact,
  onOpenWorkspaceTarget,
}: {
  projectId: string;
  onSelectArtifact: (type: string, sectionId?: string | null) => void;
  onOpenWorkspaceTarget: (target: CodeWorkspaceOpenTarget) => void;
}) {
  const { t } = useTranslation();
  const {
    data: messages,
    sendMessage,
    confirmGeneration,
    modifyGeneration,
    submitInputVariables,
    cancelTask,
    retryTask,
    currentTask,
    references,
    projectReferences,
    statistics,
    steps,
    isLoading,
  } = useChat(projectId);
  const { data: agentArtifacts } = useAgentArtifacts(
    projectId,
    currentTask?.pendingAgentArtifactsVersion,
    projectId !== "new",
  );
  const [input, setInput] = useState("");
  const stepOutputGroups = useMemo(
    () => buildStepOutputGroups(steps, agentArtifacts?.artifactsByAgent ?? {}),
    [agentArtifacts?.artifactsByAgent, steps],
  );
  const stepOutputGroupsById = useMemo(
    () => new Map(stepOutputGroups.map((group) => [group.stepId, group])),
    [stepOutputGroups],
  );
  const featureTreePreview = useMemo(
    () => findRequirementsFeatureTreePreview(agentArtifacts?.artifactsByAgent ?? {}),
    [agentArtifacts?.artifactsByAgent],
  );
  const scrollRef = useRef<HTMLDivElement>(null);
  const userScrolledUp = useRef(false);
  const [optimisticConfirmMessageId, setOptimisticConfirmMessageId] = useState<string | null>(null);

  useEffect(() => {
    if (scrollRef.current && !userScrolledUp.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, statistics]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const handleScroll = () => {
      // 距底部 80px 以内视为"在底部"
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      userScrolledUp.current = !atBottom;
    };
    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, []);

  const handleSend = () => {
    if (!input.trim() || sendMessage.isPending) return;
    sendMessage.mutate(input.trim());
    setInput("");
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  const taskState = currentTask?.status;
  const taskRecord = currentTask?.task ?? null;
  const currentTaskActivePhase =
    taskRecord?.outputData && typeof taskRecord.outputData.activePhase === "string"
      ? taskRecord.outputData.activePhase
      : null;
  const waitingCardMessage = [...messages].reverse().find((message) => {
    if (message.type !== "select_options" && message.type !== "input_form") {
      return false;
    }
    // 设计注释：
    // 这里只把“当前任务自己产出的确认卡”当成活动确认卡。
    // 否则历史任务里最后一张确认消息也可能被误认成当前活动卡，
    // 进而让旧卡片跟着新任务状态一起跳，出现“明明早就确认过了却还显示运行中”的假象。
    if (!taskRecord?.id) {
      return true;
    }
    const messageTaskId = typeof message.metadata?.taskId === "string" ? message.metadata.taskId : null;
    return messageTaskId === taskRecord.id;
  });

  useEffect(() => {
    if (!optimisticConfirmMessageId) {
      return;
    }
    // 设计注释：
    // 用户点下确认按钮后，我们先在前端把这张卡立刻锁住，
    // 避免后端确认接口还没回包的几秒内被重复点击。
    // 只有当任务已经离开 waiting_user，或者当前活动确认卡已经换成别的卡时，才解除这层本地锁。
    if (taskState !== "waiting_user" || waitingCardMessage?.id !== optimisticConfirmMessageId) {
      setOptimisticConfirmMessageId(null);
    }
  }, [optimisticConfirmMessageId, taskState, waitingCardMessage?.id]);
  const pendingTaskRound = useMemo(() => {
    const prompt = typeof taskRecord?.inputData?.prompt === "string" ? taskRecord.inputData.prompt : "";
    if (!taskRecord || !prompt.trim()) {
      return null;
    }
    if (!["running", "waiting_user"].includes(taskRecord.status)) {
      return null;
    }
    return {
      taskId: taskRecord.id,
      prompt,
      createdAt: taskRecord.createdAt ?? new Date().toISOString(),
    };
  }, [taskRecord]);
  const timeline = useMemo(() => {
    const baseTimeline = buildMessageTimelineWithPending(messages, pendingTaskRound);
    if (taskState !== "waiting_user") {
      return baseTimeline;
    }
    return moveActiveConfirmationEntryToTail(baseTimeline, waitingCardMessage?.id);
  }, [messages, pendingTaskRound, taskState, waitingCardMessage?.id]);
  const referenceIds = new Set(references.map((file) => file.id));
  const projectOnlyReferences = projectReferences.filter((file) => !referenceIds.has(file.id));
  const outputData = (taskRecord?.outputData ?? {}) as {
    existingArtifacts?: ExistingArtifactContext[];
    requestedPrompt?: string;
    analysisSource?: string;
    analysisReason?: string;
    artifactSources?: Record<string, unknown>;
    contextSummary?: Record<string, unknown>;
  };
  const modifyArtifacts = Array.isArray(outputData.existingArtifacts) ? outputData.existingArtifacts : [];
  const modifyPrompt = typeof outputData.requestedPrompt === "string" ? outputData.requestedPrompt : null;
  const showModifyContext = taskRecord?.taskType === "modify" && (modifyArtifacts.length > 0 || !!modifyPrompt);
  const waitingConfirmationKind =
    waitingCardMessage && waitingCardMessage.type === "select_options"
      ? ((waitingCardMessage.metadata ?? {}) as SelectOptionsMetadata).confirmationKind
      : null;
  const composerLocked =
    taskState === "waiting_user" &&
    (waitingCardMessage?.type === "input_form" || waitingConfirmationKind === "coverage_conflict");

  const handleInputFormError = (error: unknown) => {
    console.error("[UI ACTION] submitInputVariables_failed", error);
    const description = error instanceof ApiError ? error.message : t("chat.error.unknown");
    toast({
      title: t("chat.error.unknown"),
      description,
      variant: "destructive",
    });
  };

  return (
    <div className="flex flex-col h-full bg-background border-r border-border relative">
      <div className="flex-1 overflow-y-auto p-4 space-y-6" ref={scrollRef}>
        <ReferencesCard
          files={references}
          title={t("chat.referencesTitle")}
          hint={t("chat.referencesHint")}
        />
        <ReferencesCard
          files={projectOnlyReferences.length ? projectOnlyReferences : !references.length ? projectReferences : []}
          title={t("chat.projectReferencesTitle")}
          hint={t("chat.projectReferencesHint")}
        />
        {showModifyContext ? (
          <ModifyContextCard
            prompt={modifyPrompt}
            artifacts={modifyArtifacts}
          />
        ) : null}
        <TaskInsightCard currentTask={currentTask} />

        <AnimatePresence initial={false}>
          {timeline.map((entry) => {
            if (entry.kind === "task_round") {
              return (
                <motion.div
                  key={`task-round:${entry.taskId}`}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="mr-auto flex w-full max-w-[90%] flex-col items-start"
                >
                  <TaskRoundCard
                    taskId={entry.taskId}
                    anchorMessage={entry.anchorMessage}
                    logs={entry.logs}
                    statusMessage={entry.statusMessage}
                    currentTask={taskRecord}
                    steps={steps}
                    agentArtifactsByAgent={agentArtifacts?.artifactsByAgent ?? {}}
                    onSelectArtifact={onSelectArtifact}
                    onCancel={() => cancelTask.mutate()}
                    onRetry={() => retryTask.mutate()}
                    isCancelling={cancelTask.isPending}
                    isRetrying={retryTask.isPending}
                    onOpenWorkspaceTarget={onOpenWorkspaceTarget}
                  />
                </motion.div>
              );
            }

            const { message, children } = entry;
            return (
              <motion.div
                key={message.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className={cn("flex flex-col max-w-[90%]", message.role === "user" ? "ml-auto items-end" : "mr-auto items-start")}
              >
                <div className="flex items-center gap-2 mb-1.5 px-1">
                  <span className="text-xs font-medium text-muted-foreground">
                    {message.role === "user" ? t("chat.you") : message.role === "agent" ? t("chat.agent") : t("chat.system")}
                  </span>
                  <span className="text-[10px] text-muted-foreground/40">{formatDateDistance(message.createdAt)}</span>
                </div>

                {(message.type === "text" || message.type === "user_response") && (
                  <div
                    className={cn(
                      "p-4 rounded-2xl text-sm leading-relaxed",
                      message.role === "user"
                        ? "bg-primary text-primary-foreground rounded-tr-sm shadow-[0_4px_20px_rgba(0,111,238,0.2)]"
                        : "bg-secondary text-foreground rounded-tl-sm border border-white/5",
                    )}
                  >
                    {message.content}
                  </div>
                )}

                {message.type === "select_options" && (
                  <ConfirmationCard
                    metadata={(message.metadata ?? {}) as SelectOptionsMetadata}
                    currentTask={currentTask?.task ?? null}
                    analysisPreviewContent={featureTreePreview?.content ?? null}
                    analysisPreviewFileName={featureTreePreview?.fileName ?? null}
                    phase={resolveConfirmationCardPhase({
                      messageId: message.id,
                      activeMessageId: waitingCardMessage?.id,
                      taskStatus: currentTask?.status ?? null,
                      currentActivePhase: currentTaskActivePhase,
                      confirmationActivePhase: resolveConfirmationMessagePhase(message.metadata ?? null),
                    })}
                    onConfirm={() =>
                      (setOptimisticConfirmMessageId(message.id),
                      confirmGeneration.mutate(
                        {
                          messageId: message.id,
                          selectedIds:
                            ((message.metadata ?? {}) as SelectOptionsMetadata).confirmationKind === "coverage_conflict"
                              ? ["confirm_overwrite"]
                              : [],
                        },
                        {
                          onError: () => {
                            setOptimisticConfirmMessageId((current) => (current === message.id ? null : current));
                          },
                        },
                      ))
                    }
                    onModify={(content) => modifyGeneration.mutate(content)}
                    onCancel={() => cancelTask.mutate()}
                    isConfirming={isInteractionCardMutationPending({
                      mutationPending: confirmGeneration.isPending,
                      submittedMessageId: confirmGeneration.variables?.messageId,
                      messageId: message.id,
                      optimisticMessageId: optimisticConfirmMessageId,
                    })}
                    isModifying={modifyGeneration.isPending}
                    isCancelling={cancelTask.isPending}
                  />
                )}

                {message.type === "input_form" && (
                  <InputFormCard
                    metadata={(message.metadata ?? {}) as InputFormMetadata}
                    phase={resolveConfirmationCardPhase({
                      messageId: message.id,
                      activeMessageId: waitingCardMessage?.id,
                      taskStatus: currentTask?.status ?? null,
                      currentActivePhase: currentTaskActivePhase,
                      confirmationActivePhase: resolveConfirmationMessagePhase(message.metadata ?? null),
                    })}
                    onSubmit={(variables) =>
                      (console.info("[UI ACTION] input_form_submit_clicked", {
                        messageId: message.id,
                        taskId: typeof message.metadata?.taskId === "string" ? message.metadata.taskId : null,
                        variableKeys: Object.keys(variables),
                      }),
                      submitInputVariables.mutate({
                        variables,
                        taskId: typeof message.metadata?.taskId === "string" ? message.metadata.taskId : undefined,
                      }, { onError: handleInputFormError }))
                    }
                    onSkip={() =>
                      (console.info("[UI ACTION] input_form_skip_clicked", {
                        messageId: message.id,
                        taskId: typeof message.metadata?.taskId === "string" ? message.metadata.taskId : null,
                      }),
                      submitInputVariables.mutate({
                        skip: true,
                        taskId: typeof message.metadata?.taskId === "string" ? message.metadata.taskId : undefined,
                      }, { onError: handleInputFormError }))
                    }
                    isSubmitting={submitInputVariables.isPending && !submitInputVariables.variables?.skip}
                    isSkipping={submitInputVariables.isPending && submitInputVariables.variables?.skip === true}
                  />
                )}

                {message.type === "artifact_card" && (
                  <ArtifactCard
                    metadata={(message.metadata ?? {}) as ArtifactCardMetadata}
                    onClick={() =>
                      onSelectArtifact(
                        formatArtifactType(((message.metadata ?? {}) as ArtifactCardMetadata).artifactType),
                        null,
                      )
                    }
                  />
                )}
              </motion.div>
            );
          })}
        </AnimatePresence>

        {statistics ? (
          <ExecutionStatsCard
            statistics={statistics}
            steps={steps}
            stepOutputGroupsById={stepOutputGroupsById}
            onOpenWorkspaceTarget={onOpenWorkspaceTarget}
          />
        ) : null}

        {isLoading ? (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-2 text-muted-foreground text-sm pl-2">
            <Loader2 className="w-4 h-4 animate-spin text-primary" />
            {t("chat.agentThinking")}
          </motion.div>
        ) : null}
      </div>

      <div className="p-4 bg-background border-t border-border">
        {taskState === "waiting_user" && waitingCardMessage ? (
          <div className="mb-3 rounded-xl border border-yellow-500/20 bg-yellow-500/5 px-4 py-3 text-sm text-yellow-100">
            {t("chat.waitingHint")}
          </div>
        ) : null}
        <div className="relative group">
          <div className="absolute -inset-1 bg-gradient-to-r from-primary/20 to-accent/20 rounded-2xl blur opacity-25 group-focus-within:opacity-50 transition duration-500" />
          <div className="relative flex flex-col bg-card rounded-xl border border-white/10 overflow-hidden focus-within:border-primary/50 transition-colors">
            <Textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                composerLocked
                  ? t("chat.inputStructuredActionPlaceholder")
                  : taskState === "waiting_user"
                    ? t("chat.inputWaitingPlaceholder")
                    : t("chat.inputDefaultPlaceholder")
              }
              className="border-0 bg-transparent focus-visible:ring-0 resize-none min-h-[100px] text-base p-4"
              disabled={composerLocked}
            />
            <div className="flex items-center justify-between p-3 bg-secondary/30 border-t border-white/5">
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" disabled>
                  <Paperclip className="w-4 h-4" />
                </Button>
                <span className="text-xs text-muted-foreground hidden sm:inline-block">{t("chat.returnHint")}</span>
              </div>
              <Button size="sm" onClick={handleSend} disabled={composerLocked || !input.trim() || sendMessage.isPending} className="rounded-full px-5" isLoading={sendMessage.isPending}>
                <Send className="w-4 h-4 mr-2" />
                {t("chat.send")}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
