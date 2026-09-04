import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "wouter";
import { motion } from "framer-motion";
import {
  Sparkles,
  TerminalSquare,
  Upload,
  Search,
  Plus,
  FileText,
  Image as ImageIcon,
  X,
  AlertCircle,
} from "lucide-react";
import { LanguageToggle } from "@/components/LanguageToggle";
import { Button, Input } from "@/components/ui";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ProjectCard } from "@/components/ProjectCard";
import { ProjectRenameDialog } from "@/components/ProjectRenameDialog";
import { toast } from "@/hooks/use-toast";
import {
  ApiError,
  useCreateAndGenerateProject,
  useCurrentUser,
  useDeleteProject,
  useLogout,
  useProjects,
  useRenameProject,
  useUploadReferenceFile,
  type Project,
  type UploadedReference,
} from "@/hooks/use-api";
import {
  appendProjectPage,
  getNextProjectPage,
  hasMoreProjectPages,
  removeProjectFromList,
  renameProjectInList,
  shouldResetProjectListForUserChange,
} from "@/lib/project-list-state";
import { savePendingProjectGeneration } from "@/lib/pending-project-generation";
import { LANDING_ROUTES } from "@/lib/landing-cta";

const PROJECTS_PER_PAGE = 12;

export default function Home() {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [prompt, setPrompt] = useState("");
  const [uploadedFiles, setUploadedFiles] = useState<UploadedReference[]>([]);
  const [visibleProjects, setVisibleProjects] = useState<Project[]>([]);
  const [projectPendingDelete, setProjectPendingDelete] =
    useState<Project | null>(null);
  const [projectPendingRename, setProjectPendingRename] =
    useState<Project | null>(null);
  const [loadedSearch, setLoadedSearch] = useState("");
  const [projectPageState, setProjectPageState] = useState({
    page: 1,
    totalPages: 1,
  });
  const [, setLocation] = useLocation();
  const { data: currentUser } = useCurrentUser();
  const logout = useLogout();
  const deleteProject = useDeleteProject();
  const renameProject = useRenameProject();
  const normalizedSearch = search.trim();
  const {
    data: projectsData,
    isLoading,
    isFetching,
  } = useProjects(normalizedSearch, page, PROJECTS_PER_PAGE);
  const createAndGenerate = useCreateAndGenerateProject();
  const uploadReferenceFile = useUploadReferenceFile();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const previousUserIdRef = useRef<string | null>(null);

  useEffect(() => {
    setPage(1);
    setVisibleProjects([]);
    setProjectPageState({ page: 1, totalPages: 1 });
  }, [normalizedSearch]);

  useEffect(() => {
    if (!projectsData) {
      return;
    }
    setVisibleProjects((current) =>
      appendProjectPage({
        currentProjects: current,
        incomingProjects: projectsData.projects,
        incomingPage: projectsData.page,
        activeSearch: loadedSearch,
        incomingSearch: normalizedSearch,
      }),
    );
    setLoadedSearch(normalizedSearch);
    setProjectPageState({
      page: projectsData.page,
      totalPages: projectsData.totalPages,
    });
  }, [loadedSearch, normalizedSearch, projectsData]);

  useEffect(() => {
    const nextUserId = currentUser?.id ?? null;
    if (
      !shouldResetProjectListForUserChange(
        previousUserIdRef.current,
        nextUserId,
      )
    ) {
      previousUserIdRef.current = nextUserId;
      return;
    }
    // 设计注释：首页自己维护了一份“已经展示出来的项目列表”，
    // 这是为了支持分页追加。但只要登录用户变了，这份本地列表就必须立即清空，
    // 否则页面在未刷新的情况下，会先短暂显示上一位用户或上一次登录留下来的旧数据。
    previousUserIdRef.current = nextUserId;
    setPage(1);
    setVisibleProjects([]);
    setLoadedSearch("");
    setProjectPageState({ page: 1, totalPages: 1 });
  }, [currentUser?.id]);

  const nextProjectPage = getNextProjectPage(projectPageState);
  const showLoadMore = hasMoreProjectPages(projectPageState);
  const isLoadingMore = isFetching && page > 1;
  const showProjectSkeleton =
    isLoading && page === 1 && visibleProjects.length === 0;

  const handleLoadMoreProjects = () => {
    if (!nextProjectPage || isFetching) {
      return;
    }
    setPage(nextProjectPage);
  };

  const handleGenerate = async () => {
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt || createAndGenerate.isPending) {
      return;
    }
    const projectId = await createAndGenerate.mutateAsync({
      prompt: trimmedPrompt,
      uploadedFileIds: uploadedFiles.map((file) => file.id),
    });
    if (typeof window !== "undefined") {
      savePendingProjectGeneration(window.sessionStorage, {
        projectId,
        prompt: trimmedPrompt,
        uploadedFileIds: uploadedFiles.map((file) => file.id),
        createdAt: new Date().toISOString(),
      });
    }
    setLocation(`/project/${projectId}`);
    setPrompt("");
    setUploadedFiles([]);
  };

  const handleChooseFile = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const files = Array.from(event.target.files ?? []);
    for (const file of files) {
      try {
        const uploaded = await uploadReferenceFile.mutateAsync(file);
        setUploadedFiles((current) => [...current, uploaded]);
        if (uploaded.fileType === "pdf" && !uploaded.contentPreview?.trim()) {
          toast({
            title: t("home.uploadNoTextTitle"),
            description: t("home.uploadNoTextDescription"),
          });
        }
      } catch (error) {
        const message =
          error instanceof ApiError
            ? error.message
            : t("home.uploadErrorFallback");
        toast({
          title: t("home.uploadErrorTitle"),
          description: message,
          variant: "destructive",
        });
      }
    }
    event.target.value = "";
  };

  const removeUploadedFile = (fileId: string) => {
    setUploadedFiles((current) => current.filter((file) => file.id !== fileId));
  };

  const uploadIcon = (type: UploadedReference["fileType"]) => {
    return type === "image" ? ImageIcon : FileText;
  };

  const isSkippedReference = (file: UploadedReference) =>
    file.fileType === "pdf" && !file.contentPreview?.trim();

  const referencePreview = (file: UploadedReference) =>
    file.contentPreview?.trim() || t("home.referenceNoPreview");

  // 交互注释：点击品牌标识回官网首页。这里刻意不用 APP_HOME_PATH——
  // 当前页面本身就是 /app，跳自己等于什么都没发生，用户会以为 logo 点坏了。
  const handleBackToLanding = () => {
    setLocation(LANDING_ROUTES.home);
  };

  const handleLogout = async () => {
    await logout.mutateAsync();
    // 交互注释：退出后落在官网首页，而不是认证页。
    // 认证页只是"想进产品但没登录"时的中转站，用它当退出终点，
    // 等于把一个主动离开的用户堵在登录表单前面，像是被强制要求重新登录。
    setLocation(LANDING_ROUTES.home);
  };

  const handleConfirmDeleteProject = async () => {
    if (!projectPendingDelete || deleteProject.isPending) {
      return;
    }

    try {
      await deleteProject.mutateAsync(projectPendingDelete.id);
      setVisibleProjects((current) =>
        removeProjectFromList(current, projectPendingDelete.id),
      );
      toast({
        title: t("home.deleteProjectSuccessTitle"),
        description: t("home.deleteProjectSuccessDescription", {
          projectName: projectPendingDelete.name,
        }),
      });
      setProjectPendingDelete(null);
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : t("home.uploadErrorFallback");
      toast({
        title: t("home.deleteProjectErrorTitle"),
        description: message,
        variant: "destructive",
      });
    }
  };

  const handleConfirmRenameProject = async (nextName: string) => {
    if (!projectPendingRename || renameProject.isPending) {
      return;
    }

    try {
      const updatedProject = await renameProject.mutateAsync({
        projectId: projectPendingRename.id,
        name: nextName,
      });
      setVisibleProjects((current) =>
        renameProjectInList(current, updatedProject.id, updatedProject.name),
      );
      toast({
        title: t("project.renameSuccessTitle"),
        description: t("project.renameSuccessDescription", {
          projectName: updatedProject.name,
        }),
      });
      setProjectPendingRename(null);
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : t("home.uploadErrorFallback");
      toast({
        title: t("project.renameErrorTitle"),
        description: message,
        variant: "destructive",
      });
    }
  };

  return (
    <div className="min-h-screen bg-background relative overflow-hidden flex flex-col">
      {/* Background Effects */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full max-w-5xl h-[500px] opacity-40 pointer-events-none mix-blend-screen">
        <img
          src={`${import.meta.env.BASE_URL}images/hero-glow.png`}
          alt="background glow"
          className="w-full h-full object-cover"
        />
      </div>

      {/* Header */}
      {/* 设计注释：顶部操作区必须始终压在主视觉内容上面，否则语言切换这类控件会被下面的大标题区域抢走点击。 */}
      <header className="px-6 py-4 relative z-20">
        {/* 设计注释：顶部导航允许在空间紧张时自动分配剩余宽度，避免右侧控件被大标题区域反向挤压。 */}
        <div className="mx-auto flex w-full max-w-7xl items-center justify-between gap-4 cursor-pointer">
          {/* 交互注释：品牌标识用 button 而不是 div 加 onClick，键盘用户才能 Tab 聚焦并回车触发；
              同时补上 hover / focus 反馈，否则一个能点但看不出能点的 logo 只会被当成装饰。 */}
          <button
            type="button"
            onClick={handleBackToLanding}
            aria-label={t("home.backToLanding")}
            className="flex items-center gap-2 rounded-md text-foreground font-bold text-lg tracking-tight transition-opacity hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-background cursor-pointer"
          >
            <TerminalSquare className="w-6 h-6 text-primary" />
            <span className="text-primary">Gmonkey</span>
          </button>
          {/* 教学注释：右侧操作区用可收缩容器包起来，语言、文档、用户区和退出按钮就不会互相顶坏。 */}
          <div className="flex min-w-0 items-center justify-end gap-3">
            <LanguageToggle />
            {/* <Button
              variant="ghost"
              size="sm"
              className="hidden min-w-[112px] shrink-0 justify-center sm:inline-flex"
            >
              {t("home.documentation")}
            </Button> */}
            {/* 用户信息区优先保证昵称可读，邮箱允许省略，避免顶部因为空间太短导致主身份信息看不清。 */}
            <div className="hidden min-w-[220px] max-w-[320px] shrink min-w-0 items-center gap-3 rounded-full border border-white/10 bg-black/20 px-3 py-1.5 md:flex">
              <div className="min-w-0 flex-1 text-right">
                {/* 昵称是用户最常看的信息，所以给更高的显示优先级，并尽量保留完整内容。 */}
                <div className="truncate text-sm font-medium text-foreground">
                  {currentUser?.name ?? t("home.currentUser")}
                </div>
                <div className="truncate text-[11px] text-muted-foreground">
                  {currentUser?.email ?? ""}
                </div>
              </div>
              {/* 头像强制固定宽高并禁止收缩，这样无论右侧空间怎样变化都能保持正圆。 */}
              <div className="h-9 w-9 shrink-0 rounded-full border border-white/20 bg-gradient-to-br from-primary to-purple-600" />
            </div>
            <Button
              variant="outline"
              size="sm"
              className="shrink-0"
              onClick={() => void handleLogout()}
              isLoading={logout.isPending}
            >
              {t("home.logout")}
            </Button>
          </div>
        </div>
      </header>

      {/* Main Hero Input */}
      {/* 教学注释：主内容不再用大幅负边距顶到导航下面，给标题和顶部操作区留出明确的呼吸空间。 */}
      <main className="relative z-0 flex flex-1 flex-col items-center px-4 pb-12 pt-8 md:pt-10">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mb-8 flex w-full max-w-4xl flex-col items-center text-center md:mb-10"
        >
          <h1 className="mb-4 text-4xl font-bold tracking-tight text-foreground text-glow md:text-5xl lg:text-6xl">
            {t("home.heroTitle")}
          </h1>
          <p className="max-w-2xl text-lg text-muted-foreground">
            {t("home.heroDescription")}
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="w-full max-w-3xl relative group"
        >
          {/* Glow effect behind input */}
          <div className="absolute -inset-1 bg-gradient-to-r from-primary/30 to-purple-600/30 rounded-3xl blur-xl opacity-50 group-hover:opacity-100 transition duration-1000 group-hover:duration-200"></div>

          <div className="relative glass-panel rounded-2xl overflow-hidden focus-within:ring-2 ring-primary/50 transition-all">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.md,.markdown,image/*"
              className="hidden"
              onChange={(event) => void handleFileChange(event)}
            />
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={t("home.promptPlaceholder")}
              className="w-full h-40 bg-transparent text-lg text-foreground placeholder:text-muted-foreground/70 p-6 resize-none focus:outline-none border-0"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void handleGenerate();
                }
              }}
            />

            <div className="bg-secondary/50 border-t border-white/5 p-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-muted-foreground hover:text-foreground"
                  onClick={handleChooseFile}
                  isLoading={uploadReferenceFile.isPending}
                >
                  <Upload className="w-5 h-5" />
                </Button>
                <div className="hidden sm:flex text-xs text-muted-foreground items-center gap-2 px-2 py-1 rounded bg-black/20 border border-white/5">
                  <Plus className="w-3 h-3" /> {t("home.uploadHint")}
                </div>
              </div>

              <div className="flex items-center gap-3">
                <span className="text-xs text-muted-foreground hidden md:block font-mono">
                  {t("home.pressReturn")}
                </span>
                <Button
                  size="lg"
                  className="rounded-xl px-6 font-semibold"
                  onClick={() => void handleGenerate()}
                  disabled={!prompt.trim() || createAndGenerate.isPending}
                  isLoading={createAndGenerate.isPending}
                >
                  <Sparkles className="w-4 h-4 mr-2" />
                  {t("home.generate")}
                </Button>
              </div>
            </div>
            {uploadedFiles.length ? (
              <div className="px-4 pb-4 bg-secondary/50">
                <div className="flex flex-wrap gap-2">
                  {uploadedFiles.map((file) => {
                    const Icon = uploadIcon(file.fileType);
                    return (
                      <Tooltip key={file.id}>
                        <TooltipTrigger asChild>
                          <div
                            className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs ${
                              isSkippedReference(file)
                                ? "border-amber-500/30 bg-amber-500/10 text-amber-100"
                                : "border-white/10 bg-black/20 text-muted-foreground"
                            }`}
                          >
                            <Icon className="w-3.5 h-3.5" />
                            <span className="max-w-[220px] truncate">
                              {file.fileName}
                            </span>
                            {isSkippedReference(file) ? (
                              <span className="inline-flex items-center gap-1 rounded-full bg-black/20 px-2 py-0.5 text-[10px] uppercase tracking-wide">
                                <AlertCircle className="w-3 h-3" />
                                {t("home.referenceSkipped")}
                              </span>
                            ) : null}
                            <button
                              type="button"
                              onClick={() => removeUploadedFile(file.id)}
                              className="text-muted-foreground hover:text-foreground"
                            >
                              <X className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent className="max-w-xs rounded-xl border border-white/10 bg-card/95 px-4 py-3 text-left text-foreground shadow-2xl">
                          <div className="space-y-2">
                            <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                              {t("home.referencePreview")}
                            </div>
                            <div className="text-sm leading-5 text-foreground/90">
                              {referencePreview(file)}
                            </div>
                          </div>
                        </TooltipContent>
                      </Tooltip>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </div>
        </motion.div>
      </main>

      {/* Recent Projects Section */}
      <div className="w-full max-w-6xl mx-auto px-6 pb-20 relative z-10">
        <div className="flex items-center justify-between mb-8 border-b border-white/5 pb-4">
          <h2 className="text-xl font-semibold text-foreground">
            {t("home.recentProjects")}
          </h2>
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t("home.searchProjects")}
              className="w-64 pl-9 bg-secondary border-none rounded-full h-9"
            />
          </div>
        </div>

        {showProjectSkeleton ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-64 rounded-2xl bg-card/50 animate-pulse"
              />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {visibleProjects.map((project, i) => (
              <motion.div
                key={project.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: i * 0.1 }}
              >
                <ProjectCard
                  project={project}
                  onDelete={setProjectPendingDelete}
                  onRename={setProjectPendingRename}
                  isDeleting={
                    deleteProject.isPending &&
                    projectPendingDelete?.id === project.id
                  }
                />
              </motion.div>
            ))}
          </div>
        )}

        {showLoadMore ? (
          <div className="mt-8 flex justify-center">
            <Button
              variant="secondary"
              size="md"
              onClick={handleLoadMoreProjects}
              isLoading={isLoadingMore}
            >
              {t("home.loadMoreProjects")}
            </Button>
          </div>
        ) : null}
      </div>

      <AlertDialog
        open={projectPendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setProjectPendingDelete(null);
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("home.deleteProjectTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("home.deleteProjectDescription", {
                projectName: projectPendingDelete?.name ?? "",
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteProject.isPending}>
              {t("chat.cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void handleConfirmDeleteProject()}
              disabled={deleteProject.isPending}
            >
              {t("home.deleteProjectConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <ProjectRenameDialog
        open={projectPendingRename !== null}
        currentName={projectPendingRename?.name ?? ""}
        isSubmitting={renameProject.isPending}
        onOpenChange={(open) => {
          if (!open) {
            setProjectPendingRename(null);
          }
        }}
        onConfirm={handleConfirmRenameProject}
      />
    </div>
  );
}
