import { getArtifactSectionIds, type ArtifactPanelTab } from "./artifact-view-model.ts";

type HistoryChange = {
  file: string;
  status: "Modified" | "Added" | "Deleted";
};

const HISTORY_FILE_TO_TAB: Array<{ tab: ArtifactPanelTab; patterns: string[] }> = [
  { tab: "prd", patterns: ["prd", "product requirements"] },
  { tab: "ui", patterns: ["ui", "page map", "user flow", "visual spec", "states"] },
  { tab: "arch", patterns: ["architecture", "data flow", "deployment", "modules"] },
  { tab: "api", patterns: ["api", "openapi", "endpoints", "schemas", "errors"] },
];

export function inferArtifactTabFromHistoryFile(file: string): ArtifactPanelTab | null {
  const normalized = file.trim().toLowerCase();
  if (!normalized) {
    return null;
  }

  for (const entry of HISTORY_FILE_TO_TAB) {
    if (entry.patterns.some((pattern) => normalized.includes(pattern))) {
      return entry.tab;
    }
  }

  return null;
}

export function getPrimaryArtifactTabFromHistoryChanges(changes: HistoryChange[]): ArtifactPanelTab | null {
  for (const change of changes) {
    const tab = inferArtifactTabFromHistoryFile(change.file);
    if (tab) {
      return tab;
    }
  }
  return null;
}

export function getArtifactVersionHighlight(tab: ArtifactPanelTab, changes: HistoryChange[]): { changed: boolean; sectionIds: string[] } {
  const changed = changes.some((change) => inferArtifactTabFromHistoryFile(change.file) === tab);
  return {
    changed,
    sectionIds: changed ? getArtifactSectionIds(tab) : [],
  };
}
