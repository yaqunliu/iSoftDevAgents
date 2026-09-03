# 前端中文 → 英文 改造计划（en-plan）

适用范围：`frontend/artifacts/ai-design-platform`（workspace 中唯一的前端应用，`frontend/scripts` 只有一个 `hello.ts`，无文案）。

---

## 1. 现状结论（先看这段）

**这个项目已经有完整的 i18n 体系，不需要从零搭建。**

- `src/i18n.ts` 用 i18next + react-i18next，内置 `en` / `zh` 两套完整资源（各约 343 个 key）。
- `src/lib/i18n-extra-locales.ts` 额外提供 `ja / ko / ru / fr / de`。
- `src/lib/locale.ts` 定义 7 种语言，`normalizeSupportedLocale()` **在无 localStorage 记录时默认返回 `en`**，`fallbackLng` 也是 `en`。
- `src/components/LanguageToggle.tsx` 提供语言下拉框，选择结果写入 `localStorage["isoftdevagents.locale"]`。
- 后端也支持 locale：`src/hooks/use-api.ts:557` 的 `currentBackendLocale()` 会把 `en/zh` 随请求发给 `agent/platform`（对应 `agent/platform/app/localization.py`）。

**所以问题不是"没有英文"，而是有 4 类中文从 i18n 体系里漏了出来。**在英文界面下依然会看到中文的，只有下面第 2 节列出的这些位置。

---

## 2. 问题分类

| 类别 | 说明 | 影响 | 数量 |
|---|---|---|---|
| **A** | `t(key, { defaultValue: "中文" })` 但该 key 在任何语言资源里都不存在 | **英文界面直接显示中文**（ja/ko/ru/fr/de 同样受害，因为回退到 en 也没有） | 18 个 key |
| **B** | JSX / toast 里硬编码中文字符串，完全没走 `t()` | **所有语言都显示中文** | 11 处 |
| **C** | `src/pages/auth.tsx` 整页未接入 i18n | **登录/注册页全中文** | 约 22 条文案 |
| **D** | 纯函数里拼接的中文（`line-diff.ts`） | 版本对比面板显示中文 | 1 处 |
| **E** | 中文代码注释 | 不影响页面，可选处理 | 约 40 个文件 |
| **F** | 后端/Agent 返回的中文内容（`taskName`、消息正文、文档正文） | 取决于后端 locale，非本次前端改造范围 | — |

---

## 3. 类别 A：补齐缺失的 i18n key（最高优先级）

这些 key 在 `resources.en` / `resources.zh` / `extraLocaleResources` **三处都不存在**，导致代码里的中文 `defaultValue` 直接渲染出来。

### 3.1 需要新增的 key 与英文文案

在 `src/i18n.ts` 的 `resources.en.translation` 中新增：

```ts
"chat.activeAgent": "Active Agent",

"artifact.historicalVersionNotice":
  "You are viewing historical version v{{version}}. Editing here creates a new version instead of overwriting the old record.",

"code.historyVersionBanner":
  "You are viewing historical version v{{version}}. Saving manually creates a new version instead of overwriting the old one.",
"code.loadingDocs": "Loading documents...",
"code.saveAsNewVersionFromHistory": "Save as new version",
"code.saveDraft": "Save draft",

"history.loading": "Loading version history...",
"history.sourceVersion": "Source version v{{version}}",
"history.restoredFromVersion": "Restored from v{{version}}",
"history.snapshotCounts":
  "{{artifacts}} artifacts / {{agentFiles}} stage files / {{files}} workspace files / {{modules}} modules",
"history.changeSummary": "{{added}} added / {{modified}} modified / {{deleted}} deleted",

"history.versionKind.generation": "Generation",
"history.versionKind.requirementsReview": "Requirements review",
"history.versionKind.architectureReview": "Architecture review",
"history.versionKind.artifactEdit": "Artifact edit",
"history.versionKind.fileEdit": "File edit",
"history.versionKind.codeEdit": "Code edit",
"history.versionKind.modify": "Modify",
"history.versionKind.rollback": "Rollback",
"history.versionKind.regenerate": "Regenerate",
```

同时在 `resources.zh.translation` 补上对应中文（把代码里现有的 `defaultValue` 原文搬过去），这样切回中文时行为不变：

| key | zh 文案（取自现有 defaultValue） |
|---|---|
| `chat.activeAgent` | `当前 Agent` |
| `artifact.historicalVersionNotice` | `当前看到的是历史版本 v{{version}}。如果在这里继续编辑，系统会创建一个新版本，不会覆盖旧记录。` |
| `code.historyVersionBanner` | `当前查看的是历史版本 v{{version}}。手动保存不会覆盖旧版本，而是创建一个新的版本。` |
| `code.loadingDocs` | `正在加载文档列表...` |
| `code.saveAsNewVersionFromHistory` | `基于该历史版本创建新版本` |
| `code.saveDraft` | `保存草稿` |
| `history.loading` | `正在加载版本历史...` |
| `history.sourceVersion` | `来源版本 v{{version}}` |
| `history.restoredFromVersion` | `从 v{{version}} 恢复` |
| `history.snapshotCounts` | `{{artifacts}} 制品 / {{agentFiles}} 阶段文件 / {{files}} 工作区文件 / {{modules}} 模块` |
| `history.changeSummary` | `新增 {{added}} / 修改 {{modified}} / 删除 {{deleted}}` |
| `history.versionKind.*` | `生成` / `需求确认` / `架构确认` / `制品编辑` / `文件编辑` / `代码编辑` / `修改生成` / `回滚恢复` / `重新生成` |

### 3.2 清理代码里的中文 defaultValue

新增 key 之后，把调用点的中文 `defaultValue` 全部改成英文（作为兜底），或直接删掉 `defaultValue`。涉及：

- `src/components/ArtifactViewer.tsx:349`
- `src/components/CodeWorkspaceSheet.tsx:794, 795, 914, 1006, 1056`
- `src/components/VersionHistorySidebar.tsx:13-21, 253, 314, 322, 329, 338`

### 3.3 顺带清理：key 已存在但 defaultValue 仍是中文（死代码，但会误导）

这 3 处 key 在 en/zh 里都有，中文兜底永远走不到，建议一并改成英文：

- `src/components/CodeWorkspaceSheet.tsx:781` → `code.historySaveHint`
- `src/components/CodeWorkspaceSheet.tsx:839` → `code.pendingVersionBadge`
- `src/components/VersionHistorySidebar.tsx:399` → `history.emptyPendingPreview`

### 3.4 可选：补 ja/ko/ru/fr/de

`fallbackLng: "en"` 意味着补完 en 之后，其它 5 种语言会自动显示英文而不再是中文——**已经解决了"漏中文"问题**。是否在 `src/lib/i18n-extra-locales.ts` 里补齐这 21 个 key 的其它语种翻译，是独立的完善项，不阻塞本次改造。

---

## 4. 类别 B：硬编码中文（无 `t()`）

### 4.1 `src/components/MermaidDiagram.tsx`

| 行 | 现状 | 处理 |
|---|---|---|
| 137 | `图表语法暂时无法渲染，下面保留原始 Mermaid 内容，方便继续排查。` | 新增 `mermaid.renderErrorHint` → `"This diagram could not be rendered. The raw Mermaid source is kept below for troubleshooting."` |
| 149 | `正在渲染 Mermaid 图表…` | 新增 `mermaid.rendering` → `"Rendering Mermaid diagram…"` |

该组件目前没有 `useTranslation()`，需要引入。

### 4.2 `src/components/CodeWorkspaceSheet.tsx`

| 行 | 现状 | 处理 |
|---|---|---|
| 306, 365, 974, 1031 | `草稿` 徽标（4 处重复） | 新增 `code.draftBadge` → `"Draft"` |
| 852 | `提交当前修改 ({projectDraftCount})` | 新增 `code.commitDrafts` → `"Commit changes ({{count}})"` |
| 769 | toast title `已提交当前修改` | 新增 `code.commitSuccessTitle` → `"Changes committed"` |
| 770 | toast description 模板字符串 `已创建版本 v${...}，共提交 ${...} 个文件。` | 新增 `code.commitSuccessDescription` → `"Created version v{{version}} with {{count}} file(s) committed."`，用 i18next 插值替换模板字符串 |

注意 770 行当前是 JS 模板字符串，改造时要换成 `t("code.commitSuccessDescription", { version: result.newVersion, count: result.committedPaths.length })`。

### 4.3 `src/pages/home.tsx`

| 行 | 现状 | 处理 |
|---|---|---|
| 271 | `currentUser?.name ?? "当前用户"` | 新增 `home.currentUser` → `"Current user"` |
| 284 | 按钮文字 `退出` | 新增 `home.logout` → `"Log out"` |

`home.tsx` 已经有 `t`，直接替换即可。

---

## 5. 类别 C：`src/pages/auth.tsx` 整页 i18n 化

这一页**完全没有引入 `useTranslation`**，是中文暴露最集中的地方。需要新增一整组 `auth.*` key。

### 5.1 建议的 key 表

```ts
// 标题与说明（随 mode 切换）
"auth.login.title": "Sign in to your account",
"auth.login.description": "Enter your email and password to continue.",
"auth.login.submit": "Sign in",
"auth.register.title": "Create your account",
"auth.register.description":
  "Create a basic account first, then you can access the home page and your projects.",
"auth.register.submit": "Sign up and continue",

// 左侧介绍栏
"auth.intro.title": "Sign in to your Agent IDE with a real account",
"auth.intro.description":
  "For now this is basic sign-up and sign-in only — no captcha, no password recovery. The goal is to get the core entry flow working.",
"auth.intro.step1.title": "1. Create an account",
"auth.intro.step1.description": "Create a basic account with a username, email, and password.",
"auth.intro.step2.title": "2. Sign in",
"auth.intro.step2.description": "The home page and project pages unlock after a successful sign-in.",
"auth.intro.step3.title": "3. Sign out safely",
"auth.intro.step3.description":
  "Signing out clears the local session token and returns you to this page.",

// Tab / 表单
"auth.tab.login": "Sign in",
"auth.tab.register": "Sign up",
"auth.field.name": "Username",
"auth.field.namePlaceholder": "e.g. Jane Doe",
"auth.field.email": "Email",
"auth.field.password": "Password",
"auth.field.passwordPlaceholder": "At least 6 characters",

// 校验与错误
"auth.error.nameRequired": "Username is required",
"auth.error.invalidEmail": "Please enter a valid email address",
"auth.error.passwordTooShort": "Password must be at least 6 characters",
"auth.error.submitFailed": "Submission failed. Please try again later.",

// 底部提示
"auth.switchToLogin": "Already have an account? Switch to sign in.",
"auth.switchToRegister": "Don't have an account? Switch to sign up.",
"auth.checkingSession": "Checking your current session...",
```

### 5.2 对应改造点

| 行 | 原中文 | 目标 key |
|---|---|---|
| 45 | `注册并进入` / `登录进入` | `auth.register.submit` / `auth.login.submit` |
| 46 | `创建你的账号` / `登录你的账号` | `auth.register.title` / `auth.login.title` |
| 49-50 | 两段说明 | `auth.register.description` / `auth.login.description` |
| 56 | `用户名不能为空` | `auth.error.nameRequired` |
| 59 | `邮箱格式不对` | `auth.error.invalidEmail` |
| 62 | `密码至少 6 位` | `auth.error.passwordTooShort` |
| 93 | `提交失败，请稍后重试` | `auth.error.submitFailed` |
| 108 | `用真实账号进入你的 Agent IDE` | `auth.intro.title` |
| 111 | 介绍段落 | `auth.intro.description` |
| 117-118 | `1. 注册账号` + 说明 | `auth.intro.step1.*` |
| 121-122 | `2. 登录进入` + 说明 | `auth.intro.step2.*` |
| 125-126 | `3. 安全退出` + 说明 | `auth.intro.step3.*` |
| 142 | Tab `登录` | `auth.tab.login` |
| 152 | Tab `注册` | `auth.tab.register` |
| 164 | label `用户名` | `auth.field.name` |
| 165 | placeholder `例如：张三` | `auth.field.namePlaceholder` |
| 170 | label `邮箱` | `auth.field.email` |
| 180 | label `密码` | `auth.field.password` |
| 185 | placeholder `至少 6 位` | `auth.field.passwordPlaceholder` |
| 202 | 切换提示 | `auth.switchToLogin` / `auth.switchToRegister` |
| 208 | `正在检查当前登录状态...` | `auth.checkingSession` |

**注意校验函数**：`validateForm()` 目前直接返回中文字符串存进 `errorMessage` state。改造时应改为返回 **i18n key**，在渲染处再 `t(errorKey)`；否则切换语言后已显示的错误提示不会跟着变。这是本次改造里唯一需要改变数据流的地方。

### 5.3 建议顺带加上语言切换器

登录页目前没有 `<LanguageToggle />`。用户在登录前无法切语言（只能靠 localStorage 或默认 en）。建议在 auth 页右上角也放一个，与 `home.tsx` 一致。

---

## 6. 类别 D：`src/lib/line-diff.ts:129`

```ts
content: `... 已省略 ${index - previousKeptIndex - 1} 行未改内容 ...`,
```

`line-diff.ts` 是纯函数，不应该依赖 i18n。**推荐做法**：把行数以结构化字段返回，由渲染层格式化。

1. 修改 `LineDiffRow` 的 `skipped` 分支类型：
   ```ts
   | {
       kind: "skipped";
       oldLineNumber: null;
       newLineNumber: null;
       content: string;        // 保留兼容，可填英文
       skippedCount: number;   // 新增
     };
   ```
2. 唯一消费方 `src/components/VersionHistorySidebar.tsx:141` 改为渲染 `t("history.skippedLines", { count: row.skippedCount })`。
3. 新增 key：`"history.skippedLines": "... {{count}} unchanged lines skipped ..."`。

（替代方案：给 `buildLineDiffRows` 传入 `t`。不推荐，会污染纯函数签名。）

---

## 7. 类别 E：中文代码注释（可选，建议单独一个 commit）

约 40 个文件含中文注释（`设计注释：` / `教学注释：` / `接口注释：` 前缀）。中文字符最集中的：

`src/lib/artifact-view-model.ts`(414) · `src/lib/execution-stats.ts`(385) · `src/lib/code-workspace-list.ts`(336) · `src/lib/confirmation-card-state.ts`(313) · `src/hooks/use-api.ts`(312) · `src/lib/chat-card-state.ts`(258) · `src/lib/step-output-model.ts`(179) · `src/lib/project-websocket-events.ts`(172) ……

**这些不影响页面显示。** 决策建议：

- 如果目标只是"页面上没有中文" → **跳过本节**。
- 如果目标是"代码库全英文" → 单独立一个 PR 处理，与文案改造分开，避免 diff 混杂难以 review。注释里包含大量设计意图说明，翻译时要保留原意，不要简化删除。

---

## 8. 类别 F：后端返回的中文（超出前端改造范围，但需知晓）

即使前端 100% 英文化，以下内容仍可能是中文：

1. **Agent 任务名与消息正文** —— `ChatArea.tsx:553/559/580` 直接渲染 `metadata.taskName` 和 `message.content`；`step-output-model.ts` 同样透传。这些由 `agent/platform` 产出。
2. **生成的文档正文** —— PRD / SRS / feature_tree 等制品内容，Agent 按 locale 生成。
3. **制品文件标题** —— `src/lib/artifact-file-labels.ts` 已做映射：已知文件名走前端 i18n key，未知文件名回退到后端原始 label（可能是中文）。这个设计是对的，新增制品类型时记得往 `ARTIFACT_FILE_LABEL_KEYS` 里补映射。

前端侧已经把 `locale` 传给后端（`use-api.ts:557` 及 1100/1109/1134/1175/1193/1739 行的调用点），所以**新建的项目在英文模式下应当产出英文内容**。历史项目里已存的中文内容不会自动改变。

---

## 9. 明确不改动的部分

| 内容 | 位置 | 原因 |
|---|---|---|
| `{ value: "zh", label: "中文" }`、`日本語`、`한국어` 等 | `src/lib/locale.ts:13-19` | 语言选择器按惯例用各语言的自称名，不应译成 "Chinese" |
| `"language.chinese": "中文"` | `src/i18n.ts` en 资源内 | 同上 |
| `resources.zh.translation` 全部中文 | `src/i18n.ts:549-922` | 中文语言包，是功能不是缺陷 |
| `extraModuleTranslations` 的 ja/ko/ru/fr/de | `src/lib/module-translations-extra.ts` | 其它语言包 |
| 测试用例里的中文 fixture | `src/lib/*.test.ts` | 见下节 |

---

## 10. 测试影响评估

前端测试是 `node:test` 风格的 `src/lib/*.test.ts`（`package.json` 里**没有配 test script**，需用 `node --test --experimental-strip-types` 或 `tsx` 手动跑）。

含中文断言的测试：

| 文件 | 断言内容 | 本次改造是否影响 |
|---|---|---|
| `runtime-log-i18n.test.ts` | 断言 `chat.logFrame.runtime.*` 系列 key **不存在**于 en/zh | ✅ 不影响——本次新增的 21 个 key 与之无交集 |
| `interaction-guidance.test.ts` | 断言 zh 语言下的提示文案 | ✅ 不影响——不修改 `resources.zh` 已有内容 |
| `artifact-file-labels.test.ts` | 断言中文 fallback label 行为 | ✅ 不影响 |
| `artifact-view-model.test.ts` / `step-output-model.test.ts` / `process-log-frame.test.ts` / `mermaid-detection.test.ts` | 中文 fixture 数据 | ✅ 不影响——模拟后端返回，与 UI 文案无关 |
| `live-query-interval.test.ts` / `project-websocket-url.test.ts` | 中文 **测试名** | ✅ 不影响，可选一并译成英文 |

**结论：本计划不会破坏任何现有测试。** 唯一需要新增测试的是第 6 节 `line-diff.ts` 的类型变更（`line-diff.ts` 当前无测试文件，建议补一个）。

---

## 11. 执行顺序

分成 4 个独立提交，每步都可单独验证：

### Step 1 — 补齐缺失 key（类别 A）
- 改 `src/i18n.ts`：en + zh 各新增 21 个 key
- 改 5 个调用点文件，把中文 `defaultValue` 换成英文
- **收益最大、风险最低**，一步就消掉了大部分英文界面下的中文泄漏

### Step 2 — 硬编码文案 i18n 化（类别 B + D）
- `MermaidDiagram.tsx`（需新引入 `useTranslation`）
- `CodeWorkspaceSheet.tsx`（含 toast 模板字符串改插值）
- `home.tsx`
- `line-diff.ts` + `VersionHistorySidebar.tsx`（类型变更）
- 新增约 10 个 key

### Step 3 — auth 页整页 i18n 化（类别 C）
- 新增约 28 个 `auth.*` key
- 引入 `useTranslation`
- **重构 `validateForm()` 返回 key 而非文案**
- 可选：加上 `<LanguageToggle />`

### Step 4（可选）— 中文注释英文化（类别 E）
- 独立 PR，不与文案改造混在一起

---

## 12. 验证方法

```bash
cd frontend/artifacts/ai-design-platform

# 1. 类型检查
pnpm run typecheck

# 2. 跑现有单测
node --test --experimental-strip-types 'src/lib/*.test.ts'

# 3. 构建
pnpm run build
```

### 静态扫描（改完每一步都跑一遍）

```bash
# A. 排除 zh 资源、其它语言包、测试后，src 下不应再有中文（除注释外）
for f in $(find src -type f \( -name '*.ts' -o -name '*.tsx' \) \
    -not -name 'i18n.ts' \
    -not -path '*i18n-extra-locales*' \
    -not -path '*module-translations-extra*' \
    -not -name '*.test.ts'); do
  out=$(grep -nP '[\x{4e00}-\x{9fff}]' "$f" | grep -vP '^\s*\d+:\s*(\*|//|/\*)')
  [ -n "$out" ] && { echo "===== $f"; echo "$out"; }
done
# 期望：Step 3 完成后只剩 src/lib/locale.ts 的语言自称名

# B. i18n.ts 的 en 资源块内不应有中文（"language.chinese" 除外）
awk '/^  en: \{/,/^  zh: \{/' src/i18n.ts | grep -nP '[\x{4e00}-\x{9fff}]'

# C. 不应再存在中文 defaultValue
perl -0777 -ne 'while (/defaultValue\s*:\s*"([^"]*[\x{4e00}-\x{9fff}][^"]*)"/gs) { print "$ARGV: $1\n" }' \
  $(find src -name '*.ts' -o -name '*.tsx' | grep -v test)
# 期望：无输出
```

### 手动验证

1. 清空 `localStorage["isoftdevagents.locale"]`，刷新 → 界面应为纯英文。
2. 逐页走查：`/auth`（登录 + 注册两个 tab、各校验错误）、`/`（首页、用户区、退出按钮）、项目页（聊天区、制品面板、Mermaid 渲染中/失败态、版本历史侧栏含 diff 与"已省略 N 行"、代码工作区含草稿徽标/提交按钮/历史版本 banner/保存 toast）。
3. 切到中文 → 所有文案应恢复中文，无回归。
4. 切到日语/法语 → 应显示英文（fallback），**不应出现中文**。

---

## 13. 工作量估算

| 步骤 | 涉及文件 | 新增 key | 预估 |
|---|---|---|---|
| Step 1 | 6 | 21 × 2 语言 | 小 |
| Step 2 | 5 | ~10 × 2 语言 | 小 |
| Step 3 | 2 | ~28 × 2 语言 | 中（含 `validateForm` 重构） |
| Step 4 | ~40 | — | 大（可选） |

Step 1-3 合计：新增约 59 个 key，改动 12 个文件。
