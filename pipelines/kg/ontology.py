# -*- coding: utf-8 -*-
"""事件知识图谱（KG）本体与抽取协议。

本模块只放静态定义：节点标签、关系类型、LLM 提示词和抽取结果校验，
不做任何 I/O，方便被抽取、建图、可视化等模块复用。
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 本体：节点标签
# ---------------------------------------------------------------------------
NODE_LABELS: dict[str, str] = {
    "Event": "事件",
    "SubEvent": "子事件/进展",
    "Phase": "传播阶段",
    "Actor": "参与主体",
    "Location": "地点",
    "Topic": "讨论议题",
    "Cause": "原因",
    "Consequence": "后果",
    "Claim": "官方通报/说法",
    "Snapshot": "舆情快照",
    "Source": "信息来源",
}

# ---------------------------------------------------------------------------
# 本体：关系类型 (起点标签, 终点标签, 语义)
# ---------------------------------------------------------------------------
REL_TYPES: dict[str, tuple[str, str, str]] = {
    "HAS_PHASE": ("Event", "Phase", "事件包含阶段"),
    "HAS_SUBEVENT": ("Event", "SubEvent", "事件包含子事件"),
    "HAS_TOPIC": ("Event", "Topic", "事件涉及议题"),
    "HAS_LOCATION": ("Event", "Location", "事件发生地"),
    "NEXT": ("SubEvent", "SubEvent", "子事件时间顺序"),
    "IN_PHASE": ("SubEvent", "Phase", "子事件所属阶段"),
    "INVOLVES": ("SubEvent", "Actor", "子事件涉及主体"),
    "AT_LOCATION": ("SubEvent", "Location", "子事件发生地点"),
    "CAUSED_BY": ("SubEvent", "Cause", "子事件原因"),
    "LED_TO": ("SubEvent", "Consequence", "子事件后果"),
    "EVIDENCED_BY": ("SubEvent", "Source", "子事件证据"),
    "ABOUT": ("Claim", "SubEvent", "通报对应的子事件"),
    "PUBLISHED_BY": ("Claim", "Actor", "通报发布主体"),
    "SUPPORTED_BY": ("Claim", "Source", "通报来源"),
    "HAS_SNAPSHOT": ("Phase", "Snapshot", "阶段舆情快照"),
}

# 节点唯一键：Neo4j 约束与 MERGE 都以 id 为准
NODE_KEY = "id"

SYSTEM_PROMPT = """你是事件知识图谱抽取器。输入是一个中文舆情事件的结构化材料（事件正文、阶段时间线、官方通报、评论角度）。
只依据材料抽取，不得引入材料之外的事实；材料没有的信息留空，不要猜测。

输出严格 JSON（不要 markdown 代码块，不要任何解释），结构如下：
{
  "event": {
    "name": "不超过 24 字的简短事件名",
    "summary": "40-80 字事件概述",
    "topic": "事件主题标签",
    "valence": "negative|neutral|positive",
    "time_text": "事发时间的原文表述",
    "region": "省/市级行政区",
    "location": "最具体的事发地点"
  },
  "sub_events": [
    {
      "id": "se_1",
      "summary": "一句话进展，不超过 80 字",
      "step": 1,
      "time_text": "该进展对应的时间段",
      "phase": "该进展所属阶段，沿用材料中的阶段名",
      "kind": "verified|official|discourse|positive",
      "status": "confirmed|partial|unconfirmed|refuted",
      "actors": ["驾驶人"],
      "location": "该进展发生地点，可为空字符串",
      "causes": ["原因短语"],
      "consequences": ["后果短语"],
      "sources": ["材料 source_refs 中的原始引用"]
    }
  ],
  "actors": [{"name": "驾驶人", "type": "person|group|organization", "role": "涉事方|处置方|救助者|讨论者|其他"}],
  "locations": ["河北保定"],
  "topics": [{"name": "事故原因", "focus": "关注事故原因与责任认定"}],
  "claims": [
    {
      "id": "claim_1",
      "text": "通报原文或压缩后的原文",
      "publisher": "公安机关",
      "published_at": "2026-10-06 22:33",
      "status": "confirmed|partial|refuted",
      "about_sub_events": ["se_6"],
      "sources": ["url 或文件引用"]
    }
  ]
}

要求：
1. id 唯一且稳定（se_1、claim_1 ...）。
2. actors 只能使用材料中出现或可明确指代的角色（如“驾驶人”“过路群众”“公安机关”），不得编造姓名；匿名者用角色名。
3. causes / consequences 只在材料明确给出时填写；传闻、推测、网络猜测不要写成原因，应放入 claims 并标注 status。
4. 每条 sub_event 的 sources 必须来自材料；找不到就写空数组。
5. 官方通报既是一条 sub_event（kind=official），也是一条 claim（about_sub_events 指向该 sub_event）。
6. 阶段名优先沿用材料中的 phase 字段，保证同一事件的阶段可排序。
7. 只输出 JSON。
"""

_ALLOWED_KINDS = {"verified", "official", "discourse", "positive"}
_ALLOWED_STATUS = {"confirmed", "partial", "unconfirmed", "refuted"}
_ALLOWED_ACTOR_TYPES = {"person", "group", "organization"}
_ALLOWED_VALENCE = {"negative", "neutral", "positive"}


class ExtractionError(ValueError):
    """抽取结果无法满足图谱结构要求。"""


def build_user_prompt(payload: dict[str, Any]) -> str:
    """把事件材料序列化进用户提示词。"""
    import json

    body = json.dumps(payload, ensure_ascii=False, indent=1)
    return (
        "请对下面的事件材料做知识图谱抽取，按系统消息中的 JSON 结构返回。\n"
        "材料：\n```json\n" + body + "\n```"
    )


def _as_text(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text[:limit]


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def validate_extraction(data: Any, event_id: str) -> tuple[dict[str, Any], list[str]]:
    """校验并归一化单事件的抽取结果，返回 (规范化结果, 警告列表)。

    结构性错误（缺少 event、sub_events 不是列表等）抛 ExtractionError；
    局部脏数据只记录警告并丢弃，避免一条坏数据毁掉整张图。
    """
    issues: list[str] = []
    if not isinstance(data, dict):
        raise ExtractionError(f"{event_id}: 顶层不是 JSON 对象")

    raw_event = data.get("event")
    if not isinstance(raw_event, dict):
        raise ExtractionError(f"{event_id}: 缺少 event 对象")

    name = _as_text(raw_event.get("name"), 60)
    if not name:
        raise ExtractionError(f"{event_id}: event.name 为空")

    event = {
        "id": event_id,
        "name": name,
        "summary": _as_text(raw_event.get("summary"), 400),
        "topic": _as_text(raw_event.get("topic"), 40),
        "valence": _as_text(raw_event.get("valence"), 20) or "neutral",
        "time_text": _as_text(raw_event.get("time_text"), 80),
        "region": _as_text(raw_event.get("region"), 40),
        "location": _as_text(raw_event.get("location"), 80),
    }
    if event["valence"] not in _ALLOWED_VALENCE:
        issues.append(f"{event_id}: valence={event['valence']} 非法，回退为 neutral")
        event["valence"] = "neutral"

    sub_events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(_as_list(data.get("sub_events")), start=1):
        if not isinstance(item, dict):
            issues.append(f"{event_id}: 第 {index} 条 sub_event 不是对象，已丢弃")
            continue
        summary = _as_text(item.get("summary"), 300)
        if not summary:
            issues.append(f"{event_id}: 第 {index} 条 sub_event 缺少 summary，已丢弃")
            continue
        sid = _as_text(item.get("id"), 40) or f"se_{index}"
        if sid in seen_ids:
            sid = f"{sid}_{index}"
        seen_ids.add(sid)

        kind = _as_text(item.get("kind"), 20) or "verified"
        if kind not in _ALLOWED_KINDS:
            issues.append(f"{event_id}/{sid}: kind={kind} 非法，回退为 verified")
            kind = "verified"
        status = _as_text(item.get("status"), 20) or "unconfirmed"
        if status not in _ALLOWED_STATUS:
            issues.append(f"{event_id}/{sid}: status={status} 非法，回退为 unconfirmed")
            status = "unconfirmed"

        step = item.get("step")
        try:
            step = int(step) if step is not None else None
        except (TypeError, ValueError):
            step = None
            issues.append(f"{event_id}/{sid}: step 不是整数，已置空")

        sub_events.append(
            {
                "id": sid,
                "summary": summary,
                "step": step,
                "time_text": _as_text(item.get("time_text"), 80),
                "phase": _as_text(item.get("phase"), 60),
                "kind": kind,
                "status": status,
                "actors": [_as_text(a, 40) for a in _as_list(item.get("actors")) if _as_text(a, 40)],
                "location": _as_text(item.get("location"), 80),
                "causes": [_as_text(c, 120) for c in _as_list(item.get("causes")) if _as_text(c, 120)],
                "consequences": [
                    _as_text(c, 120) for c in _as_list(item.get("consequences")) if _as_text(c, 120)
                ],
                "sources": [_as_text(s, 200) for s in _as_list(item.get("sources")) if _as_text(s, 200)],
            }
        )
    if not sub_events:
        raise ExtractionError(f"{event_id}: 没有任何有效 sub_event，无法建图")

    actors: list[dict[str, str]] = []
    seen_actors: set[str] = set()
    for item in _as_list(data.get("actors")):
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        actor_name = _as_text(item.get("name"), 40)
        if not actor_name or actor_name in seen_actors:
            continue
        actor_type = _as_text(item.get("type"), 20) or "group"
        if actor_type not in _ALLOWED_ACTOR_TYPES:
            issues.append(f"{event_id}: actor {actor_name} 的 type={actor_type} 非法，回退为 group")
            actor_type = "group"
        seen_actors.add(actor_name)
        actors.append(
            {
                "name": actor_name,
                "type": actor_type,
                "role": _as_text(item.get("role"), 20) or "其他",
            }
        )

    topics: list[dict[str, str]] = []
    seen_topics: set[str] = set()
    for item in _as_list(data.get("topics")):
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        topic_name = _as_text(item.get("name"), 40)
        if not topic_name or topic_name in seen_topics:
            continue
        seen_topics.add(topic_name)
        topics.append({"name": topic_name, "focus": _as_text(item.get("focus"), 160)})

    claims: list[dict[str, Any]] = []
    for index, item in enumerate(_as_list(data.get("claims")), start=1):
        if not isinstance(item, dict):
            continue
        text = _as_text(item.get("text"), 1200)
        if not text:
            continue
        status = _as_text(item.get("status"), 20) or "partial"
        if status not in _ALLOWED_STATUS:
            status = "partial"
        claims.append(
            {
                "id": _as_text(item.get("id"), 40) or f"claim_{index}",
                "text": text,
                "publisher": _as_text(item.get("publisher"), 60) or "官方",
                "published_at": _as_text(item.get("published_at"), 40),
                "status": status,
                "about_sub_events": [
                    _as_text(s, 40) for s in _as_list(item.get("about_sub_events")) if _as_text(s, 40)
                ],
                "sources": [_as_text(s, 200) for s in _as_list(item.get("sources")) if _as_text(s, 200)],
            }
        )

    locations = [_as_text(loc, 80) for loc in _as_list(data.get("locations")) if _as_text(loc, 80)]
    if event["location"] and event["location"] not in locations:
        locations.insert(0, event["location"])

    phases: list[dict[str, Any]] = []
    seen_phases: set[tuple] = set()
    for item in _as_list(data.get("phases")):
        if not isinstance(item, dict):
            continue
        phase_name = _as_text(item.get("phase"), 60)
        if not phase_name:
            continue
        try:
            step = int(item.get("step")) if item.get("step") is not None else None
        except (TypeError, ValueError):
            step = None
        dedupe_key = (step, phase_name) if step is not None else (phase_name,)
        if dedupe_key in seen_phases:
            continue
        seen_phases.add(dedupe_key)
        phases.append({"step": step, "period": _as_text(item.get("period"), 80), "phase": phase_name})

    return {
        "event": event,
        "phases": phases,
        "sub_events": sub_events,
        "actors": actors,
        "topics": topics,
        "claims": claims,
        "locations": locations,
        "extraction_mode": _as_text(data.get("extraction_mode"), 20) or "unknown",
        "warnings": issues,
    }, issues
