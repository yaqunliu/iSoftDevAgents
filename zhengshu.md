# gmonkey.ai HTTPS 证书接入方案

> 状态：**代码改动已全部落地，等待在服务器上执行部署**（进度见第 10 节）
> 编写日期：2026-09-03
> 目标：让 `http://gmonkey.ai/` 升级为 `https://gmonkey.ai/`，并做到证书自动续期。

---

## 0. 现状核实（实测数据，不是假设）

下面每一项都是写方案前实际探测过的，它们直接决定了方案怎么选。

| 项 | 实测结果 | 对方案的影响 |
|---|---|---|
| `gmonkey.ai` A 记录 | → `79.108.225.95` ✅ | HTTP-01 验证可用 |
| `www.gmonkey.ai` | **无 A 记录** | 本次证书**不覆盖** www，见第 1 节 |
| `http://gmonkey.ai/` | HTTP 200 ✅ | 80 端口通，ACME 挑战能落地 |
| `79.108.225.95:443` | **closed / filtered** 🔴 | 必须放通，见第 4 节 |
| 前端 API 基地址 | `docker-compose.yml:112` 里 `VITE_API_BASE_URL: ""` = 同源 | **不需要重新构建前端** |
| 前端 WebSocket | `project-websocket-url.ts:26` 按页面协议自动切 `ws`/`wss` | 页面变 https 后自动走 wss |
| 前端硬编码 `http://` | 无（`use-api.ts:13` 仅 localhost 兜底） | 无混合内容（mixed content）风险 |
| 机器规格 | 1.6G 内存 / 2 核 / 已加 swap | 新增容器必须挑轻量的 |

**结论：前端代码一行都不用改。** 这是本方案成立的关键前提——因为前端打包时 API 地址就是空字符串（同源），WebSocket 地址也是从 `window.location` 推导的，所以页面一旦通过 https 打开，API 和 WebSocket 会自动跟着变成 `https` / `wss`。

---

## 1. 证书覆盖范围

**本次只签裸域 `gmonkey.ai`。**

原因：`www.gmonkey.ai` 目前没有 A 记录。Let's Encrypt 会对证书里写的**每一个**域名做验证，只要有一个解析不到，**整次签发都会失败**——不是"跳过那一个"，是全盘失败。

以后要加 `www`：先在 DNS 加一条 `www` 的 A 记录指向 `79.108.225.95`，等生效后在 `Caddyfile` 里把域名补上，重启 caddy 容器即可重新签发。成本很低，不必现在为它阻塞上线。

---

## 2. 方案选择

### 方案 A：前置 Caddy 容器（**已选定**）

新增一个 `caddy` 容器占住宿主机 80/443，反向代理到现有 `web:80`。Caddy 内置 ACME 客户端，首次启动自动签发，到期自动续期。

- **优点**
  - 改动最小：不动 `nginx.conf`，不动前端镜像
  - 没有"先有鸡先有蛋"问题（见下方对比）
  - 续期零维护：不需要 cron，不需要 reload 钩子
- **代价**：多一个常驻容器。Caddy 是静态二进制，常驻约 20–40MB，这台 1.6G 的机器可以接受

### 方案 B：现有 nginx 直接上 TLS + certbot（未采用）

- **优点**：不增加常驻进程
- **代价**
  - `nginx.conf` 必须拆成"签发前 / 签发后"两套。因为 nginx 的 443 server 块如果引用了还不存在的证书文件，进程直接起不来——而证书又必须等 nginx 起来响应 ACME 挑战才能签出来。这就是上面说的先有鸡先有蛋
  - 要额外挂 `/var/www/certbot` 和 `/etc/letsencrypt` 两个卷
  - 续期要单独配定时任务 + `nginx -s reload` 钩子

步骤明显更多、出错面更大，所以不采用。

---

## 3. 前置条件（动代码之前必须先确认）

1. **准备一个真实邮箱**给 Let's Encrypt，用于证书到期提醒。
   真实值只写在服务器的 `.env` 里，**不进仓库**；`.env.server.example` 里只放占位示例。
2. **放通 443 端口**（两层都要开，缺一不可）：
   - 系统防火墙：命令见第 4 节
   - **云厂商安全组**：只能在控制台操作。部署手册第 2.4 节踩过这个坑——系统里开了但安全组没开，从外面照样访问不到

---

## 4. 代码改动清单

> ✅ 下面全部已落地。实际实施时比原方案多做了三处，已在表格里标出。

| 文件 | 动作 | 内容 | 状态 |
|---|---|---|---|
| `deploy/docker/Caddyfile` | **新增** | 单域名；反代到 `web:80`；HTTP→HTTPS 跳转；WebSocket 透传；`flush_interval -1` 关响应缓冲 | ✅ |
| `docker-compose.yml` | 改 | 新增 `caddy` 服务（占 80/443，挂 `caddy_data`、`caddy_config` 两个**具名卷**）；`web` 的端口发布收回到 `127.0.0.1:9080:80` | ✅ |
| `.env.server.example` | 改 | 新增 `ISOFTDEVAGENTS_SITE_DOMAIN`、`ISOFTDEVAGENTS_ACME_EMAIL` 并写注释；`ISOFTDEVAGENTS_WEB_PORT` 改 9080 且注释成"仅本机调试" | ✅ |
| `deploy/SERVER-DEPLOY.md` | 改 | 新增第 6 节 HTTPS；第 9 节"上线后建议补的几件事"里 HTTPS 一条标记为已完成 | ✅ |
| `deploy/docker/nginx.conf` | **不动** | 继续只监听 80，处在 Caddy 后面 | ✅ |
| 前端全部代码 | **不动** | 同源配置下自动跟随 https / wss | ✅ |
| **［追加］** `docker-compose.yml` | 改 | `caddy` 挂 `profiles: ["https"]`；`.env.server.example` 里加 `COMPOSE_PROFILES=https` 做总开关 | ✅ |
| **［追加］** `deploy/docker/run-server.sh` | 改 | 开了 https profile 但域名为空 / 邮箱还是占位值时，启动前直接拦住报错（和已有的口令检查同一套路） | ✅ |
| **［追加］** `deploy/docker/Caddyfile` | 改 | 全局块加 `protocols h1 h2` 关掉 HTTP/3 | ✅ |

### 三处追加的原因

**其一，`profiles: ["https"]` + `COMPOSE_PROFILES` 开关。**
原方案没考虑本地开发：如果 `caddy` 是普通服务，Mac 上一执行 `docker compose up` 就会冒出一个抢 80/443、还去给 `gmonkey.ai` 反复申请证书的容器——反复签发正好会撞上第 8 节说的速率限制。挂上 profile 后，只有服务器 `.env` 里设了 `COMPOSE_PROFILES=https` 才会带上它。已实测确认 `docker compose` 会从 `.env` **文件**读这个变量，不必导出成 shell 环境变量。

**其二，`run-server.sh` 的启动前检查。**
`ISOFTDEVAGENTS_ACME_EMAIL` 留空时，Caddyfile 里的 `email {$...}` 会变成一个没有参数的指令，Caddy 报的是相当难读的配置解析错误。提前拦住，把问题说清楚。

**其三，关掉 HTTP/3。**
HTTP/3 走 **UDP** 443，而本方案和云安全组只放通了 **TCP** 443。留着 h3 的话，Caddy 会在响应头里通告一个根本连不上的 h3 端点，浏览器要先尝试失败再回落到 TCP，白白多一次往返。

### ⚠️ 两个关键点

**其一：`caddy_data` 必须是具名卷。**
证书就存在这个卷里。容器重建但卷保留 → 不会重复签发 → 不会撞 Let's Encrypt 的速率限制（同一组域名每周 5 张）。如果这里用了匿名卷或者不挂卷，每次 `docker compose up --build` 都会重新签一次，五次之后这一周就签不出来了。

**其二：`web` 必须从 80 端口退下来。**
外网流量一律经 Caddy 进入，`web` 只保留 `127.0.0.1:9080` 供服务器本机调试。否则 80 端口会和 Caddy 冲突。

---

## 5. 执行步骤（服务器上）

### 5.0 先放通 443

```bash
# 先看用的是哪套防火墙
command -v ufw && ufw status
command -v firewall-cmd && firewall-cmd --state
iptables -L INPUT -n | head -20
```

按结果选一条执行：

```bash
# ufw（Ubuntu/Debian 常见）
ufw allow 443/tcp && ufw reload && ufw status

# firewalld（CentOS/Rocky/Alma 常见）
firewall-cmd --permanent --add-port=443/tcp && firewall-cmd --reload

# 纯 iptables
iptables -I INPUT -p tcp --dport 443 -j ACCEPT
apt-get install -y iptables-persistent && netfilter-persistent save
```

**别忘了云厂商控制台的安全组，也要放通 443/tcp。**

### 5.1 同步代码

在 Mac 上执行（沿用部署手册第 1 节的命令，注意保持 `--exclude '.env'`，否则带 `--delete` 的同步会把服务器上的 `.env` 删掉）：

```bash
cd /Users/user/Documents/work/code/iSoftDevAgents

rsync -avz --delete \
  --exclude '.git' --exclude '.DS_Store' --exclude 'node_modules' \
  --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '.pytest_cache' --exclude '.env' \
  --exclude 'deploy/docker/backend.env' \
  --exclude 'agent/platform/data' --exclude 'agent/platform/log' \
  --exclude 'frontend/artifacts/ai-design-platform/dist' \
  ./ root@79.108.225.95:/root/iSoftDevAgents/
```

### 5.2 补充服务器 `.env`

服务器上现有的 `.env` 是从旧模板复制的：里面是 `ISOFTDEVAGENTS_WEB_PORT=80`，另外三个变量都还没有。**四个都要处理，不是只加域名和邮箱。**

```bash
ssh root@79.108.225.95
cd /root/iSoftDevAgents

# 1. 先让 web 从 80 退到 9080——不改这条，caddy 会因端口冲突起不来
sed -i 's|^ISOFTDEVAGENTS_WEB_PORT=.*|ISOFTDEVAGENTS_WEB_PORT=9080|' .env

# 2. 追加另外三个变量（注意把邮箱换成你自己的真实邮箱）
cat >> .env <<'EOF'
ISOFTDEVAGENTS_WEB_BIND_HOST=127.0.0.1
COMPOSE_PROFILES=https
ISOFTDEVAGENTS_SITE_DOMAIN=gmonkey.ai
ISOFTDEVAGENTS_ACME_EMAIL=你的真实邮箱
EOF

# 3. 确认四个值都对
grep -E '^(COMPOSE_PROFILES|ISOFTDEVAGENTS_SITE_DOMAIN|ISOFTDEVAGENTS_ACME_EMAIL|ISOFTDEVAGENTS_WEB_PORT|ISOFTDEVAGENTS_WEB_BIND_HOST)=' .env
```

`COMPOSE_PROFILES=https` 是 caddy 的总开关，`docker compose` 会直接从 `.env` 文件读它，不需要 `export`。设好之后后续 `docker compose up -d --build` 会自动带上 caddy。

### 5.3 按顺序启动（**顺序不能反**）

```bash
# 第一步：先让 web 退到 9080，把 80 端口腾出来
docker compose up -d --no-deps web

# 第二步：再起 caddy，它会接管 80/443 并自动签发证书
docker compose up -d caddy

# 第三步：盯日志，等待签发成功
docker compose logs -f caddy
```

> **为什么必须是这个顺序？**
> Caddy 启动的瞬间就要占 80 端口。如果 `web` 还占着 80，caddy 会直接因端口冲突起不来。所以必须先让 web 退下去。

看到日志里出现 `certificate obtained successfully` 就是签发成功。

---

## 6. 验证清单

### 6.1 命令行验证

```bash
# 1. 证书签发成功且证书链完整
curl -vI https://gmonkey.ai/ 2>&1 | grep -E "issuer|subject|HTTP/"

# 2. HTTP 自动跳转 HTTPS（期望 308）
curl -sI http://gmonkey.ai/ | head -3

# 3. API 经两层代理（caddy → nginx → backend）仍然通
curl -s https://gmonkey.ai/api/healthz

# 4. 容器状态与内存占用，确认没把这台小机器压垮
docker compose ps && docker stats --no-stream
```

### 6.2 浏览器人工验证（curl 覆盖不到，必须做）

1. **WebSocket 握手**：打开一个项目，看 DevTools → Network，确认
   `wss://gmonkey.ai/api/projects/<id>/ws` 返回 **101 Switching Protocols**
2. **长任务不断流**：完整跑一次 Agent 生成，确认几分钟的长连接没被代理层掐断。
   现有 nginx 配了 3600s 超时（`nginx.conf:29-31`），Caddy 默认对流式响应不做缓冲，理论上没问题，**但必须实测**——只看 `healthz` 通过不能说明长连接没问题。

---

## 7. 回滚方案

改动全部是**加法**，回滚很干净——而且落地后端口是走 `.env` 变量的，**不需要改 `docker-compose.yml`**：

```bash
docker compose stop caddy

# .env 里改三行：web 重新对外占 80，并关掉 caddy 的 profile 开关
sed -i 's|^ISOFTDEVAGENTS_WEB_BIND_HOST=.*|ISOFTDEVAGENTS_WEB_BIND_HOST=0.0.0.0|' .env
sed -i 's|^ISOFTDEVAGENTS_WEB_PORT=.*|ISOFTDEVAGENTS_WEB_PORT=80|' .env
sed -i 's|^COMPOSE_PROFILES=|#COMPOSE_PROFILES=|' .env

docker compose up -d --no-deps web
```

即可回到 `http://79.108.225.95/` 的纯 HTTP 状态。证书留在 `caddy_data` 卷里，不影响下次再开启。

> 注意最后一行 `sed` 把 `COMPOSE_PROFILES` 注释掉这一步不能省：不注释的话，下次 `docker compose up -d --build` 又会把 caddy 拉起来，和已经退回 80 的 web 抢端口。

---

## 8. 风险点与处置

| 风险 | 说明 | 处置 |
|---|---|---|
| **速率限制** | 反复重建容器且证书卷没保住，会耗尽每周 5 次配额 | 用具名卷；调试阶段可先用 Let's Encrypt **staging** 环境跑通流程，再切正式环境 |
| **端口冲突** | Caddy 和 web 抢 80 | 严格按第 5.3 节顺序执行 |
| **内存不足** | 这台机只有 1.6G，多一个常驻容器 | Caddy 占用很小，但上线后用 `docker stats` 实测确认一次 |
| **长连接被掐** | 两层代理叠加，超时策略可能不一致 | 必须实测一次完整 Agent 生成，不能只看 healthz |
| **DNS 未生效** | 若以后加 www 但记录没生效就签发 | 整次签发会失败；先 `dig` 确认再签 |

---

## 9. 本次不做、但建议排期的事

1. **HSTS** —— 等 HTTPS 稳定跑一两周再开。
   一旦开启且被浏览器缓存，出问题时**没法快速退回 HTTP**，所以不宜和本次改动一起上。
2. **收紧 CORS** —— `agent/platform/app/main.py:85-87` 是 `allow_origins=["*"]` + `allow_credentials=True`。
   同源部署下没有实际影响，但这个组合本身不该留，建议改成显式域名白名单。
3. **日志轮转** —— 与本次无关，但 `ISOFTDEVAGENTS_AGENT_DEBUG_LLM_IO=1` 会持续写文件，跑久了会涨得很快。

---

## 10. 待办

**代码部分（本机，已完成）**

- [x] 实施第 4 节的代码改动
- [x] 校验 `docker compose config`：默认不含 caddy、`COMPOSE_PROFILES=https` 时含 caddy
- [x] 实测确认 `docker compose` 会从 `.env` **文件**读取 `COMPOSE_PROFILES`
- [x] 确认 caddy 与 web 同在 `default` 网络，`reverse_proxy web:80` 可解析
- [ ] `caddy validate` 校验 Caddyfile 语法 —— **本机 Docker daemon 未运行，没跑成**，改在服务器上 5.3 起容器时验证（配置错的话 caddy 会直接启动失败并打出错误行）

**部署部分（服务器，待执行）**

- [ ] 提供一个真实邮箱给 Let's Encrypt
- [ ] 系统防火墙放通 443/tcp
- [ ] **云厂商安全组**放通 443/tcp（只能在控制台操作）
- [ ] 按第 5 节执行部署（注意 5.2 要改 / 加**四个**变量）
- [ ] 完成第 6 节全部验证项（含浏览器人工验证两项）
