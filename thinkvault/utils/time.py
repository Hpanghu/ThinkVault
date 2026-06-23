"""时间工具模块"""

from datetime import datetime, timezone


def get_current_time() -> str:
    """获取当前时间的 ISO 8601 格式字符串（UTC）"""
    return datetime.now(timezone.utc).isoformat()


def to_local_time(utc_str: str) -> str:
    """将 UTC 时间字符串转换为本地时间"""
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
