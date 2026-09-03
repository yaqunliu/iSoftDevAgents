import type { ArtifactPanelTab } from "./artifact-view-model.ts";

export type ArtifactRenderMode = "preview" | "markdown" | "yaml";

export function isMarkdownArtifactTab(tab: ArtifactPanelTab): boolean {
  return tab === "prd" || tab === "ui" || tab === "arch";
}

export function isYamlArtifactTab(tab: ArtifactPanelTab): boolean {
  return tab === "api";
}

export function getDefaultArtifactRenderMode(tab: ArtifactPanelTab): ArtifactRenderMode {
  if (isYamlArtifactTab(tab)) {
    return "yaml";
  }
  return "preview";
}
