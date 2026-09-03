export type ProjectListItem = {
  id: string;
};

type AppendProjectPageInput<TProject extends ProjectListItem> = {
  currentProjects: TProject[];
  incomingProjects: TProject[];
  incomingPage: number;
  activeSearch: string;
  incomingSearch: string;
};

type ProjectPageState = {
  page: number;
  totalPages: number;
};

function normalizeSearch(value: string): string {
  return value.trim().toLowerCase();
}

export function appendProjectPage<TProject extends ProjectListItem>({
  currentProjects,
  incomingProjects,
  incomingPage,
  activeSearch,
  incomingSearch,
}: AppendProjectPageInput<TProject>): TProject[] {
  const isFirstPage = incomingPage <= 1;
  const isSameSearch = normalizeSearch(activeSearch) === normalizeSearch(incomingSearch);

  if (isFirstPage || !isSameSearch) {
    return incomingProjects;
  }

  const seenIds = new Set(currentProjects.map((project) => project.id));
  const appended = incomingProjects.filter((project) => {
    if (seenIds.has(project.id)) {
      return false;
    }
    seenIds.add(project.id);
    return true;
  });
  return [...currentProjects, ...appended];
}

export function removeProjectFromList<TProject extends ProjectListItem>(
  currentProjects: TProject[],
  projectId: string,
): TProject[] {
  return currentProjects.filter((project) => project.id !== projectId);
}

export function renameProjectInList<TProject extends ProjectListItem & { name: string }>(
  currentProjects: TProject[],
  projectId: string,
  nextName: string,
): TProject[] {
  return currentProjects.map((project) => {
    if (project.id !== projectId) {
      return project;
    }
    return {
      ...project,
      name: nextName,
    };
  });
}

export function hasMoreProjectPages({ page, totalPages }: ProjectPageState): boolean {
  return page < totalPages;
}

export function getNextProjectPage({ page, totalPages }: ProjectPageState): number | null {
  if (!hasMoreProjectPages({ page, totalPages })) {
    return null;
  }
  return page + 1;
}

// 接口注释：判断首页是否应该因为登录身份变化而清空本地项目列表。
// 第一次进入首页时 previousUserId 还不存在，这时不能清空列表，否则会把 React Query
// 刚从缓存恢复出来的项目列表擦掉，造成“详情页返回首页不刷新就空白”的问题。
export function shouldResetProjectListForUserChange(
  previousUserId: string | null,
  nextUserId: string | null,
): boolean {
  return previousUserId !== null && previousUserId !== nextUserId;
}
