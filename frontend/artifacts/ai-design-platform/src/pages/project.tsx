import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useRoute } from "wouter";
import { ChevronLeft, Loader2, Pencil } from "lucide-react";
import { Link } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import { ChatArea } from "@/components/ChatArea";
import { ArtifactViewer } from "@/components/ArtifactViewer";
import { CodeWorkspaceSheet } from "@/components/CodeWorkspaceSheet";
import { LanguageToggle } from "@/components/LanguageToggle";
import { ProjectRenameDialog } from "@/components/ProjectRenameDialog";
import { VersionHistorySidebar } from "@/components/VersionHistorySidebar";
import { ApiError, useCurrentTask, useGenerateProject, useHistory, useProject, useRenameProject } from "@/hooks/use-api";
import { type CodeWorkspaceOpenTarget, type CodeWorkspaceSelectionRequest } from "@/lib/code-workspace-target";
import { Button } from "@/components/ui";
import { getPrimaryArtifactTabFromHistoryChanges, inferArtifactTabFromHistoryFile } from "@/lib/version-history-link";
import {
  buildPendingGenerationActivityItems,
  clearPendingProjectGeneration,
  readPendingProjectGeneration,
} from "@/lib/pending-project-generation";
import { toast } from "@/hooks/use-toast";
import { APP_HOME_PATH } from "@/lib/app-routes";

export default function ProjectPage() {
  const { t } = useTranslation();
  const [, params] = useRoute("/project/:id");
  const projectId = params?.id || "new";
  const queryClient = useQueryClient();
  const { data: project, isLoading, isError } = useProject(projectId);
  const { data: currentTask } = useCurrentTask(projectId);
  const { data: history } = useHistory(projectId);
  const generateProject = useGenerateProject();
  const renameProject = useRenameProject();
  
  const [activeTab, setActiveTab] = useState("prd");
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isRenameDialogOpen, setIsRenameDialogOpen] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [isCodeWorkspaceOpen, setIsCodeWorkspaceOpen] = useState(false);
  const [codeWorkspaceTarget, setCodeWorkspaceTarget] = useState<CodeWorkspaceSelectionRequest | null>(null);
  const codeWorkspaceRequestRef = useRef(0);
  const highlightedChanges =
    selectedVersion === null ? [] : history?.find((checkpoint) => checkpoint.version === selectedVersion)?.changes ?? [];

  const openCodeWorkspace = (target?: CodeWorkspaceOpenTarget) => {
    codeWorkspaceRequestRef.current += 1;
    setCodeWorkspaceTarget(
      target
        ? {
            ...target,
            requestId: codeWorkspaceRequestRef.current,
          }
        : null,
    );
    setIsCodeWorkspaceOpen(true);
  };

  const focusVersionArtifact = (version: number, file?: string) => {
    setSelectedVersion(version);
    const checkpoint = history?.find((entry) => entry.version === version);
    const targetTab =
      (file ? inferArtifactTabFromHistoryFile(file) : null) ??
      getPrimaryArtifactTabFromHistoryChanges(checkpoint?.changes ?? []);
    if (targetTab) {
      setActiveTab(targetTab);
      setActiveSectionId(null);
    }
  };

  useEffect(() => {
    if (projectId === "new" || typeof window === "undefined") {
      return;
    }
    const pending = readPendingProjectGeneration(window.sessionStorage, projectId);
    if (!pending || currentTask?.task || generateProject.isPending) {
      return;
    }

    queryClient.setQueryData(
      ["live-activity", projectId],
      buildPendingGenerationActivityItems(projectId, pending.createdAt),
    );

    generateProject.mutate(
      {
        projectId,
        prompt: pending.prompt,
        uploadedFileIds: pending.uploadedFileIds,
      },
      {
        onSuccess: async () => {
          clearPendingProjectGeneration(window.sessionStorage, projectId);
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ["current-task", projectId] }),
            queryClient.invalidateQueries({ queryKey: ["chat", projectId] }),
            queryClient.invalidateQueries({ queryKey: ["projects"] }),
          ]);
        },
        onError: (error) => {
          clearPendingProjectGeneration(window.sessionStorage, projectId);
          toast({
            title: t("home.uploadErrorTitle"),
            description: error instanceof Error ? error.message : t("chat.error.unknown"),
            variant: "destructive",
          });
        },
      },
    );
  }, [currentTask?.task, generateProject, projectId, queryClient, t]);

  const handleRenameProject = async (nextName: string) => {
    if (!project) {
      return;
    }

    try {
      await renameProject.mutateAsync({
        projectId: project.id,
        name: nextName,
      });
      toast({
        title: t("project.renameSuccessTitle"),
        description: t("project.renameSuccessDescription", { projectName: nextName }),
      });
      setIsRenameDialogOpen(false);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : t("chat.error.unknown");
      toast({
        title: t("project.renameErrorTitle"),
        description: message,
        variant: "destructive",
      });
    }
  };

  if (projectId !== "new" && isLoading) {
    return (
      <div className="h-screen w-full flex items-center justify-center bg-background text-muted-foreground">
        <div className="flex items-center gap-3 text-sm">
          <Loader2 className="w-4 h-4 animate-spin text-primary" />
          <span>{t("artifact.loading")}</span>
        </div>
      </div>
    );
  }

  if (projectId !== "new" && (isError || !project)) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background px-6">
        <div className="w-full max-w-md rounded-2xl border border-white/10 bg-card/70 p-8 text-center shadow-2xl">
          <h1 className="text-2xl font-semibold text-foreground">{t("notFound.title")}</h1>
          <p className="mt-3 text-sm text-muted-foreground">{t("notFound.description")}</p>
          <div className="mt-6 flex justify-center">
            <Link href={APP_HOME_PATH}>
              <Button>
                <ChevronLeft className="w-4 h-4 mr-2" />
                {t("notFound.returnHome")}
              </Button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen w-full flex bg-background overflow-hidden text-foreground">
      
      {/* Left Panel: Chat & Context (40%) */}
      <div className="w-[40%] min-w-[400px] max-w-[600px] flex flex-col border-r border-white/10 bg-[#0a0a0a] z-10 shadow-2xl">
        {/* Header */}
        <header className="h-14 flex items-center px-4 border-b border-white/10 shrink-0 bg-background/80 backdrop-blur-md">
          <Link href={APP_HOME_PATH}>
            <button className="p-2 -ml-2 mr-2 text-muted-foreground hover:text-foreground rounded-lg hover:bg-white/5 transition-colors">
              <ChevronLeft className="w-5 h-5" />
            </button>
          </Link>
          <div className="flex flex-col">
            <h1 className="text-sm font-semibold truncate max-w-[200px]">{project?.name || t("project.defaultName")}</h1>
            <span className="text-[10px] text-muted-foreground font-mono">{t("project.idLabel")}: {projectId}</span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="ml-2 h-8 w-8 text-muted-foreground hover:text-foreground"
            onClick={() => setIsRenameDialogOpen(true)}
            aria-label={t("project.rename")}
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <div className="ml-auto">
            <LanguageToggle />
          </div>
        </header>

        {/* Chat Interface */}
        <div className="flex-1 overflow-hidden">
          <ChatArea 
            projectId={projectId} 
            onSelectArtifact={(type, sectionId) => {
              setActiveTab(type);
              setActiveSectionId(sectionId ?? null);
            }}
            onOpenWorkspaceTarget={openCodeWorkspace}
          />
        </div>
      </div>

      {/* Right Panel: Artifacts (60%) */}
      <div className="flex-1 flex flex-col relative bg-[#0f0f0f]">
         <ArtifactViewer 
           projectId={projectId}
           activeTab={activeTab}
           activeSectionId={activeSectionId}
           selectedVersion={selectedVersion}
           highlightedChanges={highlightedChanges}
           currentVersion={project?.currentVersion}
           onVersionChange={setSelectedVersion}
           onTabChange={(tab) => {
             setActiveTab(tab);
             setActiveSectionId(null);
           }}
           onSectionChange={setActiveSectionId}
           onOpenCodeWorkspace={() => openCodeWorkspace()}
           onOpenHistory={() => setIsHistoryOpen(true)}
         />
      </div>

      {/* Slide-over Version History */}
      <VersionHistorySidebar 
        projectId={projectId}
        isOpen={isHistoryOpen}
        selectedVersion={selectedVersion}
        currentVersion={project?.currentVersion}
        onSelectVersion={(version) => focusVersionArtifact(version)}
        onSelectChange={(version, file) => focusVersionArtifact(version, file)}
        onClose={() => setIsHistoryOpen(false)}
      />

      <CodeWorkspaceSheet
        projectId={projectId}
        version={selectedVersion ?? project?.currentVersion ?? null}
        currentVersion={project?.currentVersion}
        pendingAgentArtifactsVersion={currentTask?.pendingAgentArtifactsVersion}
        isOpen={isCodeWorkspaceOpen}
        openTarget={codeWorkspaceTarget}
        onVersionChange={setSelectedVersion}
        onOpenChange={setIsCodeWorkspaceOpen}
      />

      <ProjectRenameDialog
        open={isRenameDialogOpen}
        currentName={project?.name ?? ""}
        isSubmitting={renameProject.isPending}
        onOpenChange={setIsRenameDialogOpen}
        onConfirm={handleRenameProject}
      />
    </div>
  );
}
