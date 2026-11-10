# -*- coding: utf-8 -*-
"""把抽取结果规范化为属性图，并生成 Cypher / 报告。

产物：
- out/graph.json        前后端通用的节点-边结构
- out/graph.cypher      cypher-shell / Neo4j Browser 可直接执行
- out/statements.json   逐条 Cypher，供 Python 驱动分批执行
- out/report.md         建图统计与事件脉络报告
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from pipelines.kg.ontology import NODE_LABELS, REL_TYPES


# ---------------------------------------------------------------------------
# Cypher 字面量
# ---------------------------------------------------------------------------


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    text = text.replace("\\", "\\\\").replace("'", "\\'").replace("\r", "").replace("\n", "\\n")
    return f"'{text}'"


def _props_literal(props: dict[str, Any]) -> str:
    parts = [f"{key}: {_literal(value)}" for key, value in props.items() if value not in (None, "")]
    return "{" + ", ".join(parts) + "}"


def _hash(text: str, size: int = 10) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:size]


# ---------------------------------------------------------------------------
# 图构建
# ---------------------------------------------------------------------------


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_node(self, node_id: str, label: str, name: str, **props: Any) -> None:
        clean = {key: value for key, value in props.items() if value not in (None, "")}
        current = self.nodes.get(node_id)
        if current is None:
            self.nodes[node_id] = {"id": node_id, "label": label, "name": name, "props": clean}
        else:
            current["props"].update(clean)
            if name and not current["name"]:
                current["name"] = name

    def add_edge(self, source: str, target: str, rel_type: str, **props: Any) -> None:
        if source not in self.nodes or target not in self.nodes:
            raise ValueError(f"关系 {rel_type} 引用了不存在的节点：{source} -> {target}")
        if rel_type not in REL_TYPES:
            raise ValueError(f"未定义的关系类型：{rel_type}")
        clean = {key: value for key, value in props.items() if value not in (None, "")}
        key = (source, rel_type, target)
        if key in self.edges:
            self.edges[key]["props"].update(clean)
        else:
            self.edges[key] = {"source": source, "target": target, "type": rel_type, "props": clean}

    def to_dict(self, meta: dict[str, Any]) -> dict[str, Any]:
        nodes = sorted(self.nodes.values(), key=lambda n: (n["label"], n["id"]))
        edges = sorted(self.edges.values(), key=lambda e: (e["type"], e["source"], e["target"]))
        return {"meta": meta, "nodes": nodes, "edges": edges}


def build_graph(
    extractions: list[dict[str, Any]],
    snapshots_by_event: dict[str, list[dict[str, Any]]] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshots_by_event = snapshots_by_event or {}
    graph = Graph()
    location_ids: dict[str, str] = {}

    def location_node_for(name: str) -> str:
        canonical = re.sub(r"(一处|一|附近|周边|左右)", "", name)
        if canonical in location_ids:
            return location_ids[canonical]
        node_id = f"location:{name}"
        graph.add_node(node_id, "Location", name)
        location_ids[canonical] = node_id
        return node_id

    for extraction in extractions:
        event = extraction["event"]
        event_id = event["id"]
        event_node = f"event:{event_id}"
        actor_meta = {actor["name"]: actor for actor in extraction.get("actors", [])}
        provenance = extraction.get("provenance") or {}
        graph.add_node(
            event_node,
            "Event",
            event.get("name", event_id),
            event_id=event_id,
            summary=event.get("summary", ""),
            topic=event.get("topic", ""),
            valence=event.get("valence", ""),
            time_text=event.get("time_text", ""),
            region=event.get("region", ""),
            location=event.get("location", ""),
            extraction_mode=extraction.get("extraction_mode", ""),
            origin=provenance.get("origin", ""),
            manifest_title=provenance.get("manifest_title", ""),
            run_id=provenance.get("run_id", ""),
            initial_opinion_mode=provenance.get("initial_opinion_mode", ""),
            init_negative_rate=provenance.get("init_negative_rate"),
            init_neutral_rate=provenance.get("init_neutral_rate"),
            init_positive_rate=provenance.get("init_positive_rate"),
            real_trend_source=provenance.get("real_trend_source", ""),
        )

        # 事件级地点（同一地点的不同表述合并到一个节点）
        for location_name in [event.get("location", ""), *extraction.get("locations", [])]:
            if not location_name:
                continue
            location_node = location_node_for(location_name)
            graph.add_edge(event_node, location_node, "HAS_LOCATION")

        phase_nodes: dict[str, str] = {}
        phase_name_nodes: dict[str, str] = {}
        for item in extraction.get("phases", []):
            phase_name = item.get("phase") or "未分阶段"
            step = item.get("step")
            phase_key = f"{step}" if step is not None else phase_name
            if phase_key in phase_nodes:
                continue
            phase_node = f"phase:{event_id}:{phase_key}"
            phase_nodes[phase_key] = phase_node
            phase_name_nodes.setdefault(phase_name, phase_node)
            graph.add_node(
                phase_node,
                "Phase",
                phase_name,
                phase_name=phase_name,
                step=step,
                period=item.get("period", ""),
                event_id=event_id,
            )
            graph.add_edge(event_node, phase_node, "HAS_PHASE", order=len(phase_nodes))

        for order, sub in enumerate(extraction["sub_events"]):
            phase_name = sub.get("phase") or "未分阶段"
            step = sub.get("step")
            phase_key = f"{step}" if step is not None else phase_name
            if phase_key not in phase_nodes:
                phase_node = f"phase:{event_id}:{phase_key}"
                phase_nodes[phase_key] = phase_node
                phase_name_nodes.setdefault(phase_name, phase_node)
                graph.add_node(
                    phase_node,
                    "Phase",
                    phase_name,
                    phase_name=phase_name,
                    step=step,
                    period=sub.get("time_text", ""),
                    event_id=event_id,
                )
                graph.add_edge(event_node, phase_node, "HAS_PHASE", order=len(phase_nodes))
            phase_node = phase_nodes[phase_key]

            sub_node = f"subevent:{event_id}:{sub['id']}"
            graph.add_node(
                sub_node,
                "SubEvent",
                sub.get("summary", "")[:60],
                sub_id=sub["id"],
                summary=sub.get("summary", ""),
                kind=sub.get("kind", ""),
                status=sub.get("status", ""),
                step=step,
                time_text=sub.get("time_text", ""),
                event_id=event_id,
            )
            graph.add_edge(event_node, sub_node, "HAS_SUBEVENT", order=order)
            graph.add_edge(sub_node, phase_node, "IN_PHASE")
            if order > 0:
                previous = f"subevent:{event_id}:{extraction['sub_events'][order - 1]['id']}"
                graph.add_edge(previous, sub_node, "NEXT")

            for actor_name in sub.get("actors", []):
                actor_node = f"actor:{actor_name}"
                info = actor_meta.get(actor_name, {})
                graph.add_node(
                    actor_node,
                    "Actor",
                    actor_name,
                    actor_type=info.get("type", "group"),
                    role=info.get("role", ""),
                )
                graph.add_edge(sub_node, actor_node, "INVOLVES", role=info.get("role", "参与者"))

            location_name = sub.get("location", "")
            if location_name:
                graph.add_edge(sub_node, location_node_for(location_name), "AT_LOCATION")

            for cause_text in sub.get("causes", []):
                cause_node = f"cause:{_hash(cause_text)}"
                graph.add_node(cause_node, "Cause", cause_text[:60], text=cause_text)
                graph.add_edge(sub_node, cause_node, "CAUSED_BY")

            for consequence_text in sub.get("consequences", []):
                consequence_node = f"consequence:{_hash(consequence_text)}"
                graph.add_node(
                    consequence_node, "Consequence", consequence_text[:60], text=consequence_text
                )
                graph.add_edge(sub_node, consequence_node, "LED_TO")

            for ref in sub.get("sources", []):
                source_node = f"source:{_hash(ref)}"
                graph.add_node(source_node, "Source", ref[:60], ref=ref)
                graph.add_edge(sub_node, source_node, "EVIDENCED_BY")

        # 事件级议题
        for topic in extraction.get("topics", []):
            topic_node = f"topic:{topic['name']}"
            graph.add_node(topic_node, "Topic", topic["name"], focus=topic.get("focus", ""))
            graph.add_edge(event_node, topic_node, "HAS_TOPIC")

        # 官方通报
        for claim in extraction.get("claims", []):
            claim_node = f"claim:{event_id}:{claim['id']}"
            graph.add_node(
                claim_node,
                "Claim",
                claim.get("publisher", "官方") + "通报",
                claim_id=claim["id"],
                text=claim.get("text", ""),
                publisher=claim.get("publisher", ""),
                published_at=claim.get("published_at", ""),
                status=claim.get("status", ""),
                event_id=event_id,
            )
            for sub_id in claim.get("about_sub_events", []):
                target = f"subevent:{event_id}:{sub_id}"
                if target in graph.nodes:
                    graph.add_edge(claim_node, target, "ABOUT")
            publisher = claim.get("publisher") or "官方"
            if f"actor:{publisher}" not in graph.nodes:
                graph.add_node(f"actor:{publisher}", "Actor", publisher, actor_type="organization")
            graph.add_edge(claim_node, f"actor:{publisher}", "PUBLISHED_BY")
            for ref in claim.get("sources", []):
                source_node = f"source:{_hash(ref)}"
                graph.add_node(source_node, "Source", ref[:60], ref=ref)
                graph.add_edge(claim_node, source_node, "SUPPORTED_BY")

        # 阶段舆情快照
        for snapshot in snapshots_by_event.get(event_id, []):
            step = snapshot.get("step")
            phase_name = snapshot.get("phase") or "未分阶段"
            phase_node = (phase_nodes.get(str(step)) if step is not None else None) or phase_name_nodes.get(
                phase_name
            )
            if phase_node is None:
                phase_node = f"phase:{event_id}:{phase_name}"
                phase_nodes[phase_name] = phase_node
                phase_name_nodes[phase_name] = phase_node
                graph.add_node(
                    phase_node, "Phase", phase_name, phase_name=phase_name, step=step, event_id=event_id
                )
                graph.add_edge(event_node, phase_node, "HAS_PHASE", order=len(phase_nodes))
            snapshot_node = f"snapshot:{event_id}:{step}"
            graph.add_node(
                snapshot_node,
                "Snapshot",
                f"第{step}阶段",
                event_id=event_id,
                step=step,
                trend=snapshot.get("trend", ""),
                negative_rate=snapshot.get("negative_rate"),
                question_rate=snapshot.get("question_rate"),
                accept_rate=snapshot.get("accept_rate"),
            )
            graph.add_edge(phase_node, snapshot_node, "HAS_SNAPSHOT")

    payload_meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "events": len(extractions),
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        **(meta or {}),
    }
    return graph.to_dict(payload_meta)


# ---------------------------------------------------------------------------
# Cypher 生成
# ---------------------------------------------------------------------------


def graph_to_statements(payload: dict[str, Any]) -> list[str]:
    statements: list[str] = []
    for label in NODE_LABELS:
        statements.append(
            f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
        )

    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in payload["nodes"]:
        by_label[node["label"]].append(node)

    for label, nodes in by_label.items():
        for node in nodes:
            props = {"id": node["id"], "name": node["name"], **node["props"]}
            statements.append(f"MERGE (n:{label} {{id: {_literal(node['id'])}}}) SET n += {_props_literal(props)}")

    for edge in payload["edges"]:
        source_label = next(n["label"] for n in payload["nodes"] if n["id"] == edge["source"])
        target_label = next(n["label"] for n in payload["nodes"] if n["id"] == edge["target"])
        match = (
            f"MATCH (a:{source_label} {{id: {_literal(edge['source'])}}}) "
            f"MATCH (b:{target_label} {{id: {_literal(edge['target'])}}}) "
            f"MERGE (a)-[r:{edge['type']}]->(b)"
        )
        if edge["props"]:
            match += f" SET r += {_props_literal(edge['props'])}"
        statements.append(match)
    return statements


def write_cypher(payload: dict[str, Any], path: Path) -> None:
    statements = graph_to_statements(payload)
    header = [
        "// 事件知识图谱载入脚本",
        f"// 生成时间：{payload['meta']['generated_at']}",
        f"// 节点：{payload['meta']['nodes']}，关系：{payload['meta']['edges']}，事件：{payload['meta']['events']}",
        "// 用法：cypher-shell -a bolt://localhost:7687 -u neo4j -p <password> -f graph.cypher",
        "",
    ]
    path.write_text("\n".join(header + [s + ";" for s in statements]) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


def _fmt_rate(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def render_report(payload: dict[str, Any], extractions: list[dict[str, Any]]) -> str:
    meta = payload["meta"]
    label_counts = Counter(node["label"] for node in payload["nodes"])
    rel_counts = Counter(edge["type"] for edge in payload["edges"])

    topic_events: dict[str, set[str]] = defaultdict(set)
    actor_events: dict[str, set[str]] = defaultdict(set)
    names = {node["id"]: node["name"] for node in payload["nodes"]}
    out_edges: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in payload["edges"]:
        out_edges[edge["source"]].append(edge)

    for node in payload["nodes"]:
        if node["label"] != "Event":
            continue
        for edge in out_edges[node["id"]]:
            if edge["type"] == "HAS_TOPIC":
                topic_events[names[edge["target"]]].add(node["name"])
            elif edge["type"] == "HAS_SUBEVENT":
                for sub_edge in out_edges[edge["target"]]:
                    if sub_edge["type"] == "INVOLVES":
                        actor_events[names[sub_edge["target"]]].add(node["name"])

    lines: list[str] = []
    lines.append("# 事件知识图谱构建报告")
    lines.append("")
    lines.append(f"- 生成时间：{meta['generated_at']}")
    lines.append(f"- 抽取模式：{meta.get('extraction_mode', '-')}")
    lines.append(f"- 事件数：{meta['events']}　节点数：{meta['nodes']}　关系数：{meta['edges']}")
    lines.append(f"- 数据来源：`{meta.get('source_dir', 'data/historical_replay/events')}`（历史复现真实事件库）")
    if meta.get("metrics_source"):
        lines.append(f"- 指标来源：`{meta['metrics_source']}`（historical_replay 批次）")
    lines.append("")

    lines.append("## 一、图谱规模")
    lines.append("")
    lines.append("| 节点标签 | 含义 | 数量 |")
    lines.append("| --- | --- | ---: |")
    for label, meaning in NODE_LABELS.items():
        if label_counts.get(label):
            lines.append(f"| `{label}` | {meaning} | {label_counts[label]} |")
    lines.append("")
    lines.append("| 关系类型 | 含义 | 数量 |")
    lines.append("| --- | --- | ---: |")
    for rel_type, (_, _, meaning) in REL_TYPES.items():
        if rel_counts.get(rel_type):
            lines.append(f"| `{rel_type}` | {meaning} | {rel_counts[rel_type]} |")
    lines.append("")

    lines.append("## 二、事件清单")
    lines.append("")
    lines.append("| 事件 | 时间 | 地区 | 子事件 | 议题 | 阶段 |")
    lines.append("| --- | --- | --- | ---: | ---: | ---: |")
    for extraction in extractions:
        event = extraction["event"]
        sub_count = len(extraction["sub_events"])
        topic_count = len(extraction["topics"])
        phase_count = len(extraction.get("phases") or []) or len(
            {sub.get("step") for sub in extraction["sub_events"]}
        )
        lines.append(
            f"| {event['name']} | {event.get('time_text') or '-'} | {event.get('region') or '-'} "
            f"| {sub_count} | {topic_count} | {phase_count} |"
        )
    lines.append("")

    lines.append("## 三、事件脉络")
    for extraction in extractions:
        event = extraction["event"]
        lines.append("")
        lines.append(f"### {event['name']}")
        lines.append("")
        if event.get("summary"):
            lines.append(f"> {event['summary']}")
            lines.append("")
        current_phase = None
        for sub in extraction["sub_events"]:
            phase = sub.get("phase") or "未分阶段"
            if phase != current_phase:
                lines.append("")
                lines.append(f"**{phase}**（{sub.get('time_text') or '-'}）")
                lines.append("")
                current_phase = phase
            marker = {"verified": "✔", "official": "📢", "discourse": "💬", "positive": "＋"}.get(
                sub.get("kind"), "·"
            )
            lines.append(f"- {marker} {sub['summary']}")
        if extraction.get("claims"):
            lines.append("")
            lines.append("官方通报：")
            for claim in extraction["claims"]:
                lines.append(f"- [{claim.get('status')}] {claim.get('publisher')}（{claim.get('published_at') or '-'}）：{claim['text'][:120]}…")
        lines.append("")

    lines.append("## 四、跨事件关联")
    lines.append("")
    shared_topics = {name: ids for name, ids in topic_events.items() if len(ids) >= 2}
    lines.append("共享议题（出现在 2 个及以上事件）：" if shared_topics else "共享议题：暂无（每个事件的议题相对独立）。")
    if shared_topics:
        lines.append("")
        lines.append("| 议题 | 覆盖事件数 |")
        lines.append("| --- | ---: |")
        for name, ids in sorted(shared_topics.items(), key=lambda item: -len(item[1])):
            lines.append(f"| {name} | {len(ids)} |")
    lines.append("")
    shared_actors = {name: ids for name, ids in actor_events.items() if len(ids) >= 2}
    if shared_actors:
        lines.append("跨事件出现的主体：")
        lines.append("")
        for name, ids in sorted(shared_actors.items(), key=lambda item: -len(item[1])):
            lines.append(f"- `{name}`：{len(ids)} 个事件")
        lines.append("")

    snapshots = [node for node in payload["nodes"] if node["label"] == "Snapshot"]
    if snapshots:
        lines.append("## 五、阶段舆情快照")
        lines.append("")
        lines.append("| 事件 | 阶段 | 趋势 | 负面情绪 | 质疑官方 | 接受官方 |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: |")
        event_names = {extraction["event"]["id"]: extraction["event"]["name"] for extraction in extractions}
        for node in sorted(snapshots, key=lambda n: (n["props"].get("event_id", ""), n["props"].get("step") or 0)):
            props = node["props"]
            lines.append(
                f"| {event_names.get(props.get('event_id'), '-')} | {props.get('step')} "
                f"| {props.get('trend') or '-'} | {_fmt_rate(props.get('negative_rate'))} "
                f"| {_fmt_rate(props.get('question_rate'))} | {_fmt_rate(props.get('accept_rate'))} |"
            )
        lines.append("")

    lines.append("## 六、口径与局限")
    lines.append("")
    lines.append("- 实体只来自 `demo/experiments` 中已有的事件材料（正文、阶段时间线、官方通报、评论角度），不引入外部事实。")
    lines.append("- 规则模式用关键词与句式切分抽取，稳定但召回有限；大模型模式按同一套 JSON 协议抽取，可显著提升实体、原因与后果的完整性。")
    lines.append("- 官方通报的 `status` 沿用材料中的 `official_statement_status`：`clear` 记为 confirmed，其余记为 partial。")
    lines.append("- 舆情快照来自实验产出的 `metrics_history.jsonl`，只代表该次仿真的 Agent 统计口径。")
    return "\n".join(lines)


def write_graph_artifacts(
    extractions: list[dict[str, Any]],
    snapshots_by_event: dict[str, list[dict[str, Any]]],
    out_dir: Path,
    meta: dict[str, Any],
) -> dict[str, Any]:
    payload = build_graph(extractions, snapshots_by_event, meta)
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "graph.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    statements = graph_to_statements(payload)
    (out_dir / "statements.json").write_text(
        json.dumps(statements, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    write_cypher(payload, out_dir / "graph.cypher")
    (out_dir / "report.md").write_text(render_report(payload, extractions), encoding="utf-8")
    return payload
