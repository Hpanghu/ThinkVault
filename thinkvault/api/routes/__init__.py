"""API 路由 — V2.0 聚合入口

各功能模块拆分到独立文件，本文件仅负责 router 汇总注册。
"""

from fastapi import APIRouter

from thinkvault.api.routes.chat import chat_router
from thinkvault.api.routes.documents import documents_router
from thinkvault.api.routes.model import model_router
from thinkvault.api.routes.conversations import conversations_router
from thinkvault.api.routes.kb import kb_router

router = APIRouter()

router.include_router(chat_router)
router.include_router(documents_router)
router.include_router(model_router)
router.include_router(conversations_router)
router.include_router(kb_router)