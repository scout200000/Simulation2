# -*- coding: utf-8 -*-
"""从 MongoDB ``events`` 集合发现可入图的事件（非历史复现事件）。

历史复现事件有完整的 5 个输入文件（`data/historical_replay/events/`），
策略运行/采集事件只存在于 MongoDB。这里读取每个 ``event_id`` 的最新一条
记录，跳过测试占位、过短正文和已入图的事件，返回 kg 管线使用的 ``Bundle``。

事件统一标记 ``origin=event_store``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipelines.kg.extract import Bundle

ORIGIN = "event_store"

# 语料标题缺失时给少数已知事件一个正式名；其余取正文首句。
_TITLE_HINTS = {
    "event_wuhan_halloween_rideshare_20261101": "武汉万圣节网约车被困事件",
    "event_gaoyang_assault_001": "河北高阳商场门口殴打他人事件",
}

_LOCATION_HINTS = {
    "event_wuhan_halloween_rideshare_20261101": "武汉江汉路",
}

_SKIP_MARKERS = ("测试事件", "测试正文", "占位")


def _title_for(event_id: str, content: str) -> str:
    if event_id in _TITLE_HINTS:
        return _TITLE_HINTS[event_id]
    head = content.split("。", 1)[0].strip()
    return head[:30] if head else event_id


def discover_store_events(
    uri: str,
    database: str,
    exclude_ids: set[str] | None = None,
    timeout_ms: int = 3000,
) -> list[Bundle]:
    """读取 MongoDB 事件集合，返回可入图的 Bundle 列表。"""

    try:
        import pymongo
    except ImportError:  # 离线环境不安装 pymongo 时跳过该数据源
        return []

    exclude = {item for item in (exclude_ids or set()) if item}
    client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)
    try:
        collection = client[database]["events"]
        latest: dict[str, tuple[str, dict[str, Any]]] = {}
        for doc in collection.find({}):
            event_id = str(doc.get("event_id") or "").strip()
            if not event_id:
                continue
            stamp = str(doc.get("updated_at") or "")
            previous = latest.get(event_id)
            if previous is None or stamp >= previous[0]:
                latest[event_id] = (stamp, doc)
    finally:
        client.close()

    bundles: list[Bundle] = []
    for event_id, (_, doc) in sorted(latest.items()):
        data = doc.get("data") if isinstance(doc.get("data"), dict) else {}
        content = str(data.get("event_content") or data.get("content") or "").strip()
        if event_id in exclude:
            continue
        if event_id.lower().startswith("event_test") or "test" in event_id.lower():
            continue
        if len(content) < 20 or any(marker in content for marker in _SKIP_MARKERS):
            continue
        labels = data.get("event_labels") if isinstance(data.get("event_labels"), dict) else {}
        bundles.append(
            Bundle(
                event_id=event_id,
                directory=Path("mongodb://events"),
                event_input={
                    "event_id": event_id,
                    "event_content": content,
                    "event_labels": labels or {"topic": "社会事件", "event_valence": "negative"},
                },
                manifest={
                    "title": _title_for(event_id, content),
                    "source": f"MongoDB future_simulation.events/{event_id}",
                    "location_hint": _LOCATION_HINTS.get(event_id, ""),
                },
                origin=ORIGIN,
            )
        )
    return bundles
