"""MongoDB 单文件备份与恢复。

清理 Persona、关系网络和事件记录的 JSON 源文件后，MongoDB 是唯一数据源。
本模块把五类集合导出为一个可提交、可审计的 JSON 文件，并在需要时恢复。

备份是逻辑导出，不保存 Mongo 的 ObjectId：恢复时用 ``agent_id``、
文件作用域、``(scope, event_id, step)`` 等业务主键重建文档。
"""

from __future__ import annotations

from pathlib import Path

from app.infrastructure.database.mongo_client import (
    EVENTS_COLLECTION,
    EVENT_STATES_COLLECTION,
    MONGO_DATABASE,
    PERSONAS_COLLECTION,
    PERSONA_POLICY_COLLECTION,
    SOCIAL_NETWORK_COLLECTION,
    get_database,
    utc_now,
)
from app.infrastructure.database.repositories.social_networks import network_id
from app.infrastructure.storage.json_storage import load_json, save_json
from app.main.config.settings import MONGO_BACKUP_FILE


BACKUP_VERSION = 1


def export_database(output_file=None) -> dict:
    """导出五类集合到一个 JSON 文件，返回备份内容。"""

    output_path = Path(output_file or MONGO_BACKUP_FILE)
    database = get_database()

    personas = []
    for document in database[PERSONAS_COLLECTION].find().sort("agent_id", 1):
        data = document.get("data")
        if not isinstance(data, dict):
            continue
        agent_id = str(document.get("agent_id") or document.get("_id") or "")
        if not agent_id:
            continue
        personas.append(
            {
                "agent_id": agent_id,
                "scope": document.get("scope"),
                "source_path": document.get("source_path"),
                "data": data,
            }
        )

    policies = []
    for document in database[PERSONA_POLICY_COLLECTION].find():
        data = document.get("data")
        if isinstance(data, dict):
            policies.append(
                {
                    "scope": document.get("scope"),
                    "source_path": document.get("source_path"),
                    "data": data,
                }
            )

    networks = []
    for document in database[SOCIAL_NETWORK_COLLECTION].find():
        data = document.get("data")
        if not isinstance(data, dict):
            continue
        networks.append(
            {
                "scope": document.get("scope") or document.get("_id"),
                "kind": document.get("kind") or "snapshot",
                "source_path": document.get("source_path"),
                "network_id": document.get("network_id") or network_id(data),
                "data": data,
            }
        )

    events = []
    for document in database[EVENTS_COLLECTION].find():
        data = document.get("data")
        if not isinstance(data, dict):
            continue
        events.append(
            {
                "scope": document.get("scope") or document.get("_id"),
                "source_path": document.get("source_path"),
                "data": data,
            }
        )

    event_states = []
    for document in database[EVENT_STATES_COLLECTION].find().sort(
        [("scope", 1), ("event_id", 1), ("step", 1)]
    ):
        record = document.get("record")
        if not isinstance(record, dict):
            continue
        event_states.append(
            {
                "scope": document.get("scope"),
                "event_id": document.get("event_id"),
                "step": document.get("step"),
                "record": record,
            }
        )

    payload = {
        "version": BACKUP_VERSION,
        "database": MONGO_DATABASE,
        "exported_at": utc_now().isoformat(),
        "personas": personas,
        "persona_policies": policies,
        "social_networks": networks,
        "events": events,
        "event_states": event_states,
    }
    save_json(output_path, payload)
    return payload


def restore_database(backup_file=None, reset=False) -> dict:
    """从备份恢复五类集合；``reset=True`` 时先清空集合。"""

    backup_path = Path(backup_file or MONGO_BACKUP_FILE)
    if not backup_path.is_file():
        raise FileNotFoundError(f"MongoDB 备份文件不存在：{backup_path}")

    payload = load_json(backup_path)
    if not isinstance(payload, dict):
        raise ValueError("MongoDB 备份必须是 JSON 对象。")
    if payload.get("version") != BACKUP_VERSION:
        raise ValueError(
            f"不支持的备份版本：{payload.get('version')}，"
            f"当前支持 {BACKUP_VERSION}。"
        )

    database = get_database()
    collections = (
        PERSONAS_COLLECTION,
        PERSONA_POLICY_COLLECTION,
        SOCIAL_NETWORK_COLLECTION,
        EVENTS_COLLECTION,
        EVENT_STATES_COLLECTION,
    )
    if reset:
        for name in collections:
            database[name].delete_many({})

    now = utc_now()
    for item in payload.get("personas", []):
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agent_id", "")).strip()
        data = item.get("data")
        if not agent_id or not isinstance(data, dict):
            continue
        database[PERSONAS_COLLECTION].replace_one(
            {"_id": agent_id},
            {
                "_id": agent_id,
                "agent_id": agent_id,
                "scope": item.get("scope"),
                "source_path": item.get("source_path"),
                "data": data,
                "updated_at": now,
            },
            upsert=True,
        )

    for item in payload.get("persona_policies", []):
        if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
            continue
        database[PERSONA_POLICY_COLLECTION].replace_one(
            {"_id": "policy"},
            {
                "_id": "policy",
                "scope": item.get("scope"),
                "source_path": item.get("source_path"),
                "data": item["data"],
                "updated_at": now,
            },
            upsert=True,
        )

    for item in payload.get("social_networks", []):
        if not isinstance(item, dict):
            continue
        scope = item.get("scope")
        data = item.get("data")
        if not scope or not isinstance(data, dict):
            continue
        database[SOCIAL_NETWORK_COLLECTION].replace_one(
            {"_id": scope},
            {
                "_id": scope,
                "scope": scope,
                "kind": item.get("kind") or "snapshot",
                "source_path": item.get("source_path"),
                "network_id": item.get("network_id") or network_id(data),
                "data": data,
                "updated_at": now,
            },
            upsert=True,
        )

    for item in payload.get("events", []):
        if not isinstance(item, dict):
            continue
        scope = item.get("scope")
        data = item.get("data")
        if not scope or not isinstance(data, dict):
            continue
        event_id = str(data.get("event_id", "")).strip()
        if not event_id:
            continue
        database[EVENTS_COLLECTION].replace_one(
            {"_id": scope},
            {
                "_id": scope,
                "scope": scope,
                "event_id": event_id,
                "source_path": item.get("source_path"),
                "data": data,
                "updated_at": now,
            },
            upsert=True,
        )

    scopes = {
        item.get("scope")
        for item in payload.get("event_states", [])
        if isinstance(item, dict) and item.get("scope")
    }
    for scope in scopes:
        database[EVENT_STATES_COLLECTION].delete_many({"scope": scope})
    for item in payload.get("event_states", []):
        if not isinstance(item, dict):
            continue
        scope = item.get("scope")
        record = item.get("record")
        if not scope or not isinstance(record, dict):
            continue
        event_id = str(record.get("event_id", "")).strip()
        step = record.get("step")
        if not event_id or isinstance(step, bool) or not isinstance(step, int):
            continue
        database[EVENT_STATES_COLLECTION].replace_one(
            {"scope": scope, "event_id": event_id, "step": step},
            {
                "scope": scope,
                "event_id": event_id,
                "step": step,
                "record": record,
                "updated_at": now,
            },
            upsert=True,
        )

    return {
        "backup_file": str(backup_path),
        "personas": database[PERSONAS_COLLECTION].count_documents({}),
        "persona_policies": database[
            PERSONA_POLICY_COLLECTION
        ].count_documents({}),
        "social_networks": database[
            SOCIAL_NETWORK_COLLECTION
        ].count_documents({}),
        "events": database[EVENTS_COLLECTION].count_documents({}),
        "event_states": database[EVENT_STATES_COLLECTION].count_documents({}),
    }


__all__ = ["BACKUP_VERSION", "export_database", "restore_database"]
