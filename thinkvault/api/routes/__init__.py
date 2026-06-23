"""API 路由 — V2.1 聚合入口

各功能模块拆分到独立文件，本文件仅负责 router 汇总注册。
v2.1+ 路由同时挂载于 /api/ 和 /api/v1/（通过 server.py 的 include_router prefix 参数）。
"""

from fastapi import APIRouter

from thinkvault.api.routes.chat import chat_router
from thinkvault.api.routes.documents import documents_router
from thinkvault.api.routes.model import model_router
from thinkvault.api.routes.conversations import conversations_router
from thinkvault.api.routes.kb import kb_router
from thinkvault.api.routes.kb_manage import router as kb_manage_router
from thinkvault.api.routes.services import services_router
from thinkvault.api.routes.roles import router as roles_router

# 入口路由器（无 prefix——版本前缀由 server.py 挂载时指定）
router = APIRouter()

router.include_router(chat_router)
router.include_router(documents_router)
router.include_router(model_router)
router.include_router(conversations_router)
router.include_router(kb_router)
router.include_router(kb_manage_router)
router.include_router(services_router)
router.include_router(roles_router)