import { useLocation } from "wouter";
import { useTranslation } from "react-i18next";
import { ArrowRight, Clock, Box, Pencil, Trash2 } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import { formatDateDistance, formatProjectStatus, type Project } from "@/hooks/use-api";

type ProjectCardProps = {
  project: Project;
  onDelete?: (project: Project) => void;
  onRename?: (project: Project) => void;
  isDeleting?: boolean;
};

export function ProjectCard({ project, onDelete, onRename, isDeleting = false }: ProjectCardProps) {
  const { t } = useTranslation();
  const [, setLocation] = useLocation();
  const statusLabel = formatProjectStatus(project.status);

  const openProject = () => {
    void setLocation(`/project/${project.id}`);
  };

  const handleDeleteClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onDelete?.(project);
  };

  const handleRenameClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onRename?.(project);
  };

  return (
    <div
      className="group relative flex h-full cursor-pointer flex-col overflow-hidden rounded-2xl border border-white/5 bg-card/40 p-5 transition-all hover:border-white/10 hover:bg-card/80 hover:shadow-2xl hover:shadow-primary/5"
      onClick={openProject}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openProject();
        }
      }}
      role="button"
      tabIndex={0}
    >
      <div className="absolute right-4 top-4 z-10 flex items-center gap-2">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8 rounded-full bg-black/30 text-muted-foreground hover:bg-white/10 hover:text-foreground"
          onClick={handleRenameClick}
          aria-label={t("project.rename")}
        >
          <Pencil className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8 rounded-full bg-black/30 text-muted-foreground hover:bg-red-500/15 hover:text-red-200"
          onClick={handleDeleteClick}
          isLoading={isDeleting}
          aria-label={t("home.deleteProject")}
        >
          {!isDeleting ? <Trash2 className="h-4 w-4" /> : null}
        </Button>
      </div>

      <div className="relative mb-4 flex aspect-[16/9] w-full items-center justify-center overflow-hidden rounded-xl border border-white/5 bg-gradient-to-br from-secondary to-background">
        {project.thumbnail ? (
          <img
            src={project.thumbnail}
            alt={project.name}
            className="h-full w-full object-cover opacity-60 mix-blend-overlay transition-transform duration-500 group-hover:scale-105"
          />
        ) : (
          <Box className="h-10 w-10 text-white/10" />
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-background/80 to-transparent" />
      </div>

      <div className="mb-2 flex items-start justify-between gap-3 pr-20">
        <h3 className="text-lg font-semibold text-foreground transition-colors group-hover:text-primary">{project.name}</h3>
        <Badge variant={project.status === "completed" ? "success" : "default"}>
          {statusLabel}
        </Badge>
      </div>

      <div className="mt-auto flex items-center justify-between border-t border-white/5 pt-4 text-sm text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5" />
          <span>{formatDateDistance(project.updatedAt)}</span>
        </div>
        <div className="flex -translate-x-2 items-center gap-1 text-primary opacity-0 transition-all duration-300 group-hover:translate-x-0 group-hover:opacity-100">
          <span>{t("project.open")}</span>
          <ArrowRight className="h-4 w-4" />
        </div>
      </div>
    </div>
  );
}
