"""API 服务入口 — V2.0"""

import os
import secrets
import threading
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pathlib import Path
from dotenv import load_dotenv

from thinkvault.api.routes import router
from thinkvault.utils.logger import logger
from thinkvault import __version__ as _app_version

# 自动加载项目根目录 .env 文件
# 设置 THINKVAULT_DISABLE_AUTH=1 可跳过加载（供 TestClient 集成测试使用）
if not os.environ.get("THINKVAULT_DISABLE_AUTH"):
    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)

# ---- API Token 认证 ----
# 设置 THINKVAULT_API_TOKEN 环境变量启用认证；未设置则跳过（开发模式）
THINKVAULT_API_TOKEN = os.environ.get("THINKVAULT_API_TOKEN", "")
_security = HTTPBearer(auto_error=False)

if not THINKVAULT_API_TOKEN:
    logger.warning("THINKVAULT_API_TOKEN 未设置，API 认证已禁用（开发模式）。生产环境请设置此环境变量。")


async def verify_api_token(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
    request: Request = None,
):
    """API Token 认证依赖。TOKEN 未配置时：
    - 仅允许 localhost/127.0.0.1 访问（开发模式安全降级）
    - 非 localhost 请求返回 401
    - THINKVAULT_DISABLE_AUTH=1 时完全跳过（供测试使用）"""
    if os.environ.get("THINKVAULT_DISABLE_AUTH"):
        return True
    if not THINKVAULT_API_TOKEN:
        # 开发模式：未设置 token 时仅允许本地访问
        if request:
            client_host = request.client.host if request.client else ""
            if client_host not in ("127.0.0.1", "::1", "localhost"):
                raise HTTPException(
                    status_code=401,
                    detail="未设置 API Token 时仅允许本地访问，请设置 THINKVAULT_API_TOKEN 环境变量",
                )
        return True
    # 1) Bearer header
    if credentials and secrets.compare_digest(credentials.credentials, THINKVAULT_API_TOKEN):
        return True
    # 2) Query parameter (for SSE/EventSource which cannot set headers)
    if request:
        query_token = request.query_params.get("token", "")
        if query_token and secrets.compare_digest(query_token, THINKVAULT_API_TOKEN):
            return True
    raise HTTPException(status_code=401, detail="未提供认证令牌，请在 Authorization header 或 ?token= 参数中传入")

# CORS origins — 明确指定 WebUI 实际端口，生产环境可通过环境变量覆盖
# 设置 THINKVAULT_CORS_ORIGINS="https://yourdomain.com" 进行白名单控制
CORS_ORIGINS = os.environ.get(
    "THINKVAULT_CORS_ORIGINS",
    "http://127.0.0.1:8000,http://localhost:8000"
).split(",")

# ── 速率限制配置 ──
# 注意：当前为内存存储，服务重启后所有计数器归零，不会持久化到磁盘。
# 对于单机部署场景，重启重置是合理行为；若需跨重启保留状态，
# 可将 _rate_limit_store 替换为 Redis / SQLite 等持久化后端。
_RATE_LIMIT_REQUESTS = int(os.environ.get("THINKVAULT_RATE_LIMIT", "60"))   # 每窗口最大请求数
_RATE_LIMIT_WINDOW = int(os.environ.get("THINKVAULT_RATE_WINDOW", "60"))    # 窗口秒数
_rate_limit_store: dict[str, list[float]] = {}  # IP -> [timestamps]
import asyncio
_rate_limit_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 — 后台加载 Embedding 模型避免阻塞服务启动"""
    logger.info("ThinkVault API 服务启动 (V2.0)")

    # v2.1+ 迁移旧版独立数据库到统一 thinkvault.db
    from thinkvault.core.db import migrate_to_unified_db
    migrate_to_unified_db()

    # v2.1+ 初始化预置角色
    from thinkvault.config import ensure_builtin_roles
    ensure_builtin_roles()

    # 后台线程加载 Embedding 模型（首次可能需从 HuggingFace 下载，耗时较长）
    from thinkvault.core.container import container
    _embedder_thread = threading.Thread(
        target=container.embedder.load, daemon=True, name="embedder-loader"
    )
    _embedder_thread.start()
    logger.info("Embedding 模型后台加载中，健康检查和模型管理端点立即可用")

    # 启动后台任务管理器
    from thinkvault.core.task_manager import task_manager
    task_manager.start()

    # 预热检索缓存（Embedding 模型 + BM25 索引）
    try:
        container.retriever.warmup()
    except Exception as e:
        logger.warning(f"检索缓存预热失败（不影响运行）: {e}")

    yield

    # 停止后台任务管理器
    from thinkvault.core.task_manager import task_manager
    await task_manager.stop()

    # 清理所有核心服务资源（embedding 模型、httpx 连接池等）
    from thinkvault.core.container import container
    container.unload_all()

    # 停止服务管理器中的子进程
    from thinkvault.core.service_manager import service_manager
    import asyncio
    await service_manager.stop_all()
    service_manager.stop_monitor()

    logger.info("ThinkVault API 服务关闭")


def create_app() -> FastAPI:
    app = FastAPI(
        title="ThinkVault",
        description="个人 AI 工作台 — 把本地文档变成可对话的私人图书馆",
        version="2.0.0",
        lifespan=lifespan,
    )

    # ── CORS 中间件（必须在速率限制之前，确保 429 响应也带 CORS 头）──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "PATCH"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # ── 速率限制中间件（滑动窗口，基于 IP）──
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        import time as _time
        from fastapi.responses import JSONResponse
        client_ip = request.client.host if request.client else "unknown"
        now = _time.time()
        window_start = now - _RATE_LIMIT_WINDOW

        async with _rate_limit_lock:
            # 清理过期记录
            timestamps = _rate_limit_store.get(client_ip, [])
            timestamps = [t for t in timestamps if t > window_start]

            if len(timestamps) >= _RATE_LIMIT_REQUESTS:
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"请求过于频繁，请 {_RATE_LIMIT_WINDOW}s 后重试"},
                )

            timestamps.append(now)
            _rate_limit_store[client_ip] = timestamps
        return await call_next(request)

    # ── API 路由挂载 ──
    app.include_router(router, dependencies=[Depends(verify_api_token)])

    # 添加版本响应头到所有 HTTP 响应
    @app.middleware("http")
    async def add_version_header(request, call_next):
        response = await call_next(request)
        response.headers["X-ThinkVault-Version"] = _app_version
        return response

    webui_dir = Path(__file__).parent.parent / "webui"
    if webui_dir.exists():
        app.mount("/", StaticFiles(directory=str(webui_dir), html=True), name="webui")

    return app


def run_server(host: str = "127.0.0.1", port: int = 8000):
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()
