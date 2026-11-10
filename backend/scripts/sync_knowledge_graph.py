"""把已完成的策略会话补录到 Neo4j 事件图谱。

用于启用 Neo4j 之后，把历史已完成、但当时尚未入库的策略事件补进去；
新会话在运行结束时会自动入库，不需要本脚本。

用法::

    py backend/scripts/sync_knowledge_graph.py
    py backend/scripts/sync_knowledge_graph.py --experiment-id event_gaoyang
"""

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.application.knowledge_graph_sync import sync_event_after_run  # noqa: E402
from app.main.config.settings import EXPERIMENT_DIR  # noqa: E402

_COMPLETED = {"completed", "partial_failed"}


def main() -> int:
    parser = argparse.ArgumentParser(description="补录已完成策略会话到 Neo4j 图谱")
    parser.add_argument(
        "--experiment-id",
        default="",
        help="只处理名称包含该子串的实验（可选）",
    )
    args = parser.parse_args()

    if not EXPERIMENT_DIR.is_dir():
        print(f"实验目录不存在：{EXPERIMENT_DIR}", file=sys.stderr)
        return 1

    total = 0
    added = 0
    for experiment_dir in sorted(EXPERIMENT_DIR.iterdir()):
        if not experiment_dir.is_dir():
            continue
        if args.experiment_id and args.experiment_id not in experiment_dir.name:
            continue
        control_file = experiment_dir / "web_control.json"
        if not control_file.is_file():
            continue
        try:
            control = json.loads(control_file.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if control.get("status") not in _COMPLETED:
            continue
        total += 1
        result = sync_event_after_run(experiment_dir, control)
        if result.get("status") in {"added", "stored_locally"}:
            added += 1
        print(
            f"{experiment_dir.name}: "
            f"{result.get('status')} "
            f"event={result.get('event_id', '-')} "
            f"nodes={result.get('nodes', '-')} edges={result.get('edges', '-')}"
            + (f" error={result.get('error')}" if result.get("error") else "")
        )

    print(f"完成：扫描 {total} 个已完成会话，新增 {added} 个事件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
