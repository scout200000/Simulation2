"""关系网络（社交网络快照与网络参数）的 MongoDB 仓储。

同一个集合 ``social_networks`` 保存两类文档：

* ``kind=snapshot``：某个状态目录/实验目录下的固定关注网络快照；
* ``kind=config``：``configs/social_network_config.json`` 中的网络参数。

文档以文件作用域（项目内相对路径）为 ``_id``，与现有实验目录一一对应，
因此共享基线、各策略场景和回滚检查点可以各自保留独立网络快照。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from app.infrastructure.database.mongo_client import (
    SOCIAL_NETWORK_COLLECTION,
    get_database,
    json_mirror_enabled,
    mongo_enabled,
    scope_key,
    scope_prefix,
    utc_now,
)
from app.infrastructure.storage.json_storage import load_json, save_json


KIND_SNAPSHOT = "snapshot"
KIND_CONFIG = "config"


def network_id(data: dict) -> str:
    """返回与键顺序无关的网络内容哈希。"""

    payload = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _document(path, data, kind) -> dict:
    return {
        "_id": scope_key(path),
        "scope": scope_key(path),
        "kind": kind,
        "source_path": str(Path(path).resolve()),
        "network_id": network_id(data),
        "data": data,
        "updated_at": utc_now(),
    }


def _load_from_mongo(path, kind):
    document = get_database()[SOCIAL_NETWORK_COLLECTION].find_one(
        {"_id": scope_key(path), "kind": kind}
    )
    if document and isinstance(document.get("data"), dict):
        return document["data"]
    return None


def _load_document(path, kind, required=False):
    if not mongo_enabled():
        if Path(path).is_file():
            return load_json(path)
        if required:
            raise FileNotFoundError(f"关系网络文件不存在：{path}")
        return None

    data = _load_from_mongo(path, kind)
    if data is not None:
        return data

    # MongoDB 尚无该作用域时，从 JSON 镜像回填，兼容首次迁移和目录复制。
    if Path(path).is_file():
        data = load_json(path)
        if isinstance(data, dict):
            save_network_document(path, data, kind)
            return data

    if required:
        raise FileNotFoundError(f"关系网络文件不存在：{path}")
    return None


def save_network_document(path, data, kind) -> None:
    """写入网络文档并同步 JSON 镜像。"""

    if not isinstance(data, dict):
        raise ValueError("关系网络数据必须是 JSON 对象。")
    if not mongo_enabled():
        save_json(path, data)
        return

    get_database()[SOCIAL_NETWORK_COLLECTION].replace_one(
        {"_id": scope_key(path)},
        _document(path, data, kind),
        upsert=True,
    )
    if json_mirror_enabled():
        save_json(path, data)


def social_network_exists(path) -> bool:
    """判断快照是否已存在于 MongoDB 或 JSON 镜像。"""

    if not mongo_enabled():
        return Path(path).is_file()
    if _load_from_mongo(path, KIND_SNAPSHOT) is not None:
        return True
    return Path(path).is_file()


def load_social_network(path, required=False):
    """读取固定社交网络快照；不存在时返回 ``None``。"""

    data = _load_document(path, KIND_SNAPSHOT, required=required)
    if data is not None and not isinstance(data, dict):
        raise ValueError(f"社交网络快照必须是 JSON 对象：{path}")
    return data


def save_social_network(path, snapshot) -> None:
    """保存固定社交网络快照。"""

    if not isinstance(snapshot, dict):
        raise ValueError("社交网络快照必须是 JSON 对象。")
    save_network_document(path, snapshot, KIND_SNAPSHOT)


def load_social_network_config(path, required=True):
    """读取网络参数配置。"""

    data = _load_document(path, KIND_CONFIG, required=required)
    if data is not None and not isinstance(data, dict):
        raise ValueError(f"社交网络配置必须是 JSON 对象：{path}")
    return data


def save_social_network_config(path, config) -> None:
    """保存网络参数配置。"""

    if not isinstance(config, dict):
        raise ValueError("社交网络配置必须是 JSON 对象。")
    save_network_document(path, config, KIND_CONFIG)


def delete_social_network(path) -> None:
    """删除单个网络文档（不删除 JSON 镜像）。"""

    if not mongo_enabled():
        return
    get_database()[SOCIAL_NETWORK_COLLECTION].delete_one(
        {"_id": scope_key(path)}
    )


def delete_social_networks_under(directory) -> None:
    """删除目录作用域下的全部网络文档。"""

    if not mongo_enabled():
        return
    pattern = "^" + re.escape(scope_prefix(directory))
    get_database()[SOCIAL_NETWORK_COLLECTION].delete_many(
        {"scope": {"$regex": pattern}}
    )


def copy_social_network(source_path, target_path) -> None:
    """把一个作用域的网络文档复制到另一个作用域。"""

    if not mongo_enabled():
        if Path(source_path).is_file():
            save_json(target_path, load_json(source_path))
        return

    source = _load_from_mongo(source_path, KIND_SNAPSHOT)
    if source is None and Path(source_path).is_file():
        source = load_json(source_path)
        if isinstance(source, dict):
            save_network_document(source_path, source, KIND_SNAPSHOT)

    database = get_database()
    database[SOCIAL_NETWORK_COLLECTION].delete_one({"_id": scope_key(target_path)})
    if source is not None:
        database[SOCIAL_NETWORK_COLLECTION].replace_one(
            {"_id": scope_key(target_path)},
            _document(target_path, source, KIND_SNAPSHOT),
            upsert=True,
        )
        if json_mirror_enabled():
            save_json(target_path, source)


__all__ = [
    "KIND_CONFIG",
    "KIND_SNAPSHOT",
    "copy_social_network",
    "delete_social_network",
    "delete_social_networks_under",
    "load_social_network",
    "load_social_network_config",
    "network_id",
    "save_social_network",
    "save_social_network_config",
    "social_network_exists",
]
