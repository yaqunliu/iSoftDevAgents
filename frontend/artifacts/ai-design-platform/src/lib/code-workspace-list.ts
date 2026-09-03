import type { CodeTreeNode } from "@/hooks/use-api";

export type WorkspaceDocListEntry = {
  key: string;
  agent: string;
  fileName: string;
};

export type WorkspaceDocGroup<T extends WorkspaceDocListEntry = WorkspaceDocListEntry> = {
  agent: string;
  items: T[];
};

export type WorkspaceDocFolder = {
  id: string;
  agent: string;
  fileNames: string[];
};

export type WorkspaceDocGroupExpandedState = Record<string, boolean>;
export type CodeTreeExpandedState = Record<string, boolean>;

// 这里给没有翻译文案时做兜底，把 requirements_agent 这种内部名字
// 转成更容易阅读的 Requirements Agent。
export function humanizeAgentSourceName(source: string): string {
  return source
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

// 这里专门给工作区左侧列表做分组，保持 Agent 首次出现的顺序不变，
// 这样用户切换阶段时，看到的文件顺序会稳定，不会一会儿跳来跳去。
export function groupWorkspaceDocItems<T extends WorkspaceDocListEntry>(items: T[]): WorkspaceDocGroup<T>[] {
  const groups: WorkspaceDocGroup<T>[] = [];
  const groupMap = new Map<string, WorkspaceDocGroup<T>>();

  for (const item of items) {
    const existingGroup = groupMap.get(item.agent);
    if (existingGroup) {
      existingGroup.items.push(item);
      continue;
    }

    const nextGroup: WorkspaceDocGroup<T> = {
      agent: item.agent,
      items: [item],
    };
    groupMap.set(item.agent, nextGroup);
    groups.push(nextGroup);
  }

  return groups;
}

// 这里给左侧文档树准备最轻的数据，只保留文件夹和文件名，
// 这样界面层就不用再自己拼结构，也能避免把多余信息重新显示出来。
export function buildWorkspaceDocFolders<T extends WorkspaceDocListEntry>(items: T[]): WorkspaceDocFolder[] {
  return groupWorkspaceDocItems(items).map((group) => ({
    id: group.agent,
    agent: group.agent,
    fileNames: group.items.map((item) => item.fileName),
  }));
}

// 接口注释：
// 左侧文档树的展开状态只按 Agent 分组保存。
// 已经存在的分组保留用户上一次的选择，新出现的分组默认展开，
// 这样刷新数据后不会把用户刚刚收起的文件夹又强行展开。
export function syncWorkspaceDocGroupExpandedState<T extends WorkspaceDocListEntry>(
  groups: WorkspaceDocGroup<T>[],
  currentState: WorkspaceDocGroupExpandedState,
): WorkspaceDocGroupExpandedState {
  const nextState: WorkspaceDocGroupExpandedState = {};
  for (const group of groups) {
    nextState[group.agent] = currentState[group.agent] ?? true;
  }
  return nextState;
}

function collectFolderPaths(
  nodes: CodeTreeNode[],
  currentPath = "",
  result: string[] = [],
): string[] {
  for (const node of nodes) {
    if (node.type !== "folder") {
      continue;
    }
    const folderPath = currentPath ? `${currentPath}/${node.name}` : node.name;
    result.push(folderPath);
    if (node.children?.length) {
      collectFolderPaths(node.children, folderPath, result);
    }
  }
  return result;
}

// 接口注释：
// Files 树的展开状态按“文件夹路径”保存。
// 已存在的文件夹继续沿用用户当前选择，新出现的文件夹默认展开，
// 这样刷新代码树时不会把用户刚收起的目录自动弹开。
export function syncCodeTreeExpandedState(
  nodes: CodeTreeNode[],
  currentState: CodeTreeExpandedState,
): CodeTreeExpandedState {
  const nextState: CodeTreeExpandedState = {};
  for (const folderPath of collectFolderPaths(nodes)) {
    nextState[folderPath] = currentState[folderPath] ?? true;
  }
  return nextState;
}

// 教学注释：
// 当右侧已经选中了某个文件时，左侧树至少要把它的所有父目录展开，
// 不然用户会看到“文件已经打开了，但树里像是消失了”的违和感。
export function expandCodeTreeFoldersForSelection(
  selectedFilePath: string | null,
  currentState: CodeTreeExpandedState,
): CodeTreeExpandedState {
  const normalized = String(selectedFilePath ?? "").trim().replace(/\\/g, "/");
  if (!normalized) {
    return currentState;
  }
  const segments = normalized.split("/").filter(Boolean);
  if (segments.length <= 1) {
    return currentState;
  }

  const nextState = { ...currentState };
  let currentPath = "";
  for (const segment of segments.slice(0, -1)) {
    currentPath = currentPath ? `${currentPath}/${segment}` : segment;
    nextState[currentPath] = true;
  }
  return nextState;
}
