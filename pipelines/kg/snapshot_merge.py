# -*- coding: utf-8 -*-
"""把本地快照（``var/knowledge_graph/graph.json``）中已有、但本次抽取源里
没有的事件还原成 kg 管线可用的 extraction。

用途：图谱是增量维护的——历史复现事件来自事件库，策略事件由后端
``knowledge_graph_sync`` 写入，历史语料与事件库事件由管线并入。重新跑管线时
如果不带上快照里的策略事件，``out/graph.json`` 会静默变少。这个模块负责把
快照里的“快照独有事件”还原成 extraction，交给 ``build_graph`` 一起重建。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def snapshot_event_ids(payload: dict[str, Any] | None) -> set[str]:
    if not payload:
        return set()
    ids = set()
    for node in payload.get("nodes") or []:
        if not isinstance(node, dict) or node.get("label") != "Event":
            continue
        props = node.get("props") or {}
        event_id = props.get("event_id") or str(node.get("id") or "").split(":", 1)[-1]
        if event_id:
            ids.add(str(event_id))
    return ids


def extraction_from_snapshot(payload: dict[str, Any], event_id: str) -> dict[str, Any] | None:
    """按 Event / SubEvent / Topic / Actor / Location 还原一个事件子图。"""

    nodes = {node["id"]: node for node in payload.get("nodes") or []}
    edges = payload.get("edges") or []
    event_node = nodes.get(f"event:{event_id}")
    if event_node is None:
        return None
    event_props = event_node.get("props") or {}

    out_edges: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        out_edges.setdefault(edge.get("source"), []).append(edge)

    phases = []
    for edge in out_edges.get(event_node["id"], []):
        if edge.get("type") == "HAS_PHASE" and edge.get("target") in nodes:
            props = nodes[edge["target"]].get("props") or {}
            phases.append(
                {
                    "step": props.get("step"),
                    "period": props.get("period", ""),
                    "phase": props.get("phase_name", ""),
                }
            )

    sub_events = []
    sub_node_ids: set[str] = set()
    for edge in out_edges.get(event_node["id"], []):
        if edge.get("type") != "HAS_SUBEVENT":
            continue
        sub_id = edge.get("target")
        sub = nodes.get(sub_id)
        if sub is None:
            continue
        sub_node_ids.add(sub_id)
        props = sub.get("props") or {}
        actors, sources, causes, consequences = [], [], [], []
        phase = ""
        location = ""
        for sub_edge in out_edges.get(sub_id, []):
            target = nodes.get(sub_edge.get("target"), {})
            edge_type = sub_edge.get("type")
            if edge_type == "INVOLVES":
                actors.append(target.get("name", ""))
            elif edge_type == "EVIDENCED_BY":
                sources.append(target.get("name", ""))
            elif edge_type == "CAUSED_BY":
                causes.append(target.get("name", ""))
            elif edge_type == "LED_TO":
                consequences.append(target.get("name", ""))
            elif edge_type == "IN_PHASE":
                phase = (target.get("props") or {}).get("phase_name", "")
            elif edge_type == "AT_LOCATION":
                location = target.get("name", "")
        sub_events.append(
            {
                "id": props.get("sub_id") or str(sub_id).split(":")[-1],
                "summary": props.get("summary", ""),
                "step": props.get("step"),
                "time_text": props.get("time_text", ""),
                "phase": phase,
                "kind": props.get("kind", ""),
                "status": props.get("status", ""),
                "actors": [name for name in actors if name],
                "location": location,
                "causes": [name for name in causes if name],
                "consequences": [name for name in consequences if name],
                "sources": [name for name in sources if name],
            }
        )

    topics = []
    for edge in out_edges.get(event_node["id"], []):
        if edge.get("type") == "HAS_TOPIC" and edge.get("target") in nodes:
            topic = nodes[edge["target"]]
            props = topic.get("props") or {}
            topics.append({"name": topic.get("name", ""), "focus": props.get("focus", "")})

    actors: list[dict[str, str]] = []
    for sub in sub_events:
        for name in sub["actors"]:
            if name and all(item["name"] != name for item in actors):
                actor_node = nodes.get(f"actor:{name}", {})
                props = actor_node.get("props") or {}
                actors.append(
                    {
                        "name": name,
                        "type": props.get("actor_type", "group"),
                        "role": props.get("role", "其他"),
                    }
                )

    locations = []
    for edge in out_edges.get(event_node["id"], []):
        if edge.get("type") == "HAS_LOCATION" and edge.get("target") in nodes:
            locations.append(nodes[edge["target"]].get("name", ""))
    for sub in sub_events:
        if sub["location"] and sub["location"] not in locations:
            locations.append(sub["location"])

    claims = []
    for edge in edges:
        if edge.get("type") != "ABOUT" or edge.get("target") not in sub_node_ids:
            continue
        claim_node = nodes.get(edge.get("source"))
        if claim_node is None or claim_node.get("label") != "Claim":
            continue
        props = claim_node.get("props") or {}
        publisher = props.get("publisher", "")
        sources = []
        for claim_edge in out_edges.get(claim_node["id"], []):
            target = nodes.get(claim_edge.get("target"), {})
            if claim_edge.get("type") == "PUBLISHED_BY" and not publisher:
                publisher = target.get("name", "")
            elif claim_edge.get("type") == "SUPPORTED_BY":
                sources.append(target.get("name", ""))
        claims.append(
            {
                "id": props.get("claim_id") or str(claim_node["id"]).split(":")[-1],
                "text": props.get("text", "") or claim_node.get("name", ""),
                "publisher": publisher or "官方",
                "published_at": props.get("published_at", ""),
                "status": props.get("status", "partial"),
                "about_sub_events": [
                    (nodes[edge["target"]].get("props") or {}).get("sub_id", "")
                ],
                "sources": [name for name in sources if name],
            }
        )

    return {
        "event": {
            "id": event_id,
            "name": event_props.get("name") or event_node.get("name", ""),
            "summary": event_props.get("summary", ""),
            "topic": event_props.get("topic", ""),
            "valence": event_props.get("valence", ""),
            "time_text": event_props.get("time_text", ""),
            "region": event_props.get("region", ""),
            "location": event_props.get("location", ""),
        },
        "phases": phases,
        "sub_events": sub_events,
        "actors": actors,
        "topics": topics,
        "claims": claims,
        "locations": [name for name in locations if name],
        "extraction_mode": event_props.get("extraction_mode", "heuristic") or "heuristic",
        "warnings": [],
    }
