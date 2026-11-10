# -*- coding: utf-8 -*-
"""打分与清洗：候选项归一化、热度打分、评论清洗、分层采样。

这里全部是纯函数，不碰网络也不碰模型，便于单测和复算。
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from datetime import datetime, timezone
from typing import Any, Iterable

# 广告 / 引流 / 灌水特征（命中即丢）
NOISE_PATTERNS = (
    "加微信", "加vx", "加v", "私信我", "点击链接", "详情咨询", "优惠券", "代购",
    "返利", "兼职", "日赚", "刷单", "复制打开", "领红包", "扫码", "关注公众号",
)
# 清洗后仍有意义的长度下限（中文字符数）
MIN_CHARS = 4

POS_WORDS = (
    "支持", "感谢", "点赞", "棒", "优秀", "暖心", "及时", "负责", "透明", "满意",
    "放心", "靠谱", "良心", "辛苦了", "加油", "感动", "有担当", "高效", "专业",
    "合理", "认可", "期待", "好转", "改善", "值得", "敬佩", "给力", "进步",
)
NEG_WORDS = (
    "失望", "愤怒", "气愤", "离谱", "恶心", "垃圾", "骗", "坑", "退钱", "抵制",
    "差劲", "无语", "太差", "追责", "问责", "敷衍", "甩锅", "冷漠", "难受",
    "担忧", "焦虑", "可怕", "恐惧", "谴责", "严惩", "不作为", "官僚", "拖延",
    "隐瞒", "造假", "欺骗", "黑心", "无良", "缺德", "烂", "翻车", "塌方", "寒心",
)
NEGATORS = ("不", "没", "无", "别", "未")

# 规则聚类的议题词表（离线模式使用；接入大模型后由模型自行归纳）
ISSUE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("责任认定与追责", ("责任", "追责", "问责", "处罚", "认定", "肇事", "判")),
    ("官方回应与信息透明", ("通报", "回应", "官方", "声明", "辟谣", "谣言", "隐瞒", "透明")),
    ("赔偿与善后", ("赔偿", "补偿", "善后", "保险", "医药费", "赔付")),
    ("安全管理与监管", ("安全", "监管", "隐患", "制度", "管理", "检查", "整改")),
    ("对受害者的同情", ("可怜", "心疼", "孩子", "家属", "无辜", "祈祷", "安息")),
    ("情绪宣泄与道德评判", ("畜生", "人渣", "该死", "愤怒", "气愤", "恶心", "无语")),
    ("媒体与传播质疑", ("媒体", "热搜", "带节奏", "剪辑", "标题党", "营销号", "流量")),
    ("其他/未归类", ()),
)


# --------------------------------------------------------------------------
# 候选项
# --------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def candidate_from_search(result: dict, query: str) -> dict:
    """搜索接口结果 → 候选项。"""
    url = result.get("url", "")
    return {
        "url": url,
        "title": (result.get("title") or "").strip(),
        "site": result.get("site_name") or _domain(url),
        "source": "search",
        "snippet": (result.get("snippet") or "")[:160],
        "summary": (result.get("summary") or "")[:800],
        "published_at": result.get("date") or "",
        "engagement": {},
        "authority": int(result.get("authority") or 0),
        "rerank_score": float(result.get("rerank_score") or 0.0),
        "query": query,
    }


def candidate_from_hotlist(item: dict, platform: str) -> dict:
    return {
        "url": item.get("url", ""),
        "title": (item.get("title") or "").strip(),
        "site": item.get("site") or _domain(item.get("url", "")),
        "source": "hotlist",
        "platform": platform,
        "snippet": (item.get("snippet") or "")[:160],
        "summary": "",
        "published_at": item.get("published_at") or "",
        "engagement": item.get("engagement") or {},
        "authority": 3,
        "rerank_score": 0.0,
        "hn_id": item.get("hn_id", ""),
        "query": f"hotlist:{platform}",
    }


def _domain(url: str) -> str:
    match = re.match(r"https?://([^/]+)", url or "")
    return match.group(1) if match else ""


def _url_key(url: str) -> str:
    return re.sub(r"[?#].*$", "", url).rstrip("/").lower()


def dedupe_candidates(items: Iterable[dict]) -> list[dict]:
    """URL 去重；保留来源优先级更高（热榜 > 搜索）与更完整的一条。"""
    best: dict[str, dict] = {}
    for item in items:
        key = _url_key(item.get("url", ""))
        if not key:
            continue
        current = best.get(key)
        if current is None:
            best[key] = item
            continue
        # 热榜优先，其次看互动量
        rank = lambda c: (c.get("source") == "hotlist", _engagement(c))
        if rank(item) >= rank(current):
            merged = {**current, **item}
            merged["source"] = item.get("source") or current.get("source")
            best[key] = merged
    return list(best.values())


def _engagement(item: dict) -> int:
    eng = item.get("engagement") or {}
    return int(eng.get("likes", 0)) + 3 * int(eng.get("comments", 0))


def keyword_hits(text: str, keywords: Iterable[str]) -> int:
    text = text or ""
    return sum(1 for kw in keywords if kw and kw in text)


def rule_score(item: dict, keywords: list[str], tau_hours: float = 48.0) -> float:
    """规则初筛分：关键词命中 + 来源 + 新鲜度 + 权威度 + 互动量。"""
    text = f"{item.get('title', '')} {item.get('snippet', '')} {item.get('summary', '')}"
    hits = keyword_hits(text, keywords)
    source_bonus = 0.35 if item.get("source") == "hotlist" else 0.0
    fresh = freshness(item.get("published_at", ""), tau_hours)
    authority = min(1.0, (item.get("authority") or 0) / 4)
    engage = min(1.0, math.log10(1 + _engagement(item)) / 6)
    return 0.45 * min(1.0, hits / 3) + source_bonus + 0.15 * fresh + 0.10 * authority + 0.15 * engage


def freshness(published_at: str, tau_hours: float = 48.0) -> float:
    moment = _parse_time(published_at)
    if not moment:
        return 0.5
    delta = (_now() - moment).total_seconds() / 3600
    if delta < 0:
        return 1.0
    return math.exp(-delta / max(1.0, tau_hours))


def hotness(item: dict, tau_hours: float = 48.0) -> dict[str, float]:
    """热度分：点赞 0.35 / 评论 0.25 / 新鲜度 0.20 / 权威度 0.10 / 增速 0.10。

    各项先归一化到 0~1，避免不同平台量纲直接相加。
    """
    eng = item.get("engagement") or {}
    likes = min(1.0, math.log10(1 + int(eng.get("likes", 0))) / 6)
    comments = min(1.0, math.log10(1 + int(eng.get("comments", 0))) / 5)
    fresh = freshness(item.get("published_at", ""), tau_hours)
    authority = min(1.0, (item.get("authority") or 0) / 4)
    velocity = 0.5  # 单次采样拿不到增速，取中性值
    parts = {
        "likes": round(likes, 3),
        "comments": round(comments, 3),
        "freshness": round(fresh, 3),
        "authority": round(authority, 3),
        "velocity": velocity,
    }
    total = (
        0.35 * likes + 0.25 * comments + 0.20 * fresh + 0.10 * authority + 0.10 * velocity
    )
    return {"hotness": round(total, 3), **parts}


# --------------------------------------------------------------------------
# 评论清洗
# --------------------------------------------------------------------------


def _norm_for_dedup(text: str) -> str:
    core = re.sub(r"[\s\W_]+", "", text)
    return hashlib.sha1(core.encode("utf-8")).hexdigest()[:16]


def is_noise(text: str) -> bool:
    if len(text) < MIN_CHARS:
        return True
    if not re.search(r"[\u4e00-\u9fffA-Za-z]", text):
        return True
    return any(pattern in text for pattern in NOISE_PATTERNS)


def clean_comments(raw: Iterable[dict], min_chars: int = MIN_CHARS) -> tuple[list[dict], dict]:
    """去重、去噪、去广告。返回 (评论列表, 清洗统计)。"""
    stats = {"input": 0, "empty": 0, "too_short": 0, "noise": 0, "duplicate": 0, "kept": 0}
    seen: set[str] = set()
    out: list[dict] = []

    for item in raw:
        stats["input"] += 1
        text = (item.get("text") or "").strip()
        if not text:
            stats["empty"] += 1
            continue
        if len(text) < min_chars:
            stats["too_short"] += 1
            continue
        if is_noise(text):
            stats["noise"] += 1
            continue
        key = _norm_for_dedup(text)
        if key in seen:
            stats["duplicate"] += 1
            continue
        seen.add(key)
        out.append(item)

    stats["kept"] = len(out)
    return out, stats


# --------------------------------------------------------------------------
# 分层采样
# --------------------------------------------------------------------------


def stratified_sample(
    comments: list[dict],
    target: int,
    per_post_min: int = 20,
    seed: int = 17,
) -> tuple[list[dict], dict]:
    """热评 40% / 最新 30% / 随机 30%，并保证每帖下限。

    直接取前 N 条热评会得到极化样本，这里按通道分层以保留长尾与反驳意见。
    """
    if not comments:
        return [], {"target": target, "sampled": 0, "channels": {}, "per_post": {}}

    rng = random.Random(seed)
    by_post: dict[str, list[dict]] = {}
    for item in comments:
        by_post.setdefault(item.get("post_id") or "unknown", []).append(item)

    picked: dict[str, dict] = {}

    def take(bucket: list[dict], count: int, channel: str) -> int:
        taken = 0
        for item in bucket:
            if taken >= count or len(picked) >= target:
                break
            cid = item["comment_id"]
            if cid in picked:
                continue
            picked[cid] = {**item, "sampling_channel": channel}
            taken += 1
        return taken

    # 1) 每帖保底
    per_post_quota = max(1, min(per_post_min, target // max(1, len(by_post))))
    for items in by_post.values():
        hot = sorted(items, key=lambda c: -int(c.get("likes", 0)))
        latest = sorted(items, key=lambda c: c.get("created_at", ""), reverse=True)
        shuffled = items[:]
        rng.shuffle(shuffled)
        take(hot[: per_post_quota // 2 + 1], per_post_quota // 2 + 1, "top")
        take(latest[: per_post_quota // 3 + 1], per_post_quota // 3 + 1, "latest")
        take(shuffled[: per_post_quota // 3 + 1], per_post_quota // 3 + 1, "random")

    # 2) 剩余额度按通道比例补足
    remaining = target - len(picked)
    if remaining > 0:
        pools = {
            "top": sorted(
                (c for c in comments if c["comment_id"] not in picked),
                key=lambda c: -int(c.get("likes", 0)),
            ),
            "latest": sorted(
                (c for c in comments if c["comment_id"] not in picked),
                key=lambda c: c.get("created_at", ""),
                reverse=True,
            ),
            "random": [c for c in comments if c["comment_id"] not in picked],
        }
        rng.shuffle(pools["random"])
        quota = {"top": int(remaining * 0.4), "latest": int(remaining * 0.3)}
        quota["random"] = remaining - quota["top"] - quota["latest"]
        for channel in ("top", "latest", "random"):
            take(pools[channel], quota[channel], channel)

    sampled = list(picked.values())
    channels: dict[str, int] = {}
    per_post: dict[str, int] = {}
    for item in sampled:
        channels[item["sampling_channel"]] = channels.get(item["sampling_channel"], 0) + 1
        per_post[item["post_id"]] = per_post.get(item["post_id"], 0) + 1

    return sampled, {
        "target": target,
        "sampled": len(sampled),
        "channels": channels,
        "per_post": per_post,
        "seed": seed,
    }


# --------------------------------------------------------------------------
# 规则情感 / 聚类（离线回退用）
# --------------------------------------------------------------------------


def _flip_if_negated(text: str, word: str) -> int:
    index = text.find(word)
    window = text[max(0, index - 3): index]
    return -1 if any(neg in window for neg in NEGATORS) else 1


def heuristic_sentiment(text: str) -> str:
    pos = sum(_flip_if_negated(text, w) for w in POS_WORDS if w in text)
    neg = sum(_flip_if_negated(text, w) for w in NEG_WORDS if w in text)
    score = pos - neg
    if score > 0:
        return "positive"
    if score < 0:
        return "negative"
    return "neutral"


def heuristic_cluster(text: str) -> str:
    for label, words in ISSUE_RULES:
        if any(word in text for word in words):
            return label
    return ISSUE_RULES[-1][0]


def heuristic_stance(text: str, sentiment: str) -> str:
    if any(w in text for w in ("支持", "认可", "点赞", "理解")):
        return "support"
    if any(w in text for w in ("反对", "抵制", "追责", "严惩", "谴责")):
        return "oppose"
    return {"negative": "oppose", "positive": "support"}.get(sentiment, "neutral")


def sentiment_shares(tags: Iterable[dict]) -> dict[str, float]:
    counts = {"negative": 0, "neutral": 0, "positive": 0}
    total = 0
    for tag in tags:
        if tag.get("is_noise"):
            continue
        label = tag.get("sentiment") or "neutral"
        counts[label] = counts.get(label, 0) + 1
        total += 1
    if not total:
        return {k: 0.0 for k in counts}
    return {k: round(v / total, 3) for k, v in counts.items()}
