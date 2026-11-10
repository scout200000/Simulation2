"""健康检查路由。"""

from __future__ import annotations

from http import HTTPStatus

from app.infrastructure.database.mongo_client import mongo_health
from app.main.config.settings import get_deepseek_api_key_source


def health():
    """返回服务存活状态、主存储与模型密钥配置状态。"""

    key_source = get_deepseek_api_key_source()
    return (
        {
            "status": "ok",
            "service": "future-backend",
            "api_version": "1",
            "storage": mongo_health(),
            "llm": {
                "deepseek_configured": key_source != "none",
                "deepseek_key_source": key_source,
            },
        },
        HTTPStatus.OK,
    )


__all__ = ["health"]
