"""模型管理路由 — 后端探测 / 状态 / 硬件检测 / 健康检查

ThinkVault 使用 OpenAI 兼容 API 模式，推理委托给外部后端（llama-cpp-python server 等）。
模型加载/卸载由外部后端管理，本模块仅提供后端可用性探测与状态查询。
"""

import asyncio
import json
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from thinkvault.core.container import container
from thinkvault.utils.hardware import detect_hardware
from thinkvault.utils.logger import logger
from thinkvault.utils.security import validate_url_for_ssrf
from thinkvault import __version__

from thinkvault.api.schemas import (
    ModelLoadRequest, ModelInfo, HardwareInfo, ModelListResponse, ModelListItem,
)

model_router = APIRouter()

# 后端探测进度 — 全局状态（跨请求共享）
_model_load_progress: dict = {"status": "idle", "progress": 0, "message": ""}
_progress_lock = threading.Lock()


def _set_progress(status: str, progress: float, message: str):
    with _progress_lock:
        _model_load_progress["status"] = status
        _model_load_progress["progress"] = progress
        _model_load_progress["message"] = message


@model_router.get("/api/model", response_model=ModelInfo)
async def get_model_info():
    return ModelInfo(
        loaded=container.thinkvault_llm.is_loaded,
        model_path=container.thinkvault_llm.base_url,
        model_name=container.thinkvault_llm.model,
    )


@model_router.post("/api/model/load")
async def load_model(req: ModelLoadRequest):
    """探测推理后端可用性。更新 LLM client 的 base_url / model_name / api_key 后检查连接。"""
    # SSRF/DNS rebinding 防护：校验用户提供的 base_url
    try:
        safe_url = validate_url_for_ssrf(req.model_path)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # 重新配置 LLM 客户端（base_url、model、api_key）
    await container.thinkvault_llm.reconfigure(
        base_url=safe_url,
        model=req.model_name,
        api_key=req.api_key,
    )

    """探测推理后端可用性 — 通过 GET /v1/models 检查连接"""
    _set_progress("loading", 0.0, "正在探测推理后端...")

    async def _check_with_progress():
        try:
            _set_progress("loading", 0.3, "正在连接推理后端...")
            available = await container.thinkvault_llm.check_availability()
            if available:
                _set_progress("loaded", 1.0, "推理后端连接成功")
            else:
                _set_progress("error", 0.0, "无法连接推理后端，请确认 llama-cpp-python server 已运行")
            return available
        except Exception as e:
            _set_progress("error", 0.0, f"探测异常: {e}")
            return False

    success = await _check_with_progress()

    return {"status": "ok" if success else "error", "base_url": container.thinkvault_llm.base_url}


@model_router.get("/api/model/load/progress")
async def model_load_progress():
    """SSE 端点 — 实时推送后端探测进度"""
    async def progress_generator():
        last_status = ""
        while True:
            with _progress_lock:
                current = dict(_model_load_progress)
            if current["status"] != last_status or current["status"] == "loading":
                yield f"data: {json.dumps(current, ensure_ascii=False)}\n\n"
                last_status = current["status"]
            if current["status"] in ("loaded", "error"):
                await asyncio.sleep(0.3)
                yield f"data: {json.dumps(current, ensure_ascii=False)}\n\n"
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(
        progress_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@model_router.post("/api/model/unload")
async def unload_model():
    """断开后端连接（关闭 httpx 客户端并重置可用状态）"""
    llm = container.thinkvault_llm
    llm.mark_unavailable()
    await llm.close()
    _set_progress("idle", 0.0, "")
    return {"status": "ok"}


@model_router.get("/api/hardware", response_model=HardwareInfo)
async def get_hardware_info():
    profile = detect_hardware()
    return HardwareInfo(
        cpu_count=profile.cpu_count, total_ram_gb=profile.total_ram_gb,
        available_ram_gb=profile.available_ram_gb, gpu_name=profile.gpu_name,
        vram_gb=profile.vram_gb, has_cuda=profile.has_cuda,
        recommended_tier=profile.recommended_model_tier,
        recommended_spec=profile.recommended_model_spec,
    )


@model_router.get("/api/model/list", response_model=ModelListResponse)
async def list_models():
    """扫描本地模型目录和推理后端，返回可用模型列表"""
    import os
    from pathlib import Path
    models = []

    # 1. 扫描本地模型目录
    model_dir = Path(os.path.expanduser("~/.thinkvault/models"))
    if model_dir.is_dir():
        for f in sorted(model_dir.glob("*.gguf")):
            size_mb = f.stat().st_size / (1024 * 1024)
            models.append(ModelListItem(
                id=f.name,
                name=f.name,
                source="local",
                size_mb=round(size_mb, 1),
            ))

    # 2. 探测推理后端已加载的模型
    try:
        llm = container.thinkvault_llm
        if llm.is_loaded:
            # 尝试从 /v1/models 获取远端模型列表
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{llm.base_url}/models")
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("data", []):
                        mid = m.get("id", "")
                        if not any(x.id == mid for x in models):
                            models.append(ModelListItem(
                                id=mid,
                                name=mid,
                                source="remote",
                                size_mb=0,
                            ))
    except Exception:
        logger.debug("获取远端模型列表失败", exc_info=True)

    return ModelListResponse(models=models, count=len(models))


@model_router.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "version": __version__,
        "model_loaded": container.thinkvault_llm.is_loaded,
    }