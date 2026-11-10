"""Neo4j 图数据库访问层（历史事件知识图谱）。

后端不依赖 ``neo4j`` 驱动：通过 Neo4j 的 HTTP 事务接口执行参数化 Cypher，
运行环境只需要已有的 ``requests`` 依赖。标签与关系类型来自固定本体白名单
（与 ``pipelines/kg/ontology.py`` 保持一致），属性值全部走参数，避免注入。

Neo4j 不可用时由调用方回退到 ``graph.json`` 快照，不影响页面与仿真主流程。
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any

import requests


# 与 pipelines/kg/ontology.py 的 NODE_LABELS / REL_TYPES 对齐。
NODE_LABELS = frozenset(
    {
        "Event",
        "SubEvent",
        "Phase",
        "Actor",
        "Location",
        "Topic",
        "Cause",
        "Consequence",
        "Claim",
        "Snapshot",
        "Source",
    }
)
REL_TYPES = frozenset(
    {
        "HAS_PHASE",
        "HAS_SUBEVENT",
        "HAS_TOPIC",
        "HAS_LOCATION",
        "NEXT",
        "IN_PHASE",
        "INVOLVES",
        "AT_LOCATION",
        "CAUSED_BY",
        "LED_TO",
        "EVIDENCED_BY",
        "ABOUT",
        "PUBLISHED_BY",
        "SUPPORTED_BY",
        "HAS_SNAPSHOT",
    }
)

_BATCH_SIZE = 300


class Neo4jError(RuntimeError):
    """Neo4j 连接、认证或 Cypher 执行失败。"""


def build_merge_statements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """把 ``graph.json`` 形状的节点/边转成参数化 MERGE 语句。

    节点按 ``id`` MERGE 并补齐属性；关系按 ``(source, type, target)`` MERGE。
    全局实体（Actor / Topic / Location 等）因此可以在多个事件之间复用。
    """

    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    node_labels: dict[str, str] = {}
    statements: list[dict[str, Any]] = []

    for node in nodes:
        label = str(node.get("label") or "")
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        if label not in NODE_LABELS:
            raise Neo4jError(f"未定义的节点标签：{label}")
        node_labels[node_id] = label
        props = dict(node.get("props") or {})
        props["name"] = str(node.get("name") or props.get("name") or "")
        statements.append(
            {
                "statement": f"MERGE (n:`{label}` {{id: $id}}) SET n += $props",
                "parameters": {"id": node_id, "props": props},
            }
        )

    for edge in edges:
        rel_type = str(edge.get("type") or "")
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if not source or not target:
            continue
        if rel_type not in REL_TYPES:
            raise Neo4jError(f"未定义的关系类型：{rel_type}")
        source_label = node_labels.get(source)
        target_label = node_labels.get(target)
        match_source = (
            f"MATCH (a:`{source_label}` {{id: $source}})"
            if source_label
            else "MATCH (a {id: $source})"
        )
        match_target = (
            f"MATCH (b:`{target_label}` {{id: $target}})"
            if target_label
            else "MATCH (b {id: $target})"
        )
        edge_props = dict(edge.get("props") or {})
        set_clause = " SET r += $props" if edge_props else ""
        parameters = {"source": source, "target": target}
        if edge_props:
            parameters["props"] = edge_props
        statements.append(
            {
                "statement": (
                    f"{match_source} {match_target} "
                    f"MERGE (a)-[r:`{rel_type}`]->(b){set_clause}"
                ),
                "parameters": parameters,
            }
        )

    return statements


class Neo4jRepository:
    """Neo4j HTTP 事务接口的最小封装。"""

    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        database: str = "neo4j",
        timeout: float = 5.0,
        query_api: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.database = database or "neo4j"
        self.timeout = timeout
        # Neo4j Aura 只开放 Query API（/db/{db}/query/v2），本地 Neo4j
        # 默认走事务接口（/db/{db}/tx/commit）。
        self.query_api = query_api
        self._session = requests.Session()
        self._session.auth = (user, password)
        self._lock = threading.Lock()
        self._available: bool | None = None
        self._checked_at = 0.0

    @property
    def endpoint(self) -> str:
        suffix = "query/v2" if self.query_api else "tx/commit"
        return f"{self.base_url}/db/{self.database}/{suffix}"

    # ── 底层 ──────────────────────────────────────────────
    def _handle_response(self, response):
        if response.status_code in (401, 403):
            raise Neo4jError("Neo4j 认证失败，请检查 NEO4J_USER / NEO4J_PASSWORD。")
        if response.status_code >= 400:
            raise Neo4jError(
                f"Neo4j HTTP {response.status_code}：{response.text[:200]}"
            )
        return response.json()

    def _post(self, statements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not statements:
            return []
        if self.query_api:
            return [self._post_query(item) for item in statements]
        try:
            response = self._session.post(
                self.endpoint,
                json={"statements": statements},
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise Neo4jError(f"无法连接 Neo4j（{self.base_url}）：{error}") from error
        payload = self._handle_response(response)
        errors = payload.get("errors") or []
        if errors:
            first = errors[0] or {}
            raise Neo4jError(str(first.get("message") or first))
        return payload.get("results") or []

    def _post_query(self, item: dict[str, Any]) -> dict[str, Any]:
        """Neo4j Query API（Aura）：一次一条语句。"""

        try:
            response = self._session.post(
                self.endpoint,
                json={
                    "statement": item["statement"],
                    "parameters": item.get("parameters") or {},
                },
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise Neo4jError(f"无法连接 Neo4j（{self.base_url}）：{error}") from error
        payload = self._handle_response(response)
        errors = payload.get("errors") or []
        if errors:
            first = errors[0] or {}
            raise Neo4jError(str(first.get("message") or first))
        data = payload.get("data") or {}
        fields = data.get("fields") or []
        values = data.get("values") or []
        return {
            "columns": fields,
            "data": [{"row": list(row)} for row in values],
        }

    @staticmethod
    def _value(results: list[dict[str, Any]], index: int = 0):
        if index >= len(results):
            return None
        rows = results[index].get("data") or []
        if not rows:
            return None
        row = rows[0].get("row") or []
        return row[0] if row else None

    # ── 可用性 / 查询 ─────────────────────────────────────
    def available(self, ttl: float = 15.0) -> bool:
        """带短缓存的连通性探测，避免每次请求都 ping。"""

        now = time.monotonic()
        with self._lock:
            if self._available is not None and now - self._checked_at < ttl:
                return self._available
        try:
            results = self._post([{"statement": "RETURN 1 AS ok"}])
            ok = self._value(results) == 1
        except (Neo4jError, ValueError):
            ok = False
        with self._lock:
            self._available = ok
            self._checked_at = now
        return ok

    def event_exists(self, event_id: str) -> bool:
        results = self._post(
            [
                {
                    "statement": (
                        "MATCH (e:Event {event_id: $event_id}) "
                        "RETURN count(e) AS count"
                    ),
                    "parameters": {"event_id": str(event_id)},
                }
            ]
        )
        return bool(self._value(results) or 0)

    def count_events(self) -> int:
        results = self._post(
            [{"statement": "MATCH (e:Event) RETURN count(e) AS count"}]
        )
        return int(self._value(results) or 0)

    def event_ids(self) -> list[str]:
        """返回图中已有的事件 ID，用于本地快照补录判断。"""

        results = self._post(
            [
                {
                    "statement": (
                        "MATCH (e:Event) WHERE e.event_id IS NOT NULL "
                        "RETURN e.event_id AS event_id"
                    )
                }
            ]
        )
        ids = set()
        for record in (results[0].get("data") if results else []) or []:
            row = record.get("row") or []
            value = str(row[0]).strip() if row and row[0] is not None else ""
            if value:
                ids.add(value)
        return sorted(ids)

    def read_graph(self) -> dict[str, Any]:
        """读取本体范围内的全部节点与关系，返回 ``graph.json`` 形状。"""

        node_statement = (
            "MATCH (n) WHERE any(label IN labels(n) WHERE label IN $labels) "
            "RETURN labels(n) AS labels, properties(n) AS props"
        )
        edge_statement = (
            "MATCH (a)-[r]->(b) "
            "WHERE type(r) IN $types AND a.id IS NOT NULL AND b.id IS NOT NULL "
            "RETURN a.id AS source, type(r) AS type, b.id AS target, "
            "properties(r) AS props"
        )
        results = self._post(
            [
                {
                    "statement": node_statement,
                    "parameters": {"labels": sorted(NODE_LABELS)},
                },
                {
                    "statement": edge_statement,
                    "parameters": {"types": sorted(REL_TYPES)},
                },
            ]
        )

        nodes: list[dict[str, Any]] = []
        for record in (results[0].get("data") if results else []) or []:
            row = record.get("row") or []
            labels = row[0] or []
            props = dict(row[1] or {})
            label = next(
                (item for item in labels if item in NODE_LABELS), None
            )
            if not label:
                continue
            node_id = str(props.pop("id", "") or "").strip()
            if not node_id:
                continue
            name = str(props.pop("name", "") or "")
            nodes.append(
                {
                    "id": node_id,
                    "label": label,
                    "name": name,
                    "props": props,
                }
            )

        edges: list[dict[str, Any]] = []
        for record in (results[1].get("data") if len(results) > 1 else []) or []:
            row = record.get("row") or []
            if len(row) < 4:
                continue
            source, rel_type, target, props = row[:4]
            if rel_type not in REL_TYPES or not source or not target:
                continue
            edges.append(
                {
                    "source": str(source),
                    "target": str(target),
                    "type": str(rel_type),
                    "props": dict(props or {}),
                }
            )

        nodes.sort(key=lambda item: (item["label"], item["id"]))
        edges.sort(key=lambda item: (item["type"], item["source"], item["target"]))
        return {
            "meta": {
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "events": len(
                    [node for node in nodes if node["label"] == "Event"]
                ),
                "nodes": len(nodes),
                "edges": len(edges),
                "extraction_mode": "neo4j",
                "event_scope": "Neo4j 图数据库",
            },
            "nodes": nodes,
            "edges": edges,
        }

    # ── 写入 ─────────────────────────────────────────────
    def merge_graph(self, payload: dict[str, Any]) -> int:
        """把节点/边 MERGE 进 Neo4j，返回写入的节点+边数量。"""

        if self.query_api:
            return self._merge_graph_query(payload)
        statements = build_merge_statements(payload)
        for start in range(0, len(statements), _BATCH_SIZE):
            self._post(statements[start : start + _BATCH_SIZE])
        return len(statements)

    def _merge_graph_query(self, payload: dict[str, Any]) -> int:
        """Query API 批量写入：按节点标签/关系类型 UNWIND，减少请求数。"""

        node_labels: dict[str, str] = {}
        nodes_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for node in payload.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            label = str(node.get("label") or "")
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                continue
            if label not in NODE_LABELS:
                raise Neo4jError(f"未定义的节点标签：{label}")
            node_labels[node_id] = label
            props = dict(node.get("props") or {})
            props["name"] = str(node.get("name") or props.get("name") or "")
            nodes_by_label[label].append({"id": node_id, "props": props})

        edges_by_group: dict[
            tuple[str, str | None, str | None], list[dict[str, Any]]
        ] = defaultdict(list)
        for edge in payload.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            rel_type = str(edge.get("type") or "")
            source = str(edge.get("source") or "").strip()
            target = str(edge.get("target") or "").strip()
            if not source or not target:
                continue
            if rel_type not in REL_TYPES:
                raise Neo4jError(f"未定义的关系类型：{rel_type}")
            edges_by_group[
                (
                    rel_type,
                    node_labels.get(source),
                    node_labels.get(target),
                )
            ].append(
                {
                    "source": source,
                    "target": target,
                    "props": dict(edge.get("props") or {}),
                }
            )

        count = 0
        for label, items in nodes_by_label.items():
            self._post(
                [
                    {
                        "statement": (
                            f"UNWIND $nodes AS item "
                            f"MERGE (n:`{label}` {{id: item.id}}) "
                            "SET n += item.props"
                        ),
                        "parameters": {"nodes": items},
                    }
                ]
            )
            count += len(items)

        for (rel_type, source_label, target_label), items in edges_by_group.items():
            if source_label and target_label:
                match_source = f"MATCH (a:`{source_label}`) WHERE a.id = item.source"
                match_target = f"MATCH (b:`{target_label}`) WHERE b.id = item.target"
            else:
                match_source = "MATCH (a) WHERE a.id = item.source"
                match_target = "MATCH (b) WHERE b.id = item.target"
            self._post(
                [
                    {
                        "statement": (
                            "UNWIND $edges AS item "
                            f"{match_source} "
                            f"{match_target} "
                            f"MERGE (a)-[r:`{rel_type}`]->(b) "
                            "SET r += item.props"
                        ),
                        "parameters": {"edges": items},
                    }
                ]
            )
            count += len(items)
        return count

    def merge_event(self, payload: dict[str, Any]) -> int:
        """写入一个事件子图；节点/边已按事件自包含。"""

        return self.merge_graph(payload)


_REPOSITORY: Neo4jRepository | None = None
_REPOSITORY_LOCK = threading.Lock()


def get_repository() -> Neo4jRepository:
    """返回进程内共享的 Neo4j 仓库（配置来自 settings）。"""

    global _REPOSITORY
    if _REPOSITORY is not None:
        return _REPOSITORY
    with _REPOSITORY_LOCK:
        if _REPOSITORY is None:
            from app.main.config.settings import (
                NEO4J_DATABASE,
                NEO4J_HTTP_URL,
                NEO4J_PASSWORD,
                NEO4J_QUERY_API,
                NEO4J_TIMEOUT,
                NEO4J_USER,
            )

            _REPOSITORY = Neo4jRepository(
                base_url=NEO4J_HTTP_URL,
                user=NEO4J_USER,
                password=NEO4J_PASSWORD,
                database=NEO4J_DATABASE,
                timeout=NEO4J_TIMEOUT,
                query_api=(
                    NEO4J_QUERY_API
                    if NEO4J_QUERY_API is not None
                    else NEO4J_HTTP_URL.startswith("https://")
                ),
            )
    return _REPOSITORY


__all__ = [
    "NODE_LABELS",
    "REL_TYPES",
    "Neo4jError",
    "Neo4jRepository",
    "build_merge_statements",
    "get_repository",
]
