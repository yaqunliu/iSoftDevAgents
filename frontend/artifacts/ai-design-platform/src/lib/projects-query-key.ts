// 接口注释：统一生成项目列表查询 key，确保“搜索条件”和“当前登录身份”一起参与缓存隔离。
// 这样退出后重新登录，或者切换到另一个账号时，就不会误用上一位用户留下来的项目列表缓存。
export function buildProjectsQueryKey(params: {
  authScope: string;
  search?: string;
  page?: number;
  limit?: number;
}): [string, string, string, number, number] {
  const { authScope, search = "", page = 1, limit = 12 } = params;

  return ["projects", authScope, search.trim(), page, limit];
}
