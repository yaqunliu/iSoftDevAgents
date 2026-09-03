# iSoftDevAgents 单机服务器部署手册

目标机器：`79.108.225.95`
部署方式：Docker Compose（`postgres` + `backend` + `web/nginx`）
对外访问：`http://79.108.225.95/`（80 端口）

---

## 0. 本次部署为适配服务器所做的代码改动

| 文件 | 改动 | 原因 |
|---|---|---|
| `deploy/docker/web.Dockerfile` | 补装原生二进制包改为**按构建架构分支** | 原来写死 `linux-arm64`（Mac 上调通的形态），在 x86_64 服务器上 pnpm 会因 os/cpu 不匹配直接构建失败 |
| `docker-compose.yml` | `postgres` 端口默认绑 `127.0.0.1` | 原来 `5432` 直接发布到公网，且默认口令是 `isoftdev` |
| `docker-compose.yml` | `backend` 端口默认绑 `127.0.0.1` | 前端经容器内网访问后端，9010 不需要暴露到公网 |
| `deploy/docker/backend.Dockerfile` | 增装 `pytest` | `TestAgent/tools/run_py_test.py` 要 `python -m pytest`，原镜像里没有，测试阶段必然失败 |
| `docker-compose.yml` | **透传** `MAX_CONCURRENT_WORKFLOWS` / `AGENT_EXECUTOR_MAX_WORKERS` / `PG_POOL_MIN` / `PG_POOL_MAX` | 这几个是小内存机器的关键旋钮，代码里本来就支持环境变量，但 compose 没有透传，导致不管机器多小都按「8 个并发工作流 + 10 线程 + 10 条常驻 PG 连接」跑 |
| `agent/platform/app/services/store.py:78` | 连接池 `min_size/max_size` 改为可配置 | 原来硬编码 `10/50`。每条连接对应一个 PostgreSQL 后端进程，常驻 10 条在 1.6G 机器上纯属浪费 |
| `deploy/docker/web.Dockerfile` | 新增 `NODE_OPTIONS` 构建参数 | 给 V8 堆设上限，让 Rollup 到点就 GC，而不是一路涨到被 OOM killer 杀掉 |
| `.env.server.example` | 新增服务器专用 env 模板 | 镜像源改回官方源（机器在海外，国内镜像会超时）、端口改 80、强制改数据库口令、**按 1.6G 内存预设并发旋钮** |
| `deploy/docker/run-server.sh` | 新增部署辅助脚本（**可选**） | 只做启动前检查；配好 `.env` 后直接 `docker compose up -d --build` 即可，不需要这个脚本 |

所有默认值都保持和改动前一致，**本地开发流程（`run-local.sh` + 清华镜像 + arm64 + 8 并发）未受任何影响**。低内存配置只通过服务器的 env 文件生效。

---

## 1. 从本机把代码推上服务器

在 **你的 Mac** 上执行：

```bash
cd /Users/user/Documents/work/code/iSoftDevAgents

rsync -avz --delete \
  --exclude '.git' \
  --exclude '.DS_Store' \
  --exclude 'node_modules' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.pytest_cache' \
  --exclude '.env' \
  --exclude 'deploy/docker/backend.env' \
  --exclude 'agent/platform/data' \
  --exclude 'agent/platform/log' \
  --exclude 'frontend/artifacts/ai-design-platform/dist' \
  ./ root@79.108.225.95:/root/iSoftDevAgents/
```

代码总共约 13MB，推送很快。

---

## 2. 登录服务器并确认环境

```bash
ssh root@79.108.225.95
```

### 2.1 看清楚这台机是什么配置

```bash
uname -m                 # 期望 x86_64
nproc                    # CPU 核数
free -h                  # 内存
df -h /                  # 磁盘剩余
cat /etc/os-release | head -2
```

**本机实测结果（`sg04`，2026-09-03）：**

| 项 | 实测值 | 结论 |
|---|---|---|
| 架构 | `x86_64` | ✅ 走本次新增的 x64 分支 |
| CPU | 2 核 | ⚠️ 构建会慢，能用 |
| 磁盘 | 50G / 剩 44G | ✅ 够 |
| 系统 | Ubuntu 26.04 LTS | ✅ |
| **内存** | **1.6Gi 总量 / 1.0Gi 可用 / swap = 0** | 🔴 **不够，必须先加 swap** |

**内存这一项是本次部署的真实瓶颈，必须正视：**

- **构建期**：前端 `vite build`（Rollup 打 React 19 + Tailwind 4）在 1.6G 无 swap 的机器上**几乎必然被 OOM killer 杀掉**（退出码 137）
- **运行期**：每个 Agent 是独立子进程，起来要把整套 CrewAI + LiteLLM 加载一遍，**单进程常驻 500–800MB**。加上 backend 基线（约 150–250MB，好消息是 crewai 在后端主进程里是惰性加载的，不占这块）+ postgres（约 150MB）+ nginx，**同时只能跑 1 个 Agent，且必须靠 swap 兜底**

所以第 2.3 步（加 swap）和第 3.3 步（并发降到 1）**都不是可选项**。

> **建议：把这台机升到 4GB 内存。** 1.6GB + swap 能把服务跑起来、能验证整条链路，但 Agent 真实执行时会持续换页,单轮生成可能从几分钟拖到几十分钟。这是配置问题,不是代码问题——我把能调的旋钮都调到最省了。

### 2.2 装 Docker（已装则跳过）

```bash
docker --version && docker compose version
```

没有输出就装：

```bash
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker compose version    # 确认 compose v2 插件在
```

### 2.3 加 swap —— 这台机**必须做**

实测 swap = 0、可用内存仅 1.0Gi。不加 swap 前端构建一定挂。磁盘有 44G 空闲，拿 6G 出来做 swap：

```bash
# 幂等：已经有 /swapfile 就先关掉重建
swapoff /swapfile 2>/dev/null; rm -f /swapfile

fallocate -l 6G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile

# 开机自动挂载（避免重复写入 fstab）
grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab

# 小内存机器让内核更积极地换页，而不是宁可 OOM kill
sysctl -w vm.swappiness=60
grep -q '^vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=60' >> /etc/sysctl.conf

free -h    # 确认 Swap 一行变成 6.0Gi
```

预期输出里 Swap 那行应该是：

```
Swap:          6.0Gi          0B       6.0Gi
```

### 2.4 打开 80 端口

我从外面探测过：这台机现在**只有 22 端口通,80/443/9080 全不通**。所以这一步必须做。

```bash
# 先看用的是哪套防火墙
command -v ufw && ufw status
command -v firewall-cmd && firewall-cmd --state
iptables -L INPUT -n | head -20
```

按结果选一条：

```bash
# ufw（Ubuntu/Debian 常见）
ufw allow 80/tcp && ufw reload && ufw status

# firewalld（CentOS/Rocky/Alma 常见）
firewall-cmd --permanent --add-port=80/tcp && firewall-cmd --reload

# 纯 iptables
iptables -I INPUT -p tcp --dport 80 -j ACCEPT
# 持久化（Debian 系）
apt-get install -y iptables-persistent && netfilter-persistent save
```

> **别忘了云厂商那一层。** 如果这是 VPS/云主机，控制台里的**安全组 / 防火墙规则**也要放通 80/tcp。系统内防火墙开了但安全组没开，从外面照样访问不到。

---

## 3. 配置环境变量

```bash
cd /root/iSoftDevAgents
cp .env.server.example .env
chmod 600 .env
```

### 为什么文件名必须是 `.env`

`docker compose` 会**自动读取 compose 文件所在目录下的 `.env`**，用它填充 `docker-compose.yml` 里的 `${VAR}` 插值。所以只要文件叫 `.env` 且放在仓库根目录，后面所有命令都可以是干净的：

```bash
docker compose up -d --build      # 不需要 --env-file
```

三点注意：

- **不会和后端自己的配置打架。** 后端进程读的是 `agent/platform/.env` 和 `agent/platform/.env.local`（见 `app/config.py:39`），根目录这个 `.env` 只服务于 compose 的变量插值，两者互不干扰。
- **别在你 Mac 的仓库根目录建 `.env`。** compose 在本地同样会自动读它，会把你本地开发也切成 80 端口 + 官方源 + 低内存并发配置。服务器专用的东西只留在服务器上。
- **rsync 必须排除 `.env`。** 第 1 步的命令带 `--delete`，如果不排除，每次同步都会把服务器上的 `.env` 删掉。上面的 rsync 已经加了 `--exclude '.env'`。

### 3.1 必须改的两处（不改起不来）

生成一个强口令：

```bash
openssl rand -hex 24
```

把输出填进两个地方，**两处必须一致**：

```bash
vi .env
```

```bash
POSTGRES_PASSWORD=<刚生成的口令>
DATABASE_URL=postgresql://isoftdev:<刚生成的口令>@postgres:5432/isoftdev
```

或者用命令一次改掉：

```bash
PGPASS=$(openssl rand -hex 24)
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PGPASS}|" .env
sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://isoftdev:${PGPASS}@postgres:5432/isoftdev|" .env
grep -E '^(POSTGRES_PASSWORD|DATABASE_URL)=' .env
```

### 3.2 LLM Key（本次先占位）

按你的选择，`ISOFTDEVAGENTS_LLM_API_KEY` 保持占位值 `REPLACE-WITH-YOUR-REAL-KEY`。

启动脚本会打一条 WARNING 然后照常启动。这个状态下：

- ✅ 前端页面、注册登录、建项目、数据库、WebSocket —— 都能验证
- ❌ 五个 Agent 的生成链路 —— 全部不可用

拿到真实 Key 后：

```bash
cd /root/iSoftDevAgents
sed -i 's|^ISOFTDEVAGENTS_LLM_API_KEY=.*|ISOFTDEVAGENTS_LLM_API_KEY=你的真实key|' .env
./deploy/docker/run-server.sh restart-backend
```

同时确认 `ISOFTDEVAGENTS_LLM_BASE_URL` 和 `ISOFTDEVAGENTS_LLM_MODEL` 跟你的服务商对得上。

### 3.3 确认小内存旋钮已生效（这台机必须保持这组值）

模板里已经按 1.6G 内存预设好了，确认一下没被改掉：

```bash
grep -E '^(ISOFTDEVAGENTS_MAX_CONCURRENT_WORKFLOWS|ISOFTDEVAGENTS_AGENT_EXECUTOR_MAX_WORKERS|ISOFTDEVAGENTS_PG_POOL_MIN|ISOFTDEVAGENTS_PG_POOL_MAX|WEB_BUILD_NODE_OPTIONS)=' \
  .env
```

期望输出：

```
ISOFTDEVAGENTS_MAX_CONCURRENT_WORKFLOWS=1
ISOFTDEVAGENTS_AGENT_EXECUTOR_MAX_WORKERS=2
ISOFTDEVAGENTS_PG_POOL_MIN=2
ISOFTDEVAGENTS_PG_POOL_MAX=10
WEB_BUILD_NODE_OPTIONS=--max-old-space-size=1536
```

这几个值分别把「并发工作流」从 8 降到 1、「Agent 线程池」从 10 降到 2、「常驻 PG 连接」从 10 降到 2、并给前端构建的 V8 堆设了上限。**升级内存之后可以往上调。**

---

## 4. 构建并启动（分两步，别让两个构建的内存峰值叠在一起）

1.6G 内存的机器上,**不要**一条命令同时构建 backend 和 web。分开跑,失败时也更容易定位。

### 4.1 先构建后端

```bash
cd /root/iSoftDevAgents
docker compose build backend
```

装的是 crewai[tools] 全家桶（onnxruntime / pyarrow / lancedb / chromadb 等,都是预编译 wheel,不用现场编译）。**预计 10–25 分钟**,镜像约 2.5–3.5GB。

### 4.2 再构建前端

```bash
docker compose build web
```

这一步是内存风险最高的地方（~1000 个 npm 包 + Rollup 打包）。**预计 15–40 分钟**,2 核 + swap 会比较慢,耐心等,中途别 Ctrl-C。

另开一个 SSH 窗口盯内存：

```bash
watch -n 2 free -h
```

看到 Swap 被吃掉一两 G 是正常的;只要没出现 `Killed` 就是在正常推进。

### 4.3 启动

```bash
docker compose up -d
docker compose ps
```

> **之后的日常更新一条命令就够：**
>
> ```bash
> cd /root/iSoftDevAgents && docker compose up -d --build
> ```
>
> `docker compose` 会自动读取仓库根目录的 `.env` 做变量插值，不需要 `--env-file`。
> 上面分两步只是首次构建时为了避开内存峰值叠加，不是常态。

---

## 5. 验证

按顺序跑，每一步都该有明确输出：

```bash
# 1. 三个容器都在，backend 应该是 healthy
docker compose ps

# 2. 后端健康检查（服务器本机）
curl -s http://127.0.0.1:9010/api/healthz

# 3. 数据库建表成功（应该看到 17 张表）
docker compose exec postgres \
  psql -U isoftdev -d isoftdev -c '\dt'

# 4. Alembic 迁移跑过了
docker compose logs backend --tail=300 \
  | grep -iE "alembic|STARTUP"

# 5. Nginx 经内网转发到后端（走 web 容器）
curl -s http://127.0.0.1/api/healthz

# 6. 前端静态页面
curl -sI http://127.0.0.1/ | head -3
```

然后在**你自己的浏览器**里打开：

```
http://79.108.225.95/
```

应该看到登录页。注册一个账号 → 进首页 → 建项目。走到这里就说明前端、后端、数据库、WebSocket 整条链路都通了。

---

## 6. 出问题时怎么查

```bash
cd /root/iSoftDevAgents
docker compose logs backend  --tail=200
docker compose logs web      --tail=100
docker compose logs postgres --tail=50
```

### 常见故障对照

| 现象 | 原因 | 处理 |
|---|---|---|
| 前端构建报 `Cannot find module @rollup/rollup-linux-x64-gnu` | 架构分支没生效 | `uname -m` 确认架构；`docker compose build --no-cache web` 重建 |
| 前端构建被 `Killed` / 退出码 137 | 内存不足,OOM | ① 确认 2.3 的 swap 真的挂上了(`free -h`)② 确认 `WEB_BUILD_NODE_OPTIONS=--max-old-space-size=1536` 生效 ③ 还挂就把它降到 `1024` 再试 ④ 都不行就走下面的「兜底方案」 |
| 后端容器跑一会儿被 OOM kill / 容器反复重启 | Agent 子进程把内存吃干 | 确认 `ISOFTDEVAGENTS_MAX_CONCURRENT_WORKFLOWS=1`;仍然不行就只能升内存 |
| Agent 生成极慢(几十分钟) | 内存不够,在持续换页 | `free -h` 看 swap 用量。这是 1.6G 机器的固有代价,升到 4G 可解 |
| 后端构建卡在下载依赖 | 镜像源指向国内 | 确认 env 里 `PIP_INDEX_URL=https://pypi.org/simple` |
| `backend` 一直 unhealthy | 连不上数据库 | 确认 `POSTGRES_PASSWORD` 和 `DATABASE_URL` 里的密码**完全一致** |
| 浏览器打不开但 `curl 127.0.0.1` 正常 | 防火墙/安全组 | 回到 2.4,别忘了云厂商安全组 |
| 页面能开但接口 502 | backend 没起来 | `logs backend` 看真实报错 |
| Agent 一启动就报 LLM 认证失败 | Key 还是占位值 | 回到 3.2 |
| Agent 报 `ModuleNotFoundError` | 该 Agent 的依赖没进镜像 | 见下方「已知依赖缺口」 |

### 已知依赖缺口

后端镜像只安装了 `agent/platform/pyproject.toml` 的顶层依赖，**`agent/requirements.txt` 整个没被安装**。容器内各 Agent 通过 subprocess 回落到 `python3`（= 平台 venv）运行。

已覆盖：`crewai` / `crewai-tools` / `litellm` / `openai` / `pydantic` / `pymongo` / `jinja2` / `PyYAML` / `python-dotenv` / `pytest`(本次补装)

可能缺失（等真实报错再补，不要提前塞）：

- `landingai_ade` —— `agent/Requirements Agent/reagent/src/reagent/RequirementExtraction.py:1` 无保护地 import,而这个包**不在任何依赖清单里**。一旦这条代码路径被走到就会 ImportError
- `python-docx` / `openpyxl` / `pdfplumber` / `PyMuPDF` —— 大概率作为 crewai-tools 的传递依赖已经装上了

补装方式（在 `deploy/docker/backend.Dockerfile` 的 pytest 那一行后面加）：

```dockerfile
RUN .venv/bin/pip install --no-cache-dir <缺失的包名>
```

然后 `./deploy/docker/run-server.sh up` 重建。

### 兜底方案：前端在服务器上怎么都构建不出来

如果 swap 加了、堆上限调了、还是过不去,就换成「在别处构建镜像 → 推到服务器」。

**方案 A:在你的 Mac 上交叉构建**(需要 Docker Desktop 在跑)

```bash
# Mac 上
cd /Users/user/Documents/work/code/iSoftDevAgents
docker buildx build --platform linux/amd64 \
  -f deploy/docker/web.Dockerfile \
  --build-arg VITE_API_BASE_URL= \
  --build-arg BASE_PATH=/ \
  --build-arg NPM_CONFIG_REGISTRY=https://registry.npmmirror.com \
  -t isoftdevagents-web:latest \
  --load .

docker save isoftdevagents-web:latest | gzip | \
  ssh root@79.108.225.95 'gunzip | docker load'
```

⚠️ Apple Silicon 上构建 amd64 镜像走 QEMU 模拟,**会非常慢(可能 1–2 小时)**,而且 Node 原生包在模拟环境下容易出问题。所以这是兜底,不是首选。

**方案 B:只把构建产物传上去**(最省事,推荐作为兜底)

前端最终产物就是一堆静态文件,nginx 直接伺服即可:

```bash
# Mac 上(本机 arm64 原生构建,快)
cd /Users/user/Documents/work/code/iSoftDevAgents/frontend
pnpm install
VITE_API_BASE_URL= BASE_PATH=/ pnpm --filter @workspace/ai-design-platform run build

# 传上去
rsync -avz --delete \
  artifacts/ai-design-platform/dist/public/ \
  root@79.108.225.95:/root/iSoftDevAgents/web-dist/
```

然后在服务器上把 `web` 服务换成不构建、直接挂载产物。在 `docker-compose.yml` 里把 `web` 的 `build:` 段替换成：

```yaml
  web:
    image: nginx:1.27-alpine
    restart: unless-stopped
    depends_on:
      backend:
        condition: service_healthy
    volumes:
      - ./deploy/docker/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./web-dist:/usr/share/nginx/html:ro
    ports:
      - "${ISOFTDEVAGENTS_WEB_PORT:-80}:80"
```

静态产物与架构无关,所以在 Mac 上构建、在 x86 服务器上伺服完全没问题。这个方案还顺带省掉了服务器上 Node 那一整套构建负担。

---

## 7. 日常运维

```bash
cd /root/iSoftDevAgents

./deploy/docker/run-server.sh ps                # 看状态
./deploy/docker/run-server.sh logs              # 跟日志
./deploy/docker/run-server.sh restart-backend   # 只重启后端(改完 env 用这个)
./deploy/docker/run-server.sh down              # 停服务(数据卷保留)
./deploy/docker/run-server.sh up                # 重新构建启动
```

### 更新代码

在 Mac 上重跑第 1 步的 rsync，然后服务器上：

```bash
cd /root/iSoftDevAgents && ./deploy/docker/run-server.sh up
```

### 数据在哪

| 数据 | 位置 | 备份方式 |
|---|---|---|
| 业务数据（17 张表：项目/消息/产物/代码文件/版本…） | Docker 卷 `pgdata` | `docker compose exec postgres pg_dump -U isoftdev isoftdev > backup.sql` |
| 上传文件、Agent 调试包 | 宿主机 `/root/iSoftDevAgents/agent/platform/data` | 直接 tar |
| LLM 调试日志 | 宿主机 `/root/iSoftDevAgents/agent/platform/log` | 会持续增长,注意清理 |

> `down` 不会删数据卷。**只有 `down -v` 才会删库**,别手滑。

---

## 8. 上线后建议补的几件事（不阻断本次部署）

1. **HTTPS** —— 目前是纯 HTTP,登录口令明文过网。建议在前面加 Caddy 或用 certbot 配 Let's Encrypt
2. **收紧 CORS** —— `agent/platform/app/main.py:86` 是 `allow_origins=["*"]` + `allow_credentials=True`。同源访问没影响,但这个组合本身不该留
3. **日志轮转** —— `ISOFTDEVAGENTS_AGENT_DEBUG_LLM_IO=1` 会把每次模型输入输出（各 12000 字符上限）写文件,跑久了会涨得很快。稳定后可以关掉,或给 `log/` 配 logrotate
4. **单实例限制** —— Agent 通过 subprocess 在 backend 容器内执行,产物先落本地目录再入库,所以**不要横向扩到多实例**
