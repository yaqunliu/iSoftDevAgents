FROM python:3.11-slim

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ARG UV_HTTP_TIMEOUT=600

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    UV_LINK_MODE=copy \
    UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX} \
    UV_HTTP_TIMEOUT=${UV_HTTP_TIMEOUT}

RUN pip install --no-cache-dir uv==0.9.13

WORKDIR /app

# 接口注释：
# 先复制依赖声明文件，尽量利用 Docker 缓存，避免每次改业务代码都重装依赖。
COPY agent/platform/pyproject.toml /app/agent/platform/pyproject.toml
COPY agent/platform/uv.lock /app/agent/platform/uv.lock
COPY agent/platform/README.md /app/agent/platform/README.md
COPY agent/requirements.txt /app/agent/requirements.txt

WORKDIR /app/agent/platform

# 设计注释：
# 平台原本用 uv.lock 锁定了完整依赖树，但锁文件里的源地址和哈希会强绑定官方下载地址。
# 在本地 Docker 网络环境不稳定时，这层绑定反而会让镜像源和超时配置失效。
# 这里退一步，只从 pyproject 读取平台“顶层依赖”，交给 pip 正常解析并安装。
# 这样虽然少了锁文件级别的精确约束，但能显著提高本地和单机服务器部署成功率。
RUN python -c "from pathlib import Path; import tomllib; payload = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8')); deps = payload.get('project', {}).get('dependencies', []); Path('/tmp/platform-direct-requirements.txt').write_text('\\n'.join(deps) + '\\n', encoding='utf-8')" \
    && python -m venv .venv \
    && .venv/bin/pip install --no-cache-dir -r /tmp/platform-direct-requirements.txt

# 原因注释：
# TestAgent 的 `tools/run_py_test.py` 会用 `python -m pytest` 真正执行生成出来的测试。
# pytest 只在 pyproject 的 dev 依赖组里，上面那步不会装它，
# 结果就是容器里测试阶段必然失败。这里显式补上运行期需要的 pytest。
RUN .venv/bin/pip install --no-cache-dir "pytest>=8.4,<9"

# 原因注释：
# 当前 `agent/requirements.txt` 同时混入了多代 CrewAI 与相关依赖，
# 直接硬装进同一个运行环境会触发大量版本冲突。
# 为了让 Docker 更接近本地“共享一个可运行环境”的模式，
# 这里统一把默认启用 Agent 运行期需要的依赖收口到平台后端依赖里安装。
# 这样容器内各个 Agent 回退到共享 python3 时，行为会更接近本地实际运行方式。

WORKDIR /app
COPY agent /app/agent

RUN mkdir -p /app/agent/platform/data /app/agent/platform/log

ENV PATH="/app/agent/platform/.venv/bin:${PATH}"

WORKDIR /app/agent/platform

EXPOSE 9010

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9010"]
