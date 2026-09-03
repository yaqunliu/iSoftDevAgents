#!/bin/sh
#
# 教学注释：
# 这是「单机服务器正式部署」入口，和本地测试用的 run-local.sh 分开。
# 两者的差别：
# 1. 这里显式用 --env-file 把 deploy/docker/backend.env 交给 docker compose，
#    不依赖当前 shell 是否 export 过变量，重启服务器后行为一致。
# 2. 这里不关 BuildKit。run-local.sh 关掉是为了绕开本机的构建缓存损坏问题，
#    服务器上开着 BuildKit 缓存命中更好。
# 3. 这里会先做几项启动前检查，避免带着占位密钥、缺目录的状态跑起来。

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

cd "$REPO_ROOT"

ENV_FILE="$REPO_ROOT/deploy/docker/backend.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: 缺少 $ENV_FILE" >&2
  echo "请先执行：cp deploy/docker/backend.env.server.example deploy/docker/backend.env" >&2
  echo "然后把里面的占位值改成真实值。" >&2
  exit 1
fi

# 设计注释：
# 这两个宿主目录是 backend 的 bind mount 源。
# 如果不预先建好，Docker 会自动以 root 属主创建，
# 后续想在宿主机上翻日志或产物就会各种 Permission denied。
mkdir -p "$REPO_ROOT/agent/platform/data" "$REPO_ROOT/agent/platform/log"

# 原因注释：
# 数据库口令沿用模板里的占位值，等于公网上一台带弱口令的库。
# 这里直接拦住，不给"忘了改"留机会。
if grep -q '^POSTGRES_PASSWORD=CHANGE-ME-strong-password' "$ENV_FILE"; then
  echo "ERROR: $ENV_FILE 里的 POSTGRES_PASSWORD 还是模板占位值。" >&2
  echo "请改成你自己的强口令，并同步改 DATABASE_URL 里的同一个密码。" >&2
  exit 1
fi

# 教学注释：
# LLM Key 只警告不拦截。
# 平台本身（注册登录、建项目、前后端联通、数据库）可以先在没有 Key 的情况下验证，
# 只有 Agent 生成链路会失效。填好 Key 后重启 backend 即可生效。
if grep -q '^ISOFTDEVAGENTS_LLM_API_KEY=REPLACE-WITH-YOUR-REAL-KEY' "$ENV_FILE"; then
  echo "WARNING: ISOFTDEVAGENTS_LLM_API_KEY 仍是占位值。" >&2
  echo "         平台可以启动，但五个 Agent 都无法真正生成产物。" >&2
  echo "         填好之后执行：$0 restart-backend" >&2
  echo "" >&2
fi

COMPOSE="docker compose --env-file $ENV_FILE"

case "${1:-up}" in
  up)
    exec $COMPOSE up -d --build
    ;;
  logs)
    exec $COMPOSE logs -f --tail=200
    ;;
  ps)
    exec $COMPOSE ps
    ;;
  restart-backend)
    # 教学注释：改完 env 里的 Key 之后只需要重建 backend，不用动前端和数据库。
    exec $COMPOSE up -d --no-deps --force-recreate backend
    ;;
  down)
    exec $COMPOSE down
    ;;
  *)
    exec $COMPOSE "$@"
    ;;
esac
