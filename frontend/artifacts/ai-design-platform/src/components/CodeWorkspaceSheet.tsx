import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Braces, ChevronDown, ChevronRight, Download, Edit3, Eye, FileCode2, FolderTree, Lock, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge, Button, Textarea } from "@/components/ui";
import {
  ApiError,
  getEditorUserId,
  getCodePreviewUrl,
  useAcquireCodeFileLock,
  type CodeTreeNode,
  useCodeFile,
  useCodeTree,
  useCommitProjectDrafts,
  useDownloadCode,
  type ProjectFileEntry,
  useProjectDrafts,
  useProjectFile,
  useProjectFiles,
  useReleaseCodeFileLock,
  useSaveProjectFileDraft,
  useUpdateCodeFile,
  useUpdateProjectFile,
} from "@/hooks/use-api";
import {
  buildWorkspaceDocKey,
  resolveWorkspaceDocSelection,
  type CodeWorkspaceSelectionRequest,
} from "@/lib/code-workspace-target";
import { resolveCodeWorkspaceVersion } from "@/lib/code-workspace-version";
import { shouldAutoSwitchWorkspaceMode, type WorkspaceMode } from "@/lib/code-workspace-mode";
import { resolveWorkspaceVersionState } from "@/lib/workspace-version-state";
import {
  expandCodeTreeFoldersForSelection,
  groupWorkspaceDocItems,
  humanizeAgentSourceName,
  syncCodeTreeExpandedState,
  syncWorkspaceDocGroupExpandedState,
  type CodeTreeExpandedState,
  type WorkspaceDocGroupExpandedState,
} from "@/lib/code-workspace-list";
import { detectPreviewLanguage, highlightCodeLine, type CodeToken } from "@/lib/preview-format";
import { cn } from "@/lib/utils";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "@/hooks/use-toast";

type WorkspaceDocItem = {
  key: string;
  agent: string;
  path: string;
  fileName: string;
  fileType: string;
  contentType: string;
  language: string;
  isEditable: boolean;
  hasDraft: boolean;
  mappedArtifactTypes: string[];
};

function flattenFirstFile(nodes: CodeTreeNode[]): string | null {
  for (const node of nodes) {
    if (node.type === "file" && node.path) {
      return node.path;
    }
    if (node.children?.length) {
      const nested = flattenFirstFile(node.children);
      if (nested) return nested;
    }
  }
  return null;
}

function isPreviewableFile(path: string | null): boolean {
  return Boolean(path && path.toLowerCase().endsWith(".html"));
}

function sourceLabel(t: ReturnType<typeof useTranslation>["t"], source: string) {
  return t(`chat.source.${source}`, { defaultValue: humanizeAgentSourceName(source) });
}

function codeTokenClass(token: CodeToken) {
  if (token.type === "keyword") return "text-fuchsia-300";
  if (token.type === "string") return "text-emerald-300";
  if (token.type === "number") return "text-amber-300";
  if (token.type === "comment") return "text-slate-500";
  if (token.type === "property") return "text-sky-300";
  if (token.type === "tag") return "text-rose-300";
  return "text-slate-200";
}

function toDocItem(file: ProjectFileEntry): WorkspaceDocItem {
  const agent =
    file.stage === "requirements"
      ? "requirements_agent"
      : file.stage === "architecture"
        ? "architecture_agent"
        : file.stage === "ui"
          ? "ui_agent"
          : file.stage === "coding"
            ? "coding_agent"
            : file.stage === "test"
              ? "test_agent"
              : "artifacts";
  return {
    key: buildWorkspaceDocKey(agent, file.fileName),
    agent,
    path: file.path,
    fileName: file.fileName,
    fileType: file.language,
    contentType: file.contentType,
    language: file.language,
    isEditable: file.isEditable,
    hasDraft: Boolean(file.hasDraft),
    mappedArtifactTypes: file.derivedArtifactType ? [file.derivedArtifactType] : [],
  };
}

function buildWorkspaceDocItems(files: ProjectFileEntry[] | undefined): WorkspaceDocItem[] {
  return [...(files ?? [])]
    .filter((file) => file.stage !== "workspace")
    .sort((left, right) => left.path.localeCompare(right.path))
    .map((file) => toDocItem(file));
}

function MarkdownPreview({ content }: { content: string }) {
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
            const raw = String(children);
            const isInlineCode = !className && !raw.includes("\n");
            if (isInlineCode) {
              return (
                <code className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[0.9em] text-cyan-200">
                  {children}
                </code>
              );
            }
            const language = className?.replace("language-", "") ?? "text";
            return (
              <div className="mt-6 overflow-hidden rounded-2xl border border-white/10 bg-[#05080d]">
                <div className="border-b border-white/10 px-4 py-2 text-[11px] uppercase tracking-[0.2em] text-slate-400">
                  {language}
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

function CodePreview({
  content,
  language,
}: {
  content: string;
  language: ReturnType<typeof detectPreviewLanguage>;
}) {
  const lines = content.split("\n");
  return (
    <div className="overflow-hidden rounded-xl border border-white/10 bg-[#05080d]">
      <div className="border-b border-white/10 px-4 py-2 text-[11px] uppercase tracking-[0.18em] text-slate-400">
        {language}
      </div>
      <pre className="max-h-[70vh] overflow-auto p-4 text-sm leading-6">
        {lines.map((line, lineIndex) => {
          const tokens = highlightCodeLine(line, language);
          return (
            <div key={`${lineIndex}-${line}`} className="table-row">
              <span className="table-cell select-none pr-4 text-right text-xs text-slate-500">{lineIndex + 1}</span>
              <span className="table-cell whitespace-pre-wrap break-words">
                {tokens.map((token, tokenIndex) => (
                  <span key={`${lineIndex}-${tokenIndex}-${token.text}`} className={codeTokenClass(token)}>
                    {token.text}
                  </span>
                ))}
              </span>
            </div>
          );
        })}
      </pre>
    </div>
  );
}

function CodeTree({
  nodes,
  selectedPath,
  onSelect,
  expandedFolders,
  onToggleFolder,
  draftPaths,
  currentPath = "",
  level = 0,
}: {
  nodes: CodeTreeNode[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  expandedFolders: CodeTreeExpandedState;
  onToggleFolder: (folderPath: string) => void;
  draftPaths: Set<string>;
  currentPath?: string;
  level?: number;
}) {
  return (
    <div className="space-y-1">
      {nodes.map((node) => {
        if (node.type === "folder") {
          const folderPath = currentPath ? `${currentPath}/${node.name}` : node.name;
          const isExpanded = expandedFolders[folderPath] ?? true;
          return (
            <div key={folderPath}>
              <button
                type="button"
                onClick={() => onToggleFolder(folderPath)}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-[11px] font-medium tracking-[0.04em] text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground"
                style={{ paddingLeft: `${level * 14 + 8}px` }}
              >
                {isExpanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
                <FolderTree className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{node.name}</span>
              </button>
              {isExpanded && node.children?.length ? (
                <CodeTree
                  nodes={node.children}
                  selectedPath={selectedPath}
                  onSelect={onSelect}
                  expandedFolders={expandedFolders}
                  onToggleFolder={onToggleFolder}
                  draftPaths={draftPaths}
                  currentPath={folderPath}
                  level={level + 1}
                />
              ) : null}
            </div>
          );
        }

        return (
          <button
            key={node.path ?? `${level}-${node.name}`}
            type="button"
            onClick={() => node.path && onSelect(node.path)}
            className={cn(
              "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors",
              selectedPath === node.path
                ? "bg-primary/10 text-foreground"
                : "text-muted-foreground hover:bg-white/5 hover:text-foreground",
            )}
            style={{ paddingLeft: `${level * 14 + 8}px` }}
          >
            <FileCode2 className="h-4 w-4 shrink-0" />
            <span className="truncate">{node.name}</span>
            {node.path && draftPaths.has(node.path) ? (
              <span className="ml-auto rounded-full border border-amber-500/20 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-200">
                草稿
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

function DocTree({
  groups,
  selectedDocKey,
  onSelect,
  expandedGroups,
  onToggleGroup,
  t,
}: {
  groups: Array<{ agent: string; items: WorkspaceDocItem[] }>;
  selectedDocKey: string | null;
  onSelect: (key: string) => void;
  expandedGroups: WorkspaceDocGroupExpandedState;
  onToggleGroup: (agent: string) => void;
  t: ReturnType<typeof useTranslation>["t"];
}) {
  return (
    <div className="space-y-2">
      {groups.map((group) => {
        const isExpanded = expandedGroups[group.agent] ?? true;
        return (
          <div key={group.agent}>
            <button
              type="button"
              onClick={() => onToggleGroup(group.agent)}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-[11px] font-medium tracking-[0.04em] text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground"
            >
              {isExpanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
              <FolderTree className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{sourceLabel(t, group.agent)}</span>
            </button>
            {isExpanded ? (
              <div className="mt-1 space-y-1">
                {group.items.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => onSelect(item.key)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors",
                      selectedDocKey === item.key
                        ? "bg-primary/10 text-foreground"
                        : "text-muted-foreground hover:bg-white/5 hover:text-foreground",
                    )}
                    style={{ paddingLeft: "22px" }}
                  >
                    <FileCode2 className="h-4 w-4 shrink-0" />
                    <span className="truncate">{item.fileName}</span>
                    {item.hasDraft ? (
                      <span className="ml-auto rounded-full border border-amber-500/20 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-200">
                        草稿
                      </span>
                    ) : null}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function CodeWorkspaceSheet({
  projectId,
  version,
  currentVersion,
  pendingAgentArtifactsVersion,
  isOpen,
  openTarget,
  onVersionChange,
  onOpenChange,
}: {
  projectId: string;
  version: number | null;
  currentVersion?: number;
  pendingAgentArtifactsVersion?: number | null;
  isOpen: boolean;
  openTarget?: CodeWorkspaceSelectionRequest | null;
  onVersionChange: (version: number) => void;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const workspaceVersion = useMemo(
    () => resolveCodeWorkspaceVersion(version, currentVersion ?? null, pendingAgentArtifactsVersion ?? null),
    [currentVersion, pendingAgentArtifactsVersion, version],
  );
  const { data: codeTree, isLoading: isTreeLoading, isError: isTreeError } = useCodeTree(projectId, workspaceVersion);
  const workspaceVersionState = useMemo(
    () =>
      resolveWorkspaceVersionState(
        codeTree?.version ?? null,
        currentVersion ?? null,
        pendingAgentArtifactsVersion ?? null,
      ),
    [codeTree?.version, currentVersion, pendingAgentArtifactsVersion],
  );
  const { data: projectFiles, isLoading: isProjectFilesLoading } = useProjectFiles(projectId, workspaceVersion);
  const { data: projectDrafts } = useProjectDrafts(projectId);
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>("docs");
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [selectedDocKey, setSelectedDocKey] = useState<string | null>(null);
  const [expandedDocGroups, setExpandedDocGroups] = useState<WorkspaceDocGroupExpandedState>({});
  const [expandedCodeFolders, setExpandedCodeFolders] = useState<CodeTreeExpandedState>({});
  const { data: codeFile, isLoading: isFileLoading, isError: isFileError } = useCodeFile(projectId, selectedFilePath, workspaceVersion);
  const docItems = useMemo(
    () => buildWorkspaceDocItems(projectFiles?.files),
    [projectFiles?.files],
  );
  const selectedDoc =
    docItems.find((item) => item.key === selectedDocKey) ??
    docItems[0] ??
    null;
  const selectedUnifiedFilePath =
    workspaceMode === "docs"
      ? (selectedDoc?.path ?? null)
      : (selectedFilePath ? `workspace/${selectedFilePath}` : null);
  const {
    data: projectFile,
    isLoading: isProjectFileLoading,
    isError: isProjectFileError,
  } = useProjectFile(projectId, selectedUnifiedFilePath, workspaceVersion);
  const downloadCode = useDownloadCode(projectId);
  const updateCodeFile = useUpdateCodeFile(projectId);
  const updateProjectFile = useUpdateProjectFile(projectId);
  const saveProjectFileDraft = useSaveProjectFileDraft(projectId);
  const commitProjectDrafts = useCommitProjectDrafts(projectId);
  const acquireCodeLock = useAcquireCodeFileLock(projectId);
  const releaseCodeLock = useReleaseCodeFileLock(projectId);
  const [isEditing, setIsEditing] = useState(false);
  const [draftContent, setDraftContent] = useState("");
  const [lastSyncedContent, setLastSyncedContent] = useState("");
  const [lockOwner, setLockOwner] = useState<NonNullable<typeof codeFile>["lock"]>(null);
  const [editorStatus, setEditorStatus] = useState<"idle" | "unsaved" | "autosaving" | "autosaved" | "saving" | "saved" | "error">("idle");
  const editorUserId = useMemo(() => getEditorUserId(), []);
  const saveActionRef = useRef<(() => Promise<void>) | null>(null);

  const treeNodes = useMemo(() => codeTree?.tree ?? [], [codeTree?.tree]);
  const docGroups = useMemo(() => groupWorkspaceDocItems(docItems), [docItems]);
  const workspaceDraftPaths = useMemo(
    () =>
      new Set(
        (projectFiles?.files ?? [])
          .filter((file) => file.stage === "workspace" && file.hasDraft)
          .map((file) => file.path.replace(/^workspace\//, "")),
      ),
    [projectFiles?.files],
  );
  const projectDraftCount = projectDrafts?.totalFiles ?? 0;
  const hasPreview = isPreviewableFile(selectedFilePath);
  const isHistoricalVersion =
    typeof version === "number" &&
    typeof currentVersion === "number" &&
    version !== currentVersion;
  const isLockedByAnotherUser = Boolean(lockOwner && lockOwner.lockedBy !== editorUserId);
  const hasUnsavedChanges = isEditing && draftContent !== lastSyncedContent;

  useEffect(() => {
    const firstFile = flattenFirstFile(treeNodes);
    if (!firstFile) {
      setSelectedFilePath(null);
      return;
    }
    setSelectedFilePath((current) => (current ? current : firstFile));
  }, [treeNodes]);

  useEffect(() => {
    if (!selectedFilePath) {
      return;
    }
    const fileStillExists = (() => {
      const search = (nodes: CodeTreeNode[]): boolean =>
        nodes.some((node) => {
          if (node.type === "file") {
            return node.path === selectedFilePath;
          }
          return node.children ? search(node.children) : false;
        });
      return search(treeNodes);
    })();
    if (!fileStillExists) {
      setSelectedFilePath(flattenFirstFile(treeNodes));
    }
  }, [selectedFilePath, treeNodes]);

  useEffect(() => {
    setExpandedCodeFolders((current) => syncCodeTreeExpandedState(treeNodes, current));
  }, [treeNodes]);

  useEffect(() => {
    setExpandedCodeFolders((current) => expandCodeTreeFoldersForSelection(selectedFilePath, current));
  }, [selectedFilePath]);

  useEffect(() => {
    if (shouldAutoSwitchWorkspaceMode(workspaceMode, isProjectFilesLoading, docItems.length)) {
      setSelectedDocKey(null);
      setWorkspaceMode("code");
      return;
    }
    if (isProjectFilesLoading) {
      return;
    }
    setSelectedDocKey((current) => (current && docItems.some((item) => item.key === current) ? current : docItems[0]?.key ?? null));
  }, [docItems, isProjectFilesLoading, workspaceMode]);

  useEffect(() => {
    setExpandedDocGroups((current) => syncWorkspaceDocGroupExpandedState(docGroups, current));
  }, [docGroups]);

  useEffect(() => {
    if (!selectedDoc) {
      return;
    }
    setExpandedDocGroups((current) => ({
      ...current,
      [selectedDoc.agent]: true,
    }));
  }, [selectedDoc]);

  useEffect(() => {
    if (!isOpen || !openTarget) {
      return;
    }
    if (openTarget.kind === "doc") {
      setWorkspaceMode("docs");
      const nextDocKey = resolveWorkspaceDocSelection(docItems, openTarget);
      if (nextDocKey) {
        setSelectedDocKey(nextDocKey);
      }
      return;
    }
    setWorkspaceMode("code");
    setSelectedFilePath(openTarget.filePath);
  }, [docItems, isOpen, openTarget]);

  useEffect(() => {
    const nextContent = projectFile?.content ?? codeFile?.content ?? "";
    setDraftContent(nextContent);
    setLastSyncedContent(nextContent);
    setLockOwner(workspaceMode === "docs" ? null : codeFile?.lock ?? null);
    setIsEditing(false);
    setEditorStatus("idle");
  }, [workspaceMode, codeFile?.content, codeFile?.path, codeFile?.version, projectFile?.content, projectFile?.path, projectFile?.version]);

  useEffect(() => {
    if (!isEditing) {
      return;
    }
    setEditorStatus(hasUnsavedChanges ? "unsaved" : "idle");
  }, [draftContent, hasUnsavedChanges, isEditing]);

  useEffect(() => {
    if (workspaceMode !== "code" || !isEditing || !selectedFilePath) {
      return;
    }
    return () => {
      void releaseCodeLock.mutateAsync({ filePath: selectedFilePath, userId: editorUserId }).catch(() => undefined);
    };
  }, [editorUserId, isEditing, releaseCodeLock, selectedFilePath, workspaceMode]);

  useEffect(() => {
    if (!isEditing || !isOpen) {
      return;
    }
    const handleKeydown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void saveActionRef.current?.();
      }
    };
    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [isEditing, isOpen]);

  useEffect(() => {
    if (workspaceMode !== "code" || !isEditing || !selectedFilePath || isHistoricalVersion || !hasUnsavedChanges) {
      return;
    }
    const timer = window.setTimeout(() => {
      setEditorStatus("autosaving");
      void saveProjectFileDraft
        .mutateAsync({
          filePath: `workspace/${selectedFilePath}`,
          content: draftContent,
          version,
          userId: editorUserId,
        })
        .then((updated) => {
          setLastSyncedContent(updated.content);
          setEditorStatus("autosaved");
        })
        .catch((error: unknown) => {
          setEditorStatus("error");
          const message =
            error instanceof ApiError ? error.message : t("code.autosaveErrorDescription");
          toast({
            title: t("code.autosaveErrorTitle"),
            description: message,
            variant: "destructive",
          });
        });
    }, 30000);
    return () => window.clearTimeout(timer);
  }, [saveProjectFileDraft, draftContent, editorUserId, hasUnsavedChanges, isEditing, isHistoricalVersion, selectedFilePath, t, version, workspaceMode]);

  const handleDownload = async () => {
    const result = await downloadCode.mutateAsync(version);
    const url = URL.createObjectURL(result.blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = result.filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  const stopEditing = () => {
    setIsEditing(false);
    const latestContent = projectFile?.content ?? codeFile?.content ?? "";
    setDraftContent(latestContent);
    setLastSyncedContent(latestContent);
    setEditorStatus("idle");
  };

  const handleStartEdit = async () => {
    if (workspaceMode === "docs") {
      if (!projectFile?.isEditable) {
        return;
      }
      setDraftContent(projectFile.content);
      setLastSyncedContent(projectFile.content);
      setIsEditing(true);
      setEditorStatus("idle");
      return;
    }
    if (!codeFile || !selectedFilePath) {
      return;
    }
    try {
      const lock = await acquireCodeLock.mutateAsync({
        filePath: selectedFilePath,
        version,
        userId: editorUserId,
      });
      setLockOwner(lock);
      setDraftContent(projectFile?.content ?? codeFile.content);
      setLastSyncedContent(projectFile?.content ?? codeFile.content);
      setIsEditing(true);
      setEditorStatus("idle");
    } catch (error) {
      const message = error instanceof ApiError ? error.message : t("code.lockErrorDescription");
      toast({
        title: t("code.lockErrorTitle"),
        description: message,
        variant: "destructive",
      });
    }
  };

  const handleSave = async () => {
    if (!isHistoricalVersion) {
      if (!selectedUnifiedFilePath) {
        return;
      }
      setEditorStatus("saving");
      try {
        const updated = await saveProjectFileDraft.mutateAsync({
          filePath: selectedUnifiedFilePath,
          content: draftContent,
          version,
          userId: editorUserId,
        });
        setLastSyncedContent(updated.content);
        setEditorStatus("saved");
        setIsEditing(false);
      } catch (error) {
        setEditorStatus("error");
        const message = error instanceof ApiError ? error.message : t("code.saveErrorDescription");
        toast({
          title: t("code.saveErrorTitle"),
          description: message,
          variant: "destructive",
        });
      }
      return;
    }

    if (workspaceMode === "docs") {
      if (!selectedDoc?.path) {
        return;
      }
      setEditorStatus("saving");
      try {
        const updated = await updateProjectFile.mutateAsync({
          filePath: selectedDoc.path,
          content: draftContent,
          version,
          userId: editorUserId,
        });
        setLastSyncedContent(updated.content);
        if (updated.version !== (version ?? updated.version)) {
          onVersionChange(updated.version);
        }
        setEditorStatus("saved");
        setIsEditing(false);
      } catch (error) {
        setEditorStatus("error");
        const message = error instanceof ApiError ? error.message : t("code.saveErrorDescription");
        toast({
          title: t("code.saveErrorTitle"),
          description: message,
          variant: "destructive",
        });
      }
      return;
    }
    if (!codeFile || !selectedFilePath) {
      return;
    }
    setEditorStatus("saving");
    try {
      const updated = await updateCodeFile.mutateAsync({
        filePath: selectedFilePath,
        content: draftContent,
        version,
        userId: editorUserId,
      });
      setLastSyncedContent(updated.content);
      setLockOwner(updated.lock ?? null);
      if (updated.version !== (version ?? updated.version)) {
        onVersionChange(updated.version);
      }
      setEditorStatus("saved");
      setIsEditing(false);
    } catch (error) {
      setEditorStatus("error");
      const message = error instanceof ApiError ? error.message : t("code.saveErrorDescription");
      toast({
        title: t("code.saveErrorTitle"),
        description: message,
        variant: "destructive",
      });
    }
  };

  const handleCommitDrafts = async () => {
    const result = await commitProjectDrafts.mutateAsync({
      description: `Committed ${projectDraftCount} draft file(s).`,
      userId: editorUserId,
    });
    onVersionChange(result.newVersion);
    toast({
      title: "已提交当前修改",
      description: `已创建版本 v${result.newVersion}，共提交 ${result.committedPaths.length} 个文件。`,
    });
  };

  saveActionRef.current = handleSave;

  const editorStatusLabel = (() => {
    if (isLockedByAnotherUser) {
      return t("code.lockedByOther");
    }
    if (isHistoricalVersion && isEditing) {
      return t("code.historySaveHint", { defaultValue: "你正在查看历史版本，保存后会基于这个版本创建新版本。" });
    }
    if (editorStatus === "unsaved") return t("code.status.unsaved");
    if (editorStatus === "autosaving") return t("code.status.autosaving");
    if (editorStatus === "autosaved") return t("code.status.autosaved");
    if (editorStatus === "saving") return t("code.status.saving");
    if (editorStatus === "saved") return t("code.status.saved");
    if (editorStatus === "error") return t("code.status.error");
    if (isEditing) return t("code.lockedBySelf");
    return null;
  })();

  const saveButtonLabel = isHistoricalVersion
    ? t("code.saveAsNewVersionFromHistory", { defaultValue: "基于该历史版本创建新版本" })
    : t("code.saveDraft", { defaultValue: "保存草稿" });
  // 这里必须始终以接口返回的最新文件内容为准，不能再从左侧树节点缓存里取内容，
  // 否则用户切换版本或保存为新版本后，右侧预览会继续显示旧内容。
  const selectedDocContent = projectFile?.content ?? "";
  const selectedDocPreviewLanguage = detectPreviewLanguage(selectedDoc?.fileName ?? "");
  const selectedCodeContent = projectFile?.content ?? codeFile?.content ?? "";
  const selectedCodePreviewLanguage = detectPreviewLanguage(selectedFilePath ?? "");

  return (
    <Sheet
      open={isOpen}
      onOpenChange={(open) => {
        if (!open && isEditing) {
          stopEditing();
        }
        onOpenChange(open);
      }}
    >
      <SheetContent side="right" className="w-full border-white/10 bg-[#0f0f0f] p-0 text-foreground sm:max-w-[1100px]">
        <div className="flex h-full flex-col">
          <SheetHeader className="border-b border-white/10 px-6 py-5">
            <div className="flex items-start justify-between gap-6">
              <div>
                <SheetTitle className="flex items-center gap-2">
                  <Braces className="h-5 w-5 text-primary" />
                  {t("code.title")}
                </SheetTitle>
                <SheetDescription className="mt-1">
                  {t("code.description")}
                </SheetDescription>
              </div>
              <div className="flex items-center gap-3 pr-8">
                {workspaceVersionState.version ? (
                  <Badge
                    variant="outline"
                    className={cn(
                      "bg-secondary",
                      workspaceVersionState.isPendingPreview
                        ? "border-amber-500/30 bg-amber-500/10 text-amber-200"
                        : "text-muted-foreground",
                    )}
                  >
                    {workspaceVersionState.isPendingPreview
                      ? t("code.pendingVersionBadge", {
                          defaultValue: "预览 v{{version}}",
                          version: workspaceVersionState.version,
                        })
                      : `v${workspaceVersionState.version}`}
                  </Badge>
                ) : null}
                {!isHistoricalVersion && projectDraftCount > 0 ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => void handleCommitDrafts()}
                    isLoading={commitProjectDrafts.isPending}
                  >
                    提交当前修改 ({projectDraftCount})
                  </Button>
                ) : null}
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void handleDownload()}
                  isLoading={downloadCode.isPending}
                >
                  <Download className="mr-2 h-4 w-4" />
                  {t("code.download")}
                </Button>
              </div>
            </div>
          </SheetHeader>

          <div className="grid min-h-0 flex-1 grid-cols-[320px_minmax(0,1fr)] overflow-hidden">
            <div className="flex min-h-0 flex-col border-r border-white/10 bg-black/20">
              <div className="border-b border-white/10 px-4 py-4">
                <div className="inline-flex rounded-lg border border-white/10 bg-black/20 p-1">
                  <button
                    type="button"
                    onClick={() => setWorkspaceMode("docs")}
                    className={cn(
                      "rounded-md px-3 py-1.5 text-xs transition-colors",
                      workspaceMode === "docs" ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {t("code.docs", { defaultValue: "Docs" })}
                  </button>
                  <button
                    type="button"
                    onClick={() => setWorkspaceMode("code")}
                    className={cn(
                      "rounded-md px-3 py-1.5 text-xs transition-colors",
                      workspaceMode === "code" ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {t("code.files")}
                  </button>
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
                {workspaceMode === "docs" ? (
                  <div className="space-y-3">
                    {docItems.length ? (
                      <DocTree
                        groups={docGroups}
                        selectedDocKey={selectedDocKey}
                        onSelect={setSelectedDocKey}
                        expandedGroups={expandedDocGroups}
                        onToggleGroup={(agent) =>
                          setExpandedDocGroups((current) => ({
                            ...current,
                            [agent]: !(current[agent] ?? true),
                          }))
                        }
                        t={t}
                      />
                    ) : isProjectFilesLoading ? (
                      <div className="px-2 text-sm text-muted-foreground">
                        {t("code.loadingDocs", { defaultValue: "正在加载文档列表..." })}
                      </div>
                    ) : (
                      <div className="px-2 text-sm text-muted-foreground">
                        {t("code.docsEmpty", { defaultValue: "No raw agent documents are available for this version yet." })}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div>
                      <div className="mb-2 px-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
                        {t("code.files")}
                      </div>
                      {isTreeLoading ? (
                        <div className="px-2 text-sm text-muted-foreground">{t("code.loadingTree")}</div>
                      ) : isTreeError ? (
                        <div className="px-2 text-sm text-muted-foreground">{t("code.empty")}</div>
                      ) : (
                        <CodeTree
                          nodes={treeNodes}
                          selectedPath={selectedFilePath}
                          onSelect={setSelectedFilePath}
                          expandedFolders={expandedCodeFolders}
                          draftPaths={workspaceDraftPaths}
                          onToggleFolder={(folderPath) =>
                            setExpandedCodeFolders((current) => ({
                              ...current,
                              [folderPath]: !(current[folderPath] ?? true),
                            }))
                          }
                        />
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="min-h-0 overflow-hidden bg-[#101010]">
              <div className="flex h-full flex-col">
                {workspaceMode === "code" ? (
                  <div className="border-b border-white/10 px-6 py-4">
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                          {t("code.selectedFile")}
                        </div>
                        <div className="mt-1 text-sm font-medium text-foreground">
                          {selectedFilePath ?? t("code.noFileSelected")}
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        {codeFile ? (
                          <Badge variant="outline" className="bg-transparent text-muted-foreground">
                            {projectFile?.language ?? codeFile.language}
                          </Badge>
                        ) : null}
                        {projectFile?.hasDraft ? (
                          <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-amber-200">
                            草稿
                          </Badge>
                        ) : null}
                        {codeFile ? (
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={acquireCodeLock.isPending || isLockedByAnotherUser}
                            onClick={() => void (isEditing ? stopEditing() : handleStartEdit())}
                          >
                            <Edit3 className="mr-2 h-4 w-4" />
                            {isEditing ? t("code.cancelEdit") : t("code.edit")}
                          </Button>
                        ) : null}
                      </div>
                    </div>
                    {editorStatusLabel ? (
                      <div
                        className={cn(
                          "mt-3 flex items-center gap-2 rounded-xl border px-3 py-2 text-xs",
                          isLockedByAnotherUser
                            ? "border-amber-500/30 bg-amber-500/10 text-amber-200"
                            : "border-white/10 bg-black/30 text-muted-foreground",
                        )}
                      >
                        {isLockedByAnotherUser ? <Lock className="h-3.5 w-3.5" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                        <span>{editorStatusLabel}</span>
                      </div>
                    ) : null}
                    {isHistoricalVersion ? (
                      <div className="mt-3 rounded-xl border border-cyan-500/20 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-100">
                        {t("code.historyVersionBanner", {
                          defaultValue: "当前查看的是历史版本 v{{version}}。手动保存不会覆盖旧版本，而是创建一个新的版本。",
                          version,
                        })}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="border-b border-white/10 px-6 py-4">
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                          {t("code.selectedFile")}
                        </div>
                        <div className="mt-1 text-sm font-medium text-foreground">
                          {selectedDoc?.path ?? t("code.noFileSelected")}
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        {selectedDoc ? (
                          <Badge variant="outline" className="bg-transparent text-muted-foreground">
                            {selectedDoc.language}
                          </Badge>
                        ) : null}
                        {projectFile?.hasDraft ? (
                          <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-amber-200">
                            草稿
                          </Badge>
                        ) : null}
                        {selectedDoc?.isEditable ? (
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={isProjectFileLoading}
                            onClick={() => void (isEditing ? stopEditing() : handleStartEdit())}
                          >
                            <Edit3 className="mr-2 h-4 w-4" />
                            {isEditing ? t("code.cancelEdit") : t("code.edit")}
                          </Button>
                        ) : null}
                      </div>
                    </div>
                    {editorStatusLabel ? (
                      <div className="mt-3 flex items-center gap-2 rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-xs text-muted-foreground">
                        <ShieldCheck className="h-3.5 w-3.5" />
                        <span>{editorStatusLabel}</span>
                      </div>
                    ) : null}
                    {isHistoricalVersion ? (
                      <div className="mt-3 rounded-xl border border-cyan-500/20 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-100">
                        {t("code.historyVersionBanner", {
                          defaultValue: "当前查看的是历史版本 v{{version}}。手动保存不会覆盖旧版本，而是创建一个新的版本。",
                          version,
                        })}
                      </div>
                    ) : null}
                  </div>
                )}

                <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
                  {workspaceMode === "docs" ? (
                    !selectedDoc ? (
                      <div className="rounded-2xl border border-white/10 bg-card/50 px-6 py-8 text-center text-muted-foreground">
                        {t("code.docsEmpty", { defaultValue: "No raw agent documents are available for this version yet." })}
                      </div>
                    ) : isProjectFileLoading ? (
                      <div className="text-sm text-muted-foreground">
                        {t("code.loadingFile")}
                      </div>
                    ) : isProjectFileError || !projectFile ? (
                      <div className="rounded-2xl border border-white/10 bg-card/50 px-6 py-8 text-center text-muted-foreground">
                        {t("code.empty")}
                      </div>
                    ) : (
                      <div className="space-y-4">
                        {isEditing ? (
                          <div className="space-y-4">
                            <Textarea
                              value={draftContent}
                              onChange={(event) => setDraftContent(event.target.value)}
                              className="min-h-[60vh] border-white/10 bg-black/40 font-mono text-sm leading-6 text-muted-foreground"
                            />
                            <div className="flex justify-end gap-3">
                              <Button variant="ghost" onClick={stopEditing}>
                                {t("chat.cancel")}
                              </Button>
                              <Button
                                onClick={() => void handleSave()}
                                isLoading={isHistoricalVersion ? updateProjectFile.isPending : saveProjectFileDraft.isPending}
                                disabled={!hasUnsavedChanges}
                              >
                                {saveButtonLabel}
                              </Button>
                            </div>
                          </div>
                        ) : selectedDocContent.trim() ? (
                          selectedDocPreviewLanguage === "markdown" ? (
                            <div className="rounded-2xl border border-white/10 bg-black/20 p-5">
                              <MarkdownPreview content={selectedDocContent} />
                            </div>
                          ) : selectedDocPreviewLanguage !== "text" ? (
                            <CodePreview content={selectedDocContent} language={selectedDocPreviewLanguage} />
                          ) : (
                            <pre className="overflow-x-auto rounded-2xl border border-white/10 bg-black/40 p-5 text-sm leading-6 text-muted-foreground">
                              {selectedDocContent}
                            </pre>
                          )
                        ) : (
                          <div className="rounded-2xl border border-white/10 bg-card/50 px-6 py-8 text-center text-muted-foreground">
                            {t("chat.outputPreviewEmpty")}
                          </div>
                        )}
                      </div>
                    )
                  ) : isProjectFileLoading ? (
                    <div className="text-sm text-muted-foreground">{t("code.loadingFile")}</div>
                  ) : isProjectFileError || !projectFile ? (
                    <div className="rounded-2xl border border-white/10 bg-card/50 px-6 py-8 text-center text-muted-foreground">
                      {t("code.empty")}
                    </div>
                  ) : hasPreview ? (
                    <Tabs defaultValue="preview" className="space-y-4">
                      <TabsList className="bg-black/30">
                        <TabsTrigger value="preview">
                          <Eye className="mr-2 h-4 w-4" />
                          {t("code.preview")}
                        </TabsTrigger>
                        <TabsTrigger value="source">
                          <FileCode2 className="mr-2 h-4 w-4" />
                          {t("code.source")}
                        </TabsTrigger>
                      </TabsList>
                      <TabsContent value="preview" className="mt-0">
                        <div className="overflow-hidden rounded-2xl border border-white/10 bg-white">
                          <iframe
                            title={selectedFilePath ?? "preview"}
                            src={selectedFilePath ? getCodePreviewUrl(projectId, selectedFilePath, version) : undefined}
                            className="h-[70vh] w-full border-0"
                          />
                        </div>
                      </TabsContent>
                      <TabsContent value="source" className="mt-0">
                        {isEditing ? (
                          <div className="space-y-4">
                            <Textarea
                              value={draftContent}
                              onChange={(event) => setDraftContent(event.target.value)}
                              className="min-h-[60vh] border-white/10 bg-black/40 font-mono text-sm leading-6 text-muted-foreground"
                            />
                            <div className="flex justify-end gap-3">
                              <Button variant="ghost" onClick={stopEditing}>
                                {t("chat.cancel")}
                              </Button>
                              <Button
                                onClick={() => void handleSave()}
                                isLoading={isHistoricalVersion ? updateCodeFile.isPending : saveProjectFileDraft.isPending}
                                disabled={!hasUnsavedChanges}
                              >
                                {saveButtonLabel}
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <pre className="overflow-x-auto rounded-2xl border border-white/10 bg-black/40 p-5 text-sm leading-6 text-muted-foreground">
                            {selectedCodeContent}
                          </pre>
                        )}
                      </TabsContent>
                    </Tabs>
                  ) : (
                    isEditing ? (
                      <div className="space-y-4">
                        <Textarea
                          value={draftContent}
                          onChange={(event) => setDraftContent(event.target.value)}
                          className="min-h-[60vh] border-white/10 bg-black/40 font-mono text-sm leading-6 text-muted-foreground"
                        />
                        <div className="flex justify-end gap-3">
                          <Button variant="ghost" onClick={stopEditing}>
                            {t("chat.cancel")}
                          </Button>
                          <Button
                            onClick={() => void handleSave()}
                            isLoading={isHistoricalVersion ? updateCodeFile.isPending : saveProjectFileDraft.isPending}
                            disabled={!hasUnsavedChanges}
                          >
                            {saveButtonLabel}
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <pre className="overflow-x-auto rounded-2xl border border-white/10 bg-black/40 p-5 text-sm leading-6 text-muted-foreground">
                        {selectedCodeContent}
                      </pre>
                    )
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
