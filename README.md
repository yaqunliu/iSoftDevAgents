# iSoftDevAgents

## 当前版本概览

当前仓库的正式主线是：

- 前端：`frontend/artifacts/ai-design-platform`
- 平台后端：`agent/platform`
- Agent 目录：`agent/`

当前平台的目标是让用户在前端输入需求后，由 `agent/platform` 调度真实 Agent，逐步产出需求分析、架构设计、主产物文档和代码工作区内容。

当前工作区已经重点推进的能力：

- 接入真实 `Requirements Agent`
- 接入真实 `Architecture Agent`
- 主产物维持 4 个固定视图：`PRD / UI / Architecture / API`
- 前端支持步骤流、阶段卡片、步骤输出文件查看
- Markdown 预览已转向富样式展示
- Token 展示已改为三态语义：`pending / reported / unreported`
- 平台后端支持把 Agent 运行日志与 LLM 调试信息直接输出到服务终端，便于调试
- 新增最基础的邮箱注册、登录、退出与当前登录态能力
- 前端已改为先登录，再进入首页和项目页
- `Requirements Agent` 的三个人工反馈检查点已经打通前后端真实交互，当前可以从模块确认一路继续到最终 `SRS.md`
- 平台模式下，需求反馈不再走旧的内存字符串回调，而是直接注入到 Requirements Agent 正在阻塞等待的输入源中
- 需求草稿阶段等待用户反馈时，不再继续消耗 Agent 的运行超时预算
- `Requirements Agent` 运行时默认会关闭 CrewAI tracing 与 OpenTelemetry 遥测，避免测试和联调时被 `telemetry.crewai.com` 的噪音日志干扰
- 平台的 Agent 超时现在按“每个主步骤单独计时”处理，`Requirements / Architecture / UI / Coding` 默认都是各自 `3600` 秒
- `TestAgent` 已接入平台统一桥梁，当前会在代码生成后独立执行测试阶段，默认也使用单独的 `3600` 秒预算
- UI Agent 失败时，后端会把输入、stdout、stderr、已生成的部分文件打包到 `agent/platform/data/agent-debug/ui-agent/`
- UI Agent 当前仍然输出单页 UI 原型，但不再把业务场景写死成五子棋或其他固定游戏
- 前端步骤输出现在会按 Agent 阶段严格归属，架构阶段不会再错误显示 Requirements Agent 的历史文件

需要注意：

- 当前仓库仍处于持续整改阶段，部分链路已经是真实 Agent，部分边界行为还在继续校正
- `Coding Agent` 的完整端到端联调仍需要继续以真实项目案例验证
- 根目录这个 `README.md` 现在作为版本说明总入口，后续每次提交功能改动都必须同步更新

## 当前版本内容

### 1. 平台形态

- 前端负责项目创建、聊天时间线、步骤卡片、Artifact 查看、代码工作区查看
- `agent/platform` 负责任务编排、消息存储、步骤记录、统计聚合、Artifact 汇总、Agent 调度
- `agent/Requirements Agent` 提供需求分析与需求文档原始产物
- `agent/Architecture Agent` 提供架构设计原始产物
- `agent/Coding Agent` 用于后续代码生成链路
- `agent/TestAgent` 用于补充测试规划与测试用例阶段

### 2. 当前主产物模型

平台主面板当前固定展示以下 4 类主产物：

- `PRD`
- `UI`
- `Architecture`
- `API`

说明：

- 这 4 个是平台主视图，不等于 Agent 原始文件全集
- Agent 会生成更多原始文件，后端负责把原始文件映射、汇总成这 4 个主产物
- 原始文件与主产物的映射正在逐步透明化到前端
- 主产物面板到底该显示哪些文件，统一以 [docs/artifact-panel-contract.md](/Users/imnight/code/iSoftDevAgents/docs/artifact-panel-contract.md) 为准；后端唯一归类入口是 `agent/platform/app/services/agent_output_contracts.py` 里的 `build_main_panel_contract(...)`

### 3. 当前步骤与调试能力

当前任务执行过程中，系统会记录：

- 当前任务状态
- 步骤列表
- 步骤耗时
- Token 使用状态
- 步骤产出文件
- 当前正在运行的 Agent 阶段

为方便调试，平台后端支持开启 Agent 日志直出：

```bash
cd agent/platform
uv sync
env ISOFTDEVAGENTS_AGENT_DEBUG_STDIO=1 uv run --no-sync python -m uvicorn app.main:app --host 127.0.0.1 --port 9010
```

开启后，后端终端会直接看到类似：

```text
[Requirements Agent stdout] ...
[Architecture Agent stderr] ...
```

开发模式建议优先使用 `./run_dev.sh`。
这个脚本已经排除了 `data/` 和 `tests/` 下的文件变动，避免 Agent 生成文件时触发 `uvicorn --reload` 自动重启。

### 4. 当前前端体验方向

当前前端已经围绕以下方向整改：

- 任务 Step 卡片固定在当前时间线末尾显示
- 中间产物支持折叠查看
- Markdown 内容按富样式预览，而不是裸文本
- 代码类内容按代码预览方式展示，而不是统一纯文本
- Step Outputs 不再在聊天卡片里内联展开文件正文，改为点击文件后在 `Code Workspace` 中查看对应原始文档或代码文件
- `UI Draft` 的展示语义正在从“伪代码文件”纠正为“文档型草稿”
- `Code Workspace` 已支持 `Docs` 视图，可直接查看 Requirements/Architecture Agent 的原始产物文件
- 用户现在需要先完成注册或登录，前端才会开放首页与项目页

## 项目结构

```text
iSoftDevAgents/
├── README.md
├── agent/
├── docs/
├── frontend/
├── output/
└── var/
```

## 运行方式

### 五段 Agent 冒烟联调

当前仓库新增了一个面向五子棋需求的统一 CLI 联调入口：

```bash
python3 scripts/run_gomoku_five_agent_smoke.py
```

这条命令会按以下顺序串联真实或半真实 Agent：

1. `Requirements Agent analysis`
2. `Requirements Agent full`
3. `Architecture Agent`
4. `Coding Agent`
5. `UI Agent`
6. `TestAgent`

默认运行输出会落到：

```text
var/gomoku-five-agent/<run_id>/
```

调试记录会追加到：

```text
docs/gomoku-five-agent-debug-record.md
```

### 前端

运行环境：

- Node.js `24`
- `pnpm`

安装与启动：

```bash
cd frontend
pnpm install
pnpm --filter @workspace/ai-design-platform run dev
```

默认访问地址：

```text
http://localhost:9080/
```

常用命令：

```bash
cd frontend
pnpm run typecheck
pnpm run build
```

### 平台后端

运行环境：

- Python `3.10+`

安装与启动：

```bash
cd agent/platform
uv sync
./run_dev.sh
```

健康检查地址：

```text
http://localhost:9010/api/healthz
```

### 配置分层

当前项目建议明确分成三套配置：

1. 本地直接开发：
   - 使用 `agent/platform/.env.local`
   - 适合放你自己电脑上的绝对路径、调试日志路径、本机 Python 路径
2. 本地 Docker 测试：
   - 使用 `deploy/docker/backend.env` 或 `deploy/docker/backend.env.local`
   - 只放“容器里也成立”的变量，不要放宿主机绝对路径
3. 服务器正式部署：
   - 使用服务器私有 env 文件，或面板 / systemd / CI 注入环境变量
   - 不要依赖仓库里的 `agent/platform/.env.local`

### 本地直接开发

平台后端启动时会读取：

- `agent/platform/.env`
- `agent/platform/.env.local`

适合放的变量：

```bash
ISOFTDEVAGENTS_LLM_BASE_URL=https://api.modelverse.cn/v1
ISOFTDEVAGENTS_LLM_MODEL=gpt-5.4
ISOFTDEVAGENTS_LLM_API_KEY=your-secret-key
ISOFTDEVAGENTS_ENABLE_REAGENT=1
ISOFTDEVAGENTS_ENABLE_ARCH_AGENT=1
ISOFTDEVAGENTS_AGENT_TIMEOUT=3600
ISOFTDEVAGENTS_ANALYSIS_AGENT_TIMEOUT=3600
ISOFTDEVAGENTS_GENERATION_AGENT_TIMEOUT=3600
ISOFTDEVAGENTS_ARCHITECTURE_AGENT_TIMEOUT=3600
ISOFTDEVAGENTS_UI_AGENT_TIMEOUT=3600
ISOFTDEVAGENTS_CODING_AGENT_TIMEOUT=3600
ISOFTDEVAGENTS_TEST_AGENT_TIMEOUT=3600
ISOFTDEVAGENTS_REAGENT_PYTHON_BIN=/absolute/path/to/python
```

### Docker 部署 / 本地 Docker 测试

当前仓库已经补了一套适合单机服务器的 Docker Compose 部署方式：

- `docker-compose.yml`
- `deploy/docker/backend.Dockerfile`
- `deploy/docker/web.Dockerfile`
- `deploy/docker/nginx.conf`
- `deploy/docker/backend.env.example`
- `deploy/docker/run-local.sh`

推荐形态：

- `backend` 容器：运行 FastAPI + Agent 调度
- `web` 容器：提供前端静态页面，并通过 Nginx 反向代理 `/api`
- `platform-data` 卷：持久化 `agent/platform/data`
- `platform-log` 卷：持久化 `agent/platform/log`

本地直接启动：

```bash
./deploy/docker/run-local.sh -d
```

这个脚本只会读取：

- `deploy/docker/backend.env`
- `deploy/docker/backend.env.local`

如果这两个文件都不存在，就只使用 `docker-compose.yml` 里的默认值和你当前 shell 已经 export 的变量。

默认访问地址：

```text
http://localhost:9080/
```

停止：

```bash
docker compose down
```

如果要在本地 Docker 测试，建议做法：

1. 复制 `deploy/docker/backend.env.example` 为 `deploy/docker/backend.env`
2. 把真实的 LLM Key、模型、超时、调试开关填进去
3. 不要写 `/Users/...` 这类宿主机路径
4. 运行 `./deploy/docker/run-local.sh -d`

如果要部署到服务器，建议做法：

1. 复制 `deploy/docker/backend.env.example` 为你自己的私有 env 文件
2. 把真实的 LLM Key 和 Agent 开关填进去
3. 通过 `docker compose --env-file /path/to/backend.env up -d --build` 启动
4. 或者通过环境变量 / 面板把这些值注入 `docker compose`

说明：

- 当前后端仍依赖本地 SQLite 与运行目录，所以最适合“单机 Compose”部署
- 在没有把 SQLite 换成独立数据库之前，不建议直接上多实例
- Docker 容器里已经显式清空了 Agent 的宿主机 Python 路径配置，避免误读本机 `.env`
- `deploy/docker/backend.env` 应该视为私有文件，不要提交到仓库
- 不要把真实密钥提交到仓库
- `ISOFTDEVAGENTS_AGENT_DEBUG_STDIO=1` 会增加后端终端日志量
- `ISOFTDEVAGENTS_ANALYSIS_AGENT_TIMEOUT` 和 `ISOFTDEVAGENTS_GENERATION_AGENT_TIMEOUT` 当前默认已经提升到 `3600` 秒，用于给真实 Agent 更长的执行窗口
- `ISOFTDEVAGENTS_ARCHITECTURE_AGENT_TIMEOUT`、`ISOFTDEVAGENTS_UI_AGENT_TIMEOUT`、`ISOFTDEVAGENTS_CODING_AGENT_TIMEOUT` 会覆盖各自步骤的默认生成超时
- `ISOFTDEVAGENTS_TEST_AGENT_TIMEOUT` 会覆盖测试阶段的默认超时
- 现在的超时语义是“每个主 Agent 步骤单独计时”，不是整轮任务共用一个小时
- `ISOFTDEVAGENTS_REAGENT_PYTHON_BIN` 用于显式指定 Requirements Agent 的 Python 解释器
- `agent/platform/.venv` 现在由 `uv sync` 自动管理，也建议把它作为 `Requirements Agent` 的 Python 环境，避免 3.11/3.12 混用导致 `crewai` / `numpy` 导入失败
- `Requirements Agent` 当前依赖 `prompt_toolkit` 来同时支持“本地终端阻塞输入”和“平台前端反馈注入等待输入”两种运行方式
- `Requirements Agent` 在等待人工反馈时，不会继续消耗自己的运行超时预算
- UI Agent 当前仍按“单页 UI 原型”合同运行；如果失败，优先查看 `agent/platform/data/agent-debug/ui-agent/` 里的调试包
- 平台内部当前保留一套统一模型名，再由桥梁层按 Agent 运行时做最后转换：CrewAI / LiteLLM 类 Agent 继续使用带前缀格式，UI 这类直连 OpenAI SDK 的 Agent 会自动改成兼容接口更容易接受的裸模型名
- `TestAgent` 当前也走 CrewAI / LiteLLM 风格模型名适配，所以会自动复用带前缀的统一模型名
- 平台运行 `Requirements Agent` 时，会显式把 `CREWAI_TRACING_ENABLED=false`、`OTEL_SDK_DISABLED=true`、`CREWAI_DISABLE_TELEMETRY=true`、`CREWAI_DISABLE_TRACKING=true` 压到运行环境里，减少 tracing 401、DNS 失败、重试导出这类误导性日志

## 当前支持的后端接口

- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{id}`
- `POST /api/upload`
- `POST /api/projects/{id}/generate`
- `GET /api/projects/{id}/messages`
- `POST /api/projects/{id}/messages`
- `GET /api/projects/{id}/tasks`
- `GET /api/projects/{id}/task/current`
- `GET /api/projects/{id}/statistics`
- `GET /api/projects/{id}/steps`
- `POST /api/projects/{id}/confirm`
- `POST /api/projects/{id}/modify`
- `POST /api/projects/{id}/tasks/{task_id}/cancel`
- `POST /api/projects/{id}/tasks/{task_id}/retry`
- `GET /api/projects/{id}/artifacts/{artifact_type}`
- `GET /api/projects/{id}/versions`
- `WS /api/projects/{id}/ws`

## 已知影响与注意事项

### 1. 开启真实 Agent 的影响

- 后端运行时间会显著长于模板模式
- 对本地 Python 环境、依赖和模型配置更敏感
- 需要更详细的日志和更长的超时配置

### 2. 开启调试日志的影响

- 终端输出会明显变多
- 更利于排查是哪个 Agent、哪个阶段、哪个文件生成失败

### 3. Artifact 视图与代码工作区的关系

- Artifact 主面板用于查看审批文档
- Code Workspace 用于查看真实代码文件树
- 两者相关，但不应该混为同一层数据

## 变更记录

### 2026-04-03

- 完成 `Requirements Agent` 人工反馈桥梁整改，平台前端提交的反馈现在会直接送进 Agent 正在等待的输入流
- 保留本地终端阻塞输入体验，同时让平台模式支持同一套 `multiline_input()` 入口
- 修复需求草稿阶段等待人工反馈时仍然消耗总超时预算的问题
- 默认 Agent 超时窗口调整为 `3600` 秒，便于完整跑通需求阶段到 `SRS.md`
- 修复需求阶段过程卡片展示滞后问题，进入等待和恢复执行时会主动刷新状态文案
- 修复 SRS 单章输出偶发使用旧 JSON 形状时导致 `SRS.md` 落盘失败的问题，新增章节归一化兼容
- 默认关闭 Requirements Agent 运行中的 CrewAI tracing 与遥测导出，避免 `telemetry.crewai.com` 带来的 401、网络重试和域名解析失败噪音日志

### 2026-04-01

本轮已确认或正在落地的调整：

- 优先接入真实 `Requirements Agent`，而不是直接走伪造分析结果
- `Requirements Agent` 已开始改为由 backend 进程内直接加载执行，不再依赖 subprocess 桥接来跑主流程
- 后端增加 Agent 调试日志镜像能力，可在服务终端直接查看 Requirements/Architecture Agent 的运行输出
- 后端新增 CrewAI LLM I/O 调试补丁，开启后可直接在服务终端看到每次模型输入输出
- Requirements Agent 的 `feature_tree.md` 解析兼容更多格式，降低“文件已生成但解析失败”的概率
- 前端任务时间线中的 Step 卡片改为固定贴在当前轮次末尾显示
- 前端步骤输出与中间产物查看能力持续增强
- `Code Workspace` 新增 `Docs` 视图，用户可以直接查看 `feature_tree.md`、`survey.md`、`draft_event_list.md`、`draft_context_diagram.md` 等原始 Agent 文档
- 聊天区 `Step Outputs` 卡片已改为“文件列表 -> 点击打开 Code Workspace”，不再在任务卡片内挤压显示原文件内容
- `process_log` 现在会实时累计当前阶段已识别的 `outputFiles`，前端优先使用日志自身文件列表展示步骤产物，避免把第一步需求分析文件错误复用到后续产物生成步骤
- 产物生成阶段的实时输出现在会过滤前一步已经展示过的文件，避免在首次确认后继续把 `feature_tree.md` 这类分析阶段文件混入当前生成中的 Step Outputs
- 相同文件名的流式日志会被去重，`Success/OK` 类状态会翻译为“已生成 xxx 文件”，减少“文件已写好但界面还停留在上一条生成中”的滞后感
- 模块确认后的 Requirements 阶段不再跑重型 `full` 流程，改为平台专用 `drafts` 流程，只生成当前主产物需要的需求草稿文件，避免重复产出、长时间卡住和无法结束
- 第二阶段会把已确认的 `feature_tree.md` 作为种子文件延续到新版本 `Code Workspace -> Docs`，但不会再把它误显示为当前阶段“新生成文件”
- 第二阶段 Requirements drafts 生成过程中，原始文档现在会按“生成一个、登记一个、显示一个”的方式实时进入 `Code Workspace -> Docs`，不再必须等整批文件全部完成后才可见
- 聊天区 `Step Outputs` 文件卡片已移除重复的“Open in Code Workspace”说明文案，只保留点击打开行为，减少视觉噪音
- `Generating core artifacts` 阶段现在会在 Requirements drafts 完成后明确切换到 `Architecture Agent` 的接力状态，避免界面长时间停留在最后一个需求文件上，造成“重复生成同一文件”的错觉
- 模块确认后的第二阶段现在被正式拆成两个独立阶段：`Generating requirements drafts` 与 `Generating architecture draft`，后端事件、步骤记录和前端 phase 模型保持一致
- Architecture Agent 现在支持从真实 `analysis_task_output.txt` 回收出基础架构草稿，避免因为组件设计文件缺失而把整轮任务直接打成失败
- 右侧 Artifact 面板在任务运行且主文档尚未落盘时，优先显示生成态而不是一直卡在 `Loading artifact...`
- README 升级为仓库顶层版本说明与变更记录入口

影响：

- 联调时更容易定位真实 Agent 是否被调用
- 聊天区纵向空间更稳定，长文档统一在 `Code Workspace` 中查看，避免任务卡片被原始文件正文撑开
- 步骤卡片里的文件列表会和当前日志阶段保持一致，运行中的 `Generating ...` 日志不再错误显示第一步 `feature_tree.md/project_description.md`
- `Requirements Agent` 的错误、超时、部分产物回收现在可以直接在 backend 内处理，日志链路更完整
- 任务过程对用户更可见
- Requirements/Architecture 的原始文档不再只能从聊天步骤里找，用户可以在统一工作区直接浏览
- 用户在第一次确认模块后，第二阶段看到的文件集合会更接近真实需求草稿产物，且不会被 `full` 流程生成的大量 BRD/SRS 中间文件干扰
- `Code Workspace -> Docs` 在实时生成阶段会优先展示最新的原始 Agent 文档版本，因此用户能边生成边查看，而不是只能看到旧版本或空列表
- 用户现在能明确区分“需求草稿还在生成”还是“已经切到架构草稿阶段”，不会再把 Architecture Agent 的长耗时误判成 Requirements Agent 死循环
- 即使 Architecture Agent 只产出分析文本，平台也能给出可审阅的 Architecture 草稿，降低整轮任务中途失败概率
- 后续每次提交都必须补充此处变更记录，说明新增功能和影响范围

## README 维护规则

从当前版本开始，后续每次提交任何功能、流程、接口、Agent 集成、前端展示、配置方式的变动时，都必须同步更新根目录 [README.md](/Users/imnight/code/iSoftDevAgents/README.md)。

至少要更新以下内容中的一项或多项：

- `当前版本概览`
- `当前版本内容`
- `已知影响与注意事项`
- `变更记录`

新增变更记录时，必须写清楚：

- 改了什么
- 新支持了什么
- 对前端、后端、Agent、配置或用户流程有什么影响

## 参考文档

- [agent/platform/README.md](/Users/imnight/code/iSoftDevAgents/agent/platform/README.md)
- [前端后端API设计.md](/Users/imnight/code/iSoftDevAgents/docs/前端后端API设计.md)
- [前端收敛与lib处理方案.md](/Users/imnight/code/iSoftDevAgents/docs/前端收敛与lib处理方案.md)
- [requirements-agent-debug-checklist.md](/Users/imnight/code/iSoftDevAgents/docs/requirements-agent-debug-checklist.md)
- [gomoku-agent-smoke-test.md](/Users/imnight/code/iSoftDevAgents/docs/gomoku-agent-smoke-test.md)
