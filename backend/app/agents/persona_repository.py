"""Persona 读取服务。

2026/11/03，修改功能：Persona 以 MongoDB 为主存储；未启用 MongoDB 或
目录中新增文件时自动回退/回填 JSON，保持原有调用方式不变。
"""

from app.infrastructure.database.repositories.personas import (
    load_personas_from_store,
)
from app.main.config.settings import PERSONA_DIR


def load_personas(persona_dir=PERSONA_DIR, max_count=None):
    """读取 Persona；MongoDB 主存储，JSON 目录作为兼容镜像。"""

    return load_personas_from_store(persona_dir, max_count=max_count)


def load_first_persona(persona_dir=PERSONA_DIR):
    """读取 Persona 中的第一份 Agent。"""

    personas = load_personas(persona_dir, max_count=1)
    if not personas:
        raise FileNotFoundError(f"没有找到 Persona 文件：{persona_dir}")
    return personas[0]
