# my-agent —— 一键容器化部署
# 构建:  docker build -t my-agent .
# 运行:  docker run --rm -p 127.0.0.1:8000:8000 -e AGENT_API_TOKEN=你的令牌 my-agent
# 或用 docker compose up(推荐,见 docker-compose.yml)。

FROM python:3.12-slim

# 运行期工具:git 供个别依赖,curl 供健康检查;装完即清缓存,保持镜像精简。
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先拷依赖声明,利用 Docker 层缓存(源码变动不必重装依赖)。
COPY pyproject.toml ./
# 再拷源码并安装(含真实模型/Web/记忆/渠道全部 extras)。
COPY . .
RUN pip install --no-cache-dir -e ".[all]"

# 容器内默认绑 0.0.0.0(由宿主机端口映射控制可达范围);数据落在挂载卷 /app/logs。
ENV AGENT_PROJECT_ROOT=/app \
    AGENT_LOG_DIR=/app/logs \
    AGENT_WEB_HOST=0.0.0.0 \
    AGENT_WEB_PORT=8000 \
    AGENT_PROVIDER=mock

EXPOSE 8000

# 健康检查:Web 首页可访问即视为健康。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${AGENT_WEB_PORT}/" >/dev/null || exit 1

# ⚠ 容器内非本机访问会要求 AGENT_API_TOKEN(见 /ws 与 /api/* 鉴权)。
# 对外暴露务必通过 -e AGENT_API_TOKEN=... 设置令牌。
CMD ["myagent-web"]
