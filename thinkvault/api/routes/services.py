"""服务管理路由 — 一键启动/停止本地推理服务

提供 WebUI 一键启动 llama-cpp-python server 的能力，
包括服务状态查询、启动、停止和健康检查。
"""

import asyncio
import json
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from thinkvault.api.schemas import ServiceStatus

from thinkvault.core.service_manager import service_manager
from thinkvault.utils.logger import logger

services_router = APIRouter()

# 仅允许本地服务地址
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}

# 启动进度 — 全局状态
_startup_progress: dict = {"status": "idle", "step": "", "message": "", "services": {}}
_startup_lock = threading.Lock()


class ServiceStartRequest(BaseModel):
    """服务启动请求"""
    model_path: str = ""
    model_name: str = ""
    port: int = 8080
    n_ctx: int = 2048
    host: str = "127.0.0.1"
    n_gpu_layers: int = 0


@services_router.get("/api/services/status", response_model=ServiceStatus)
async def get_services_status():
    """获取所有服务状态"""
    return service_manager.get_status()


@services_router.post("/api/services/start")
async def start_services(req: ServiceStartRequest):
    """一键启动本地推理服务

    流程：
    1. 如未指定 model_path，自动扫描本地模型目录选择第一个可用模型
    2. 启动 llama-cpp-python server 子进程
    3. 等待服务就绪
    4. 自动连接到推理后端
    """
    from thinkvault.core.container import container

    # 仅允许本地服务地址
    if req.host not in _ALLOWED_HOSTS:
        raise HTTPException(400, detail=f"仅允许本地服务地址: {', '.join(_ALLOWED_HOSTS)}")

    with _startup_lock:
        _startup_progress["status"] = "starting"
        _startup_progress["message"] = "正在准备启动服务..."

    # Step 1: 确定模型路径
    model_path = req.model_path
    model_name = req.model_name

    if not model_path:
        with _startup_lock:
            _startup_progress["step"] = "scan"
            _startup_progress["message"] = "正在扫描本地模型..."

        models = service_manager.list_local_models()
        if not models:
            with _startup_lock:
                _startup_progress["status"] = "error"
                _startup_progress["message"] = "未找到本地模型，请将 .gguf 文件放入 ~/.thinkvault/models/ 目录"
            return {
                "status": "error",
                "message": "未找到本地模型，请将 .gguf 文件放入 ~/.thinkvault/models/ 目录",
            }

        # 选择第一个模型（或匹配 model_name）
        selected = models[0]
        if model_name:
            for m in models:
                if m["id"] == model_name or m["name"] == model_name:
                    selected = m
                    break

        model_path = selected["path"]
        model_name = selected["name"]

    with _startup_lock:
        _startup_progress["step"] = "start_server"
        _startup_progress["message"] = f"正在启动推理服务 (模型: {model_name})..."
        _startup_progress["services"]["llama_server"] = "starting"

    # Step 2: 启动 llama-cpp-python server
    result = await service_manager.start_llama_server(
        model_path=model_path,
        port=req.port,
        n_ctx=req.n_ctx,
        host=req.host,
        n_gpu_layers=req.n_gpu_layers,
    )

    if result["status"] in ("error",):
        with _startup_lock:
            _startup_progress["status"] = "error"
            _startup_progress["message"] = result["message"]
            _startup_progress["services"]["llama_server"] = "error"
        return result

    # Step 3: 连接到推理后端
    with _startup_lock:
        _startup_progress["step"] = "connect"
        _startup_progress["message"] = "正在连接推理后端..."
        _startup_progress["services"]["llama_server"] = "running"

    base_url = f"http://{req.host}:{req.port}/v1"
    await container.thinkvault_llm.reconfigure(
        base_url=base_url,
        model=model_name,
        api_key="",
    )

    available = await container.thinkvault_llm.check_availability()

    if available:
        with _startup_lock:
            _startup_progress["status"] = "ready"
            _startup_progress["message"] = "所有服务已就绪"
            _startup_progress["services"]["llama_server"] = "running"
            _startup_progress["services"]["backend"] = "connected"
        return {
            "status": "ok",
            "message": "服务启动成功，推理后端已连接",
            "base_url": base_url,
            "model": model_name,
            "services": service_manager.get_status()["services"],
        }
    else:
        with _startup_lock:
            _startup_progress["status"] = "partial"
            _startup_progress["message"] = "推理服务已启动但后端连接失败，请稍后重试"
            _startup_progress["services"]["llama_server"] = "running"
            _startup_progress["services"]["backend"] = "disconnected"
        return {
            "status": "partial",
            "message": "推理服务已启动但后端连接失败，请稍后重试",
            "base_url": base_url,
            "model": model_name,
            "services": service_manager.get_status()["services"],
        }


@services_router.post("/api/services/stop")
async def stop_services():
    """停止所有本地服务"""
    from thinkvault.core.container import container

    # 先断开后端连接
    llm = container.thinkvault_llm
    llm.mark_unavailable()
    await llm.close()

    # 停止所有子进程
    result = await service_manager.stop_all()

    with _startup_lock:
        _startup_progress["status"] = "idle"
        _startup_progress["step"] = ""
        _startup_progress["message"] = ""
        _startup_progress["services"] = {}

    return result


@services_router.get("/api/services/start/progress")
async def services_start_progress():
    """SSE 端点 — 实时推送服务启动进度"""
    async def progress_generator():
        last_status = ""
        while True:
            with _startup_lock:
                current = dict(_startup_progress)
            if current["status"] != last_status or current["status"] == "starting":
                yield f"data: {json.dumps(current, ensure_ascii=False)}\n\n"
                last_status = current["status"]
            if current["status"] in ("ready", "error", "partial", "idle"):
                await asyncio.sleep(0.3)
                yield f"data: {json.dumps(current, ensure_ascii=False)}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        progress_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@services_router.get("/api/services/models")
async def list_available_models():
    """列出本地可用的 GGUF 模型（供启动服务时选择）"""
    models = service_manager.list_local_models()
    return {"models": models, "count": len(models)}
