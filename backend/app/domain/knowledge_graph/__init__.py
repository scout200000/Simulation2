"""事件知识图谱的规范化与事件关联推导。

图谱由 ``Simulation2-main/kg`` 管线从历史复现事件库抽取生成（大模型或规则），
产物是 ``graph.json``：以 Event 为中心，通过 Topic / Location / Actor /
Cause / Consequence 等实体把不同历史事件连起来。同名实体在管线中全局合并，
因此这些实体本身就是历史事件之间的桥梁。

本模块只做**只读整理**：

* 把管线产物规范化为前端可直接渲染的事件视图；
* 按共享实体推导事件—事件关联，并给出关联原因；
* 不做抽取、不生成 Cypher、不访问图数据库。
"""

from __future__ import annotations

from collections import defaultdict

EVENT_LABEL = "Event"
ENTITY_LABELS = ("Topic", "Location", "Actor", "Cause", "Consequence")

LABEL_META = {
    "Event": {"name": "事件", "color": "#e85d2a", "shape": "circle", "order": 0},
    "Topic": {"name": "议题", "color": "#4f6fa8", "shape": "circle", "order": 1},
    "Actor": {"name": "主体", "color": "#1d746b", "shape": "square", "order": 2},
    "Location": {"name": "地点", "color": "#b5813f", "shape": "diamond", "order": 3},
    "Cause": {"name": "成因", "color": "#7b5fa6", "shape": "hex", "order": 4},
    "Consequence": {"name": "后果", "color": "#c05952", "shape": "square", "order": 5},
    "Phase": {"name": "阶段", "color": "#6b8f7d", "shape": "circle", "order": 6},
    "SubEvent": {"name": "子事件", "color": "#8b9fce", "shape": "circle", "order": 7},
    "Claim": {"name": "通报", "color": "#7b5fa6", "shape": "circle", "order": 8},
    "Source": {"name": "来源", "color": "#9aa8a1", "shape": "circle", "order": 9},
    "Snapshot": {"name": "快照", "color": "#b98a4b", "shape": "circle", "order": 10},
}

# 后端管线中用于连接事件实体的边类型。
RELATION_META = {
    "HAS_TOPIC": "议题",
    "HAS_LOCATION": "地点",
    "INVOLVES": "涉及主体",
    "CAUSED_BY": "成因",
    "LED_TO": "后果",
}

# 事件—事件关联原因的措辞。
LINK_REASON_NAMES = {
    "Topic": "共同议题",
    "Actor": "共同主体",
    "Location": "同一地域",
    "Cause": "相近成因",
    "Consequence": "相似后果",
}


def label_meta(label):
    """返回标签的展示信息；未知标签给出兜底样式。"""

    return LABEL_META.get(
        label,
        {"name": label or "实体", "color": "#7d8c85", "shape": "circle", "order": 99},
    )


def normalize_place(value):
    """地点归一化：去掉省/市/县/区等后缀，便于合并同一地域的不同写法。"""

    text = str(value or "").strip()
    if not text:
        return ""
    for token in ("特别行政区", "自治区", "省", "市", "县", "区"):
        text = text.replace(token, "")
    return text


def _as_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # 过滤 NaN


def _entity_view(node):
    """把图谱节点整理成前端实体视图。"""

    props = node.get("props") or {}
    label = node.get("label") or ""
    detail = ""
    if label == "Topic":
        detail = str(props.get("focus") or "")
    elif label == "Actor":
        parts = [props.get("actor_type"), props.get("role")]
        detail = " · ".join(str(part) for part in parts if part)
    elif label in ("Cause", "Consequence"):
        detail = str(props.get("text") or "")
    elif label == "Location":
        detail = ""

    name = node.get("name") or detail or node.get("id", "")
    return {
        "id": node["id"],
        "label": label,
        "typeName": label_meta(label)["name"],
        "color": label_meta(label)["color"],
        "shape": label_meta(label)["shape"],
        "name": name,
        "detail": detail,
        "props": props,
    }


def _event_node_view(node):
    """把 Event 节点整理成前端事件视图。"""

    props = node.get("props") or {}
    return {
        "id": node["id"],
        "eventId": props.get("event_id") or node.get("id", "").split(":", 1)[-1],
        "name": node.get("name") or props.get("manifest_title") or "",
        "summary": str(props.get("summary") or ""),
        "topic": props.get("topic") or "",
        "valence": props.get("valence") or "",
        "timeText": props.get("time_text") or "",
        "region": props.get("region") or "",
        "location": props.get("location") or "",
        "runId": props.get("run_id") or "",
        "origin": props.get("origin") or "",
        "extractionMode": props.get("extraction_mode") or "",
        "initialOpinion": {
            "negative": _as_number(props.get("init_negative_rate")),
            "neutral": _as_number(props.get("init_neutral_rate")),
            "positive": _as_number(props.get("init_positive_rate")),
        },
    }


def build_event_graph(raw, source=""):
    """由 ``pipelines/kg/out/graph.json`` 生成前端事件图谱视图。

    返回结构：

    ``events``        事件列表，附带各自的议题/主体/地点/成因/后果/通报/阶段；
    ``entities``      事件层实体，``shared`` 表示被多个事件共享；
    ``eventLinks``    事件—事件关联，附共享实体与原因统计；
    ``meta``          产物元信息与规模统计。
    """

    if not isinstance(raw, dict):
        raise ValueError("知识图谱数据必须是 JSON 对象。")

    raw_nodes = raw.get("nodes") or []
    raw_edges = raw.get("edges") or []
    nodes = {
        node["id"]: node
        for node in raw_nodes
        if isinstance(node, dict) and node.get("id")
    }
    edges = [edge for edge in raw_edges if isinstance(edge, dict)]

    event_ids = sorted(
        node_id
        for node_id, node in nodes.items()
        if node.get("label") == EVENT_LABEL
    )
    if not event_ids:
        raise ValueError("知识图谱中没有 Event 节点。")

    subevent_event = {}
    claim_subevent = {}
    claim_publisher = {}
    phase_snapshots = defaultdict(list)
    event_phases = defaultdict(list)

    for edge in edges:
        edge_type = edge.get("type")
        source_id = edge.get("source")
        target_id = edge.get("target")
        if edge_type == "HAS_SUBEVENT":
            subevent_event[target_id] = source_id
        elif edge_type == "HAS_PHASE":
            event_phases[source_id].append(target_id)
        elif edge_type == "ABOUT":
            claim_subevent[source_id] = target_id
        elif edge_type == "PUBLISHED_BY":
            claim_publisher[source_id] = target_id
        elif edge_type == "HAS_SNAPSHOT":
            phase_snapshots[source_id].append(target_id)

    event_entities = {event_id: defaultdict(set) for event_id in event_ids}
    event_subevents = defaultdict(list)

    for edge in edges:
        edge_type = edge.get("type")
        source_id = edge.get("source")
        target_id = edge.get("target")
        if edge_type in ("HAS_TOPIC", "HAS_LOCATION"):
            if source_id in event_entities and target_id in nodes:
                event_entities[source_id][nodes[target_id]["label"]].add(target_id)
        elif edge_type in ("INVOLVES", "CAUSED_BY", "LED_TO"):
            event_id = subevent_event.get(source_id)
            if event_id in event_entities and target_id in nodes:
                event_entities[event_id][nodes[target_id]["label"]].add(target_id)
        elif edge_type == "HAS_SUBEVENT" and source_id in event_entities:
            event_subevents[source_id].append(target_id)

    # 同一城市的不同写法（河北保定 / 河北省保定市）按区域归一化后合并到同一个地点节点。
    location_by_key = {}
    for node_id, node in nodes.items():
        if node.get("label") != "Location":
            continue
        key = normalize_place(node.get("name"))
        if key and key not in location_by_key:
            location_by_key[key] = node_id
    for event_id in event_ids:
        props = nodes[event_id].get("props") or {}
        location_id = location_by_key.get(normalize_place(props.get("region")))
        if location_id:
            event_entities[event_id]["Location"].add(location_id)

    def views(event_id, label):
        bucket = event_entities[event_id].get(label, set())
        return sorted(
            (_entity_view(nodes[node_id]) for node_id in bucket if node_id in nodes),
            key=lambda item: (item["name"], item["id"]),
        )

    events = []
    for event_id in event_ids:
        node = nodes[event_id]
        view = _event_node_view(node)

        claims = []
        for claim_id, sub_id in claim_subevent.items():
            if subevent_event.get(sub_id) != event_id:
                continue
            claim_node = nodes.get(claim_id, {})
            claim_props = claim_node.get("props") or {}
            claims.append(
                {
                    "id": claim_id,
                    "text": claim_props.get("text") or claim_node.get("name") or "",
                    "publisher": claim_props.get("publisher") or "",
                    "publishedAt": claim_props.get("published_at") or "",
                    "status": claim_props.get("status") or "",
                }
            )
        claims.sort(key=lambda item: item["publishedAt"])

        phases = []
        snapshots = []
        for phase_id in sorted(
            event_phases.get(event_id, []),
            key=lambda item: (
                nodes.get(item, {}).get("props", {}).get("step") or 0
            ),
        ):
            phase_node = nodes.get(phase_id, {})
            phase_props = phase_node.get("props") or {}
            phases.append(
                {
                    "id": phase_id,
                    "name": phase_node.get("name") or phase_props.get("phase_name") or "",
                    "step": phase_props.get("step"),
                    "period": phase_props.get("period") or "",
                }
            )
            for snapshot_id in phase_snapshots.get(phase_id, []):
                snapshot_node = nodes.get(snapshot_id, {})
                snapshot_props = snapshot_node.get("props") or {}
                snapshots.append(
                    {
                        "step": snapshot_props.get("step"),
                        "trend": snapshot_props.get("trend") or "",
                        "negativeRate": _as_number(snapshot_props.get("negative_rate")),
                        "questionRate": _as_number(snapshot_props.get("question_rate")),
                        "acceptRate": _as_number(snapshot_props.get("accept_rate")),
                    }
                )

        view.update(
            {
                "topics": views(event_id, "Topic"),
                "actors": views(event_id, "Actor"),
                "locations": views(event_id, "Location"),
                "causes": views(event_id, "Cause"),
                "consequences": views(event_id, "Consequence"),
                "claims": claims,
                "phases": phases,
                "snapshots": snapshots,
                "counts": {
                    "phases": len(phases),
                    "subEvents": len(event_subevents.get(event_id, [])),
                    "claims": len(claims),
                    "topics": len(event_entities[event_id].get("Topic", ())),
                    "actors": len(event_entities[event_id].get("Actor", ())),
                },
            }
        )
        events.append(view)

    # 实体 → 事件倒排，用于 Shared 标记与事件关联。
    entity_events = defaultdict(set)
    for event_id, buckets in event_entities.items():
        for ids in buckets.values():
            for node_id in ids:
                entity_events[node_id].add(event_id)

    entities = []
    for node_id, event_set in entity_events.items():
        node = nodes.get(node_id)
        if not node:
            continue
        view = _entity_view(node)
        view["eventIds"] = sorted(event_set)
        view["shared"] = len(event_set) > 1
        view["order"] = label_meta(node.get("label"))["order"]
        entities.append(view)
    entities.sort(key=lambda item: (item["order"], item["name"], item["id"]))

    event_links = []
    for index, left in enumerate(event_ids):
        for right in event_ids[index + 1:]:
            shared_ids = []
            for label in ENTITY_LABELS:
                shared_ids.extend(
                    sorted(
                        event_entities[left].get(label, set())
                        & event_entities[right].get(label, set())
                    )
                )
            if not shared_ids:
                continue
            shared_views = [
                _entity_view(nodes[node_id])
                for node_id in shared_ids
                if node_id in nodes
            ]
            counts = defaultdict(int)
            for item in shared_views:
                counts[item["label"]] += 1
            reasons = [
                f"{LINK_REASON_NAMES.get(label, '共享实体')} {count}"
                for label, count in sorted(counts.items())
                if count
            ]
            event_links.append(
                {
                    "source": left,
                    "target": right,
                    "sharedEntityIds": shared_ids,
                    "shared": shared_views,
                    "counts": dict(counts),
                    "weight": len(shared_views),
                    "label": " · ".join(reasons),
                }
            )
    event_links.sort(
        key=lambda item: (-item["weight"], item["source"], item["target"])
    )

    meta = dict(raw.get("meta") or {})
    meta.update(
        {
            "source": str(source or ""),
            "eventCount": len(event_ids),
            "nodeCount": len(nodes),
            "edgeCount": len(edges),
            "entityCount": len(entities),
            "sharedEntityCount": sum(1 for item in entities if item["shared"]),
            "eventLinkCount": len(event_links),
        }
    )

    return {
        "meta": meta,
        "events": events,
        "entities": entities,
        "eventLinks": event_links,
        "labels": LABEL_META,
        "relations": RELATION_META,
    }


__all__ = [
    "ENTITY_LABELS",
    "EVENT_LABEL",
    "LABEL_META",
    "RELATION_META",
    "build_event_graph",
    "label_meta",
    "normalize_place",
]
