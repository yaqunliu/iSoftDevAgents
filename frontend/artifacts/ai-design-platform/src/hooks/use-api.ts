import { useEffect, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import i18n from "@/i18n";
import { backendLocaleForLanguage, dateLocaleForLanguage } from "@/lib/locale";
import { reduceLiveActivityEvent, type LiveActivityItem } from "@/lib/task-activity";
import { RequestTimeoutError, fetchWithTimeout } from "@/lib/api-request";
import { buildProjectsQueryKey } from "@/lib/projects-query-key";
import { projectWorkspaceQueryKeys } from "@/lib/project-workspace-query-keys";
import { buildProjectWebSocketQueryPlan } from "@/lib/project-websocket-events";
import { buildProjectWebSocketUrl } from "@/lib/project-websocket-url";
import { resolveLiveQueryRefetchInterval } from "@/lib/live-query-interval";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:9010").replace(/\/+$/, "");
const API_REQUEST_TIMEOUT_MS = Number(import.meta.env.VITE_API_REQUEST_TIMEOUT_MS ?? "15000");
const AUTH_TOKEN_STORAGE_KEY = "isoftdevagents.authToken";

type ProjectStatus = "idle" | "running" | "waiting_user" | "completed" | "failed" | "cancelled";
type HistoryChangeStatus = "Modified" | "Added" | "Deleted";
type MessageRole = "user" | "agent" | "system";
type MessageType = "text" | "process_log" | "artifact_card" | "select_options" | "input_form" | "user_response";
type ArtifactType = "prd" | "ui" | "architecture" | "api_spec";
type TaskStatus = "idle" | "running" | "waiting_user" | "completed" | "failed" | "cancelled";
type VersionKind =
  | "generation"
  | "requirements_review"
  | "architecture_review"
  | "artifact_edit"
  | "file_edit"
  | "code_edit"
  | "modify"
  | "rollback"
  | "regenerate";
type TaskErrorType =
  | "GENERATION_FAILED"
  | "PARSING_FAILED"
  | "FILE_PARSE_FAILED"
  | "COVERAGE_CONFLICT"
  | "ROLLBACK_FAILED"
  | "TASK_CANCELLED"
  | "CONTEXT_EXPIRED"
  | "CODE_FILE_LOCKED"
  | "CODE_FILE_LOCK_REQUIRED"
  | "AUTOSAVE_REQUIRES_CURRENT_VERSION";

export type Project = {
  id: string;
  name: string;
  description: string;
  status: ProjectStatus;
  thumbnail?: string | null;
  currentVersion: number;
  createdAt: string;
  updatedAt: string;
};

export type AuthUser = {
  id: string;
  email: string;
  name: string;
  avatarUrl?: string | null;
};

export type SelectOption = {
  id: string;
  label: string;
  labelEn: string;
  description?: string;
  checked?: boolean;
};

export type Message = {
  id: string;
  projectId: string;
  role: MessageRole;
  type: MessageType;
  content: string;
  metadata?: Record<string, unknown> | null;
  parentId?: string | null;
  createdAt: string;
};

export type ArtifactCardMetadata = {
  artifactId: string;
  artifactType: ArtifactType;
  title: string;
  preview?: string;
};

export type ProcessLogMetadata = {
  taskName?: string;
  duration?: string;
  status?: "running" | "completed" | "failed" | "waiting_user";
  phase?: string;
  sourceAgent?: string;
  outputFiles?: string[];
  rawFileName?: string;
  latestOutputFile?: string;
  runtimePid?: number;
  runtimeState?: string;
  secondsSinceLastOutput?: number;
  elapsedSeconds?: number;
};

export type SelectOptionsMetadata = {
  confirmationKind?: string;
  activePhase?: string;
  title?: string;
  message?: string;
  options?: SelectOption[];
  outputFiles?: string[];
  artifactTypes?: string[];
  conflicts?: Array<{
    id?: string;
    type?: string;
    name?: string;
    version?: number;
  }>;
  confirmText?: string;
  cancelText?: string;
};

export type InputVariableField = {
  id: string;
  label: string;
  type?: "text" | "password" | "textarea";
  required?: boolean;
  placeholder?: string;
};

export type InputFormMetadata = {
  confirmationKind?: string;
  activePhase?: string;
  title?: string;
  message?: string;
  variables?: InputVariableField[];
  outputFiles?: string[];
  submitText?: string;
  skipText?: string;
};

export type ArtifactContent = {
  id: string;
  projectId: string;
  version: number;
  type: ArtifactType;
  title: string;
  content: string;
  sourceFiles?: string[];
  sourceAgent?: string;
  sourceStatus?: string;
  artifactKind?: "document" | "code_binding" | "synthesized" | string;
  displayPath?: string;
  rawSourceAvailable?: boolean;
  format?: string;
  mermaidCode?: string | null;
  description?: string | null;
  pages?: Array<{
    id: string;
    name: string;
    route: string;
    thumbnailUrl?: string | null;
    previewUrl?: string | null;
    code?: string;
  }>;
  metadata?: Record<string, unknown> | null;
  createdAt: string;
};

export type HistoryCheckpoint = {
  id: string;
  version: number;
  versionKind: VersionKind;
  sourceVersion?: number | null;
  restoredFromVersion?: number | null;
  createdByType: "agent" | "user" | "system";
  createdBy?: string | null;
  description: string;
  changes: { file: string; status: HistoryChangeStatus }[];
  stateManifest: {
    artifacts: string[];
    codeFiles: string[];
    agentArtifacts: Record<string, string[]>;
  };
  modulesSnapshot: Array<{
    id: string;
    name: string;
    nameEn: string;
    isSelected: boolean;
  }>;
  isCurrent: boolean;
  createdAt: string;
};

export type ExecutionStats = {
  totalDuration: number;
  stepsCount: number;
  itemsRead: number;
  tokens: {
    input: number;
    output: number;
    total: number;
  };
  cost: number;
  model: string;
  usageStatus: "pending" | "reported" | "unreported";
  reportedSteps: number;
  unreportedSteps: number;
  agentUsage: Array<{
    agent: string;
    totalTokens: number;
    cost: number;
    model?: string | null;
    usageStatus: "pending" | "reported" | "unreported";
  }>;
  startedAt: string;
  completedAt?: string | null;
};

export type StepRecord = {
  id: string;
  stepName: string;
  stepType: "process_log" | "artifact" | "generation";
  duration: number;
  tokensUsed: number;
  cost: number;
  status: "running" | "completed" | "failed";
  metadata?: Record<string, unknown> | null;
  createdAt: string;
};

export type AgentArtifactRecord = {
  id: string;
  projectId: string;
  version: number;
  taskId?: string | null;
  agent: string;
  fileName: string;
  fileType: string;
  contentType: string;
  content?: string | null;
  isPrimarySource: boolean;
  mappedArtifactTypes: ArtifactType[];
  createdAt: string;
};

export type CurrentTask = {
  id: string;
  projectId: string;
  taskType: "generate" | "modify" | "confirm" | "rollback" | "regenerate";
  status: TaskStatus;
  inputData: Record<string, unknown>;
  outputData?: Record<string, unknown> | null;
  errorType?: TaskErrorType | null;
  errorMessage?: string | null;
  parentTaskId?: string | null;
  createdAt: string;
  startedAt?: string | null;
  completedAt?: string | null;
};

export type PlannedArtifactFile = {
  fileName: string;
  label: string;
  agent: string;
  mappedArtifactTypes: ArtifactType[];
  status: "pending" | "running" | "completed" | "failed";
  contentAvailable?: boolean;
};

export type ExistingArtifactContext = {
  id: string;
  type: ArtifactType;
  title: string;
  version: number;
  content: string;
};

export type UploadedReference = {
  id: string;
  userId?: string | null;
  projectId?: string | null;
  fileName: string;
  fileType: "pdf" | "markdown" | "image";
  filePath: string;
  fileSize: number;
  contentPreview?: string | null;
  thumbnailUrl?: string | null;
  isTemporary?: boolean;
  createdAt?: string;
};

export type CodeTreeNode = {
  name: string;
  type: "file" | "folder";
  path?: string;
  children?: CodeTreeNode[];
};

export type CodeTreeResponse = {
  projectId: string;
  version: number;
  tree: CodeTreeNode[];
};

export type CodeFileContent = {
  fileName: string;
  path: string;
  language: string;
  content: string;
  lineCount: number;
  updatedAt: string;
  version: number;
  lock?: CodeFileLockState | null;
};

export type ProjectFileEntry = {
  path: string;
  fileName: string;
  stage: string;
  sourceType: "agent_generated" | "system_derived" | "user_edited";
  derivedArtifactType?: string | null;
  contentType: string;
  language: string;
  isEditable: boolean;
  version: number;
  updatedAt: string;
  hasDraft?: boolean;
  draftBaseVersion?: number | null;
  draftUpdatedAt?: string | null;
  draftUpdatedBy?: string | null;
};

export type ProjectFileContent = ProjectFileEntry & {
  content: string;
};

export type ProjectFilesResponse = {
  projectId: string;
  version: number;
  tree: CodeTreeNode[];
  files: ProjectFileEntry[];
};

export type ProjectDraftEntry = {
  path: string;
  fileName: string;
  stage: string;
  sourceType: string;
  baseVersion: number;
  updatedAt: string;
  updatedBy?: string | null;
};

export type ProjectDraftsResponse = {
  projectId: string;
  baseVersion: number;
  currentVersion: number;
  totalFiles: number;
  files: ProjectDraftEntry[];
};

export type CommitProjectDraftsResponse = {
  status: string;
  projectId: string;
  baseVersion: number;
  newVersion: number;
  committedPaths: string[];
};

export type CodeModuleSummary = {
  id: string;
  name: string;
  nameEn: string;
  folderPath: string;
  fileCount: number;
  lineCount: number;
};

export type CurrentTaskResponse = {
  task: CurrentTask | null;
  status: TaskStatus | "idle";
  confirmationData?: Record<string, unknown> | null;
  round?: {
    taskId: string;
    status: TaskStatus;
    anchorMessageId?: string | null;
    anchorContent?: string | null;
    logsCount: number;
    latestLogId?: string | null;
    latestLog?: string | null;
    latestPhase?: string | null;
    updatedAt?: string | null;
  } | null;
  progress?: {
    taskId: string;
    taskName: string;
    status: string;
    progress: number;
  } | null;
  statistics?: ExecutionStats | null;
  activeAgent?: string | null;
  activePhase?: string | null;
  agentOutputsReady?: string[];
  pendingAgentArtifactsVersion?: number | null;
  plannedArtifactFiles?: Record<string, PlannedArtifactFile[]>;
};

type AgentArtifactsResponse = {
  projectId: string;
  version?: number | null;
  artifactsByAgent: Record<string, AgentArtifactRecord[]>;
};

type ProjectsResponse = {
  projects: Project[];
  total: number;
  page: number;
  totalPages: number;
};

export type PagedProjects = ProjectsResponse;

type MessagesResponse = {
  messages: Message[];
  total: number;
};

type StepsResponse = {
  steps: StepRecord[];
};

type VersionsResponse = {
  versions: Array<{
    id: string;
    version: number;
    versionKind: VersionKind;
    sourceVersion?: number | null;
    restoredFromVersion?: number | null;
    createdByType: "agent" | "user" | "system";
    createdBy?: string | null;
    description: string;
    changes: { file: string; status: HistoryChangeStatus }[];
    stateManifest: {
      artifacts: string[];
      codeFiles: string[];
      agentArtifacts: Record<string, string[]>;
    };
    modulesSnapshot: Array<{
      id: string;
      name: string;
      nameEn: string;
      isSelected: boolean;
    }>;
    isCurrent: boolean;
    createdAt: string;
  }>;
};

type GenerateResponse = {
  projectId: string;
  taskId: string;
  status: string;
  message: string;
};

type RollbackResponse = {
  status: "success";
  newVersion: number;
  message: string;
};

type CodeModulesResponse = {
  modules: CodeModuleSummary[];
};

export type CodeFileLockState = {
  filePath: string;
  version: number;
  lockedBy: string;
  lockedAt: string;
  updatedAt: string;
};

export type { LiveActivityItem };

type CodeFileLockResponse = CodeFileLockState & {
  isConflict: boolean;
};

export class ApiError extends Error {
  status: number;
  errorType?: string | null;

  constructor(message: string, status: number, errorType?: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errorType = errorType;
  }
}

function getStoredValue(key: string): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(key);
}

function setStoredValue(key: string, value: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(key, value);
}

function removeStoredValue(key: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(key);
}

export function getStoredAuthToken(): string | null {
  return getStoredValue(AUTH_TOKEN_STORAGE_KEY);
}

export function setStoredAuthToken(token: string): void {
  setStoredValue(AUTH_TOKEN_STORAGE_KEY, token);
}

export function clearStoredAuthToken(): void {
  removeStoredValue(AUTH_TOKEN_STORAGE_KEY);
}

async function postAuthJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const payload = (await response.json()) as T | { detail?: string };
  if (!response.ok) {
    const maybeDetail = (payload as { detail?: string }).detail;
    const detail = typeof maybeDetail === "string" ? maybeDetail : `Request failed with ${response.status}`;
    throw new ApiError(detail, response.status);
  }
  return payload as T;
}

async function ensureAuthToken(): Promise<string | null> {
  return getStoredAuthToken();
}

function currentBackendLocale(): "en" | "zh" {
  return backendLocaleForLanguage(i18n.language);
}

export function formatDateDistance(iso: string): string {
  const value = new Date(iso).getTime();
  if (Number.isNaN(value)) {
    return iso;
  }

  const locale = dateLocaleForLanguage(i18n.language);
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const diff = Date.now() - value;
  const seconds = Math.max(1, Math.floor(diff / 1000));
  if (seconds < 60) {
    return formatter.format(-seconds, "second");
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return formatter.format(-minutes, "minute");
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return formatter.format(-hours, "hour");
  }
  const days = Math.floor(hours / 24);
  if (days < 7) {
    return formatter.format(-days, "day");
  }
  return new Date(iso).toLocaleDateString(locale);
}

export function formatProjectStatus(status: ProjectStatus): string {
  return i18n.t(`project.status.${status}`, { defaultValue: status });
}

export function formatArtifactType(type: ArtifactType): "prd" | "ui" | "arch" | "api" {
  if (type === "architecture") return "arch";
  if (type === "api_spec") return "api";
  return type;
}

export function formatArtifactTypeLabel(type: ArtifactType): string {
  return i18n.t(`artifact.tab.${formatArtifactType(type)}`);
}

export function formatHistoryChangeStatus(status: HistoryChangeStatus): string {
  if (status === "Added") return i18n.t("history.status.added");
  if (status === "Deleted") return i18n.t("history.status.deleted");
  return i18n.t("history.status.modified");
}

function toBackendArtifactType(type: string): ArtifactType {
  if (type === "arch") return "architecture";
  if (type === "api") return "api_spec";
  if (type === "prd" || type === "ui") return type;
  return "prd";
}

function buildVersionQuery(version?: number | null): string {
  const params = new URLSearchParams();
  if (typeof version === "number") {
    params.set("version", String(version));
  }
  return params.size ? `?${params.toString()}` : "";
}

export function getEditorUserId(): string {
  if (typeof window === "undefined") {
    return "local-user";
  }
  const key = "isoftdevagents.editorUserId";
  const existing = window.localStorage.getItem(key);
  if (existing) {
    return existing;
  }
  const next =
    typeof window.crypto !== "undefined" && typeof window.crypto.randomUUID === "function"
      ? window.crypto.randomUUID()
      : `local-user-${Math.random().toString(36).slice(2, 10)}`;
  window.localStorage.setItem(key, next);
  return next;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const headers = new Headers(init?.headers ?? {});
  if (!path.startsWith("/api/auth/")) {
    const token = await ensureAuthToken();
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const requestUrl = `${API_BASE_URL}${path}`;
  const requestMethod = init?.method ?? "GET";
  console.info("[UI ACTION] apiFetch_start", {
    method: requestMethod,
    url: requestUrl,
    hasAuthHeader: headers.has("Authorization"),
    contentType: headers.get("Content-Type"),
  });

  let response: Response;
  try {
    // 设计注释：统一超时可以避免后端卡死时，React Query 永远停在 isLoading=true。
    response = await fetchWithTimeout({
      url: requestUrl,
      timeoutMs: Number.isFinite(API_REQUEST_TIMEOUT_MS) && API_REQUEST_TIMEOUT_MS > 0 ? API_REQUEST_TIMEOUT_MS : 15000,
      fetchImpl: async (input, requestInit) =>
        fetch(input, {
          headers,
          ...init,
          ...requestInit,
        }),
    });
  } catch (error) {
    console.error("[UI ACTION] apiFetch_network_error", {
      method: requestMethod,
      url: requestUrl,
      error,
    });
    if (error instanceof RequestTimeoutError) {
      throw new ApiError(
        `The backend API did not respond in time. Please check the server and try again.`,
        504,
        "REQUEST_TIMEOUT",
      );
    }
    throw error;
  }

  console.info("[UI ACTION] apiFetch_response", {
    method: requestMethod,
    url: requestUrl,
    status: response.status,
    ok: response.ok,
  });

  if (!response.ok) {
    // 这里统一处理未登录和登录失效，避免页面继续误以为自己还在线。
    if (response.status === 401 && !path.startsWith("/api/auth/")) {
      clearStoredAuthToken();
    }
    const text = await response.text();
    try {
      const payload = JSON.parse(text) as { detail?: string | { message?: string; errorType?: string } };
      if (typeof payload.detail === "string") {
        throw new ApiError(payload.detail, response.status);
      }
      if (payload.detail && typeof payload.detail === "object") {
        throw new ApiError(
          payload.detail.message || `Request failed with ${response.status}`,
          response.status,
          payload.detail.errorType,
        );
      }
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
    }
    throw new ApiError(text || `Request failed with ${response.status}`, response.status);
  }

  return response.json() as Promise<T>;
}

type AuthPayload = AuthUser & {
  token: string;
};

// 接口注释：把后端返回的登录结果写入前端缓存，供页面层直接读取当前用户。
function writeCurrentUserCache(queryClient: ReturnType<typeof useQueryClient>, payload: AuthPayload): void {
  queryClient.setQueryData<AuthUser>(["auth", "me", payload.token], {
    id: payload.id,
    email: payload.email,
    name: payload.name,
    avatarUrl: payload.avatarUrl ?? null,
  });
}

export function useCurrentUser() {
  const token = getStoredAuthToken();

  return useQuery({
    queryKey: ["auth", "me", token ?? "anonymous"],
    enabled: Boolean(token),
    retry: false,
    queryFn: async () => apiFetch<AuthUser>("/api/users/me"),
  });
}

export function useRegister() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ email, password, name }: { email: string; password: string; name: string }) =>
      postAuthJson<AuthPayload>("/api/auth/register", {
        email,
        password,
        name,
      }),
    onSuccess: (payload) => {
      setStoredAuthToken(payload.token);
      writeCurrentUserCache(queryClient, payload);
    },
  });
}

export function useLogin() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ email, password }: { email: string; password: string }) =>
      postAuthJson<AuthPayload>("/api/auth/login", {
        email,
        password,
      }),
    onSuccess: (payload) => {
      setStoredAuthToken(payload.token);
      writeCurrentUserCache(queryClient, payload);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      const token = getStoredAuthToken();
      if (!token) {
        return;
      }
      await apiFetch<{ message: string }>("/api/auth/logout", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
    },
    onSettled: () => {
      clearStoredAuthToken();
      queryClient.removeQueries({ queryKey: ["auth", "me"] });
    },
  });
}

function useProjectWebSocket(projectId: string | null) {
  const queryClient = useQueryClient();
  const workspaceQueryKeys = useMemo(
    () => (projectId ? projectWorkspaceQueryKeys(projectId) : []),
    [projectId],
  );

  useEffect(() => {
    if (!projectId || projectId === "new") {
      return;
    }

    let disposed = false;
    let socket: WebSocket | null = null;

    void (async () => {
      const token = await ensureAuthToken();
      if (!token || disposed) {
        return;
      }

      const wsUrl = buildProjectWebSocketUrl({
        apiBaseUrl: API_BASE_URL,
        projectId,
        accessToken: token,
        currentOrigin: typeof window !== "undefined" ? window.location.origin : null,
      });
      socket = new WebSocket(wsUrl);

      socket.onopen = () => {
        console.info("[UI ACTION] project_websocket_open", { projectId, wsUrl });
      };

      socket.onerror = (event) => {
        console.error("[UI ACTION] project_websocket_error", { projectId, event });
      };

      socket.onclose = (event) => {
        console.warn("[UI ACTION] project_websocket_close", {
          projectId,
          code: event.code,
          reason: event.reason,
          wasClean: event.wasClean,
        });
      };

      socket.onmessage = (event) => {
        let payload: { type?: string; data?: Record<string, unknown> };
        try {
          payload = JSON.parse(event.data) as { type?: string; data?: Record<string, unknown> };
        } catch (error) {
          console.error("[UI ACTION] project_websocket_message_parse_failed", {
            projectId,
            error,
            rawData: event.data,
          });
          return;
        }
        const type = payload.type;

        const messagePayload =
          type === "message" || type === "message_update"
            ? ((payload.data ?? null) as { type?: unknown; metadata?: Record<string, unknown> | null } | null)
            : null;
        const queryPlan = buildProjectWebSocketQueryPlan(type, messagePayload);

        // invalidateQueries 会自动 refetch active queries，不需要再单独 refetch。
        // 之前同时 invalidate + refetch 导致同一请求发两遍。
        if (queryPlan.invalidateChat) {
          void queryClient.invalidateQueries({ queryKey: ["chat", projectId] });
        }

        if (queryPlan.invalidateCurrentTask) {
          void queryClient.invalidateQueries({ queryKey: ["current-task", projectId] });
          void queryClient.invalidateQueries({ queryKey: ["projects"] });
        }

        if (type === "task_update") {
          void queryClient.invalidateQueries({ queryKey: ["tasks", projectId] });
          // current-task 已在上面 invalidateCurrentTask 中处理，不重复
          void queryClient.invalidateQueries({ queryKey: ["steps", projectId] });
          void queryClient.invalidateQueries({ queryKey: ["agent-artifacts", projectId] });
          for (const queryKey of workspaceQueryKeys) {
            void queryClient.invalidateQueries({ queryKey });
          }
        }

        if (type === "agent_progress") {
          queryClient.setQueryData<LiveActivityItem[]>(["live-activity", projectId], (current = []) =>
            reduceLiveActivityEvent(current, payload),
          );
          // 进度数据已通过 setQueryData 写入缓存，不再触发 current-task refetch。
          // agent_progress 是最高频事件（每 5 秒），每次 invalidate 会导致
          // 所有标签页同时请求 /task/current，是请求风暴的主要来源之一。
        }

        if (type === "artifact_update") {
          const artifactType = typeof payload.data?.artifactType === "string" ? formatArtifactType(payload.data.artifactType as ArtifactType) : null;
          if (artifactType) {
            void queryClient.invalidateQueries({ queryKey: ["artifact", projectId, artifactType] });
          }
          void queryClient.invalidateQueries({ queryKey: ["agent-artifacts", projectId] });
          for (const queryKey of workspaceQueryKeys) {
            void queryClient.invalidateQueries({ queryKey });
          }
          void queryClient.invalidateQueries({ queryKey: ["chat", projectId] });
        }

        if (type === "version_update") {
          void queryClient.invalidateQueries({ queryKey: ["history", projectId] });
          void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
          void queryClient.invalidateQueries({ queryKey: ["agent-artifacts", projectId] });
          for (const queryKey of workspaceQueryKeys) {
            void queryClient.invalidateQueries({ queryKey });
          }
        }

        if (type === "statistics") {
          void queryClient.invalidateQueries({ queryKey: ["statistics", projectId] });
        }
      };
    })();

    return () => {
      disposed = true;
      socket?.close();
    };
  }, [projectId, queryClient, workspaceQueryKeys]);
}

export function useProjects(search = "", page = 1, limit = 12) {
  const authScope = getStoredAuthToken() ?? "anonymous";

  return useQuery({
    // 设计注释：项目列表天然属于“当前登录用户”的私有数据。
    // 如果缓存 key 不带登录身份，退出后重新登录，或者切到别的账号时，
    // React Query 就可能把上一位用户的项目列表直接复用出来，直到页面被强制刷新才纠正。
    queryKey: buildProjectsQueryKey({
      authScope,
      search,
      page,
      limit,
    }),
    // 原因注释：首页是用户最常回到的页面，这里即使缓存还很新，也要在重新挂载时主动拉一次最新列表，
    // 避免从项目详情返回首页时，继续停留在几分钟前的列表快照上。
    refetchOnMount: "always",
    queryFn: async () => {
      const params = new URLSearchParams({ page: String(page), limit: String(limit) });
      if (search.trim()) {
        params.set("search", search.trim());
      }
      return apiFetch<ProjectsResponse>(`/api/projects?${params.toString()}`);
    },
  });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: ["project", id],
    enabled: id !== "new",
    queryFn: async () => apiFetch<Project>(`/api/projects/${id}`),
  });
}

export function useCurrentTask(projectId: string) {
  useProjectWebSocket(projectId);
  return useQuery({
    queryKey: ["current-task", projectId],
    enabled: projectId !== "new",
    queryFn: async () => apiFetch<CurrentTaskResponse>(`/api/projects/${projectId}/task/current`),
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.status === "running" ? 10_000 : false;
    },
  });
}

export function useSteps(projectId: string, taskId?: string | null, taskStatus?: TaskStatus | "idle" | null) {
  return useQuery({
    queryKey: ["steps", projectId, taskId ?? "latest"],
    enabled: projectId !== "new",
    queryFn: async () => {
      const query = taskId ? `?task_id=${encodeURIComponent(taskId)}` : "";
      const data = await apiFetch<StepsResponse>(`/api/projects/${projectId}/steps${query}`);
      return data.steps;
    },
    refetchInterval: () => resolveLiveQueryRefetchInterval(taskStatus),
  });
}

export function useStatistics(projectId: string, taskId?: string | null, taskStatus?: TaskStatus | "idle" | null) {
  return useQuery({
    queryKey: ["statistics", projectId, taskId ?? "latest"],
    enabled: projectId !== "new",
    queryFn: async () => {
      const query = taskId ? `?task_id=${encodeURIComponent(taskId)}` : "";
      return apiFetch<ExecutionStats>(`/api/projects/${projectId}/statistics${query}`);
    },
    refetchInterval: () => resolveLiveQueryRefetchInterval(taskStatus),
  });
}

export function useCurrentReferences(projectId: string, taskId?: string | null, taskStatus?: TaskStatus | "idle" | null) {
  return useQuery({
    queryKey: ["references", projectId, taskId ?? "latest"],
    enabled: projectId !== "new",
    queryFn: async () => {
      const query = taskId ? `?task_id=${encodeURIComponent(taskId)}` : "";
      return apiFetch<UploadedReference[]>(`/api/projects/${projectId}/references/current${query}`);
    },
    refetchInterval: () => resolveLiveQueryRefetchInterval(taskStatus),
  });
}

export function useProjectReferences(projectId: string) {
  return useQuery({
    queryKey: ["project-references", projectId],
    enabled: projectId !== "new",
    queryFn: async () => apiFetch<UploadedReference[]>(`/api/projects/${projectId}/references`),
  });
}

export function useChat(projectId: string) {
  const queryClient = useQueryClient();
  const currentTaskQuery = useCurrentTask(projectId);
  const liveActivityQuery = useLiveActivity(projectId);
  const stepsQuery = useSteps(projectId, currentTaskQuery.data?.task?.id, currentTaskQuery.data?.status);
  const statisticsQuery = useStatistics(projectId, currentTaskQuery.data?.task?.id, currentTaskQuery.data?.status);
  const referencesQuery = useCurrentReferences(projectId, currentTaskQuery.data?.task?.id, currentTaskQuery.data?.status);
  const projectReferencesQuery = useProjectReferences(projectId);

  const messagesQuery = useQuery({
    queryKey: ["chat", projectId],
    enabled: projectId !== "new",
    queryFn: async () => {
      const data = await apiFetch<MessagesResponse>(`/api/projects/${projectId}/messages?page=1&limit=200`);
      return data.messages;
    },
    refetchInterval: () => resolveLiveQueryRefetchInterval(currentTaskQuery.data?.status),
  });

  const invalidateProjectState = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["chat", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["current-task", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["tasks", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["statistics", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["steps", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["history", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["artifact", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["agent-artifacts", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["references", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project-references", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["projects"] }),
    ]);
  };

  const clearLiveActivity = () => {
    queryClient.setQueryData<LiveActivityItem[]>(["live-activity", projectId], []);
  };

  const resetLiveActivityForNewTask = () => {
    const currentTask = currentTaskQuery.data?.task;
    const confirmationKind =
      currentTask?.outputData && typeof currentTask.outputData.confirmationKind === "string"
        ? currentTask.outputData.confirmationKind
        : null;
    const startsNewTask =
      !currentTask ||
      currentTask.status === "completed" ||
      currentTask.status === "failed" ||
      currentTask.status === "cancelled" ||
      confirmationKind === "artifact_review";
    if (startsNewTask) {
      clearLiveActivity();
    }
  };

  const sendMessage = useMutation({
    mutationFn: async (content: string) => {
      const currentTask = currentTaskQuery.data?.task;
      const confirmationKind =
        currentTask?.outputData && typeof currentTask.outputData.confirmationKind === "string"
          ? currentTask.outputData.confirmationKind
          : null;
      if (currentTask?.status === "waiting_user" && confirmationKind === "artifact_review") {
        return apiFetch(`/api/projects/${projectId}/modify`, {
          method: "POST",
          body: JSON.stringify({
            taskId: currentTask.id,
            content,
            locale: currentBackendLocale(),
          }),
        });
      }
      return apiFetch(`/api/projects/${projectId}/messages`, {
        method: "POST",
        body: JSON.stringify({
          content,
          type: "text",
          locale: currentBackendLocale(),
        }),
      });
    },
    onMutate: resetLiveActivityForNewTask,
    onSuccess: invalidateProjectState,
  });

  const confirmGeneration = useMutation({
    mutationFn: async ({
      selectedIds,
    }: {
      messageId?: string;
      selectedIds: string[];
    }) => {
      const currentTask = currentTaskQuery.data?.task;
      if (!currentTask) {
        throw new Error("Current task not found");
      }
      return apiFetch(`/api/projects/${projectId}/confirm`, {
        method: "POST",
        body: JSON.stringify({
          taskId: currentTask.id,
          action: "confirm",
          data: { selectedIds },
          locale: currentBackendLocale(),
        }),
      });
    },
    onSuccess: invalidateProjectState,
  });

  const submitInputVariables = useMutation({
    mutationFn: async ({
      variables,
      skip,
      taskId,
    }: {
      variables?: Record<string, string>;
      skip?: boolean;
      taskId?: string;
    }) => {
      const currentTask = currentTaskQuery.data?.task;
      const targetTaskId = taskId ?? currentTask?.id;
      const feedbackText = typeof variables?.feedback === "string" ? variables.feedback.trim() : "";
      console.info("[UI ACTION] submitInputVariables", {
        projectId,
        currentTaskId: currentTask?.id ?? null,
        targetTaskId: targetTaskId ?? null,
        skip: Boolean(skip),
        feedback: feedbackText,
        variableKeys: variables ? Object.keys(variables) : [],
      });
      if (!targetTaskId) {
        throw new Error("Current task not found");
      }
      return apiFetch(`/api/projects/${projectId}/messages`, {
        method: "POST",
        body: JSON.stringify({
          taskId: targetTaskId,
          type: "user_response",
          content: skip ? "No changes requested." : feedbackText || "Submitted form response.",
          response: {
            variables,
            skip: Boolean(skip),
          },
          locale: currentBackendLocale(),
        }),
      });
    },
    onSuccess: invalidateProjectState,
  });

  const modifyGeneration = useMutation({
    mutationFn: async (content: string) => {
      const currentTask = currentTaskQuery.data?.task;
      if (!currentTask) {
        throw new Error("Current task not found");
      }
      return apiFetch(`/api/projects/${projectId}/modify`, {
        method: "POST",
        body: JSON.stringify({
          taskId: currentTask.id,
          content,
          locale: currentBackendLocale(),
        }),
      });
    },
    onMutate: clearLiveActivity,
    onSuccess: invalidateProjectState,
  });

  const cancelTask = useMutation({
    mutationFn: async () => {
      const currentTask = currentTaskQuery.data?.task;
      if (!currentTask) {
        throw new Error("Current task not found");
      }
      return apiFetch(`/api/projects/${projectId}/tasks/${currentTask.id}/cancel`, {
        method: "POST",
      });
    },
    onSuccess: invalidateProjectState,
  });

  const retryTask = useMutation({
    mutationFn: async () => {
      const currentTask = currentTaskQuery.data?.task;
      if (!currentTask) {
        throw new Error("Current task not found");
      }
      return apiFetch(`/api/projects/${projectId}/tasks/${currentTask.id}/retry`, {
        method: "POST",
      });
    },
    onMutate: clearLiveActivity,
    onSuccess: invalidateProjectState,
  });

  const messages = useMemo(() => messagesQuery.data ?? [], [messagesQuery.data]);

  return {
    data: messages,
    sendMessage,
    confirmGeneration,
    modifyGeneration,
    submitInputVariables,
    cancelTask,
    retryTask,
    currentTask: currentTaskQuery.data ?? null,
    references: referencesQuery.data ?? [],
    projectReferences: projectReferencesQuery.data ?? [],
    liveActivity: liveActivityQuery.data ?? [],
    steps: stepsQuery.data ?? [],
    statistics: statisticsQuery.data ?? currentTaskQuery.data?.statistics ?? null,
    isLoading:
      messagesQuery.isLoading ||
      currentTaskQuery.isLoading ||
      referencesQuery.isLoading ||
      projectReferencesQuery.isLoading ||
      stepsQuery.isLoading ||
      statisticsQuery.isLoading,
  };
}

export function useLiveActivity(projectId: string) {
  return useQuery({
    queryKey: ["live-activity", projectId],
    enabled: false,
    initialData: [] as LiveActivityItem[],
    queryFn: async () => [] as LiveActivityItem[],
  });
}

export function useArtifact(projectId: string, type: string, version?: number | null) {
  return useQuery({
    queryKey: ["artifact", projectId, type, version ?? "latest"],
    enabled: projectId !== "new",
    queryFn: async () => {
      const artifactType = toBackendArtifactType(type);
      const query = buildVersionQuery(version);
      return apiFetch<ArtifactContent>(`/api/projects/${projectId}/artifacts/${artifactType}${query}`);
    },
    retry: false,
  });
}

export function useAgentArtifacts(projectId: string, version?: number | null, enabled = true) {
  return useQuery({
    queryKey: ["agent-artifacts", projectId, version ?? "latest"],
    enabled: projectId !== "new" && enabled,
    queryFn: async () => {
      const query = buildVersionQuery(version);
      return apiFetch<AgentArtifactsResponse>(`/api/projects/${projectId}/agent-artifacts${query}`);
    },
    retry: false,
  });
}

export function useCodeTree(projectId: string, version?: number | null) {
  return useQuery({
    queryKey: ["code-tree", projectId, version ?? "latest"],
    enabled: projectId !== "new",
    queryFn: async () => {
      const query = buildVersionQuery(version);
      return apiFetch<CodeTreeResponse>(`/api/projects/${projectId}/code/files${query}`);
    },
    retry: false,
  });
}

export function useCodeFile(projectId: string, filePath: string | null, version?: number | null) {
  return useQuery({
    queryKey: ["code-file", projectId, filePath ?? "none", version ?? "latest"],
    enabled: projectId !== "new" && Boolean(filePath),
    queryFn: async () => {
      const query = buildVersionQuery(version);
      return apiFetch<CodeFileContent>(`/api/projects/${projectId}/code/files/${encodeURI(filePath ?? "")}${query}`);
    },
    retry: false,
  });
}

export function useCodeModules(projectId: string, version?: number | null) {
  return useQuery({
    queryKey: ["code-modules", projectId, version ?? "latest"],
    enabled: projectId !== "new",
    queryFn: async () => {
      const query = buildVersionQuery(version);
      const data = await apiFetch<CodeModulesResponse>(`/api/projects/${projectId}/code/modules${query}`);
      return data.modules;
    },
    retry: false,
  });
}

export function useProjectFiles(projectId: string, version?: number | null) {
  return useQuery({
    queryKey: ["project-files", projectId, version ?? "latest"],
    enabled: projectId !== "new",
    queryFn: async () => {
      const query = buildVersionQuery(version);
      return apiFetch<ProjectFilesResponse>(`/api/projects/${projectId}/files${query}`);
    },
    retry: false,
  });
}

export function useProjectFile(projectId: string, filePath: string | null, version?: number | null) {
  return useQuery({
    queryKey: ["project-file", projectId, filePath ?? "none", version ?? "latest"],
    enabled: projectId !== "new" && Boolean(filePath),
    queryFn: async () => {
      const query = buildVersionQuery(version);
      return apiFetch<ProjectFileContent>(`/api/projects/${projectId}/files/${encodeURI(filePath ?? "")}${query}`);
    },
    retry: false,
  });
}

export function useProjectDrafts(projectId: string) {
  return useQuery({
    queryKey: ["project-drafts", projectId],
    enabled: projectId !== "new",
    queryFn: async () => apiFetch<ProjectDraftsResponse>(`/api/projects/${projectId}/drafts`),
    retry: false,
  });
}

export function getCodePreviewUrl(projectId: string, filePath: string, version?: number | null): string {
  const query = buildVersionQuery(version);
  return `${API_BASE_URL}/api/projects/${projectId}/code/preview/${encodeURI(filePath)}${query}`;
}

export function useDownloadCode(projectId: string) {
  return useMutation({
    mutationFn: async (version?: number | null) => {
      const query = buildVersionQuery(version);
      const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/code/download${query}`);
      if (!response.ok) {
        const text = await response.text();
        throw new ApiError(text || `Request failed with ${response.status}`, response.status);
      }
      const blob = await response.blob();
      const disposition = response.headers.get("content-disposition") ?? "";
      const match = disposition.match(/filename=\"?([^"]+)\"?/);
      return {
        blob,
        filename: match?.[1] ?? `project-${projectId}.zip`,
      };
    },
  });
}

export function useUpdateCodeFile(projectId: string) {
  const queryClient = useQueryClient();

  const invalidateProjectState = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["chat", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["current-task", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["tasks", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["statistics", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["steps", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["history", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["artifact", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["code-tree", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["code-file", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["code-modules", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project-files", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project-file", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["projects"] }),
    ]);
  };

  return useMutation({
    mutationFn: async ({ filePath, content, version, userId }: { filePath: string; content: string; version?: number | null; userId?: string }) =>
      apiFetch<CodeFileContent>(`/api/projects/${projectId}/code/files/${encodeURI(filePath)}`, {
        method: "PUT",
        body: JSON.stringify({ content, version, userId }),
      }),
    onSuccess: invalidateProjectState,
  });
}

export function useAcquireCodeFileLock(projectId: string) {
  return useMutation({
    mutationFn: async ({ filePath, version, userId }: { filePath: string; version?: number | null; userId: string }) =>
      apiFetch<CodeFileLockResponse>(`/api/projects/${projectId}/code/files/${encodeURI(filePath)}/lock`, {
        method: "POST",
        body: JSON.stringify({ userId, version }),
      }),
  });
}

export function useReleaseCodeFileLock(projectId: string) {
  return useMutation({
    mutationFn: async ({ filePath, userId }: { filePath: string; userId: string }) =>
      apiFetch<{ status: string; filePath: string }>(
        `/api/projects/${projectId}/code/files/${encodeURI(filePath)}/lock?${new URLSearchParams({ userId }).toString()}`,
        {
          method: "DELETE",
        },
      ),
  });
}

export function useAutosaveCodeFile(projectId: string) {
  const queryClient = useQueryClient();

  const invalidateProjectState = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["chat", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["artifact", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["code-tree", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["code-file", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["code-modules", projectId] }),
    ]);
  };

  return useMutation({
    mutationFn: async ({ filePath, content, version, userId }: { filePath: string; content: string; version?: number | null; userId: string }) =>
      apiFetch<CodeFileContent>(`/api/projects/${projectId}/code/files/${encodeURI(filePath)}/autosave`, {
        method: "PUT",
        body: JSON.stringify({ content, version, userId }),
      }),
    onSuccess: invalidateProjectState,
  });
}

export function useUpdateProjectFile(projectId: string) {
  const queryClient = useQueryClient();

  const invalidateProjectState = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["chat", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["current-task", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["tasks", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["statistics", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["steps", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["history", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["artifact", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["agent-artifacts", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["code-tree", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["code-file", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["code-modules", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project-files", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project-file", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["projects"] }),
    ]);
  };

  return useMutation({
    mutationFn: async ({ filePath, content, version, userId }: { filePath: string; content: string; version?: number | null; userId?: string }) =>
      apiFetch<ProjectFileContent>(`/api/projects/${projectId}/files/${encodeURI(filePath)}`, {
        method: "PUT",
        body: JSON.stringify({ content, version, userId }),
      }),
    onSuccess: invalidateProjectState,
  });
}

export function useSaveProjectFileDraft(projectId: string) {
  const queryClient = useQueryClient();

  const invalidateProjectState = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["project-files", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project-file", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project-drafts", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["code-file", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["code-tree", projectId] }),
    ]);
  };

  return useMutation({
    mutationFn: async ({ filePath, content, version, userId }: { filePath: string; content: string; version?: number | null; userId?: string }) =>
      apiFetch<ProjectFileContent>(`/api/projects/${projectId}/files/${encodeURI(filePath)}/draft`, {
        method: "PUT",
        body: JSON.stringify({ content, version, userId }),
      }),
    onSuccess: invalidateProjectState,
  });
}

export function useCommitProjectDrafts(projectId: string) {
  const queryClient = useQueryClient();

  const invalidateProjectState = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["chat", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["current-task", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["tasks", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["statistics", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["steps", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["history", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["artifact", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["agent-artifacts", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["code-tree", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["code-file", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["code-modules", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project-files", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project-file", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project-drafts", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["projects"] }),
    ]);
  };

  return useMutation({
    mutationFn: async ({ description, userId }: { description?: string; userId?: string }) =>
      apiFetch<CommitProjectDraftsResponse>(`/api/projects/${projectId}/drafts/commit`, {
        method: "POST",
        body: JSON.stringify({ description, userId }),
      }),
    onSuccess: invalidateProjectState,
  });
}

export function useStartArtifactEdit(projectId: string) {
  const queryClient = useQueryClient();

  const invalidateProjectState = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["chat", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["current-task", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["tasks", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["statistics", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["steps", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["history", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["artifact", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["projects"] }),
    ]);
  };

  return useMutation({
    mutationFn: async (content: string) =>
      apiFetch(`/api/projects/${projectId}/messages`, {
        method: "POST",
        body: JSON.stringify({
          content,
          type: "text",
        }),
      }),
    onSuccess: invalidateProjectState,
  });
}

export function useUpdateArtifact(projectId: string, artifactType: "prd") {
  const queryClient = useQueryClient();

  const invalidateProjectState = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["chat", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["current-task", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["tasks", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["statistics", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["steps", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["history", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["artifact", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["projects"] }),
    ]);
  };

  return useMutation({
    mutationFn: async (content: string) =>
      apiFetch(`/api/projects/${projectId}/artifacts/${artifactType}`, {
        method: "PUT",
        body: JSON.stringify({ content }),
      }),
    onSuccess: invalidateProjectState,
  });
}

export function useRollbackVersion(projectId: string) {
  const queryClient = useQueryClient();

  const invalidateProjectState = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["chat", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["current-task", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["tasks", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["statistics", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["steps", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["history", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["artifact", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["projects"] }),
    ]);
  };

  return useMutation({
    mutationFn: async (version: number) =>
      apiFetch<RollbackResponse>(`/api/projects/${projectId}/versions/${version}/rollback`, {
        method: "POST",
      }),
    onSuccess: invalidateProjectState,
  });
}

export function useHistory(projectId: string) {
  return useQuery({
    queryKey: ["history", projectId],
    enabled: projectId !== "new",
    queryFn: async () => {
      const data = await apiFetch<VersionsResponse>(`/api/projects/${projectId}/versions`);
      return data.versions.map((version) => ({
        id: version.id,
        version: version.version,
        versionKind: version.versionKind,
        sourceVersion: version.sourceVersion,
        restoredFromVersion: version.restoredFromVersion,
        createdByType: version.createdByType,
        createdBy: version.createdBy,
        description: version.description,
        changes: version.changes,
        stateManifest: version.stateManifest,
        modulesSnapshot: version.modulesSnapshot,
        isCurrent: version.isCurrent,
        createdAt: version.createdAt,
      })) satisfies HistoryCheckpoint[];
    },
  });
}

export function useCreateAndGenerateProject() {
  return useMutation({
    mutationFn: async ({ prompt }: { prompt: string; uploadedFileIds: string[] }) => {
      const project = await apiFetch<{ id: string; name: string; status: string; createdAt: string }>("/api/projects", {
        method: "POST",
        body: JSON.stringify({
          description: prompt,
        }),
      });
      return project.id;
    },
  });
}

export function useDeleteProject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (projectId: string) =>
      apiFetch<{ status: string }>(`/api/projects/${projectId}`, {
        method: "DELETE",
      }),
    onSuccess: async (_result, projectId) => {
      await Promise.allSettled([
        queryClient.invalidateQueries({ queryKey: ["projects"] }),
        queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["chat", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["current-task", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["tasks", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["statistics", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["steps", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["history", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["artifact", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["agent-artifacts", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["code-tree", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["code-file", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["code-modules", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["project-files", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["project-file", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["project-drafts", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["references", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["project-references", projectId] }),
      ]);
    },
  });
}

export function useRenameProject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ projectId, name }: { projectId: string; name: string }) =>
      apiFetch<Project>(`/api/projects/${projectId}`, {
        method: "PUT",
        body: JSON.stringify({ name }),
      }),
    onSuccess: async (project) => {
      await Promise.allSettled([
        queryClient.invalidateQueries({ queryKey: ["projects"] }),
        queryClient.invalidateQueries({ queryKey: ["project", project.id] }),
      ]);
    },
  });
}

export function useGenerateProject() {
  return useMutation({
    mutationFn: async ({
      projectId,
      prompt,
      uploadedFileIds,
    }: {
      projectId: string;
      prompt: string;
      uploadedFileIds: string[];
    }) =>
      apiFetch<GenerateResponse>(`/api/projects/${projectId}/generate`, {
        method: "POST",
        body: JSON.stringify({
          prompt,
          uploadedFiles: uploadedFileIds,
          locale: currentBackendLocale(),
        }),
      }),
  });
}

function inferUploadType(file: File): UploadedReference["fileType"] {
  const lowerName = file.name.toLowerCase();
  if (file.type.startsWith("image/")) return "image";
  if (lowerName.endsWith(".pdf")) return "pdf";
  return "markdown";
}

export function useUploadReferenceFile() {
  return useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("type", inferUploadType(file));
      return apiFetch<UploadedReference>("/api/upload", {
        method: "POST",
        body: formData,
      });
    },
  });
}

export function useFormattedTimestamp(value?: string | null) {
  return useMemo(() => (value ? formatDateDistance(value) : ""), [value]);
}
