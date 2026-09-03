#!/bin/sh
#
# 教学注释：
# 这是「单机服务器正式部署」的可选辅助脚本。
#
# 重要：你完全可以不用它。配置好根目录的 .env 之后，
# 直接在仓库根目录执行下面这条就够了：
#
#     docker compose up -d --build
#
# docker compose 会自动读取 compose 文件同目录下的 .env 做变量插值，
# 不需要 --env-file。
#
# 这个脚本存在的唯一价值是「启动前检查」：
# 1. 确认 .env 存在
# 2. 预建 bind mount 的宿主目录，避免 Docker 用 root 属主创建后你在宿主机读不了日志
# 3. 拦住"忘了改数据库默认口令"这种会把弱口令库挂到公网的情况
# 4. 提醒 LLM Key 还是占位值

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

cd "$REPO_ROOT"

ENV_FILE="$REPO_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: 缺少 $ENV_FILE" >&2
  echo "请先执行：cp .env.server.example .env" >&2
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
  echo "ERROR: .env 里的 POSTGRES_PASSWORD 还是模板占位值。" >&2
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

case "${1:-up}" in
  up)
    exec docker compose up -d --build
    ;;
  logs)
    exec docker compose logs -f --tail=200
    ;;
  ps)
    exec docker compose ps
    ;;
  restart-backend)
    # 教学注释：改完 .env 里的 Key 之后只需要重建 backend，不用动前端和数据库。
    exec docker compose up -d --no-deps --force-recreate backend
    ;;
  down)
    exec docker compose down
    ;;
  *)
    exec docker compose "$@"
    ;;
esac
