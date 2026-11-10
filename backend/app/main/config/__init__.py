"""集中式路径与运行参数配置。"""

from app.main.config.settings import (  # noqa: F401
    BACKEND_DIR,
    CONFIG_DIR,
    DATA_DIR,
    PROJECT_DIR,
    ensure_runtime_directories,
)

__all__ = [
    "BACKEND_DIR",
    "CONFIG_DIR",
    "DATA_DIR",
    "PROJECT_DIR",
    "ensure_runtime_directories",
]
