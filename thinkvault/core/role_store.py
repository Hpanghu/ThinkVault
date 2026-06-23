"""角色存储模块 — 管理角色数据的持久化与加载"""

import uuid
from typing import Optional, List

from thinkvault.core.base_store import BaseStore
from thinkvault.utils.logger import logger


class RoleStore(BaseStore):
    """角色存储 — 管理角色数据"""

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS roles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            system_prompt TEXT NOT NULL,
            welcome_message TEXT DEFAULT '',
            is_builtin INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_roles_name ON roles(name);
    """

    _MIGRATIONS = [
        "CREATE INDEX IF NOT EXISTS idx_roles_name ON roles(name)",
    ]

    def add_role(
        self,
        name: str,
        system_prompt: str,
        description: str = "",
        welcome_message: str = "",
        is_builtin: bool = False,
        role_id: Optional[str] = None,
    ) -> str:
        """添加角色"""
        from thinkvault.utils.time import get_current_time

        rid = role_id or str(uuid.uuid4())
        now = get_current_time()

        store = self._get_store()
        with store.connect() as conn:
            conn.execute(
                """
                INSERT INTO roles (id, name, description, system_prompt, welcome_message, 
                                  is_builtin, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (rid, name, description, system_prompt, welcome_message, int(is_builtin), now, now),
            )
            conn.commit()
        logger.info(f"角色添加成功: {name} ({rid})")
        return rid

    def get_role(self, role_id: str) -> Optional[dict]:
        """根据 ID 获取角色"""
        store = self._get_store()
        with store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM roles WHERE id = ?", (role_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_role_by_name(self, name: str) -> Optional[dict]:
        """根据名称获取角色"""
        store = self._get_store()
        with store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM roles WHERE name = ?", (name,)
            ).fetchone()
            return dict(row) if row else None

    def list_roles(self) -> List[dict]:
        """获取所有角色列表"""
        store = self._get_store()
        with store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM roles ORDER BY is_builtin DESC, created_at ASC"
            ).fetchall()
            return [dict(row) for row in rows]

    def update_role(
        self,
        role_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        system_prompt: Optional[str] = None,
        welcome_message: Optional[str] = None,
    ) -> bool:
        """更新角色信息"""
        from thinkvault.utils.time import get_current_time

        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if system_prompt is not None:
            updates.append("system_prompt = ?")
            params.append(system_prompt)
        if welcome_message is not None:
            updates.append("welcome_message = ?")
            params.append(welcome_message)

        if not updates:
            return False

        updates.append("updated_at = ?")
        params.append(get_current_time())
        params.append(role_id)

        store = self._get_store()
        with store.connect() as conn:
            conn.execute(
                f"UPDATE roles SET {', '.join(updates)} WHERE id = ?",
                tuple(params),
            )
            conn.commit()
            row = conn.execute("SELECT changes() AS cnt").fetchone()
            return row["cnt"] > 0

    def delete_role(self, role_id: str) -> bool:
        """删除角色"""
        store = self._get_store()
        with store.connect() as conn:
            conn.execute("DELETE FROM roles WHERE id = ?", (role_id,))
            conn.commit()
            row = conn.execute("SELECT changes() AS cnt").fetchone()
            return row["cnt"] > 0

    def is_builtin(self, role_id: str) -> bool:
        """检查角色是否为内置角色"""
        store = self._get_store()
        with store.connect() as conn:
            row = conn.execute(
                "SELECT is_builtin FROM roles WHERE id = ?", (role_id,)
            ).fetchone()
            return row is not None and row["is_builtin"] == 1

    def count_conversations_by_role(self, role_id: str) -> int:
        """统计使用该角色的会话数量"""
        store = self._get_store()
        with store.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM conversations WHERE role_id = ?",
                (role_id,),
            ).fetchone()
            return row["cnt"] if row else 0

    def get_default_role(self) -> Optional[dict]:
        """获取默认角色（首个内置角色）"""
        store = self._get_store()
        with store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM roles WHERE is_builtin = 1 ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if row:
                return dict(row)
            rows = conn.execute("SELECT * FROM roles ORDER BY created_at ASC LIMIT 1").fetchall()
            return dict(rows[0]) if rows else None


role_store = RoleStore()
