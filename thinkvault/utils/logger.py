"""
统一日志模块 — 日志级别可通过环境变量 THINKVAULT_LOG_LEVEL 配置
"""

import logging
import os
import sys
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent.parent / "logs"

_LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def setup_logger(name: str = "thinkvault", level: int = logging.INFO) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(LOG_DIR / "thinkvault.log", encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 控制台默认 WARNING，也可通过环境变量覆盖
    console_level_name = os.environ.get("THINKVAULT_LOG_LEVEL", "WARNING").upper()
    console_level = _LOG_LEVEL_MAP.get(console_level_name, logging.WARNING)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(console_level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


def get_log_level_from_env() -> int:
    """从环境变量读取日志级别"""
    env_val = os.environ.get("THINKVAULT_LOG_LEVEL", "INFO").upper()
    return _LOG_LEVEL_MAP.get(env_val, logging.INFO)


logger = setup_logger(level=get_log_level_from_env())
