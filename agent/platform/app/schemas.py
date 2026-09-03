from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.localization import Locale


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


ProjectStatus = Literal["idle", "running", "waiting_user", "completed", "failed", "cancelled"]
MessageRole = Literal["user", "agent", "system"]
MessageType = Literal["text", "process_log", "artifact_card", "select_options", "input_form", "user_response"]
ArtifactType = Literal["prd", "ui", "architecture", "api_spec"]
TaskStatus = Literal["idle", "running", "waiting_user", "completed", "failed", "cancelled"]
TaskType = Literal["generate", "modify", "confirm", "rollback", "regenerate"]
GenerationTaskStatus = Literal["pending", "running", "completed", "failed"]
StepType = Literal["process_log", "artifact", "generation"]
StepStatus = Literal["running", "completed", "failed"]
PlannedArtifactFileStatus = Literal["pending", "running", "completed", "failed"]
FileType = Literal["pdf", "markdown", "image"]
VersionKind = Literal[
    "generation",
    "requirements_review",
    "architecture_review",
    "artifact_edit",
    "file_edit",
    "code_edit",
    "modify",
    "rollback",
    "regenerate",
]
VersionCreatedByType = Literal["agent", "user", "system"]
TaskErrorType = Literal[
    "GENERATION_FAILED",
    "PARSING_FAILED",
    "FILE_PARSE_FAILED",
    "COVERAGE_CONFLICT",
    "ROLLBACK_FAILED",
    "TASK_CANCELLED",
    "CONTEXT_EXPIRED",
    "CODE_FILE_LOCKED",
    "CODE_FILE_LOCK_REQUIRED",
    "AUTOSAVE_REQUIRES_CURRENT_VERSION",
]


class ProjectSummary(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    description: str = ""
    status: ProjectStatus = "idle"
    thumbnail: str | None = None
    currentVersion: int = 1
    createdAt: datetime = Field(default_factory=utc_now)
    updatedAt: datetime = Field(default_factory=utc_now)
    userId: str | None = None


class UploadedFile(BaseModel):
    id: str = Field(default_factory=new_id)
    userId: str | None = None
    projectId: str | None = None
    fileName: str
    filePath: str
    fileType: FileType
    fileSize: int
    contentPreview: str | None = None
    thumbnailUrl: str | None = None
    isTemporary: bool = True
    createdAt: datetime = Field(default_factory=utc_now)


class TempUser(BaseModel):
    id: str = Field(default_factory=new_id)
    email: str
    passwordHash: str
    name: str
    avatarUrl: str | None = None
    realUserId: str | None = None
    createdAt: datetime = Field(default_factory=utc_now)
    updatedAt: datetime = Field(default_factory=utc_now)


class AuthTokenRecord(BaseModel):
    id: str = Field(default_factory=new_id)
    userId: str
    tokenHash: str
    createdAt: datetime = Field(default_factory=utc_now)
    revokedAt: datetime | None = None


class Message(BaseModel):
    id: str = Field(default_factory=new_id)
    projectId: str
    role: MessageRole
    type: MessageType
    content: str
    metadata: dict[str, Any] | None = None
    parentId: str | None = None
    createdAt: datetime = Field(default_factory=utc_now)


class Artifact(BaseModel):
    id: str = Field(default_factory=new_id)
    projectId: str
    version: int
    type: ArtifactType
    title: str
    content: str
    metadata: dict[str, Any] | None = None
    createdAt: datetime = Field(default_factory=utc_now)


class CodeFile(BaseModel):
    id: str = Field(default_factory=new_id)
    projectId: str
    version: int
    filePath: str
    content: str
    createdAt: datetime = Field(default_factory=utc_now)


class AgentArtifactRecord(BaseModel):
    id: str = Field(default_factory=new_id)
    projectId: str
    version: int
    taskId: str | None = None
    agent: str
    fileName: str
    fileType: str
    contentType: str
    content: str | None = None
    isPrimarySource: bool = False
    mappedArtifactTypes: list[ArtifactType] = Field(default_factory=list)
    createdAt: datetime = Field(default_factory=utc_now)


class ProjectFileDraft(BaseModel):
    id: str = Field(default_factory=new_id)
    projectId: str
    filePath: str
    content: str
    baseVersion: int
    stage: str
    sourceType: str
    updatedBy: str | None = None
    createdAt: datetime = Field(default_factory=utc_now)
    updatedAt: datetime = Field(default_factory=utc_now)


class CodeFileLock(BaseModel):
    id: str = Field(default_factory=new_id)
    projectId: str
    filePath: str
    version: int
    lockedBy: str
    lockedAt: datetime = Field(default_factory=utc_now)
    updatedAt: datetime = Field(default_factory=utc_now)


class ProjectModule(BaseModel):
    id: str = Field(default_factory=new_id)
    projectId: str
    name: str
    nameEn: str
    isSelected: bool = True
    createdAt: datetime = Field(default_factory=utc_now)


class GenerationTask(BaseModel):
    id: str = Field(default_factory=new_id)
    projectId: str
    taskName: str
    status: GenerationTaskStatus = "pending"
    progress: int = 0
    errorMessage: str | None = None
    startedAt: datetime | None = None
    completedAt: datetime | None = None
    createdAt: datetime = Field(default_factory=utc_now)


class TaskStatistics(BaseModel):
    id: str = Field(default_factory=new_id)
    projectId: str
    taskId: str
    startedAt: datetime = Field(default_factory=utc_now)
    completedAt: datetime | None = None
    totalDuration: float = 0.0
    stepsCount: int = 0
    itemsRead: int = 0
    inputTokens: int = 0
    outputTokens: int = 0
    totalTokens: int = 0
    costAmount: float = 0.0
    modelUsed: str = "gpt-5.4"
    createdAt: datetime = Field(default_factory=utc_now)


class StepRecord(BaseModel):
    id: str = Field(default_factory=new_id)
    taskStatisticsId: str
    stepName: str
    stepType: StepType
    duration: float = 0.0
    tokensUsed: int = 0
    cost: float = 0.0
    status: StepStatus = "running"
    metadata: dict[str, Any] | None = None
    createdAt: datetime = Field(default_factory=utc_now)


class ProjectVersion(BaseModel):
    id: str = Field(default_factory=new_id)
    projectId: str
    version: int
    versionKind: VersionKind = "generation"
    sourceVersion: int | None = None
    restoredFromVersion: int | None = None
    createdByType: VersionCreatedByType = "system"
    createdBy: str | None = None
    description: str
    changes: list[dict[str, Any]] = Field(default_factory=list)
    stateManifest: dict[str, Any] = Field(default_factory=dict)
    modulesSnapshot: list[dict[str, Any]] = Field(default_factory=list)
    isCurrent: bool = True
    createdAt: datetime = Field(default_factory=utc_now)


class TaskState(BaseModel):
    id: str = Field(default_factory=new_id)
    projectId: str
    taskType: TaskType
    status: TaskStatus = "idle"
    inputData: dict[str, Any] = Field(default_factory=dict)
    outputData: dict[str, Any] | None = None
    errorType: TaskErrorType | None = None
    errorMessage: str | None = None
    parentTaskId: str | None = None
    createdAt: datetime = Field(default_factory=utc_now)
    startedAt: datetime | None = None
    completedAt: datetime | None = None


class CreateProjectRequest(BaseModel):
    name: str | None = None
    description: str = ""


class UpdateProjectRequest(BaseModel):
    name: str


class GenerateProjectRequest(BaseModel):
    prompt: str
    uploadedFiles: list[str] = Field(default_factory=list)
    locale: Locale = "en"


class SendMessageRequest(BaseModel):
    content: str | None = None
    type: Literal["text", "user_response"] = "text"
    parentId: str | None = None
    response: dict[str, Any] | None = None
    taskId: str | None = None
    locale: Locale = "en"


class ConfirmProjectRequest(BaseModel):
    taskId: str
    action: Literal["confirm"] = "confirm"
    data: dict[str, Any] = Field(default_factory=dict)
    locale: Locale = "en"


class ModifyProjectRequest(BaseModel):
    taskId: str
    content: str
    locale: Locale = "en"


class UpdateArtifactRequest(BaseModel):
    content: str


class UpdateCodeFileRequest(BaseModel):
    content: str
    version: int | None = None
    userId: str | None = None


class UpdateProjectFileDraftRequest(BaseModel):
    content: str
    version: int | None = None
    userId: str | None = None


class CommitProjectDraftsRequest(BaseModel):
    description: str | None = None
    userId: str | None = None


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    id: str
    email: str
    name: str
    avatarUrl: str | None = None
    token: str


class CurrentUserResponse(BaseModel):
    id: str
    email: str
    name: str
    avatarUrl: str | None = None


class LogoutResponse(BaseModel):
    message: str


class CodeFileLockRequest(BaseModel):
    userId: str
    version: int | None = None


class CodeFileUnlockRequest(BaseModel):
    userId: str


class ListProjectsResponse(BaseModel):
    projects: list[ProjectSummary]
    total: int
    page: int
    totalPages: int


class ListMessagesResponse(BaseModel):
    messages: list[Message]
    total: int


class ListTasksResponse(BaseModel):
    tasks: list[GenerationTask]


class StatisticsResponse(BaseModel):
    totalDuration: float
    stepsCount: int
    itemsRead: int
    tokens: dict[str, int]
    cost: float
    model: str
    usageStatus: Literal["pending", "reported", "unreported"]
    reportedSteps: int = 0
    unreportedSteps: int = 0
    agentUsage: list[dict[str, Any]] = Field(default_factory=list)
    startedAt: datetime
    completedAt: datetime | None = None


class StepsResponse(BaseModel):
    steps: list[StepRecord]


class AgentArtifactsResponse(BaseModel):
    projectId: str
    version: int | None = None
    artifactsByAgent: dict[str, list[AgentArtifactRecord]] = Field(default_factory=dict)


class AgentArtifactsByAgentResponse(BaseModel):
    projectId: str
    version: int | None = None
    agent: str
    artifacts: list[AgentArtifactRecord] = Field(default_factory=list)


class TaskRoundSnapshot(BaseModel):
    taskId: str
    status: TaskStatus
    anchorMessageId: str | None = None
    anchorContent: str | None = None
    logsCount: int = 0
    latestLogId: str | None = None
    latestLog: str | None = None
    latestPhase: str | None = None
    updatedAt: datetime | None = None


class PlannedArtifactFile(BaseModel):
    fileName: str
    label: str
    agent: str
    mappedArtifactTypes: list[ArtifactType] = Field(default_factory=list)
    status: PlannedArtifactFileStatus = "pending"
    contentAvailable: bool = False


class CurrentTaskResponse(BaseModel):
    task: TaskState | None
    status: TaskStatus | Literal["idle"]
    confirmationData: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None
    statistics: StatisticsResponse | None = None
    round: TaskRoundSnapshot | None = None
    activeAgent: str | None = None
    activePhase: str | None = None
    agentOutputsReady: list[str] = Field(default_factory=list)
    pendingAgentArtifactsVersion: int | None = None
    plannedArtifactFiles: dict[str, list[PlannedArtifactFile]] = Field(default_factory=dict)


class VersionsResponse(BaseModel):
    versions: list[ProjectVersion]


class AgentEvent(BaseModel):
    type: str
    data: dict[str, Any]
    timestamp: datetime = Field(default_factory=utc_now)
