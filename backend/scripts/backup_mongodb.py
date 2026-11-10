"""导出/恢复 future_simulation 单文件备份。

用法::

    # 默认导出到 data/backups/future_simulation.json
    py -3 backend/scripts/backup_mongodb.py

    # 指定输出文件
    py -3 backend/scripts/backup_mongodb.py --output data/backups/snapshot.json

    # 恢复（默认合并；--reset 先清空受管集合）
    py -3 backend/scripts/backup_mongodb.py --restore data/backups/future_simulation.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infrastructure.database.backup import (  # noqa: E402
    export_database,
    restore_database,
)
from app.infrastructure.database.mongo_client import (  # noqa: E402
    close_connection,
    get_database,
)
from app.main.config.settings import MONGO_BACKUP_FILE  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="MongoDB 单文件备份/恢复")
    parser.add_argument(
        "--output",
        default=str(MONGO_BACKUP_FILE),
        help="导出文件路径，默认 data/backups/future_simulation.json",
    )
    parser.add_argument(
        "--restore",
        metavar="FILE",
        help="从指定备份恢复，而不是导出",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="恢复前清空 personas/social_networks/events/event_states 集合",
    )
    args = parser.parse_args()

    try:
        get_database()
        if args.restore:
            summary = restore_database(args.restore, reset=args.reset)
            print("MongoDB 恢复完成：")
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

        payload = export_database(args.output)
        print(f"MongoDB 备份完成：{Path(args.output).resolve()}")
        print(
            json.dumps(
                {
                    "personas": len(payload["personas"]),
                    "persona_policies": len(payload["persona_policies"]),
                    "social_networks": len(payload["social_networks"]),
                    "events": len(payload["events"]),
                    "event_states": len(payload["event_states"]),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception as error:  # noqa: BLE001 - 脚本给出明确失败信息
        print(f"备份/恢复失败：{error}")
        return 1
    finally:
        close_connection()


if __name__ == "__main__":
    sys.exit(main())
