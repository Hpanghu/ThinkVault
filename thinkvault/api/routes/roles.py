"""角色管理 API"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from thinkvault.core.role_store import role_store
from thinkvault.core.conversation_store import batch_update_conversations_role
from thinkvault.config import get_default_role_id


router = APIRouter(prefix="/api/roles", tags=["roles"])


class RoleCreate(BaseModel):
    name: str = Field(..., description="角色名称（唯一）")
    system_prompt: str = Field(..., description="系统提示词")
    description: str = Field("", description="角色描述")
    welcome_message: str = Field("", description="欢迎语")


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, description="角色名称（唯一）")
    system_prompt: Optional[str] = Field(None, description="系统提示词")
    description: Optional[str] = Field(None, description="角色描述")
    welcome_message: Optional[str] = Field(None, description="欢迎语")


class RoleResponse(BaseModel):
    id: str
    name: str
    description: str
    system_prompt: str
    welcome_message: str
    is_builtin: bool
    created_at: str
    updated_at: str


@router.get("", response_model=list[RoleResponse])
def list_roles():
    """获取所有角色列表"""
    return role_store.list_roles()


@router.get("/default")
def get_default_role():
    """获取默认角色"""
    role = role_store.get_default_role()
    if not role:
        raise HTTPException(status_code=404, detail="未找到默认角色")
    return role


@router.get("/{role_id}", response_model=RoleResponse)
def get_role(role_id: str):
    """获取单个角色详情"""
    role = role_store.get_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    return role


@router.post("", response_model=RoleResponse, status_code=201)
def create_role(data: RoleCreate):
    """创建新角色"""
    if not data.name or not data.name.strip():
        raise HTTPException(status_code=400, detail="角色名称不能为空")

    existing = role_store.get_role_by_name(data.name)
    if existing:
        raise HTTPException(status_code=400, detail="角色名称已存在")

    role_id = role_store.add_role(
        name=data.name,
        system_prompt=data.system_prompt,
        description=data.description,
        welcome_message=data.welcome_message,
        is_builtin=False,
    )
    return role_store.get_role(role_id)


@router.put("/{role_id}", response_model=RoleResponse)
def update_role(role_id: str, data: RoleUpdate):
    """更新角色信息"""
    role = role_store.get_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    if role.get("is_builtin") and data.name is not None:
        raise HTTPException(status_code=400, detail="内置角色不可修改名称")

    if data.name:
        existing = role_store.get_role_by_name(data.name)
        if existing and existing["id"] != role_id:
            raise HTTPException(status_code=400, detail="角色名称已存在")

    success = role_store.update_role(
        role_id=role_id,
        name=data.name,
        description=data.description,
        system_prompt=data.system_prompt,
        welcome_message=data.welcome_message,
    )
    if not success:
        raise HTTPException(status_code=400, detail="更新失败")

    return role_store.get_role(role_id)


@router.delete("/{role_id}")
def delete_role(role_id: str, force: bool = False):
    """删除角色"""
    role = role_store.get_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    if role.get("is_builtin"):
        raise HTTPException(status_code=400, detail="内置角色不可删除")

    conv_count = role_store.count_conversations_by_role(role_id)
    if conv_count > 0 and not force:
        raise HTTPException(
            status_code=400,
            detail=f"有 {conv_count} 个会话正在使用此角色，请使用 force=true 强制删除",
        )

    if conv_count > 0:
        default_role_id = get_default_role_id()
        batch_update_conversations_role(role_id, default_role_id)

    success = role_store.delete_role(role_id)
    if not success:
        raise HTTPException(status_code=400, detail="删除失败")

    return {"message": "角色删除成功", "migrated_conversations": conv_count}
