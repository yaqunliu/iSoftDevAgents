import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight, Diff, GitCommit, RotateCcw, X } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import { formatDateDistance, formatHistoryChangeStatus, type HistoryCheckpoint, useCurrentTask, useHistory, useProjectFile, useRollbackVersion } from "@/hooks/use-api";
import { buildLineDiffRows } from "@/lib/line-diff";
import { resolveHistoryEmptyPendingPreview } from "@/lib/workspace-version-state";
import { cn } from "@/lib/utils";

function versionKindLabel(t: ReturnType<typeof useTranslation>["t"], kind: HistoryCheckpoint["versionKind"]) {
  const labels: Record<HistoryCheckpoint["versionKind"], string> = {
    generation: t("history.versionKind.generation"),
    requirements_review: t("history.versionKind.requirementsReview"),
    architecture_review: t("history.versionKind.architectureReview"),
    artifact_edit: t("history.versionKind.artifactEdit"),
    file_edit: t("history.versionKind.fileEdit"),
    code_edit: t("history.versionKind.codeEdit"),
    modify: t("history.versionKind.modify"),
    rollback: t("history.versionKind.rollback"),
    regenerate: t("history.versionKind.regenerate"),
  };
  return labels[kind] ?? kind;
}

function DiffView({
  changes,
  version,
  sourceVersion,
  projectId,
  onSelectChange,
}: {
  changes: HistoryCheckpoint["changes"];
  version: number;
  sourceVersion?: number | null;
  projectId: string;
  onSelectChange: (version: number, file: string) => void;
}) {
  const { t } = useTranslation();
  const [expandedFile, setExpandedFile] = useState<string | null>(null);

  return (
    <div className="bg-black/30 rounded-lg border border-white/5 overflow-hidden mt-2">
      <div className="px-3 py-2 text-xs text-muted-foreground border-b border-white/5 bg-white/5">
        {t("history.showing", { count: changes.length })}
      </div>
      <div className="divide-y divide-white/5">
        {changes.map((change, index) => (
          <div key={`${change.file}-${index}`}>
            <button
              className="w-full flex items-center justify-between text-xs font-mono px-3 py-2 hover:bg-white/5 transition-colors"
              onClick={() => {
                setExpandedFile(expandedFile === change.file ? null : change.file);
                onSelectChange(version, change.file);
              }}
            >
              <div className="flex items-center gap-2">
                {expandedFile === change.file ? <ChevronDown className="w-3 h-3 text-muted-foreground" /> : <ChevronRight className="w-3 h-3 text-muted-foreground" />}
                <span className="text-muted-foreground">{change.file}</span>
              </div>
              <span
                className={cn(
                  "text-[10px] px-1.5 py-0.5 rounded font-sans",
                  change.status === "Added"
                    ? "bg-green-500/10 text-green-400"
                    : change.status === "Deleted"
                      ? "bg-red-500/10 text-red-400"
                      : "bg-yellow-500/10 text-yellow-400",
                )}
              >
                {formatHistoryChangeStatus(change.status)}
              </span>
            </button>
            {expandedFile === change.file ? (
              <ChangeDiffDetail
                projectId={projectId}
                version={version}
                sourceVersion={sourceVersion}
                change={change}
              />
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function ChangeDiffDetail({
  projectId,
  version,
  sourceVersion,
  change,
}: {
  projectId: string;
  version: number;
  sourceVersion?: number | null;
  change: HistoryCheckpoint["changes"][number];
}) {
  const { t } = useTranslation();
  const shouldLoadOld = change.status !== "Added" && typeof sourceVersion === "number";
  const shouldLoadNew = change.status !== "Deleted";
  const { data: previousFile, isLoading: isLoadingPrevious } = useProjectFile(
    projectId,
    shouldLoadOld ? change.file : null,
    shouldLoadOld ? sourceVersion : null,
  );
  const { data: currentFile, isLoading: isLoadingCurrent } = useProjectFile(
    projectId,
    shouldLoadNew ? change.file : null,
    shouldLoadNew ? version : null,
  );

  const oldContent = shouldLoadOld ? previousFile?.content ?? "" : "";
  const newContent = shouldLoadNew ? currentFile?.content ?? "" : "";
  const rows = useMemo(() => buildLineDiffRows(oldContent, newContent), [newContent, oldContent]);
  const addedCount = rows.filter((row) => row.kind === "added").length;
  const deletedCount = rows.filter((row) => row.kind === "deleted").length;

  if ((shouldLoadOld && isLoadingPrevious) || (shouldLoadNew && isLoadingCurrent)) {
    return (
      <div className="bg-black/40 p-3 text-xs text-muted-foreground">
        正在加载差异内容...
      </div>
    );
  }

  return (
    <div className="overflow-hidden bg-black/40">
      <div className="flex items-center gap-3 border-b border-white/5 px-3 py-2 text-[11px] text-muted-foreground">
        <span>{t("history.fileChange", { file: change.file, status: formatHistoryChangeStatus(change.status) })}</span>
        <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-emerald-300">
          +{addedCount}
        </span>
        <span className="rounded-full border border-red-500/20 bg-red-500/10 px-2 py-0.5 text-red-300">
          -{deletedCount}
        </span>
      </div>
      <div className="max-h-72 overflow-auto font-mono text-xs">
        {rows.map((row, index) => (
          row.kind === "skipped" ? (
            <div key={`skip-${index}`} className="border-t border-white/5 bg-white/[0.03] px-3 py-2 text-slate-500">
              {row.content}
            </div>
          ) : (
            <div
              key={`${row.kind}-${index}-${row.oldLineNumber ?? "n"}-${row.newLineNumber ?? "n"}`}
              className={cn(
                "grid grid-cols-[56px_56px_28px_minmax(0,1fr)] gap-0 border-t border-white/5",
                row.kind === "added" && "bg-emerald-500/10",
                row.kind === "deleted" && "bg-red-500/10",
              )}
            >
              <div className="px-2 py-1 text-right text-slate-500">{row.oldLineNumber ?? ""}</div>
              <div className="px-2 py-1 text-right text-slate-500">{row.newLineNumber ?? ""}</div>
              <div className={cn(
                "px-1 py-1 text-center",
                row.kind === "added" ? "text-emerald-300" : row.kind === "deleted" ? "text-red-300" : "text-slate-500",
              )}>
                {row.kind === "added" ? "+" : row.kind === "deleted" ? "-" : " "}
              </div>
              <pre className="overflow-x-auto whitespace-pre-wrap break-words px-2 py-1 text-slate-200">{row.content}</pre>
            </div>
          )
        ))}
      </div>
    </div>
  );
}

function summarizeChanges(changes: HistoryCheckpoint["changes"]) {
  return changes.reduce(
    (summary, change) => {
      if (change.status === "Added") summary.added += 1;
      else if (change.status === "Deleted") summary.deleted += 1;
      else summary.modified += 1;
      return summary;
    },
    { added: 0, modified: 0, deleted: 0 },
  );
}

export function VersionHistorySidebar({
  projectId,
  isOpen,
  selectedVersion,
  currentVersion,
  onSelectVersion,
  onSelectChange,
  onClose,
}: {
  projectId: string;
  isOpen: boolean;
  selectedVersion: number | null;
  currentVersion?: number;
  onSelectVersion: (version: number) => void;
  onSelectChange: (version: number, file: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { data: history, isLoading: isHistoryLoading } = useHistory(projectId);
  const { data: currentTask } = useCurrentTask(projectId);
  const rollbackVersion = useRollbackVersion(projectId);
  const [expandedChanges, setExpandedChanges] = useState<Record<string, boolean>>({});
  const effectiveSelectedVersion = selectedVersion ?? currentVersion ?? null;
  const pendingPreviewVersion = resolveHistoryEmptyPendingPreview(
    currentTask?.pendingAgentArtifactsVersion ?? null,
    currentVersion ?? null,
  );

  const toggleChanges = (id: string) => {
    setExpandedChanges((value) => ({ ...value, [id]: !value[id] }));
  };

  const handleRollback = async (version: number) => {
    const result = await rollbackVersion.mutateAsync(version);
    onSelectVersion(result.newVersion);
  };

  return (
    <AnimatePresence>
      {isOpen ? (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40"
            onClick={onClose}
          />

          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 200 }}
            className="fixed right-0 top-0 bottom-0 w-[420px] bg-card border-l border-white/10 z-50 flex flex-col shadow-2xl"
          >
            <div className="flex items-center justify-between p-5 border-b border-white/10">
              <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                <GitCommit className="w-5 h-5 text-primary" />
                {t("history.title")}
              </h2>
              <Button variant="ghost" size="icon" onClick={onClose} className="rounded-full">
                <X className="w-5 h-5" />
              </Button>
            </div>

            <div className="flex-1 overflow-y-auto p-5">
              <div className="relative border-l border-white/10 ml-4 space-y-8 pb-10">
                {isHistoryLoading ? (
                  <div className="pl-6 text-sm text-muted-foreground">
                    {t("history.loading")}
                  </div>
                ) : history?.length ? history.map((checkpoint) => (
                  <div key={checkpoint.id} className="relative pl-6">
                    {(() => {
                      const agentFileCount = Object.values(checkpoint.stateManifest.agentArtifacts ?? {}).reduce(
                        (total, files) => total + files.length,
                        0,
                      );
                      const changeSummary = summarizeChanges(checkpoint.changes);
                      return (
                        <>
                    <div
                      className={cn(
                        "absolute -left-[5px] top-1 w-[9px] h-[9px] rounded-full border-2",
                        checkpoint.isCurrent ? "bg-primary border-primary ring-4 ring-primary/20" : "bg-card border-muted-foreground",
                      )}
                    />

                    <div
                      role="button"
                      tabIndex={0}
                      onClick={() => onSelectVersion(checkpoint.version)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onSelectVersion(checkpoint.version);
                        }
                      }}
                      className={cn(
                        "w-full rounded-2xl border px-4 py-4 text-left transition-colors",
                        effectiveSelectedVersion === checkpoint.version
                          ? "border-primary/40 bg-primary/10"
                          : "border-white/10 bg-black/10 hover:bg-white/5",
                      )}
                    >
                      <div className="mb-1 flex items-center gap-3 flex-wrap">
                        <span className="text-xs text-muted-foreground font-mono">{formatDateDistance(checkpoint.createdAt)}</span>
                        <Badge variant="outline" className="text-[10px] py-0 h-5 border-white/10 bg-white/5 text-foreground/80">
                          {versionKindLabel(t, checkpoint.versionKind)}
                        </Badge>
                        {checkpoint.isCurrent ? (
                          <Badge variant="outline" className="text-[10px] py-0 h-5 bg-primary/10 border-primary/30 text-primary">
                            {t("history.current")} v{checkpoint.version}
                          </Badge>
                        ) : null}
                        {effectiveSelectedVersion === checkpoint.version ? (
                          <Badge variant="outline" className="text-[10px] py-0 h-5 border-white/10 bg-white/5 text-foreground/80">
                            {t("history.viewing")}
                          </Badge>
                        ) : null}
                      </div>

                      <h4 className={cn("text-sm font-medium mb-3", checkpoint.isCurrent ? "text-foreground" : "text-foreground/80")}>
                        {checkpoint.description}
                      </h4>

                      <div className="mb-3 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                        {typeof checkpoint.sourceVersion === "number" ? (
                          <span className="rounded-full border border-white/10 bg-black/20 px-2 py-1">
                            {t("history.sourceVersion", { version: checkpoint.sourceVersion })}
                          </span>
                        ) : null}
                        {typeof checkpoint.restoredFromVersion === "number" ? (
                          <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-amber-200">
                            {t("history.restoredFromVersion", { version: checkpoint.restoredFromVersion })}
                          </span>
                        ) : null}
                        <span className="rounded-full border border-white/10 bg-black/20 px-2 py-1">
                          {t("history.snapshotCounts", {
                            artifacts: checkpoint.stateManifest.artifacts.length,
                            agentFiles: agentFileCount,
                            files: checkpoint.stateManifest.codeFiles.length,
                            modules: checkpoint.modulesSnapshot.filter((module) => module.isSelected).length,
                          })}
                        </span>
                        <span className="rounded-full border border-white/10 bg-black/20 px-2 py-1">
                          {t("history.changeSummary", {
                            added: changeSummary.added,
                            modified: changeSummary.modified,
                            deleted: changeSummary.deleted,
                          })}
                        </span>
                      </div>

                      <div className="flex items-center gap-2 mb-2">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs gap-1.5 text-muted-foreground hover:text-foreground"
                          onClick={(event) => {
                            event.stopPropagation();
                            toggleChanges(checkpoint.id);
                          }}
                        >
                          <Diff className="w-3 h-3" />
                          {t("history.changes")} ({checkpoint.changes.length})
                          {expandedChanges[checkpoint.id] ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                        </Button>
                        {!checkpoint.isCurrent ? (
                          <Button
                            variant="secondary"
                            size="sm"
                            className="h-7 text-xs gap-1.5"
                            disabled={currentTask?.status === "running" || currentTask?.status === "waiting_user"}
                            isLoading={rollbackVersion.isPending && rollbackVersion.variables === checkpoint.version}
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleRollback(checkpoint.version);
                            }}
                          >
                            <RotateCcw className="w-3 h-3" />
                            {t("history.rollback")}
                          </Button>
                        ) : null}
                      </div>
                    </div>

                    {expandedChanges[checkpoint.id] ? (
                      <DiffView
                        projectId={projectId}
                        changes={checkpoint.changes}
                        version={checkpoint.version}
                        sourceVersion={checkpoint.sourceVersion}
                        onSelectChange={onSelectChange}
                      />
                    ) : null}
                        </>
                      );
                    })()}
                  </div>
                )) : (
                  <div className="space-y-3 pl-6 text-sm text-muted-foreground">
                    <div>{t("history.empty")}</div>
                    {pendingPreviewVersion ? (
                      <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-xs leading-6 text-amber-100">
                        {t("history.emptyPendingPreview", { version: pendingPreviewVersion })}
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            </div>

            <div className="p-4 border-t border-white/10 bg-secondary/30 flex items-center gap-3">
              <div className={cn("relative flex h-2.5 w-2.5", currentTask?.status === "waiting_user" ? "" : "opacity-40")}>
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-yellow-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-yellow-400" />
              </div>
              <span className="text-sm text-muted-foreground">
                {currentTask?.status === "waiting_user" ? t("history.waiting") : t("history.synced")}
              </span>
            </div>
          </motion.div>
        </>
      ) : null}
    </AnimatePresence>
  );
}
