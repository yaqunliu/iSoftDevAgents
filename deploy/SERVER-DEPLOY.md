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
| `deploy/docker/backend.env.server.example` | 新增服务器专用 env 模板 | 镜像源改回官方源（机器在海外，国内镜像会超时）、端口改 80、强制改数据库口令 |
| `deploy/docker/run-server.sh` | 新增服务器部署入口 | 显式 `--env-file`，带启动前检查，不依赖 shell 是否 export 过变量 |

本地开发流程（`run-local.sh` + 清华镜像 + arm64）**未受影响**。

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
  --exclude 'agent/platform/data' \
  --exclude 'agent/platform/log' \
  --exclude 'frontend/artifacts/ai-design-platform/dist' \
  ./ root@79.108.225.95:/opt/isoftdevagents/
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

**判断标准：**

- `uname -m` = `x86_64` → 我改的 x64 分支生效，继续
- `uname -m` = `aarch64` → 也没问题，走 arm64 分支
- **磁盘剩余 < 15G → 先清理再继续**。后端镜像装的是 crewai[tools] 全家桶（onnxruntime / pyarrow / lancedb 等），预计镜像 2.5–3.5GB，构建峰值要 ~10GB
- **内存 < 4G → 先做第 2.3 步加 swap**，否则前端 `vite build` 大概率 OOM 被杀

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

### 2.3 内存不足时加 swap（内存 ≥ 4G 可跳过）

```bash
free -h | grep -i swap    # 先看有没有现成的 swap

# 如果没有，加 4G：
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
free -h
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
cd /opt/isoftdevagents
cp deploy/docker/backend.env.server.example deploy/docker/backend.env
chmod 600 deploy/docker/backend.env
```

### 3.1 必须改的两处（不改起不来）

生成一个强口令：

```bash
openssl rand -hex 24
```

把输出填进两个地方，**两处必须一致**：

```bash
vi deploy/docker/backend.env
```

```bash
POSTGRES_PASSWORD=<刚生成的口令>
DATABASE_URL=postgresql://isoftdev:<刚生成的口令>@postgres:5432/isoftdev
```

或者用命令一次改掉：

```bash
PGPASS=$(openssl rand -hex 24)
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PGPASS}|" deploy/docker/backend.env
sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://isoftdev:${PGPASS}@postgres:5432/isoftdev|" deploy/docker/backend.env
grep -E '^(POSTGRES_PASSWORD|DATABASE_URL)=' deploy/docker/backend.env
```

### 3.2 LLM Key（本次先占位）

按你的选择，`ISOFTDEVAGENTS_LLM_API_KEY` 保持占位值 `REPLACE-WITH-YOUR-REAL-KEY`。

启动脚本会打一条 WARNING 然后照常启动。这个状态下：

- ✅ 前端页面、注册登录、建项目、数据库、WebSocket —— 都能验证
- ❌ 五个 Agent 的生成链路 —— 全部不可用

拿到真实 Key 后：

```bash
cd /opt/isoftdevagents
sed -i 's|^ISOFTDEVAGENTS_LLM_API_KEY=.*|ISOFTDEVAGENTS_LLM_API_KEY=你的真实key|' deploy/docker/backend.env
./deploy/docker/run-server.sh restart-backend
```

同时确认 `ISOFTDEVAGENTS_LLM_BASE_URL` 和 `ISOFTDEVAGENTS_LLM_MODEL` 跟你的服务商对得上。

---

## 4. 构建并启动

```bash
cd /opt/isoftdevagents
./deploy/docker/run-server.sh up
```

**首次构建预计 15–40 分钟**（后端要装 crewai 全家桶，前端要装 ~1000 个 npm 包）。中途别 Ctrl-C。

想看实时构建过程就前台跑：

```bash
docker compose --env-file deploy/docker/backend.env up --build
```

启动后看状态：

```bash
./deploy/docker/run-server.sh ps
./deploy/docker/run-server.sh logs
```

---

## 5. 验证

按顺序跑，每一步都该有明确输出：

```bash
# 1. 三个容器都在，backend 应该是 healthy
docker compose --env-file deploy/docker/backend.env ps

# 2. 后端健康检查（服务器本机）
curl -s http://127.0.0.1:9010/api/healthz

# 3. 数据库建表成功（应该看到 17 张表）
docker compose --env-file deploy/docker/backend.env exec postgres \
  psql -U isoftdev -d isoftdev -c '\dt'

# 4. Alembic 迁移跑过了
docker compose --env-file deploy/docker/backend.env logs backend --tail=300 \
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
cd /opt/isoftdevagents
ENVF="--env-file deploy/docker/backend.env"

docker compose $ENVF logs backend  --tail=200
docker compose $ENVF logs web      --tail=100
docker compose $ENVF logs postgres --tail=50
```

### 常见故障对照

| 现象 | 原因 | 处理 |
|---|---|---|
| 前端构建报 `Cannot find module @rollup/rollup-linux-x64-gnu` | 架构分支没生效 | `uname -m` 确认架构；`docker compose build --no-cache web` 重建 |
| 前端构建被 `Killed` / 退出码 137 | 内存不足,OOM | 回到 2.3 加 swap;或在 Mac 上构建后 `docker save`/`load` 推镜像 |
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

---

## 7. 日常运维

```bash
cd /opt/isoftdevagents

./deploy/docker/run-server.sh ps                # 看状态
./deploy/docker/run-server.sh logs              # 跟日志
./deploy/docker/run-server.sh restart-backend   # 只重启后端(改完 env 用这个)
./deploy/docker/run-server.sh down              # 停服务(数据卷保留)
./deploy/docker/run-server.sh up                # 重新构建启动
```

### 更新代码

在 Mac 上重跑第 1 步的 rsync，然后服务器上：

```bash
cd /opt/isoftdevagents && ./deploy/docker/run-server.sh up
```

### 数据在哪

| 数据 | 位置 | 备份方式 |
|---|---|---|
| 业务数据（17 张表：项目/消息/产物/代码文件/版本…） | Docker 卷 `pgdata` | `docker compose $ENVF exec postgres pg_dump -U isoftdev isoftdev > backup.sql` |
| 上传文件、Agent 调试包 | 宿主机 `/opt/isoftdevagents/agent/platform/data` | 直接 tar |
| LLM 调试日志 | 宿主机 `/opt/isoftdevagents/agent/platform/log` | 会持续增长,注意清理 |

> `down` 不会删数据卷。**只有 `down -v` 才会删库**,别手滑。

---

## 8. 上线后建议补的几件事（不阻断本次部署）

1. **HTTPS** —— 目前是纯 HTTP,登录口令明文过网。建议在前面加 Caddy 或用 certbot 配 Let's Encrypt
2. **收紧 CORS** —— `agent/platform/app/main.py:86` 是 `allow_origins=["*"]` + `allow_credentials=True`。同源访问没影响,但这个组合本身不该留
3. **日志轮转** —— `ISOFTDEVAGENTS_AGENT_DEBUG_LLM_IO=1` 会把每次模型输入输出（各 12000 字符上限）写文件,跑久了会涨得很快。稳定后可以关掉,或给 `log/` 配 logrotate
4. **单实例限制** —— Agent 通过 subprocess 在 backend 容器内执行,产物先落本地目录再入库,所以**不要横向扩到多实例**
