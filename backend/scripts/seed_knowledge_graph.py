"""把 graph.json 导入 Neo4j 事件知识图谱。

用法::

    py backend/scripts/seed_knowledge_graph.py
    py backend/scripts/seed_knowledge_graph.py --file pipelines/kg/out/graph.json
"""

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.application.knowledge_graph_service import seed_neo4j_from_file  # noqa: E402
from app.main.config.settings import KG_GRAPH_FILE  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="导入历史事件知识图谱到 Neo4j")
    parser.add_argument(
        "--file",
        default=str(KG_GRAPH_FILE),
        help="graph.json 路径（默认 KG_GRAPH_FILE）",
    )
    args = parser.parse_args()
    try:
        result = seed_neo4j_from_file(args.file)
    except Exception as error:  # noqa: BLE001 - CLI 直接反馈错误
        print(f"导入失败：{error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
