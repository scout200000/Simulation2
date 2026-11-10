"""事件记录（事件输入与逐轮事件状态）的 MongoDB 仓储。

集合设计：

* ``events``：一个事件输入文档，``_id`` 为文件作用域，同时保存 ``event_id``；
* ``event_states``：一条事件状态记录一个文档，按
  ``(scope, event_id, step)`` 唯一，按 ``event_id, step`` 排序读出。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.infrastructure.database.mongo_client import (
    EVENTS_COLLECTION,
    EVENT_STATES_COLLECTION,
    get_database,
    json_mirror_enabled,
    mongo_enabled,
    scope_key,
    scope_prefix,
    utc_now,
)
from app.infrastructure.storage.json_storage import load_json, save_json


def _normalize_history(document):
    """把事件状态文件内容统一为记录数组。"""

    if isinstance(document, list):
        return document
    if isinstance(document, dict) and isinstance(document.get("history"), list):
        return document["history"]
    raise ValueError("event_state_history.json 必须是状态记录数组。")


def load_event_input(path, required=True):
    """读取事件输入，优先 MongoDB，缺失时从 JSON 镜像回填。"""

    if not mongo_enabled():
        if Path(path).is_file():
            return load_json(path)
        if required:
            raise FileNotFoundError(f"事件文件不存在：{path}")
        return None

    document = get_database()[EVENTS_COLLECTION].find_one(
        {"_id": scope_key(path)}
    )
    if document and isinstance(document.get("data"), dict):
        return document["data"]

    if Path(path).is_file():
        data = load_json(path)
        save_event_input(path, data)
        return data
    if required:
        raise FileNotFoundError(f"事件文件不存在：{path}")
    return None


def save_event_input(path, event_input) -> None:
    """写入事件输入并同步 JSON 镜像。"""

    if not isinstance(event_input, dict):
        raise ValueError("事件输入必须是 JSON 对象。")
    event_id = str(event_input.get("event_id", "")).strip()
    if not event_id:
        raise ValueError("事件输入缺少 event_id。")

    if not mongo_enabled():
        save_json(path, event_input)
        return

    get_database()[EVENTS_COLLECTION].replace_one(
        {"_id": scope_key(path)},
        {
            "_id": scope_key(path),
            "scope": scope_key(path),
            "event_id": event_id,
            "source_path": str(Path(path).resolve()),
            "data": event_input,
            "updated_at": utc_now(),
        },
        upsert=True,
    )
    if json_mirror_enabled():
        save_json(path, event_input)


def event_input_exists(path) -> bool:
    """判断事件输入是否已存在于 MongoDB 或 JSON 镜像。"""

    if not mongo_enabled():
        return Path(path).is_file()
    document = get_database()[EVENTS_COLLECTION].find_one(
        {"_id": scope_key(path)},
        {"_id": 1},
    )
    return document is not None or Path(path).is_file()


def delete_event_input(path) -> None:
    """删除单个事件输入文档（不删除 JSON 镜像）。"""

    if not mongo_enabled():
        return
    get_database()[EVENTS_COLLECTION].delete_one({"_id": scope_key(path)})


def load_event_state_history(path, event_id=None, required=False):
    """读取事件状态记录；MongoDB 为空时从 JSON 镜像回填。"""

    if not mongo_enabled():
        if not Path(path).is_file():
            if required:
                raise FileNotFoundError(f"事件状态文件不存在：{path}")
            return []
        return _filter_records(_normalize_history(load_json(path)), event_id)

    query = {"scope": scope_key(path)}
    if event_id is not None:
        query["event_id"] = event_id
    records = [
        document["record"]
        for document in get_database()[EVENT_STATES_COLLECTION]
        .find(query)
        .sort([("event_id", 1), ("step", 1)])
        if isinstance(document.get("record"), dict)
    ]
    if records:
        return records

    if Path(path).is_file():
        document = load_json(path)
        all_records = _normalize_history(document)
        save_event_state_history(path, all_records)
        return _filter_records(all_records, event_id)

    if required:
        raise FileNotFoundError(f"事件状态文件不存在：{path}")
    return []


def _filter_records(records, event_id):
    if event_id is None:
        return records
    return [record for record in records if record.get("event_id") == event_id]


def save_event_state_history(path, records, mirror=True) -> None:
    """用给定记录数组整体替换一个作用域的事件状态。"""

    if not isinstance(records, list):
        raise ValueError("事件状态历史必须是记录数组。")
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"事件状态历史第 {index} 条必须是 JSON 对象。")
        if not str(record.get("event_id", "")).strip():
            raise ValueError(f"事件状态历史第 {index} 条缺少 event_id。")
        if isinstance(record.get("step"), bool) or not isinstance(
            record.get("step"), int
        ):
            raise ValueError(f"事件状态历史第 {index} 条缺少整数 step。")

    if not mongo_enabled():
        save_json(path, records)
        return

    collection = get_database()[EVENT_STATES_COLLECTION]
    collection.delete_many({"scope": scope_key(path)})
    if records:
        collection.insert_many(
            [
                {
                    "scope": scope_key(path),
                    "event_id": record["event_id"],
                    "step": record["step"],
                    "record": record,
                    "updated_at": utc_now(),
                }
                for record in records
            ]
        )
    if mirror and json_mirror_enabled():
        save_json(path, records)


def append_event_state_record(path, record) -> None:
    """追加或覆盖单条事件状态记录。"""

    if not isinstance(record, dict):
        raise ValueError("事件状态记录必须是 JSON 对象。")
    if not str(record.get("event_id", "")).strip():
        raise ValueError("事件状态记录缺少 event_id。")
    if isinstance(record.get("step"), bool) or not isinstance(
        record.get("step"), int
    ):
        raise ValueError("事件状态记录缺少整数 step。")

    if not mongo_enabled():
        if Path(path).is_file():
            records = _normalize_history(load_json(path))
        else:
            records = []
        records = [
            item
            for item in records
            if not (
                item.get("event_id") == record["event_id"]
                and item.get("step") == record["step"]
            )
        ]
        records.append(record)
        save_json(path, records)
        return

    get_database()[EVENT_STATES_COLLECTION].replace_one(
        {
            "scope": scope_key(path),
            "event_id": record["event_id"],
            "step": record["step"],
        },
        {
            "scope": scope_key(path),
            "event_id": record["event_id"],
            "step": record["step"],
            "record": record,
            "updated_at": utc_now(),
        },
        upsert=True,
    )
    if json_mirror_enabled():
        # 镜像文件保持完整历史，便于实验目录复制和输入指纹。
        save_event_state_history(
            path,
            load_event_state_history(path, required=False),
            mirror=True,
        )


def event_state_history_exists(path) -> bool:
    """判断事件状态是否已存在于 MongoDB 或 JSON 镜像。"""

    if not mongo_enabled():
        return Path(path).is_file()
    if (
        get_database()[EVENT_STATES_COLLECTION].find_one(
            {"scope": scope_key(path)},
            {"_id": 1},
        )
        is not None
    ):
        return True
    return Path(path).is_file()


def delete_event_state_history(path) -> None:
    """删除一个作用域的事件状态文档。"""

    if not mongo_enabled():
        return
    get_database()[EVENT_STATES_COLLECTION].delete_many(
        {"scope": scope_key(path)}
    )


def delete_event_states_under(directory) -> None:
    """删除目录作用域下的全部事件状态文档。"""

    if not mongo_enabled():
        return
    pattern = "^" + re.escape(scope_prefix(directory))
    get_database()[EVENT_STATES_COLLECTION].delete_many(
        {"scope": {"$regex": pattern}}
    )


def copy_event_state_history(source_path, target_path) -> None:
    """把源作用域的事件状态复制到目标作用域（用于检查点/场景快照）。"""

    if not mongo_enabled():
        if Path(source_path).is_file():
            save_json(target_path, load_json(source_path))
        return

    source_records = [
        document["record"]
        for document in get_database()[EVENT_STATES_COLLECTION]
        .find({"scope": scope_key(source_path)})
        .sort([("event_id", 1), ("step", 1)])
        if isinstance(document.get("record"), dict)
    ]
    if not source_records and Path(source_path).is_file():
        source_records = _normalize_history(load_json(source_path))

    save_event_state_history(target_path, source_records)


__all__ = [
    "append_event_state_record",
    "copy_event_state_history",
    "delete_event_input",
    "delete_event_state_history",
    "delete_event_states_under",
    "event_input_exists",
    "event_state_history_exists",
    "load_event_input",
    "load_event_state_history",
    "save_event_input",
    "save_event_state_history",
]
