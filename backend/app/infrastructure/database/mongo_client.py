"""MongoDB 连接、数据库与集合索引。

Persona、关系网络与事件记录以 MongoDB 为主存储，JSON 文件作为兼容镜像
继续写入，供实验目录复制、回滚、输入指纹和报告读取使用。

环境变量：

* ``SIMULATION_STORAGE_BACKEND``：``mongodb``（默认）或 ``json``；
* ``MONGO_URI``：默认 ``mongodb://127.0.0.1:27017``；
* ``MONGO_DATABASE``：默认 ``future_simulation``；
* ``MONGO_SERVER_SELECTION_TIMEOUT_MS``：连接超时，默认 3000；
* ``MONGO_WRITE_JSON_MIRROR``：是否同步写 JSON 镜像，默认开启。
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from app.main.config.settings import (
    MONGO_DATABASE,
    MONGO_SERVER_SELECTION_TIMEOUT_MS,
    MONGO_URI,
    MONGO_WRITE_JSON_MIRROR,
    PROJECT_DIR,
    STORAGE_BACKEND,
)

try:  # 允许在未安装 pymongo 的环境中仅使用 json 后端。
    from pymongo import ASCENDING, MongoClient
    from pymongo.errors import PyMongoError
except ImportError:  # pragma: no cover - 依赖缺失时给出明确错误
    ASCENDING = None
    MongoClient = None

    class PyMongoError(Exception):
        """pymongo 不可用时的占位异常。"""


VALID_STORAGE_BACKENDS = ("mongodb", "json")

PERSONAS_COLLECTION = "personas"
PERSONA_POLICY_COLLECTION = "persona_policies"
SOCIAL_NETWORK_COLLECTION = "social_networks"
EVENTS_COLLECTION = "events"
EVENT_STATES_COLLECTION = "event_states"

_lock = threading.RLock()
_client = None
_database = None


class MongoStorageError(RuntimeError):
    """表示 MongoDB 未配置、连接失败或读写失败。"""


def storage_backend() -> str:
    """返回当前存储后端；未知取值按默认 mongodb 处理。"""

    if STORAGE_BACKEND in VALID_STORAGE_BACKENDS:
        return STORAGE_BACKEND
    return "mongodb"


def mongo_enabled() -> bool:
    """当前进程是否使用 MongoDB 主存储。"""

    return storage_backend() == "mongodb"


def json_mirror_enabled() -> bool:
    """是否在写 MongoDB 的同时写 JSON 兼容镜像。"""

    return bool(MONGO_WRITE_JSON_MIRROR)


def utc_now() -> datetime:
    """返回带时区的当前时间，统一写入 updated_at。"""

    return datetime.now(timezone.utc)


def scope_key(path) -> str:
    """把文件路径转换为稳定、可读的数据库作用域键。

    项目内路径使用相对项目根目录的 POSIX 路径，保证实验目录迁移后仍然
    可读；项目外路径（例如测试临时目录）回退为绝对路径。
    """

    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(PROJECT_DIR.resolve())
    except ValueError:
        return resolved.as_posix()
    return relative.as_posix()


def scope_prefix(directory) -> str:
    """返回用于匹配目录下全部作用域的字符串前缀。"""

    return scope_key(directory).rstrip("/") + "/"


def get_database():
    """返回已连接并完成索引初始化的数据库对象。

    连接失败时抛出 ``MongoStorageError``，避免静默退化为文件存储导致
    数据写入位置与配置不符。
    """

    global _client, _database

    if not mongo_enabled():
        raise MongoStorageError("当前存储后端不是 mongodb。")
    if MongoClient is None:
        raise MongoStorageError(
            "未安装 pymongo，无法连接 MongoDB；请先安装 requirements.txt。"
        )

    with _lock:
        if _database is not None:
            return _database

        client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=MONGO_SERVER_SELECTION_TIMEOUT_MS,
            connectTimeoutMS=MONGO_SERVER_SELECTION_TIMEOUT_MS,
            tz_aware=True,
            appname="future-backend",
        )
        try:
            client.admin.command("ping")
        except PyMongoError as error:
            client.close()
            raise MongoStorageError(
                "无法连接 MongoDB（"
                f"{MONGO_URI}，数据库 {MONGO_DATABASE}）。"
                "请先启动 MongoDB，或设置 SIMULATION_STORAGE_BACKEND=json "
                "退回文件存储。"
            ) from error

        database = client[MONGO_DATABASE]
        _ensure_indexes(database)
        _client = client
        _database = database
        return _database


def _ensure_indexes(database) -> None:
    """创建查询与唯一性约束所需的索引。"""

    database[PERSONAS_COLLECTION].create_index(
        [("agent_id", ASCENDING)],
        unique=True,
        name="uniq_persona_agent_id",
    )
    database[SOCIAL_NETWORK_COLLECTION].create_index(
        [("kind", ASCENDING), ("network_id", ASCENDING)],
        name="idx_network_kind_id",
    )
    database[EVENTS_COLLECTION].create_index(
        [("event_id", ASCENDING)],
        name="idx_event_event_id",
    )
    database[EVENT_STATES_COLLECTION].create_index(
        [("scope", ASCENDING), ("event_id", ASCENDING), ("step", ASCENDING)],
        unique=True,
        name="uniq_event_state_scope_event_step",
    )
    database[EVENT_STATES_COLLECTION].create_index(
        [("event_id", ASCENDING), ("step", ASCENDING)],
        name="idx_event_state_event_step",
    )


def mongo_health() -> dict:
    """返回健康检查信息，不抛出连接异常。"""

    info = {
        "backend": storage_backend(),
        "database": MONGO_DATABASE,
        "uri": MONGO_URI,
        "status": "disabled" if not mongo_enabled() else "unknown",
    }
    if not mongo_enabled():
        return info
    try:
        database = get_database()
        database.command("ping")
        info["status"] = "ok"
        info["collections"] = {
            PERSONAS_COLLECTION: database[PERSONAS_COLLECTION].count_documents({}),
            PERSONA_POLICY_COLLECTION: database[
                PERSONA_POLICY_COLLECTION
            ].count_documents({}),
            SOCIAL_NETWORK_COLLECTION: database[
                SOCIAL_NETWORK_COLLECTION
            ].count_documents({}),
            EVENTS_COLLECTION: database[EVENTS_COLLECTION].count_documents({}),
            EVENT_STATES_COLLECTION: database[
                EVENT_STATES_COLLECTION
            ].count_documents({}),
        }
    except MongoStorageError as error:
        info["status"] = "unavailable"
        info["error"] = str(error)
    except PyMongoError as error:  # pragma: no cover - 服务端异常
        info["status"] = "unavailable"
        info["error"] = str(error)
    return info


def close_connection() -> None:
    """关闭连接；脚本和测试结束时可选调用。"""

    global _client, _database
    with _lock:
        if _client is not None:
            _client.close()
        _client = None
        _database = None


__all__ = [
    "EVENTS_COLLECTION",
    "EVENT_STATES_COLLECTION",
    "MongoStorageError",
    "PERSONAS_COLLECTION",
    "PERSONA_POLICY_COLLECTION",
    "SOCIAL_NETWORK_COLLECTION",
    "close_connection",
    "get_database",
    "json_mirror_enabled",
    "mongo_enabled",
    "mongo_health",
    "scope_key",
    "scope_prefix",
    "storage_backend",
    "utc_now",
]
