"""ThinkVault 测试公共 fixtures

将 TestClient 提取到 conftest.py 中，所有集成测试共享同一个 client，
避免多个 module 定义同名 fixture 导致的冲突。
"""

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def client():
    """创建 TestClient，关闭认证，所有集成测试共享（session scope 避免多 module 冲突）"""
    os.environ["THINKVAULT_DISABLE_AUTH"] = "1"
    os.environ["THINKVAULT_API_TOKEN"] = ""
    # 禁用速率限制 — 测试套件发送大量请求，避免触发 429
    os.environ["THINKVAULT_RATE_LIMIT"] = "99999"
    from thinkvault.api.server import create_app
    import thinkvault.api.server as srv
    srv.THINKVAULT_API_TOKEN = ""
    # 直接修改模块变量（模块可能已被 import，环境变量不会重新读取）
    srv._RATE_LIMIT_REQUESTS = 99999
    app = create_app()
    with TestClient(app) as c:
        yield c
