"""MongoDB 基础设施：连接、索引与 Persona / 关系网络 / 事件记录仓储。"""

from app.infrastructure.database.mongo_client import (
    MongoStorageError,
    close_connection,
    get_database,
    mongo_enabled,
    mongo_health,
    storage_backend,
)

__all__ = [
    "MongoStorageError",
    "close_connection",
    "get_database",
    "mongo_enabled",
    "mongo_health",
    "storage_backend",
]
