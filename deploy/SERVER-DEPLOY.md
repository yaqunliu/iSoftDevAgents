# iSoftDevAgents 单机服务器部署手册

目标机器：`79.108.225.95`
部署方式：Docker Compose（`caddy` + `postgres` + `backend` + `web/nginx`）
对外访问：`https://gmonkey.ai/`（80 端口自动跳 443；HTTPS 配置见第 6 节）

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
| `.env.server.example` | 新增服务器专用 env 模板 | 镜像源改回官方源（机器在海外，国内镜像会超时）、打开 `https` profile 由 Caddy 对外、强制改数据库口令、**按 1.6G 内存预设并发旋钮** |
| `deploy/docker/run-server.sh` | 新增部署辅助脚本（**可选**） | 只做启动前检查；配好 `.env` 后直接 `docker compose up -d --build` 即可，不需要这个脚本 |
| `deploy/docker/Caddyfile` | **新增** | HTTPS 接入：Caddy 占住 80/443，自动签发 / 续期 Let's Encrypt 证书，反代到 `web:80` |
| `docker-compose.yml` | 新增 `caddy` 服务（挂 `https` profile） | 证书存在具名卷 `caddy_data` 里，容器重建也不会重复签发、不会撞速率限制；profile 保证本地开发不会被带上 |
| `docker-compose.yml` | `web` 的端口发布新增绑定地址，默认 `127.0.0.1:9080`（端口默认值未变，原来就是 9080） | 公网流量一律经 Caddy 进入，否则 `web` 会和 Caddy 抢 80 端口。服务器 `.env` 需从旧值 `80` 改回 `9080`，见 3.4 节 |
| `.env.server.example` | 新增 `COMPOSE_PROFILES` / `ISOFTDEVAGENTS_SITE_DOMAIN` / `ISOFTDEVAGENTS_ACME_EMAIL` | HTTPS 所需；邮箱是真实值，只写在服务器的 `.env` 里，不进仓库 |
| `deploy/docker/nginx.conf` | **不动** | 继续只监听容器内 80，处在 Caddy 后面。证书的事 nginx 完全不需要知道 |
| 前端全部代码 | **不动** | 打包时 `VITE_API_BASE_URL` 就是空字符串（同源），WebSocket 地址从 `window.location` 推导，页面变 https 后自动跟着走 https / wss |

**本地开发流程（`run-local.sh` + 清华镜像 + arm64 + 8 并发）不受影响**：低内存配置只通过服务器的 env 文件生效，`caddy` 挂在 `https` profile 上、本地不设 `COMPOSE_PROFILES`，所以 `docker compose up` 不会把它带起来（不会有容器在 Mac 上抢 80/443、也不会去给线上域名反复申请证书）。

> 唯一一处本地可感知的变化：`web` 的端口发布现在默认绑 `127.0.0.1`（原来绑所有接口）。`http://localhost:9080/` 照常，但**局域网内其他设备（手机、平板）访问 Mac 的 9080 会不通**。真需要的话在本地设 `ISOFTDEVAGENTS_WEB_BIND_HOST=0.0.0.0`。

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

### 2.4 打开 80 / 443 端口

我从外面探测过：这台机现在**只有 22 端口通,80/443/9080 全不通**。所以这一步必须做。

80 和 443 两个都要开：80 用于 HTTP→HTTPS 跳转、以及 Let's Encrypt 的 HTTP-01 域名验证（证书就是靠它签出来的，不能省）；443 才是真正的站点入口。

```bash
# 先看用的是哪套防火墙
command -v ufw && ufw status
command -v firewall-cmd && firewall-cmd --state
iptables -L INPUT -n | head -20
```

按结果选一条：

```bash
# ufw（Ubuntu/Debian 常见）
ufw allow 80/tcp && ufw allow 443/tcp && ufw reload && ufw status

# firewalld（CentOS/Rocky/Alma 常见）
firewall-cmd --permanent --add-port=80/tcp
firewall-cmd --permanent --add-port=443/tcp
firewall-cmd --reload

# 纯 iptables
iptables -I INPUT -p tcp --dport 80 -j ACCEPT
iptables -I INPUT -p tcp --dport 443 -j ACCEPT
# 持久化（Debian 系）
apt-get install -y iptables-persistent && netfilter-persistent save
```

> **别忘了云厂商那一层。** 如果这是 VPS/云主机，控制台里的**安全组 / 防火墙规则**也要放通 80/tcp 和 443/tcp。系统内防火墙开了但安全组没开，从外面照样访问不到。**443 这一条最容易漏**——之前 80 就是踩的这个坑。

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

### 3.4 HTTPS 相关的四个变量

新模板里已经带上了，确认一遍：

```bash
grep -E '^(COMPOSE_PROFILES|ISOFTDEVAGENTS_SITE_DOMAIN|ISOFTDEVAGENTS_ACME_EMAIL|ISOFTDEVAGENTS_WEB_PORT|ISOFTDEVAGENTS_WEB_BIND_HOST)=' .env
```

期望：

```
COMPOSE_PROFILES=https
ISOFTDEVAGENTS_SITE_DOMAIN=gmonkey.ai
ISOFTDEVAGENTS_ACME_EMAIL=<你的真实邮箱>
ISOFTDEVAGENTS_WEB_PORT=9080
ISOFTDEVAGENTS_WEB_BIND_HOST=127.0.0.1
```

只有 `ISOFTDEVAGENTS_ACME_EMAIL` 需要你自己填，改成一个**真实邮箱**（Let's Encrypt 用它发证书到期提醒）。这个值只写在服务器的 `.env` 里，不进仓库。

> ⚠️ **如果这台机之前已经部署过、`.env` 是从旧模板复制的**，它里面是 `ISOFTDEVAGENTS_WEB_PORT=80`，而且没有另外三个变量。这种情况必须手工补齐：
>
> ```bash
> cd /root/iSoftDevAgents
> sed -i 's|^ISOFTDEVAGENTS_WEB_PORT=.*|ISOFTDEVAGENTS_WEB_PORT=9080|' .env
> cat >> .env <<'EOF'
> ISOFTDEVAGENTS_WEB_BIND_HOST=127.0.0.1
> COMPOSE_PROFILES=https
> ISOFTDEVAGENTS_SITE_DOMAIN=gmonkey.ai
> ISOFTDEVAGENTS_ACME_EMAIL=你的真实邮箱
> EOF
> ```
>
> **`WEB_PORT` 这一条不改的话，`web` 会继续占着 80，caddy 起不来。**

`COMPOSE_PROFILES=https` 是 caddy 的总开关：`docker compose` 会读它决定启用哪些 profile，只有它被设成 `https`，`caddy` 才会随 `docker compose up -d` 一起起来。本地开发的仓库里不设这个变量，所以 Mac 上永远不会冒出一个抢 80/443、还去给线上域名申请证书的容器。

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

### 4.3 分三阶段启动：数据库 → 后端 → 前端

服务一共三个，**必须按这个顺序**。compose 里已经用 `depends_on: condition: service_healthy` 强制了依赖，所以哪怕直接 `up -d` 顺序也是对的；下面分阶段是为了每一层都能单独确认，出问题定位快。

`--no-deps` 的作用是「只起这一个，别自动把依赖拉起来」，这样才是真正的一个一个起。

---

#### 阶段 1：数据库

```bash
cd /root/iSoftDevAgents
docker compose up -d postgres
```

postgres 用的是现成镜像 `postgres:16-alpine`，**不需要 build**（所以它从来没在前面的构建输出里出现过）。

等它变成 healthy —— `pg_isready` 通过之前不要往下走：

```bash
# 轮询直到 healthy，通常 5~15 秒
until [ "$(docker inspect -f '{{.State.Health.Status}}' \
  "$(docker compose ps -q postgres)")" = "healthy" ]; do
  echo "waiting for postgres..."; sleep 2
done
echo "postgres is healthy"
```

确认库和账号已就绪：

```bash
docker compose exec postgres psql -U isoftdev -d isoftdev -c 'SELECT version();'
docker compose exec postgres psql -U isoftdev -d isoftdev -c '\dt'
```

此刻 `\dt` 应该返回 **`Did not find any relations.`** —— 空库是**正常的**。建表是后端启动时才做的，见下一阶段。

---

#### 阶段 2：后端（建表就发生在这一步）

```bash
docker compose up -d --no-deps backend
docker compose logs -f backend
```

日志里按顺序应该看到：

```text
INFO  [STARTUP] Alembic migration completed (upgrade to head)
INFO  Requirements Agent runtime: bridge_mode=... enabled=True ...
INFO  Application startup complete.
INFO  Uvicorn running on http://0.0.0.0:9010
```

看到 `Application startup complete.` 就 Ctrl-C 退出日志跟随（不会停容器）。

确认表建好了：

```bash
docker compose exec postgres psql -U isoftdev -d isoftdev -c '\dt'
```

**应该看到 18 张表** = 17 张业务表 + alembic 自己的 `alembic_version`。

再确认健康检查和迁移版本：

```bash
curl -s http://127.0.0.1:9010/api/healthz
docker compose exec postgres psql -U isoftdev -d isoftdev \
  -c 'SELECT * FROM alembic_version;'          # 期望 001
```

等 backend 变成 healthy 再起前端（`web` 的 `depends_on` 要求 backend healthy）：

```bash
until [ "$(docker inspect -f '{{.State.Health.Status}}' \
  "$(docker compose ps -q backend)")" = "healthy" ]; do
  echo "waiting for backend..."; sleep 3
done
echo "backend is healthy"
```

> backend 的 healthcheck 有 `start_period: 30s`，所以前 30 秒显示 `starting` 是正常的。

---

#### 阶段 3：前端

```bash
docker compose up -d --no-deps web
docker compose ps
```

三个服务都应该是 `Up`，postgres 和 backend 带 `(healthy)`。

注意 `web` 现在发布的是 `127.0.0.1:9080`，**不再是 80**——80/443 留给第 6 节的 caddy。所以这一步之后从外网还打不开站点，本机 `curl http://127.0.0.1:9080/` 应该是通的。走完第 6 节才对外可用。

---

> **之后的日常更新不用分阶段，一条命令就够：**
>
> ```bash
> cd /root/iSoftDevAgents && docker compose up -d --build
> ```
>
> `docker compose` 会自动读取仓库根目录的 `.env` 做变量插值，不需要 `--env-file`；
> `depends_on` 会保证 `postgres → backend → web` 的启动顺序。

---

### 4.4 数据库是怎么初始化的（不需要手动做任何事）

**结论先说：不需要 `psql` 手动建库、不需要手动跑 `alembic upgrade`。** 后端启动时自己完成，且幂等。

`app/main.py` 的 `startup_event` 里是两层：

| 顺序 | 动作 | 代码位置 |
|---|---|---|
| 1 | `store.initialize(dsn)` → `_create_schema()`，执行 **17 条 `CREATE TABLE IF NOT EXISTS`** | `app/services/store.py:88` |
| 2 | `alembic upgrade head`，跑 `001_initial_schema` 并写入 `alembic_version` | `app/main.py:3719` |

两层建的表**完全一致**（已逐个比对，17 张，无差异），而且 alembic 迁移里也全是 `CREATE TABLE IF NOT EXISTS`。所以：

- **新库**：第 1 层建表 → 第 2 层空跑一遍并把版本号打到 `001`
- **旧库**：两层都是 no-op，不会破坏已有数据
- **重启**：随便重启多少次都安全

数据库本身（`isoftdev` 库 + `isoftdev` 账号）由 `postgres:16-alpine` 镜像在**卷首次初始化时**自动创建，参数来自 compose 里的 `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD`。

#### ⚠️ 一个必须知道的坑：改密码对已存在的卷无效

`POSTGRES_PASSWORD` **只在 `pgdata` 卷第一次初始化时生效**。这是 postgres 官方镜像的行为，不是这个项目的问题。

也就是说，如果你**之前已经用别的密码起过一次 postgres**，现在改了 `.env` 里的密码：

- 卷里的 `isoftdev` 账号仍是**旧密码**
- backend 拿新密码去连 → 认证失败 → 容器反复重启
- 日志里是 `password authentication failed for user "isoftdev"`

**怎么判断卷是不是已经存在：**

```bash
docker volume ls | grep pgdata
```

**处理办法（二选一）：**

```bash
# 方案 1：库里还没有你在意的数据 —— 直接删卷重来（数据会全部丢失）
docker compose down -v
docker compose up -d postgres

# 方案 2：库里已有数据要保 —— 改数据库里的密码去匹配 .env
docker compose exec postgres psql -U isoftdev -d isoftdev \
  -c "ALTER USER isoftdev WITH PASSWORD '你在 .env 里写的那个密码';"
docker compose up -d --force-recreate backend
```

> `down -v` 里的 `-v` 是删卷,**会清空整个数据库**。不带 `-v` 的 `down` 只停容器,数据保留。别手滑。

---

## 5. 验证

按顺序跑，每一步都该有明确输出：

```bash
# 1. 三个容器都在，backend 应该是 healthy
docker compose ps

# 2. 后端健康检查（服务器本机）
curl -s http://127.0.0.1:9010/api/healthz

# 3. 数据库建表成功（应该看到 18 张表 = 17 业务表 + alembic_version）
docker compose exec postgres \
  psql -U isoftdev -d isoftdev -c '\dt'

# 4. Alembic 迁移跑过了
docker compose logs backend --tail=300 \
  | grep -iE "alembic|STARTUP"

# 5. Nginx 经内网转发到后端（走 web 容器，注意端口是 9080）
curl -s http://127.0.0.1:9080/api/healthz

# 6. 前端静态页面
curl -sI http://127.0.0.1:9080/ | head -3
```

到这里为止验证的是「内网这条链路通了」。**站点还没对外可用**——公网入口在下一节的 caddy 上。

如果你想先不开 HTTPS、只用纯 HTTP 跑起来验证，把 `.env` 里的 `COMPOSE_PROFILES=https` 注释掉，并把 `ISOFTDEVAGENTS_WEB_BIND_HOST` 改成 `0.0.0.0`、`ISOFTDEVAGENTS_WEB_PORT` 改成 `80`，然后 `docker compose up -d --no-deps web`，就回到了 `http://79.108.225.95/`。

---

## 6. 启用 HTTPS（caddy + Let's Encrypt）

### 6.0 动手之前先确认三件事

```bash
# 1. 域名解析确实指向这台机
dig +short gmonkey.ai            # 期望 79.108.225.95

# 2. 80 和 443 都放通了（含云厂商安全组，见 2.4）
#    443 没通的话证书能签出来，但外面访问不到，会很难查

# 3. web 已经从 80 退到 9080
docker compose ps web            # PORTS 一列应该是 127.0.0.1:9080->80/tcp
```

第 3 条最关键：**caddy 启动的瞬间就要占 80 端口，如果 `web` 还占着，caddy 直接因端口冲突起不来。**

如果 `web` 还在 80 上（旧 `.env` 没改），先按 3.4 节改完 `.env`，再执行：

```bash
docker compose up -d --no-deps web    # 让 web 退到 127.0.0.1:9080
```

### 6.1 起 caddy

```bash
cd /root/iSoftDevAgents
docker compose up -d caddy
docker compose logs -f caddy
```

日志里出现 `certificate obtained successfully` 就是签发成功，可以 Ctrl-C 退出日志跟随（不会停容器）。整个过程通常十几秒。

> `.env` 里设了 `COMPOSE_PROFILES=https` 之后，后续 `docker compose up -d --build` 会自动带上 caddy，不用每次单独点名。

### 6.2 验证

命令行部分：

```bash
# 1. 证书签发成功且证书链完整（issuer 应该是 Let's Encrypt）
curl -vI https://gmonkey.ai/ 2>&1 | grep -E "issuer|subject|HTTP/"

# 2. HTTP 自动跳 HTTPS（期望 308）
curl -sI http://gmonkey.ai/ | head -3

# 3. API 经两层代理（caddy → nginx → backend）仍然通
curl -s https://gmonkey.ai/api/healthz

# 4. 容器状态与内存占用，确认没把这台小机器压垮
docker compose ps && docker stats --no-stream
```

浏览器部分（**curl 覆盖不到，必须人工做**）：

1. 打开 `https://gmonkey.ai/`，注册账号 → 进首页 → 建项目，地址栏是锁标、没有混合内容警告
2. **WebSocket 握手**：DevTools → Network，确认 `wss://gmonkey.ai/api/projects/<id>/ws` 返回 **101 Switching Protocols**
3. **长任务不断流**：完整跑一次 Agent 生成，确认几分钟的长连接没被代理层掐断

第 3 条不能省。nginx 那边配了 3600s 超时（`nginx.conf:29-31`），Caddy 侧用 `flush_interval -1` 关掉了响应缓冲，理论上没问题，**但两层代理叠加的超时行为必须实测一次**——`healthz` 通过说明不了长连接没问题。

### 6.3 证书是怎么续期的（不需要做任何事）

Caddy 内置 ACME 客户端，证书到期前约 30 天自动续期，不需要 cron、不需要 reload 钩子。证书存在具名卷 `caddy_data` 里。

**唯一要守住的一条规矩：别删 `caddy_data` 卷。** 卷在，容器怎么重建都不会重新签发；卷没了，每次重建都要重签一次，而 Let's Encrypt 对同一组域名限制**每周 5 张**，用完这一周就签不出来了。

调试阶段如果需要反复试，先在 `Caddyfile` 里打开 `acme_ca` 那行走 staging 环境（文件里有注释说明），跑通后再切回正式环境。

### 6.4 回滚到纯 HTTP

改动全是加法，回滚很干净：

```bash
docker compose stop caddy

# .env 里改两行
sed -i 's|^ISOFTDEVAGENTS_WEB_BIND_HOST=.*|ISOFTDEVAGENTS_WEB_BIND_HOST=0.0.0.0|' .env
sed -i 's|^ISOFTDEVAGENTS_WEB_PORT=.*|ISOFTDEVAGENTS_WEB_PORT=80|' .env
sed -i 's|^COMPOSE_PROFILES=|#COMPOSE_PROFILES=|' .env

docker compose up -d --no-deps web
```

就回到了 `http://79.108.225.95/`。证书留在 `caddy_data` 卷里，下次再开启不用重签。

### 6.5 以后要加 www

`www.gmonkey.ai` 目前**没有 A 记录**，所以本次证书只覆盖裸域。要加的话：

1. DNS 加一条 `www` 的 A 记录指向 `79.108.225.95`，`dig +short www.gmonkey.ai` 确认生效
2. 按 `Caddyfile` 末尾的注释把域名补上
3. `docker compose up -d --force-recreate caddy`

**顺序不能反。** Let's Encrypt 会对证书里写的每一个域名逐个验证，只要有一个解析不到，是**整次签发失败**，不是跳过那一个——连原本好好的裸域证书也会一起签不出来。

---

## 7. 出问题时怎么查

```bash
cd /root/iSoftDevAgents
docker compose logs backend  --tail=200
docker compose logs web      --tail=100
docker compose logs postgres --tail=50
docker compose logs caddy    --tail=100
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
| 日志报 `password authentication failed for user "isoftdev"` | `pgdata` 卷是用旧密码初始化的，改 `.env` 对已存在的卷无效 | 见 4.4 节「改密码对已存在的卷无效」 |
| `\dt` 返回 `Did not find any relations.` | 只起了 postgres，还没起 backend | 建表发生在 backend 启动时，走完阶段 2 再看 |
| 浏览器打不开但 `curl 127.0.0.1:9080` 正常 | 防火墙/安全组,或 caddy 没起来 | 回到 2.4 放通 80/443（**别忘了云厂商安全组**）；再看 `docker compose logs caddy` |
| 页面能开但接口 502 | backend 没起来 | `logs backend` 看真实报错 |
| `caddy` 起不来，报 `address already in use` | `web` 还占着宿主机 80 端口 | 见 3.4 节把 `.env` 的 `ISOFTDEVAGENTS_WEB_PORT` 改成 9080，然后 `docker compose up -d --no-deps web` |
| `caddy` 起不来，报 email 相关的配置解析错误 | `ISOFTDEVAGENTS_ACME_EMAIL` 是空的 | `.env` 里填真实邮箱，`docker compose up -d --force-recreate caddy` |
| 证书签不出来，日志里是超时 / connection refused | 80 端口不通,ACME HTTP-01 验证走不通 | `dig +short gmonkey.ai` 确认解析对；确认系统防火墙**和云安全组**都放通了 80/tcp |
| 日志里出现 `too many certificates already issued` | 撞上 Let's Encrypt 每周 5 张的速率限制 | 通常是反复删 `caddy_data` 卷导致的。等一周，或先用 `Caddyfile` 里的 staging 环境调流程 |
| 浏览器显示证书不受信任 | `Caddyfile` 里 `acme_ca`（staging）没注释回去 | 注释掉那一行，`docker compose stop caddy && docker volume rm iSoftDevAgents_caddy_data`（这次是**故意**清缓存），再起 caddy 重签正式证书 |
| https 页面能开但 WebSocket 连不上 | 前端仍在连 `ws://` 而非 `wss://` | 前端是从 `window.location` 推导协议的，正常不该出现。真出现了就 DevTools 看请求 URL，并确认没有硬编码的 http 地址 |
| Agent 生成跑到一半连接断了 | 两层代理的超时叠加 | `nginx.conf` 已是 3600s、Caddy 用 `flush_interval -1` 关了缓冲；先 `logs caddy` 和 `logs web` 看是哪一层断的 |
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
      - "${ISOFTDEVAGENTS_WEB_PORT:-9080}:80"
```

（`web` 换成挂载模式后，它前面的 caddy 完全不受影响，照旧反代 `web:80`。）

静态产物与架构无关,所以在 Mac 上构建、在 x86 服务器上伺服完全没问题。这个方案还顺带省掉了服务器上 Node 那一整套构建负担。

---

## 8. 日常运维

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

## 9. 上线后建议补的几件事（不阻断本次部署）

1. ~~**HTTPS** —— 目前是纯 HTTP,登录口令明文过网~~ → **已完成**，见第 6 节（Caddy + Let's Encrypt，自动续期）
2. **HSTS** —— 等 HTTPS 稳定跑一两周再开。一旦开启并被浏览器缓存，出问题时**没法快速退回 HTTP**，所以不宜和 HTTPS 改动一起上。要开的话是在 `Caddyfile` 的站点块里加 `header Strict-Transport-Security "max-age=31536000"`
3. **收紧 CORS** —— `agent/platform/app/main.py:86` 是 `allow_origins=["*"]` + `allow_credentials=True`。同源访问没影响,但这个组合本身不该留
4. **日志轮转** —— `ISOFTDEVAGENTS_AGENT_DEBUG_LLM_IO=1` 会把每次模型输入输出（各 12000 字符上限）写文件,跑久了会涨得很快。稳定后可以关掉,或给 `log/` 配 logrotate
5. **单实例限制** —— Agent 通过 subprocess 在 backend 容器内执行,产物先落本地目录再入库,所以**不要横向扩到多实例**
