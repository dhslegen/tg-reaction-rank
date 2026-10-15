# 基础镜像：Astral 官方发布在 GHCR 的 uv 镜像（python:3.12-slim-bookworm + uv）。
# 用 tag + 多架构索引 digest 固定，保证可复现；升级方法见 README「开发」一节。
ARG BASE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58

# ---------- 构建阶段：按 uv.lock 安装依赖到虚拟环境 ----------
FROM ${BASE} AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---------- 运行阶段：同一基础镜像，只带虚拟环境，不带源码 ----------
FROM ${BASE}
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin app \
 && mkdir -p /app/data && chown app:app /app/data
COPY --from=build /app/.venv /app/.venv
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 DATA_DIR=/app/data PORT=8000
WORKDIR /app
VOLUME ["/app/data"]
EXPOSE 8000
# 只检查进程存活；Telegram 未登录不算不健康，否则首次部署会被反复重启
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/healthz', timeout=4)"
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["serve"]
