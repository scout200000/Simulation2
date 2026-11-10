"""历史事件知识图谱查询服务。

图谱本体与抽取在仓库根目录的 ``pipelines/kg`` 管线中实现。本服务负责：

* **优先读取 Neo4j**：页面拿到的是图数据库中的实时事件图；
* **自动初始化**：Neo4j 可用但为空时，把 ``KG_GRAPH_FILE`` 指向的
  ``graph.json`` 导入一次，保证首次打开页面就有数据；
* **JSON 快照兜底**：Neo4j 未启动或不可用时回退到本地快照，页面不中断；
* **提供事件写入入口**：策略运行结束后由 ``knowledge_graph_sync`` 调用
  ``get_repository()`` 判断事件是否已存在并写入。

配置见 ``app.main.config.settings``：``KG_NEO4J_ENABLED``、``NEO4J_HTTP_URL``、
``NEO4J_USER``、``NEO4J_PASSWORD``、``NEO4J_DATABASE``、``KG_GRAPH_FILE``。
"""

from __future__ import annotations

import threading
from pathlib import Path

from app.domain.knowledge_graph import build_event_graph
from app.infrastructure.graph.neo4j_repository import (
    Neo4jError,
    Neo4jRepository,
    get_repository,
)
from app.infrastructure.storage.json_storage import load_json
from app.main.config.settings import (
    KG_GRAPH_FILE,
    KG_NEO4J_ENABLED,
    NEO4J_DATABASE,
    NEO4J_HTTP_URL,
)

_LOCK = threading.Lock()
_JSON_CACHE: dict = {"signature": None, "payload": None}
_SEED_LOCK = threading.Lock()


def _json_signature(path: Path):
    stat = path.stat()
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _from_json() -> dict:
    path = Path(KG_GRAPH_FILE)
    if not path.is_file():
        raise FileNotFoundError(
            f"知识图谱文件不存在：{path}。请先运行 kg 管线生成 graph.json，"
            "或通过环境变量 KG_GRAPH_FILE 指向已有产物；也可以启动 Neo4j "
            "并导入图谱。"
        )

    signature = _json_signature(path)
    with _LOCK:
        if (
            _JSON_CACHE["signature"] == signature
            and _JSON_CACHE["payload"] is not None
        ):
            return _JSON_CACHE["payload"]
        payload = build_event_graph(load_json(path), source=str(path))
        payload["meta"]["storage"] = "json"
        _JSON_CACHE["signature"] = signature
        _JSON_CACHE["payload"] = payload
        return payload


def _seed_local_events(repository: Neo4jRepository) -> bool:
    """把本地快照中尚未进入 Neo4j 的事件补录进去。

    首次连接空库时相当于初始化；Neo4j 不可用期间写入本地的事件，也会在
    图数据库恢复后自动补录。已有事件不会重复写入（MERGE 幂等）。
    """

    path = Path(KG_GRAPH_FILE)
    if not path.is_file():
        return False
    raw = load_json(path)
    local_event_ids = set()
    for node in raw.get("nodes") or []:
        if not isinstance(node, dict) or node.get("label") != "Event":
            continue
        event_id = str((node.get("props") or {}).get("event_id") or "").strip()
        if event_id:
            local_event_ids.add(event_id)
    if not local_event_ids:
        return False
    remote_event_ids = set(repository.event_ids())
    if local_event_ids.issubset(remote_event_ids):
        return True
    repository.merge_graph(raw)
    return True


def _from_neo4j() -> dict | None:
    if not KG_NEO4J_ENABLED:
        return None

    repository = get_repository()
    if not repository.available():
        return None

    try:
        # 把本地快照中尚未进入 Neo4j 的事件补录进去（没有缺失时只读不写）。
        with _SEED_LOCK:
            _seed_local_events(repository)
        if repository.count_events() == 0:
            return None
        raw = repository.read_graph()
    except Neo4jError:
        return None

    payload = build_event_graph(
        raw,
        source=f"neo4j:{NEO4J_HTTP_URL}/{NEO4J_DATABASE}",
    )
    payload["meta"]["storage"] = "neo4j"
    return payload


def get_knowledge_graph() -> dict:
    """返回事件图谱视图：Neo4j 优先，本地快照兜底。"""

    payload = _from_neo4j()
    if payload is not None:
        return payload
    return _from_json()


def seed_neo4j_from_file(path: str | Path | None = None) -> dict:
    """把 ``graph.json`` 导入 Neo4j，返回导入统计。"""

    repository = get_repository()
    if not repository.available():
        raise Neo4jError("Neo4j 不可用，请检查 NEO4J_HTTP_URL 与认证配置。")

    source = Path(path or KG_GRAPH_FILE)
    if not source.is_file():
        raise FileNotFoundError(f"知识图谱文件不存在：{source}")
    raw = load_json(source)
    nodes = raw.get("nodes") or []
    edges = raw.get("edges") or []
    statements = repository.merge_graph(raw)
    return {
        "file": str(source),
        "events": len(
            [
                node
                for node in nodes
                if isinstance(node, dict) and node.get("label") == "Event"
            ]
        ),
        "nodes": len(nodes),
        "edges": len(edges),
        "statements": statements,
    }


__all__ = [
    "get_knowledge_graph",
    "get_repository",
    "seed_neo4j_from_file",
]
