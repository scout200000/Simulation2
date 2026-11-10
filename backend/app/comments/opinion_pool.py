# -*- coding: utf-8 -*-
"""初始舆论池的来源调度。

一个事件的第一轮评论可以有两条来源：

- ``generate``：按事件角度与人物类型用大模型合成（原有路径）；
- ``harvest``：从平台公开评论区采集真实评论，并在采集时完成标注。

两种来源产出同构的 ``comment_pool.json``，下游无需区分。
"""

from __future__ import annotations

from copy import deepcopy

from app.comments.pool_generator import generate_comment_pool
from app.comments.web_harvest import HarvestError, harvest_comment_pool
from app.infrastructure.storage.json_storage import load_json
from app.main.config.settings import OPINION_POOL_CONFIG_FILE

SOURCES = ("generate", "harvest")
DEFAULT_CONFIG = {
    "schema_version": 1,
    "source": "generate",
    "generate": {"comment_count": 60},
    "harvest": {
        "comment_count": 40,
        "platforms": ["bilibili"],
        "queries": [],
        "max_keywords": 4,
        "videos": 3,
        "hot_pages": 2,
        "new_pages": 1,
        "expand_ratio": 1.5,
        "qps": 1.2,
        "labeling": "compact",
    },
}

COUNT_RANGE = (10, 200)


def _clamp_count(value, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(COUNT_RANGE[0], min(COUNT_RANGE[1], number))


def normalize_opinion_pool_config(raw: dict | None) -> dict:
    """合并默认值并做边界约束，返回可直接存进 control 的配置。"""
    source = DEFAULT_CONFIG["source"]
    merged = deepcopy(DEFAULT_CONFIG)

    if isinstance(raw, dict):
        if str(raw.get("source", "")).strip() in SOURCES:
            source = str(raw["source"]).strip()
        for section in ("generate", "harvest"):
            if isinstance(raw.get(section), dict):
                merged[section].update(raw[section])

    merged["source"] = source
    merged["generate"]["comment_count"] = _clamp_count(
        merged["generate"].get("comment_count"), 60
    )
    harvest = merged["harvest"]
    harvest["comment_count"] = _clamp_count(harvest.get("comment_count"), 40)
    harvest["videos"] = max(1, min(6, int(harvest.get("videos") or 3)))
    harvest["hot_pages"] = max(1, min(5, int(harvest.get("hot_pages") or 2)))
    harvest["new_pages"] = max(0, min(3, int(harvest.get("new_pages") or 1)))
    harvest["expand_ratio"] = max(1.0, min(3.0, float(harvest.get("expand_ratio") or 1.5)))
    harvest["qps"] = max(0.3, min(5.0, float(harvest.get("qps") or 1.2)))
    if not isinstance(harvest.get("platforms"), list) or not harvest["platforms"]:
        harvest["platforms"] = ["bilibili"]
    if not isinstance(harvest.get("queries"), list):
        harvest["queries"] = []
    return merged


def load_default_config() -> dict:
    """读取 configs/opinion_pool.json；缺失时用内置默认值。"""
    if OPINION_POOL_CONFIG_FILE.is_file():
        try:
            return normalize_opinion_pool_config(load_json(OPINION_POOL_CONFIG_FILE))
        except (ValueError, OSError):
            pass
    return normalize_opinion_pool_config(None)


def resolve_config(override: dict | None = None, stored: dict | None = None) -> dict:
    """优先级：本次请求 override > 会话已存配置 > 配置文件默认值。"""
    if isinstance(override, dict) and override:
        return normalize_opinion_pool_config({**load_default_config(), **override})
    if isinstance(stored, dict) and stored:
        return normalize_opinion_pool_config(stored)
    return load_default_config()


def comment_count_for(config: dict) -> int:
    section = config.get(config.get("source", "generate"), {})
    return _clamp_count(section.get("comment_count"), 60)


def build_initial_comment_pool(
    event_input: dict,
    config: dict | None = None,
    profile_file=None,
    initial_opinion=None,
):
    """按配置生成或采集初始评论池。

    ``initial_opinion``（历史校准的人工情绪配额）只支持生成式：采集式拿到的
    是真实分布，无法精确匹配 `emotion_targets`。
    """
    resolved = normalize_opinion_pool_config(config or load_default_config())
    source = resolved["source"]

    if initial_opinion is not None:
        if source == "harvest":
            raise ValueError(
                "历史校准要求精确匹配人工情绪配额，采集式初始池无法保证，"
                "请把 opinion_pool.source 设为 generate。"
            )
        return generate_comment_pool(
            event_input=event_input,
            profile_file=profile_file,
            comment_count=comment_count_for(resolved),
            initial_opinion=initial_opinion,
        )

    if source == "harvest":
        try:
            pool = harvest_comment_pool(
                event_input,
                comment_count_for(resolved),
                resolved["harvest"],
            )
        except HarvestError as exc:
            raise ValueError(f"采集式初始舆论池失败：{exc}") from exc
        pool["opinion_pool_config"] = resolved
        return pool

    pool = generate_comment_pool(
        event_input=event_input,
        profile_file=profile_file,
        comment_count=comment_count_for(resolved),
    )
    pool["opinion_pool_config"] = resolved
    return pool


__all__ = [
    "SOURCES",
    "normalize_opinion_pool_config",
    "load_default_config",
    "resolve_config",
    "comment_count_for",
    "build_initial_comment_pool",
]
