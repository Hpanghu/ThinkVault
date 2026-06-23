"""
文件夹扫描器 — 自动扫描指定目录中的文件并索引到知识库

安全策略：
- 默认只允许扫描 THINKVAULT_DATA_DIR 下的目录
- 通过 THINKVAULT_SCAN_DIRS 环境变量可配置额外的允许目录（逗号分隔）
"""

import os
import uuid
from pathlib import Path

from thinkvault.core.parser import DocumentParser
from thinkvault.core.indexer import index_document
from thinkvault.core import document_store as doc_store
from thinkvault.utils.logger import logger


def _get_allowed_dirs() -> list[str]:
    """获取允许扫描的目录白名单。

    白名单来源：
    1. THINKVAULT_DATA_DIR 环境变量（默认 ~/.thinkvault/data）
    2. THINKVAULT_SCAN_DIRS 环境变量（逗号分隔的额外目录）
    """
    allowed = []

    # 默认数据目录
    data_dir = os.environ.get(
        "THINKVAULT_DATA_DIR",
        str(Path.home() / ".thinkvault" / "data"),
    )
    allowed.append(os.path.abspath(data_dir))

    # 用户配置的额外扫描目录
    scan_dirs = os.environ.get("THINKVAULT_SCAN_DIRS", "")
    if scan_dirs.strip():
        for d in scan_dirs.split(","):
            d = d.strip()
            if d:
                allowed.append(os.path.abspath(d))

    return allowed


def _is_path_allowed(directory_path: str) -> bool:
    """检查目录路径是否在白名单内。

    使用路径规范化的前缀匹配，防止通过 ../ 等方式绕过。
    """
    abs_path = os.path.abspath(directory_path)
    allowed_dirs = _get_allowed_dirs()

    for allowed_dir in allowed_dirs:
        # 规范化路径后检查前缀
        norm_allowed = os.path.normpath(allowed_dir)
        norm_path = os.path.normpath(abs_path)
        if norm_path == norm_allowed or norm_path.startswith(norm_allowed + os.sep):
            return True

    return False


def scan_directory(
    directory_path: str,
    knowledge_base: str = "default",
    recursive: bool = True,
) -> dict:
    """扫描指定目录，自动索引所有新文件。

    对每个文件检查是否已在 document_store 中存在（通过 file_name + file_size 判断），
    只处理 SUPPORTED_TYPES 中的文件。

    Args:
        directory_path: 要扫描的目录路径
        knowledge_base: 目标知识库名称
        recursive: 是否递归扫描子目录

    Returns:
        dict: {
            "scanned": int,   # 扫描到的文件总数
            "new": int,       # 新索引的文件数
            "skipped": int,   # 跳过（已索引或不支持的格式）的文件数
            "errors": list,   # 错误信息列表
        }
    """
    result = {
        "directory": directory_path,
        "scanned": 0,
        "new": 0,
        "skipped": 0,
        "unsupported": 0,
        "errors": [],
        "details": [],
    }

    # 路径安全检查
    if not _is_path_allowed(directory_path):
        result["errors"].append(
            f"目录不在允许扫描的白名单内: {directory_path}。"
            f"请配置 THINKVAULT_SCAN_DIRS 环境变量或将文件放到 THINKVAULT_DATA_DIR 目录下"
        )
        return result

    dir_path = Path(directory_path)
    if not dir_path.exists():
        result["errors"].append(f"目录不存在: {directory_path}")
        return result

    if not dir_path.is_dir():
        result["errors"].append(f"路径不是目录: {directory_path}")
        return result

    # 获取已有文档列表（用于去重判断）
    existing_docs = doc_store.list_documents(knowledge_base=knowledge_base)
    # 建立 file_name + file_size → doc_id 的索引
    existing_index = {
        f"{d['file_name']}_{d['file_size']}": d["id"]
        for d in existing_docs
    }

    # 收集待处理的文件
    pattern = "**/*" if recursive else "*"
    files = [f for f in dir_path.glob(pattern) if f.is_file()]

    for file_path in files:
        suffix = file_path.suffix.lower()

        # 跳过不支持的格式
        if suffix not in DocumentParser.SUPPORTED_TYPES:
            result["unsupported"] += 1
            continue

        result["scanned"] += 1

        # 检查是否已索引
        file_size = file_path.stat().st_size
        dedup_key = f"{file_path.name}_{file_size}"
        if dedup_key in existing_index:
            result["skipped"] += 1
            logger.debug(f"跳过已索引文件: {file_path.name}")
            continue

        # 解析并索引
        try:
            doc_id = uuid.uuid4().hex[:16]
            idx_result = index_document(str(file_path), knowledge_base, doc_id=doc_id)

            if idx_result["status"] != "success":
                error_msg = idx_result.get("error") or "索引失败"
                result["errors"].append(f"{file_path.name}: {error_msg}")
                result["skipped"] += 1
                continue

            result["new"] += 1
            result["details"].append({
                "file": file_path.name, "status": "indexed",
                "chunks": idx_result["chunks_count"], "doc_id": idx_result["document_id"],
            })
            logger.info(f"扫描索引成功: {file_path.name} ({idx_result['chunks_count']} 块, KB={knowledge_base})")

        except Exception as e:
            result["errors"].append(f"{file_path.name}: {str(e)}")
            logger.error(f"扫描索引失败: {file_path.name} | {e}")

    logger.info(
        f"目录扫描完成: {directory_path} | "
        f"扫描={result['scanned']} 新索引={result['new']} "
        f"跳过={result['skipped']} 不支持={result['unsupported']} "
        f"错误={len(result['errors'])}"
    )
    return result
