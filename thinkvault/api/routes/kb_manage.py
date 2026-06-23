"""知识库高级管理路由 — 扫描/监听/摘要/变更记录"""

import asyncio
import os
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from thinkvault.core.container import container
from thinkvault.core import file_change_store
from thinkvault.core import doc_summary_store
from thinkvault.core import watched_dir_store
from thinkvault.core.scanner import _is_path_allowed
from thinkvault.utils.logger import logger

router = APIRouter(prefix="/api/kb/manage", tags=["knowledge-base-management"])

# 合法知识库名规则：与 kb.py 一致
_KB_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,49}$")


# ── 请求模型 ──────────────────────────────────────────────────────

class KBScanRequest(BaseModel):
    knowledge_base: str = Field(default="default", max_length=50)
    directory_path: str = Field(..., description="要扫描的目录路径")
    recursive: bool = Field(default=True, description="是否递归扫描子目录")


class KBReindexRequest(BaseModel):
    knowledge_base: str = Field(default="default", max_length=50)
    file_path: str = Field(..., description="要重新索引的文件绝对路径")


class KBWatchAddRequest(BaseModel):
    knowledge_base: str = Field(default="default", max_length=50)
    directory_path: str = Field(..., description="要监听的目录路径")


class KBWatchRemoveRequest(BaseModel):
    directory_path: str = Field(..., description="要移除监听的目录路径")


class KBSummariesRequest(BaseModel):
    knowledge_base: str = Field(default="default", max_length=50)


# ── 辅助函数 ──────────────────────────────────────────────────────

def _validate_kb_name(name: str):
    """校验知识库名称"""
    if not _KB_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="知识库名称仅允许小写字母、数字、连字符和下划线，长度 3-50，须以字母或数字开头",
        )


def _validate_path(path: str):
    """校验目录路径安全性"""
    if not _is_path_allowed(path):
        raise HTTPException(
            status_code=400,
            detail=f"目录不在白名单内: {path}。请配置 THINKVAULT_SCAN_DIRS 环境变量或将文件放到 THINKVAULT_DATA_DIR 目录下",
        )


def _kb_exists(name: str) -> bool:
    """检查知识库是否存在"""
    return name in container.vector_store.list_knowledge_bases()


# ── 端点 ──────────────────────────────────────────────────────────

@router.post("/scan")
async def scan_directory(req: KBScanRequest):
    """触发增量扫描（后台异步执行）"""
    _validate_kb_name(req.knowledge_base)
    _validate_path(req.directory_path)

    if not os.path.isdir(req.directory_path):
        raise HTTPException(status_code=400, detail=f"目录不存在: {req.directory_path}")

    from thinkvault.core.task_manager import task_manager
    from thinkvault.core.container import container

    task_id = task_manager.submit(
        task_type="scan",
        description=f"扫描目录 {req.directory_path} → {req.knowledge_base}",
        func=container.incremental_indexer.scan,
        directory_path=req.directory_path,
        knowledge_base=req.knowledge_base,
        recursive=req.recursive,
    )
    return {"task_id": task_id, "status": "submitted", "description": f"扫描目录 {req.directory_path}"}


@router.post("/scan/sync")
async def scan_directory_sync(req: KBScanRequest):
    """触发增量扫描（同步等待结果）"""
    _validate_kb_name(req.knowledge_base)
    _validate_path(req.directory_path)

    if not os.path.isdir(req.directory_path):
        raise HTTPException(status_code=400, detail=f"目录不存在: {req.directory_path}")

    result = await asyncio.to_thread(
        container.incremental_indexer.scan,
        directory_path=req.directory_path,
        knowledge_base=req.knowledge_base,
        recursive=req.recursive,
    )
    return result


@router.post("/reindex")
async def reindex_file(req: KBReindexRequest):
    """重新索引单个文件"""
    _validate_kb_name(req.knowledge_base)
    _validate_path(req.file_path)

    if not os.path.isfile(req.file_path):
        raise HTTPException(status_code=400, detail=f"文件不存在: {req.file_path}")

    result = await asyncio.to_thread(
        container.incremental_indexer.reindex_file,
        file_path=req.file_path,
        knowledge_base=req.knowledge_base,
    )
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/watch")
async def add_watch(req: KBWatchAddRequest):
    """添加文件夹监听"""
    _validate_kb_name(req.knowledge_base)
    _validate_path(req.directory_path)

    if not os.path.isdir(req.directory_path):
        raise HTTPException(status_code=400, detail=f"目录不存在: {req.directory_path}")

    # 持久化到 watched_dir_store
    try:
        dir_id = watched_dir_store.add(req.directory_path, req.knowledge_base)
    except Exception as e:
        # 可能已存在，尝试获取已有记录
        existing = watched_dir_store.get_by_path(req.directory_path)
        if existing:
            dir_id = existing["id"]
        else:
            logger.error(f"添加监听目录失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="添加监听目录失败，请稍后重试")

    # 启动 watchdog 监听
    try:
        container.watchdog_watcher.add_watch(req.directory_path, req.knowledge_base)
    except Exception as e:
        logger.warning(f"启动监听失败（目录已记录）: {e}")

    return {
        "id": dir_id,
        "directory_path": req.directory_path,
        "knowledge_base": req.knowledge_base,
        "status": "watching",
    }


@router.delete("/watch")
async def remove_watch(req: KBWatchRemoveRequest):
    """移除文件夹监听"""
    try:
        container.watchdog_watcher.remove_watch(req.directory_path)
    except Exception as e:
        logger.error(f"移除监听失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="移除监听失败，请稍后重试")

    return {"directory_path": req.directory_path, "status": "removed"}


# ── 后台任务状态查询（必须在 /{kb_name} 路由之前注册）──────────────

@router.get("/tasks")
async def list_tasks(task_type: str = None):
    """列出所有后台任务"""
    from thinkvault.core.task_manager import task_manager
    return task_manager.list_tasks(task_type)


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """查询后台任务状态"""
    from thinkvault.core.task_manager import task_manager
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 '{task_id}' 不存在")
    return task.to_dict()


@router.post("/summaries")
async def generate_summaries(req: KBSummariesRequest):
    """批量生成文档摘要（后台异步执行）"""
    _validate_kb_name(req.knowledge_base)

    if not _kb_exists(req.knowledge_base):
        raise HTTPException(status_code=404, detail=f"知识库 '{req.knowledge_base}' 不存在")

    from thinkvault.core.task_manager import task_manager
    from thinkvault.core.container import container

    task_id = task_manager.submit(
        task_type="summary",
        description=f"生成知识库 {req.knowledge_base} 的文档摘要",
        func=container.summary_generator.generate_for_kb,
        knowledge_base=req.knowledge_base,
    )
    return {"task_id": task_id, "status": "submitted", "description": f"生成摘要: {req.knowledge_base}"}


@router.post("/summaries/sync")
async def generate_summaries_sync(req: KBSummariesRequest):
    """批量生成文档摘要（同步等待结果）"""
    _validate_kb_name(req.knowledge_base)

    if not _kb_exists(req.knowledge_base):
        raise HTTPException(status_code=404, detail=f"知识库 '{req.knowledge_base}' 不存在")

    result = await asyncio.to_thread(
        container.summary_generator.generate_for_kb,
        knowledge_base=req.knowledge_base,
    )
    return result


@router.get("/{kb_name}/changes")
async def get_file_changes(kb_name: str):
    """查看文件变更记录"""
    _validate_kb_name(kb_name)

    changes = file_change_store.get_by_knowledge_base(kb_name)
    return changes


@router.get("/{kb_name}/summaries")
async def get_doc_summaries(kb_name: str):
    """查看文档摘要"""
    _validate_kb_name(kb_name)

    summaries = doc_summary_store.get_by_knowledge_base(kb_name)
    return summaries
