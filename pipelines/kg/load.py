# -*- coding: utf-8 -*-
"""把生成好的 Cypher 语句写入 Neo4j，并做最小验收。

依赖：pip install neo4j（只有真正导库时才需要）。
"""

from __future__ import annotations

from typing import Any


def _driver(uri: str, user: str, password: str):
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:  # pragma: no cover - 取决于运行环境
        raise RuntimeError("缺少 neo4j 驱动，请先执行：py -m pip install neo4j") from exc
    return GraphDatabase.driver(uri, auth=(user, password))


def load_statements(
    statements: list[str],
    uri: str = "bolt://localhost:7687",
    user: str = "neo4j",
    password: str = "password",
    database: str | None = None,
    batch_size: int = 100,
) -> int:
    """分批执行语句，返回执行条数。约束语句单独执行。"""
    driver = _driver(uri, user, password)
    executed = 0
    try:
        with driver.session(database=database) as session:
            constraints = [s for s in statements if s.startswith("CREATE CONSTRAINT")]
            data = [s for s in statements if not s.startswith("CREATE CONSTRAINT")]
            for statement in constraints:
                session.run(statement).consume()
                executed += 1
            for start in range(0, len(data), batch_size):
                batch = data[start : start + batch_size]

                def run_batch(tx, batch=batch):
                    for statement in batch:
                        tx.run(statement).consume()
                    return len(batch)

                executed += session.execute_write(run_batch)
    finally:
        driver.close()
    return executed


def verify(
    uri: str = "bolt://localhost:7687",
    user: str = "neo4j",
    password: str = "password",
    database: str | None = None,
) -> dict[str, Any]:
    """返回图规模、标签/关系分布与事件子图规模，用于导库后自检。"""
    driver = _driver(uri, user, password)
    result: dict[str, Any] = {}
    try:
        with driver.session(database=database) as session:
            result["labels"] = [
                dict(record) for record in session.run(
                    "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count ORDER BY count DESC"
                )
            ]
            result["relationships"] = [
                dict(record) for record in session.run(
                    "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY count DESC"
                )
            ]
            result["events"] = [
                dict(record) for record in session.run(
                    "MATCH (e:Event) "
                    "OPTIONAL MATCH (e)-[:HAS_SUBEVENT]->(s:SubEvent) "
                    "OPTIONAL MATCH (e)-[:HAS_TOPIC]->(t:Topic) "
                    "RETURN e.name AS event, count(DISTINCT s) AS sub_events, count(DISTINCT t) AS topics "
                    "ORDER BY sub_events DESC"
                )
            ]
    finally:
        driver.close()
    return result
