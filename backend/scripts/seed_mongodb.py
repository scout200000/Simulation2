"""把现有 Persona、关系网络与事件记录迁移到 MongoDB。

默认导入：

* ``data/processed/personas/agent_*.json`` → ``personas``；
* ``data/processed/personas/policy_config.json`` → ``persona_policies``；
* ``configs/social_network_config.json`` 与 ``data/``、``var/`` 下已有网络快照
  → ``social_networks``；
* 默认事件、实验批次 ``event_input.json`` → ``events``；
* ``var/state`` 与 ``var/experiments`` 下的事件状态历史 → ``event_states``。

清理源 JSON 后，源文件不存在时自动从
``data/backups/future_simulation.json`` 恢复。也可显式指定备份：

    py -3 backend/scripts/seed_mongodb.py
    py -3 backend/scripts/seed_mongodb.py --reset
    py -3 backend/scripts/seed_mongodb.py --from-backup
    py -3 backend/scripts/seed_mongodb.py --from-backup --backup data/backups/old.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infrastructure.database.backup import restore_database  # noqa: E402
from app.infrastructure.database.mongo_client import (  # noqa: E402
    EVENTS_COLLECTION,
    EVENT_STATES_COLLECTION,
    PERSONAS_COLLECTION,
    PERSONA_POLICY_COLLECTION,
    SOCIAL_NETWORK_COLLECTION,
    close_connection,
    get_database,
    mongo_health,
)
from app.infrastructure.database.repositories.events import (  # noqa: E402
    save_event_input,
    save_event_state_history,
)
from app.infrastructure.database.repositories.personas import (  # noqa: E402
    save_persona_policy,
    upsert_personas,
)
from app.infrastructure.database.repositories.social_networks import (  # noqa: E402
    save_social_network,
    save_social_network_config,
)
from app.infrastructure.storage.json_storage import load_json  # noqa: E402
from app.main.config.settings import (  # noqa: E402
    DATA_DIR,
    EVENT_FILE,
    EVENT_STATE_FILE,
    MONGO_BACKUP_FILE,
    PERSONA_DIR,
    POLICY_FILE,
    SOCIAL_NETWORK_CONFIG_FILE,
    STORAGE_BACKEND,
    VAR_DIR,
)


COLLECTIONS = (
    PERSONAS_COLLECTION,
    PERSONA_POLICY_COLLECTION,
    SOCIAL_NETWORK_COLLECTION,
    EVENTS_COLLECTION,
    EVENT_STATES_COLLECTION,
)


def _skip_path(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & {"node_modules", "__pycache__", ".data", ".git"})


def _data_files(name: str) -> list[Path]:
    """在输入目录与运行产物目录中查找指定文件名。"""

    roots = [root for root in (DATA_DIR, VAR_DIR) if root.is_dir()]
    return sorted(
        path
        for root in roots
        for path in root.rglob(name)
        if path.is_file() and not _skip_path(path)
    )


def _normalize_event_states(document):
    if isinstance(document, list):
        return document
    if isinstance(document, dict) and isinstance(document.get("history"), list):
        return document["history"]
    return None


def reset_collections() -> None:
    """清空受管集合中的文档，保留集合与索引。"""

    database = get_database()
    for name in COLLECTIONS:
        database[name].delete_many({})
    print(f"已清空集合：{', '.join(COLLECTIONS)}")


def seed_personas() -> int:
    persona_files = sorted(Path(PERSONA_DIR).glob("agent_*.json"))
    personas = []
    for path in persona_files:
        try:
            data = load_json(path)
        except Exception as error:  # noqa: BLE001
            print(f"跳过无法读取的 Persona {path.name}：{error}")
            continue
        if isinstance(data, dict):
            if not data.get("agent_id"):
                data["agent_id"] = path.stem
            personas.append(data)
    written = upsert_personas(personas, persona_dir=PERSONA_DIR)
    print(f"Persona：{written} 条（目录 {len(persona_files)} 个文件）")
    return written


def seed_policy() -> int:
    if not Path(POLICY_FILE).is_file():
        print("Persona 政策配置：文件不存在，跳过。")
        return 0
    policy = load_json(POLICY_FILE)
    save_persona_policy(POLICY_FILE, policy)
    print("Persona 政策配置：1 条")
    return 1


def seed_networks() -> tuple[int, int]:
    config_count = 0
    if Path(SOCIAL_NETWORK_CONFIG_FILE).is_file():
        config = load_json(SOCIAL_NETWORK_CONFIG_FILE)
        save_social_network_config(SOCIAL_NETWORK_CONFIG_FILE, config)
        config_count = 1
        print("关系网络配置：1 条")
    else:
        print("关系网络配置：文件不存在，跳过。")

    snapshot_count = 0
    for path in _data_files("social_network_snapshot.json"):
        try:
            snapshot = load_json(path)
        except Exception as error:  # noqa: BLE001
            print(f"跳过无法读取的网络快照 {path}：{error}")
            continue
        if not isinstance(snapshot, dict):
            print(f"跳过非对象的网络快照：{path}")
            continue
        save_social_network(path, snapshot)
        snapshot_count += 1
    print(f"关系网络快照：{snapshot_count} 条")
    return config_count, snapshot_count


def seed_events() -> tuple[int, int]:
    event_files: list[Path] = []
    if Path(EVENT_FILE).is_file():
        event_files.append(Path(EVENT_FILE))
    event_files.extend(_data_files("event_input.json"))
    event_files.extend(_data_files("event.json"))

    seen = set()
    event_count = 0
    for path in event_files:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            data = load_json(path)
        except Exception as error:  # noqa: BLE001
            print(f"跳过无法读取的事件输入 {path}：{error}")
            continue
        if not isinstance(data, dict) or not data.get("event_id"):
            print(f"跳过缺少 event_id 的事件输入：{path}")
            continue
        save_event_input(path, data)
        event_count += 1
    print(f"事件输入：{event_count} 条")

    state_files: list[Path] = []
    if Path(EVENT_STATE_FILE).is_file():
        state_files.append(Path(EVENT_STATE_FILE))
    state_files.extend(_data_files("event_state_history.json"))

    state_scope_count = 0
    state_record_count = 0
    for path in state_files:
        try:
            document = load_json(path)
        except Exception as error:  # noqa: BLE001
            print(f"跳过无法读取的事件状态 {path}：{error}")
            continue
        records = _normalize_event_states(document)
        if records is None:
            print(f"跳过格式不正确的事件状态：{path}")
            continue
        valid = [
            record
            for record in records
            if isinstance(record, dict)
            and record.get("event_id")
            and isinstance(record.get("step"), int)
        ]
        if len(valid) != len(records):
            print(
                f"事件状态 {path} 有 {len(records) - len(valid)} 条记录"
                "缺少 event_id 或整数 step，已跳过。"
            )
        if not valid:
            continue
        save_event_state_history(path, valid)
        state_scope_count += 1
        state_record_count += len(valid)
    print(
        f"事件状态：{state_record_count} 条记录，"
        f"覆盖 {state_scope_count} 个状态目录"
    )
    return event_count, state_record_count


def print_summary() -> None:
    health = mongo_health()
    print("\nMongoDB 摘要：")
    print(json.dumps(health, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移 Persona/网络/事件到 MongoDB")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="先清空 personas/social_networks/events/event_states 集合",
    )
    parser.add_argument(
        "--from-backup",
        action="store_true",
        help="跳过源 JSON，直接从单文件备份恢复",
    )
    parser.add_argument(
        "--backup",
        default=str(MONGO_BACKUP_FILE),
        help="单文件备份路径，默认 data/backups/future_simulation.json",
    )
    args = parser.parse_args()

    if STORAGE_BACKEND != "mongodb":
        print(
            "当前 SIMULATION_STORAGE_BACKEND="
            f"{STORAGE_BACKEND}，请先切回 mongodb 再执行迁移。"
        )
        return 2

    try:
        get_database()

        source_exists = (
            any(Path(PERSONA_DIR).glob("agent_*.json"))
            or Path(POLICY_FILE).is_file()
            or Path(SOCIAL_NETWORK_CONFIG_FILE).is_file()
            or Path(EVENT_FILE).is_file()
        )
        backup_path = Path(args.backup)
        if args.from_backup or not source_exists:
            if not backup_path.is_file():
                raise FileNotFoundError(
                    "源 JSON 已清理且备份不存在："
                    f"{backup_path}；请恢复备份或重新提供源文件。"
                )
            summary = restore_database(backup_path, reset=args.reset)
            print(f"已从备份恢复：{backup_path.resolve()}")
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            print_summary()
            return 0

        if args.reset:
            reset_collections()

        seed_personas()
        seed_policy()
        seed_networks()
        seed_events()

        print_summary()
        return 0
    except Exception as error:  # noqa: BLE001 - 脚本需要给出明确失败信息
        print(f"迁移失败：{error}")
        return 1
    finally:
        close_connection()


if __name__ == "__main__":
    sys.exit(main())
