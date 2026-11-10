"""Persona 与 Persona 政策配置的 MongoDB 仓储。

Persona 以 ``agent_id`` 为唯一键存储；``policy_config.json`` 是 Persona
认知规则的全局参数，作为单文档保存。读取时优先 MongoDB，缺少文档时从
JSON 文件回填，兼容首次迁移和旧数据目录。
"""

from __future__ import annotations

from pathlib import Path

from app.infrastructure.database.mongo_client import (
    PERSONAS_COLLECTION,
    PERSONA_POLICY_COLLECTION,
    get_database,
    json_mirror_enabled,
    mongo_enabled,
    scope_key,
    utc_now,
)
from app.infrastructure.storage.json_storage import load_json, save_json


def _persona_files(persona_dir) -> list[Path]:
    return sorted(Path(persona_dir).glob("agent_*.json"))


def _load_personas_from_files(persona_dir, max_count=None) -> list[dict]:
    """旧 JSON 目录读取逻辑，供 json 后端和文件回填使用。"""

    persona_files = _persona_files(persona_dir)
    if max_count is not None:
        persona_files = persona_files[:max_count]

    personas = []
    for file_path in persona_files:
        try:
            personas.append(load_json(file_path))
        except Exception as error:  # noqa: BLE001 - 保留旧行为：跳过坏文件
            print(f"跳过无法读取的 Persona {file_path.name}：{error}")
    return personas


def _persona_document(persona: dict, source_path: Path) -> dict:
    agent_id = str(persona.get("agent_id") or source_path.stem).strip()
    if not agent_id:
        raise ValueError(f"Persona 缺少 agent_id：{source_path}")
    return {
        "_id": agent_id,
        "agent_id": agent_id,
        "source_path": str(source_path.resolve()),
        "scope": scope_key(source_path),
        "data": persona,
        "updated_at": utc_now(),
    }


def _import_missing_personas(persona_dir) -> None:
    """把目录中尚未入库的 Persona 文件导入 MongoDB。"""

    database = get_database()
    existing = set(database[PERSONAS_COLLECTION].distinct("agent_id"))
    missing = [
        path for path in _persona_files(persona_dir) if path.stem not in existing
    ]
    if not missing:
        return

    for file_path in missing:
        try:
            persona = load_json(file_path)
        except Exception as error:  # noqa: BLE001
            print(f"跳过无法读取的 Persona {file_path.name}：{error}")
            continue
        document = _persona_document(persona, file_path)
        database[PERSONAS_COLLECTION].replace_one(
            {"_id": document["_id"]},
            document,
            upsert=True,
        )


def load_personas_from_store(persona_dir, max_count=None) -> list[dict]:
    """按 ``agent_id`` 排序读取 Persona；MongoDB 为主存储。"""

    if not mongo_enabled():
        return _load_personas_from_files(persona_dir, max_count)

    _import_missing_personas(persona_dir)
    cursor = (
        get_database()[PERSONAS_COLLECTION]
        .find({}, {"data": 1, "agent_id": 1})
        .sort("agent_id", 1)
    )
    if max_count is not None:
        cursor = cursor.limit(max_count)
    return [
        document.get("data", {})
        for document in cursor
        if isinstance(document.get("data"), dict)
    ]


def upsert_personas(personas, persona_dir=None) -> int:
    """批量写入 Persona（以 agent_id 为键），返回写入数量。"""

    if not mongo_enabled():
        raise RuntimeError("personas 写入需要 MongoDB 存储后端。")
    if not isinstance(personas, list):
        raise ValueError("personas 必须是列表。")

    database = get_database()
    written = 0
    for index, persona in enumerate(personas):
        if not isinstance(persona, dict):
            raise ValueError(f"第 {index + 1} 个 Persona 必须是 JSON 对象。")
        agent_id = str(persona.get("agent_id", "")).strip()
        if not agent_id:
            raise ValueError(f"第 {index + 1} 个 Persona 缺少 agent_id。")
        source = (
            Path(persona_dir) / f"{agent_id}.json"
            if persona_dir is not None
            else Path(f"{agent_id}.json")
        )
        database[PERSONAS_COLLECTION].replace_one(
            {"_id": agent_id},
            _persona_document(persona, source),
            upsert=True,
        )
        written += 1
    return written


def count_personas() -> int:
    """返回库中的 Persona 数量。"""

    if not mongo_enabled():
        return 0
    return get_database()[PERSONAS_COLLECTION].count_documents({})


def load_persona_policy(path, required=True):
    """读取 Persona 政策配置，优先 MongoDB，缺失时从 JSON 回填。"""

    if not mongo_enabled():
        if Path(path).is_file():
            return load_json(path)
        if required:
            raise FileNotFoundError(f"Persona 政策配置不存在：{path}")
        return None

    database = get_database()
    document = database[PERSONA_POLICY_COLLECTION].find_one({"_id": "policy"})
    if document and isinstance(document.get("data"), dict):
        return document["data"]

    if Path(path).is_file():
        data = load_json(path)
        save_persona_policy(path, data)
        return data
    if required:
        raise FileNotFoundError(f"Persona 政策配置不存在：{path}")
    return None


def save_persona_policy(path, data) -> None:
    """写入 Persona 政策配置并同步 JSON 镜像。"""

    if not isinstance(data, dict):
        raise ValueError("Persona 政策配置必须是 JSON 对象。")
    if not mongo_enabled():
        save_json(path, data)
        return

    get_database()[PERSONA_POLICY_COLLECTION].replace_one(
        {"_id": "policy"},
        {
            "_id": "policy",
            "scope": scope_key(path),
            "source_path": str(Path(path).resolve()),
            "data": data,
            "updated_at": utc_now(),
        },
        upsert=True,
    )
    if json_mirror_enabled():
        save_json(path, data)


__all__ = [
    "count_personas",
    "load_persona_policy",
    "load_personas_from_store",
    "save_persona_policy",
    "upsert_personas",
]
