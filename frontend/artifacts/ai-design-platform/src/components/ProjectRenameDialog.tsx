import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input } from "@/components/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type ProjectRenameDialogProps = {
  open: boolean;
  currentName: string;
  isSubmitting?: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (nextName: string) => void | Promise<void>;
};

export function ProjectRenameDialog({
  open,
  currentName,
  isSubmitting = false,
  onOpenChange,
  onConfirm,
}: ProjectRenameDialogProps) {
  const { t } = useTranslation();
  const [draftName, setDraftName] = useState(currentName);

  useEffect(() => {
    if (open) {
      setDraftName(currentName);
    }
  }, [currentName, open]);

  const normalizedDraftName = draftName.trim();
  const isUnchanged = normalizedDraftName === currentName.trim();
  const isConfirmDisabled = !normalizedDraftName || isUnchanged || isSubmitting;

  const handleConfirm = () => {
    if (isConfirmDisabled) {
      return;
    }
    void onConfirm(normalizedDraftName);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="border-white/10 bg-[#101010] text-foreground sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("project.renameTitle")}</DialogTitle>
          <DialogDescription>{t("project.renameDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          {/* 教学注释：改名只涉及一个字段，用最直接的输入框能减少用户理解成本。 */}
          <Input
            value={draftName}
            maxLength={48}
            placeholder={t("project.renamePlaceholder")}
            onChange={(event) => setDraftName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                handleConfirm();
              }
            }}
          />
          <p className="text-xs text-muted-foreground">{t("project.renameHint")}</p>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            {t("chat.cancel")}
          </Button>
          <Button onClick={handleConfirm} isLoading={isSubmitting} disabled={isConfirmDisabled}>
            {t("project.renameConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
