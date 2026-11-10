"""策略运行结束后的知识图谱入库（Neo4j + 本地快照）。

每次策略会话运行完成后：

1. 从会话读取事件正文、公告时间线/所选方案、评论角度，抽取事件子图；
2. 把事件子图合并进本地快照 ``KG_GRAPH_FILE``（页面在 Neo4j 不可用时的
   兜底数据源，同时作为 Neo4j 的初始化/补录来源）；
3. 如果 Neo4j 可用，再检查 ``Event.event_id`` 是否已存在：已存在则跳过，
   新事件则 MERGE 进 Neo4j；全局实体由 Neo4j 复用，自动形成跨事件关联。

Neo4j 不可用时事件不会丢失：会写入本地快照并返回 ``stored_locally``，
页面仍能在“本地快照”模式下看到该事件；Neo4j 恢复后后端会把快照 MERGE
进图数据库。事件输入优先读本地 ``event_input.json``，缺失时从 MongoDB
读取（``MONGO_WRITE_JSON_MIRROR=0`` 时事件只在 MongoDB 中）。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import Counter
from pathlib import Path

from app.infrastructure.storage.json_storage import load_json
from app.main.config.settings import (
    KG_GRAPH_FILE,
    KG_NEO4J_ENABLED,
    PROJECT_DIR,
)

_EMOTIONS = ("negative", "neutral", "positive")
_LOCAL_LOCK = threading.Lock()


def _ensure_pipelines_importable() -> None:
    root = str(PROJECT_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)


def _initial_opinion(comment_pool: dict | None) -> dict | None:
    """用初始评论池的情绪分布近似第一轮舆情比例。"""

    comments = (comment_pool or {}).get("comments") or []
    counts = Counter(
        str(comment.get("emotion"))
        for comment in comments
        if isinstance(comment, dict) and comment.get("emotion")
    )
    total = sum(counts.get(emotion, 0) for emotion in _EMOTIONS)
    if not total:
        return None
    return {
        "mode": "strategy_comment_pool",
        "observed_distribution": {
            emotion: {"estimate": counts.get(emotion, 0) / total}
            for emotion in _EMOTIONS
        },
    }


def _official_updates(control: dict) -> dict | None:
    """把会话的公告时间线/所选方案转成 kg 管线的 official_updates。"""

    updates: list[dict] = []
    timeline = control.get("announcement_timeline") or []
    for item in timeline:
        statement = str(item.get("official_statement") or "").strip()
        if not statement:
            continue
        updates.append(
            {
                "step": item.get("round"),
                "official_statement": statement,
                "official_statement_status": item.get(
                    "official_statement_status", "clear"
                ),
            }
        )

    if not updates:
        strategy = control.get("strategy") or {}
        statement = str(strategy.get("official_statement") or "").strip()
        if statement:
            updates.append(
                {
                    "step": control.get("response_step")
                    or control.get("current_step"),
                    "official_statement": statement,
                    "official_statement_status": strategy.get(
                        "official_statement_status", "clear"
                    ),
                }
            )

    return {"official_updates": updates} if updates else None


def _read_optional(path_value) -> dict | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_file():
        return None
    try:
        return load_json(path)
    except (OSError, ValueError):
        return None


def _load_event_input(event_file) -> dict:
    """事件输入优先本地 JSON，缺失时走 MongoDB（JSON 镜像关闭时）。"""

    path = Path(event_file)
    if path.is_file():
        return load_json(path)
    from app.infrastructure.database.repositories import load_event_input

    return load_event_input(path)


def build_session_extraction(experiment_dir: Path, control: dict) -> dict:
    """从一次策略会话的材料中抽取事件要素。"""

    _ensure_pipelines_importable()
    from pipelines.kg.extract import Bundle, bundle_provenance, heuristic_extract

    experiment_dir = Path(experiment_dir)
    event_file = control.get("event_file") or str(
        experiment_dir / "event_input.json"
    )
    event_input = _load_event_input(event_file)

    comment_pool = _read_optional(
        control.get("comment_pool_file")
        or str(experiment_dir / "comment_pool.json")
    )
    event_id = str(
        control.get("event_id") or event_input.get("event_id") or ""
    ).strip()

    bundle = Bundle(
        event_id=event_id,
        directory=experiment_dir,
        event_input=event_input,
        official=_official_updates(control),
        comments=comment_pool,
        initial_opinion=_initial_opinion(comment_pool),
        run_dir=experiment_dir,
        origin="strategy_run",
    )
    extraction = heuristic_extract(bundle)
    extraction["provenance"] = bundle_provenance(bundle)
    extraction["source_bundle"] = str(experiment_dir)
    return extraction


def build_event_payload(
    experiment_dir: Path,
    extraction: dict,
) -> dict:
    """把单个事件的抽取结果建成 ``graph.json`` 形状的子图。"""

    _ensure_pipelines_importable()
    from pipelines.kg.graph import build_graph

    meta = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "events": 1,
        "extraction_mode": extraction.get("extraction_mode", "heuristic"),
        "source_dir": str(experiment_dir),
        "event_scope": "策略运行事件",
        "origin": "strategy_run",
    }
    return build_graph([extraction], {}, meta)


def _event_scoped_node(node_id: str, event_id: str) -> bool:
    """判断节点是否属于该事件（用于替换旧版本，保留共享实体）。"""

    return node_id == f"event:{event_id}" or any(
        node_id.startswith(prefix)
        for prefix in (
            f"phase:{event_id}:",
            f"subevent:{event_id}:",
            f"claim:{event_id}:",
            f"snapshot:{event_id}:",
        )
    )


def merge_local_snapshot(payload: dict, event_id: str) -> dict:
    """把事件子图合并进本地 graph.json 快照（按事件替换，保留共享实体）。"""

    path = Path(KG_GRAPH_FILE)
    with _LOCAL_LOCK:
        if path.is_file():
            raw = load_json(path)
            if not isinstance(raw, dict):
                raw = {"meta": {}, "nodes": [], "edges": []}
        else:
            raw = {"meta": {}, "nodes": [], "edges": []}

        nodes: dict[str, dict] = {}
        for node in raw.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "")
            if not node_id or _event_scoped_node(node_id, event_id):
                continue
            nodes[node_id] = node

        edges: dict[tuple[str, str, str], dict] = {}
        for edge in raw.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            if not source or not target:
                continue
            if _event_scoped_node(source, event_id) or _event_scoped_node(
                target, event_id
            ):
                continue
            edges[(source, str(edge.get("type") or ""), target)] = edge

        for node in payload.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "")
            if node_id:
                nodes[node_id] = node
        for edge in payload.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            if source and target:
                edges[(source, str(edge.get("type") or ""), target)] = edge

        now = time.strftime("%Y-%m-%d %H:%M:%S")
        event_count = len(
            [node for node in nodes.values() if node.get("label") == "Event"]
        )
        meta = dict(raw.get("meta") or {})
        meta.update(payload.get("meta") or {})
        meta.update(
            {
                "generated_at": now,
                "runtime_synced_at": now,
                "events": event_count,
                "nodes": len(nodes),
                "edges": len(edges),
                "event_scope": f"{event_count} 个事件（本地快照）",
            }
        )
        merged = {
            "meta": meta,
            "nodes": sorted(
                nodes.values(),
                key=lambda item: (item.get("label") or "", item.get("id") or ""),
            ),
            "edges": sorted(
                edges.values(),
                key=lambda item: (
                    item.get("type") or "",
                    item.get("source") or "",
                    item.get("target") or "",
                ),
            ),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(merged, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)

    return {
        "file": str(path),
        "events": event_count,
        "nodes": len(nodes),
        "edges": len(edges),
    }


def _payload_counts(payload: dict) -> dict:
    return {
        "nodes": len(payload.get("nodes") or []),
        "edges": len(payload.get("edges") or []),
    }


def sync_event_after_run(experiment_dir: Path, control: dict) -> dict:
    """策略运行结束后写入本地快照，并在 Neo4j 可用时写入图数据库。

    返回状态：

    * ``added``：Neo4j 新增成功（同时已写入本地快照）；
    * ``exists``：Neo4j 中已有该 event_id，未重复写入（本地快照已同步）；
    * ``stored_locally``：Neo4j 未启用/不可用，已写入本地快照；
    * ``skipped``：缺少 event_id；
    * ``failed``：抽取或写入失败。
    """

    event_id = str(control.get("event_id") or "").strip()
    if not event_id:
        return {"status": "skipped", "reason": "missing_event_id"}

    try:
        extraction = build_session_extraction(experiment_dir, control)
        payload = build_event_payload(experiment_dir, extraction)
    except Exception as error:  # noqa: BLE001 - 入库失败不应中断仿真
        return {"status": "failed", "event_id": event_id, "error": str(error)}

    counts = _payload_counts(payload)
    local_result = None
    local_error = None
    try:
        local_result = merge_local_snapshot(payload, event_id)
    except Exception as error:  # noqa: BLE001
        local_error = str(error)

    def result(status: str, **extra) -> dict:
        data = {"status": status, "event_id": event_id, **counts}
        if local_result:
            data["snapshot"] = local_result
        if local_error:
            data["snapshot_error"] = local_error
        data.update(extra)
        return data

    if not KG_NEO4J_ENABLED:
        if not local_result:
            return result("failed", error=local_error)
        return result("stored_locally", reason="neo4j_disabled")

    from app.application.knowledge_graph_service import get_repository
    from app.infrastructure.graph.neo4j_repository import Neo4jError

    try:
        repository = get_repository()
        if not repository.available():
            if not local_result:
                return result("failed", error=local_error)
            return result("stored_locally", reason="neo4j_unavailable")
        if repository.event_exists(event_id):
            return result("exists")
        statements = repository.merge_graph(payload)
    except Neo4jError as error:
        if local_result:
            return result(
                "stored_locally",
                reason="neo4j_error",
                error=str(error),
            )
        return result("failed", error=str(error))

    return result("added", statements=statements)


__all__ = [
    "build_event_payload",
    "build_session_extraction",
    "merge_local_snapshot",
    "sync_event_after_run",
]
