FROM node:24-bookworm-slim AS build

ARG NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
ARG PNPM_FETCH_TIMEOUT=600000
ARG PNPM_FETCH_RETRIES=5
ARG PNPM_VERSION=8.15.5

ENV PNPM_HOME="/pnpm" \
    PATH="/pnpm:${PATH}" \
    NPM_CONFIG_REGISTRY=${NPM_CONFIG_REGISTRY} \
    PNPM_FETCH_TIMEOUT=${PNPM_FETCH_TIMEOUT} \
    PNPM_FETCH_RETRIES=${PNPM_FETCH_RETRIES}

# 原因注释：
# 这份前端 workspace 目前使用的是 lockfileVersion 6，对应 pnpm 8。
# 如果这里放任 corepack 自动拉最新 pnpm 10，Docker 构建会直接因为锁文件格式不兼容而失败。
RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate

WORKDIR /app/frontend

# 接口注释：
# 这里先只复制 workspace 描述文件，尽量让 pnpm install 层稳定复用。
COPY frontend/package.json /app/frontend/package.json
COPY frontend/pnpm-lock.yaml /app/frontend/pnpm-lock.yaml
COPY frontend/pnpm-workspace.yaml /app/frontend/pnpm-workspace.yaml
COPY frontend/tsconfig.json /app/frontend/tsconfig.json
COPY frontend/tsconfig.base.json /app/frontend/tsconfig.base.json
COPY frontend/artifacts/ai-design-platform/package.json /app/frontend/artifacts/ai-design-platform/package.json
COPY frontend/scripts/package.json /app/frontend/scripts/package.json

RUN pnpm install --frozen-lockfile

# 原因注释：
# pnpm 有时不会把 Rollup / esbuild / lightningcss / tailwind-oxide 的可选原生包完整落盘。
# 这会导致 `vite build` 阶段直接报找不到 `@rollup/rollup-linux-<arch>-gnu`。
# 这里继续用 pnpm 自己补装当前平台需要的几个二进制包，避免混用 npm 把 workspace 状态弄乱。
#
# 设计注释：
# 补装的包名带死架构后缀，所以必须按当前构建架构分支。
# 之前这里写死了 arm64（本机 Mac 调通的形态），
# 在 x86_64 服务器上构建时 pnpm 会因为 os/cpu 不匹配直接失败。
# x64 分支的版本号对齐 pnpm-lock.yaml 里已有的 optional 依赖版本。
RUN set -eux; \
    build_arch="$(dpkg --print-architecture)"; \
    if [ "$build_arch" = "arm64" ]; then \
      pnpm add -Dw \
        @rollup/rollup-linux-arm64-gnu@4.60.0 \
        @esbuild/linux-arm64@0.27.4 \
        lightningcss-linux-arm64-gnu@1.32.0 \
        @tailwindcss/oxide-linux-arm64-gnu@4.2.2; \
    else \
      pnpm add -Dw \
        @rollup/rollup-linux-x64-gnu@4.60.1 \
        @esbuild/linux-x64@0.27.7 \
        lightningcss-linux-x64-gnu@1.32.0 \
        @tailwindcss/oxide-linux-x64-gnu@4.2.2; \
    fi

COPY frontend /app/frontend

ARG VITE_API_BASE_URL=/api
ARG BASE_PATH=/

# 资源注释：
# 小内存机器（1~2G）上 rollup 打包容易被 OOM killer 杀掉。
# 通过 NODE_OPTIONS 给 V8 一个明确堆上限，让它到点就 GC。
# 默认留空 = 保持 Node 自己按可用内存推断的行为，不影响大内存机器。
ARG NODE_OPTIONS=""

ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV BASE_PATH=${BASE_PATH}
ENV NODE_OPTIONS=${NODE_OPTIONS}

RUN pnpm --filter @workspace/ai-design-platform run build

FROM nginx:1.27-alpine

COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/artifacts/ai-design-platform/dist/public/ /usr/share/nginx/html/

EXPOSE 80
