import i18n from "../i18n.ts";
import { normalizeSupportedLocale } from "./locale.ts";

export type InteractionGuidance = {
  reviewHint?: string;
  scopeHint: string;
  submitHint: string;
  skipHint?: string;
};

type InteractionMetadata = {
  confirmationKind?: string | null;
  activePhase?: string | null;
  outputFiles?: unknown;
  artifactTypes?: unknown;
  options?: unknown;
  variables?: unknown;
};

function normalizeStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => String(item).trim()).filter((item) => item.length > 0);
}

function isUserReadablePrimaryOutputFile(fileName: string): boolean {
  const normalized = fileName.trim().toLowerCase();
  if (!normalized) {
    return false;
  }
  if (normalized.endsWith(".pkl")) {
    return false;
  }
  if (normalized.includes("_modify.")) {
    return false;
  }
  return normalized.endsWith(".md") || normalized.endsWith(".markdown") || normalized.endsWith(".txt") || normalized.endsWith(".json");
}

function userFacingOutputFiles(value: unknown): string[] {
  const normalizedFiles = normalizeStringList(value);
  const visible = normalizedFiles.filter(isUserReadablePrimaryOutputFile);
  return visible.length ? visible : normalizedFiles;
}

function joinExamples(items: string[], language: string): string {
  const visible = items.slice(0, 3);
  if (!visible.length) {
    return "";
  }

  const locale = normalizeSupportedLocale(language);
  if (typeof Intl !== "undefined" && typeof Intl.ListFormat === "function") {
    return new Intl.ListFormat(locale, { style: "long", type: "conjunction" }).format(visible);
  }
  return visible.join(", ");
}

// 接口注释：
// 这里专门把“等待用户操作”的不同卡片，翻译成用户能看懂的范围说明和影响说明。
// 前端组件只负责展示，不需要再自己猜“这次反馈到底会改哪里”。
export function buildInteractionGuidance(metadata: InteractionMetadata | null | undefined, language: string): InteractionGuidance | null {
  const locale = normalizeSupportedLocale(language);
  const t = i18n.getFixedT(locale);
  const confirmationKind = String(metadata?.confirmationKind || "").trim();
  const activePhase = String(metadata?.activePhase || "").trim();
  const outputFiles = userFacingOutputFiles(metadata?.outputFiles);
  const outputExamples = joinExamples(outputFiles, language);

  if (confirmationKind === "requirements_feedback") {
    return {
      reviewHint: outputExamples
        ? t("chat.guidance.requirementsFeedback.reviewWithFiles", { files: outputExamples })
        : t("chat.guidance.requirementsFeedback.review"),
      scopeHint: outputExamples
        ? t("chat.guidance.requirementsFeedback.scopeWithFiles", { files: outputExamples })
        : t("chat.guidance.requirementsFeedback.scope"),
      submitHint: t("chat.guidance.requirementsFeedback.submit"),
      skipHint: t("chat.guidance.requirementsFeedback.skip"),
    };
  }

  if (confirmationKind === "input_variables") {
    return {
      reviewHint: t("chat.guidance.inputVariables.review"),
      scopeHint: t("chat.guidance.inputVariables.scope"),
      submitHint: t("chat.guidance.inputVariables.submit"),
      skipHint: t("chat.guidance.inputVariables.skip"),
    };
  }

  if (confirmationKind === "coverage_conflict") {
    return {
      scopeHint: t("chat.guidance.coverageConflict.scope"),
      submitHint: t("chat.guidance.coverageConflict.submit"),
      skipHint: t("chat.guidance.coverageConflict.skip"),
    };
  }

  if (confirmationKind === "artifact_review") {
    const isRequirementsReview = activePhase === "waiting_for_requirements_artifact_review";
    if (isRequirementsReview) {
      return {
        reviewHint: outputExamples
          ? t("chat.guidance.artifactReview.requirements.reviewWithFiles", { files: outputExamples })
          : t("chat.guidance.artifactReview.requirements.review"),
        scopeHint: outputExamples
          ? t("chat.guidance.artifactReview.requirements.scopeWithFiles", { files: outputExamples })
          : t("chat.guidance.artifactReview.requirements.scope"),
        submitHint: t("chat.guidance.artifactReview.requirements.submit"),
      };
    }
    return {
      reviewHint: outputExamples
        ? t("chat.guidance.artifactReview.full.reviewWithFiles", { files: outputExamples })
        : t("chat.guidance.artifactReview.full.review"),
      scopeHint: outputExamples
        ? t("chat.guidance.artifactReview.full.scopeWithFiles", { files: outputExamples })
        : t("chat.guidance.artifactReview.full.scope"),
      submitHint: t("chat.guidance.artifactReview.full.submit"),
      skipHint: t("chat.guidance.artifactReview.full.skip"),
    };
  }

  const optionCount = Array.isArray(metadata?.options) ? metadata?.options.length ?? 0 : 0;
  if (optionCount > 0) {
    return {
      reviewHint: t("chat.guidance.moduleSelection.reviewWithFiles", { files: "feature_tree.md" }),
      scopeHint: t("chat.guidance.moduleSelection.scopeWithFiles", { files: "feature_tree.md" }),
      submitHint: t("chat.guidance.moduleSelection.submit"),
      skipHint: t("chat.guidance.moduleSelection.skip"),
    };
  }

  return null;
}
