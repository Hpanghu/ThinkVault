# ThinkVault Dockerfile
# 基础镜像: CPU 版本 (python:3.10-slim)
# CUDA 变体: 将 FROM 改为 nvidia/cuda:12.1-runtime-ubuntu22.04
#  并通过 pyproject.toml 安装 torch[cuda] 额外依赖

FROM python:3.10-slim

LABEL org.opencontainers.image.title="ThinkVault"
LABEL org.opencontainers.image.description="个人 AI 工作台 — 把本地文档变成可对话的私人图书馆"
LABEL org.opencontainers.image.version="2.0.0"

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 工作目录
WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir python-pptx openpyxl

# 复制应用代码和数据文件
COPY thinkvault/ ./thinkvault/
# 创建数据持久化目录
RUN mkdir -p /data/chroma /data/uploads /data/conversations

# 推理后端说明：
# ThinkVault 使用 OpenAI 兼容 API 模式，推理由外部 llama-cpp-python server 提供。
# 方式一：同一容器网络内运行 llama-cpp-python sidecar（见 docker-compose.yml）
# 方式二：指向外部推理服务地址（设置 THINKVAULT_LLM_URL 环境变量）
# 默认 URL: http://llama-cpp:8080/v1

# 暴露 API 端口
EXPOSE 8000

# 环境变量
ENV PYTHONUNBUFFERED=1
ENV THINKVAULT_DATA_DIR=/data
ENV THINKVAULT_LLM_URL=http://llama-cpp:8080/v1
ENV THINKVAULT_LLM_MODEL=default

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# 非 root 用户运行
RUN useradd -m -u 1000 thinkvault && \
    chown -R thinkvault:thinkvault /app /data
USER thinkvault

# 启动
CMD ["python", "-m", "thinkvault.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
