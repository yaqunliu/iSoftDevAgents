// 接口注释：
// 统一负责把项目实时通道地址拼成浏览器可用的 WebSocket URL。
// 调用方只需要传入 API 基础地址、项目 id 和 token，不需要自己处理相对路径、协议转换和查询参数。
export function buildProjectWebSocketUrl(params: {
  apiBaseUrl: string;
  projectId: string;
  accessToken: string;
  currentOrigin?: string | null;
}): string {
  const { apiBaseUrl, projectId, accessToken, currentOrigin } = params;
  const trimmedBaseUrl = apiBaseUrl.trim();

  // 设计注释：
  // Docker 前端常把 VITE_API_BASE_URL 设成空字符串，表示“跟当前页面同源”。
  // 这时不能直接 new URL("/api/...")，否则浏览器会抛 Invalid URL。
  const resolvedBaseUrl =
    trimmedBaseUrl.length > 0
      ? trimmedBaseUrl
      : `${normalizeOrigin(currentOrigin)}${buildProjectWebSocketPath(projectId)}`;

  const wsUrl =
    trimmedBaseUrl.length > 0
      ? new URL(buildProjectWebSocketPath(projectId), ensureTrailingSlash(trimmedBaseUrl))
      : new URL(resolvedBaseUrl);

  wsUrl.protocol = wsUrl.protocol === "https:" ? "wss:" : "ws:";
  wsUrl.searchParams.set("access_token", accessToken);
  return wsUrl.toString();
}

// 教学注释：
// 这里单独拆出路径函数，是为了让地址规则更容易复用和测试。
function buildProjectWebSocketPath(projectId: string): string {
  return `/api/projects/${projectId}/ws`;
}

function ensureTrailingSlash(value: string): string {
  return value.endsWith("/") ? value : `${value}/`;
}

function normalizeOrigin(currentOrigin?: string | null): string {
  const rawOrigin = typeof currentOrigin === "string" ? currentOrigin.trim() : "";
  if (rawOrigin.length > 0) {
    return rawOrigin.replace(/\/+$/, "");
  }
  if (typeof window !== "undefined" && typeof window.location?.origin === "string" && window.location.origin.trim().length > 0) {
    return window.location.origin.replace(/\/+$/, "");
  }
  return "http://localhost:9010";
}
