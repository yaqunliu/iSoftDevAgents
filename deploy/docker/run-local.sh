#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

cd "$REPO_ROOT"

# 教学注释：
# 本地 Docker 测试和“直接在宿主机跑后端”是两套不同场景。
# 这里专门只读取 deploy/docker 下的私有 env 文件，
# 避免把宿主机自己的 Python 路径、日志路径之类偷偷带进容器。
load_env_file() {
  target="$1"
  if [ -f "$target" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$target"
    set +a
  fi
}

load_env_file "$REPO_ROOT/deploy/docker/backend.env"
load_env_file "$REPO_ROOT/deploy/docker/backend.env.local"

# 设计注释：
# 这里默认把本地 Docker 构建切到更稳的模式。
# 一方面明确走 legacy builder，避开之前磁盘写满后 BuildKit 数据库损坏带来的假死；
# 另一方面给构建阶段补国内依赖镜像，减少 Python / Node 依赖在海外源上的超时。
export DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-0}"
export COMPOSE_DOCKER_CLI_BUILD="${COMPOSE_DOCKER_CLI_BUILD:-0}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export NPM_CONFIG_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmmirror.com}"

exec docker compose up --build "$@"
