# -*- coding: utf-8 -*-
"""评论派系判定与配额均衡采样。

派系（观点输出 / 表态判断 / 情绪激进 / 矛盾激化 / 吃瓜）描述的是**表达方式**，
不是模型的主观印象，因此用可解释的文本特征判定：同一条评论在任何一次运行里
都会得到同一个派系，也不会出现「40 条里 34 条都是同一派」的塌缩。

配额靠**选哪些评论进池**来满足，而不是改写标签：标签始终是真的，
均衡只发生在采样阶段。规则是「每派保底 + 单派上限 + 余量按可得数量分配」。
"""

from __future__ import annotations

import math
import random
import re

FACTIONS = ("观点输出派", "表态判断派", "情绪激进派", "矛盾激化派", "吃瓜派")
RESIDUAL = "表态判断派"

# 特征词表（可按语料扩充，不影响接口）
_ARGUMENT = ("因为", "所以", "但是", "其实", "本质", "说明", "证明", "意味着", "应该",
             "建议", "如果", "一方面", "另一方面", "归根结底", "说到底", "逻辑", "原因",
             "不是", "而是", "对比", "数据")
_CONFLICT = ("你们", "这些人", "这种人", "外地人", "本地人", "素质", "地域", "又是",
             "果然", "活该", "难怪", "凭什么", "算什么", "全国", "别的地方")
_EMOTION = ("愤怒", "气愤", "恶心", "垃圾", "畜生", "人渣", "暴民", "该死", "离谱",
            "无语", "失望", "寒心", "可恶", "无耻", "滚", "骂", "打", "砸")
_MEME = ("笑", "梗", "典", "绷", "doge", "哈哈", "乐", "抽象", "整活", "节目效果",
         "赢", "神人", "吃瓜", "离谱他妈")

_PUNCT = re.compile(r"[!！?？]")
_EMOJI = re.compile(r"\[[^\[\]]{1,8}\]")

# 低于这个分数视为「没有明显表达特征」，归入表态判断派（残差类）
RESIDUAL_THRESHOLD = 2.0


def _hits(text: str, words) -> int:
    return sum(1 for word in words if word in text)


def faction_scores(text: str) -> dict[str, float]:
    """返回四个「有特征」派系的得分，供 argmax 使用，也便于调试。"""
    raw = (text or "").strip()
    length = len(_EMOJI.sub("", raw))
    marks = len(_PUNCT.findall(raw))
    shout = raw.count("！") + raw.count("!")

    argument = _hits(raw, _ARGUMENT)
    conflict = _hits(raw, _CONFLICT)
    emotion = _hits(raw, _EMOTION)
    meme = _hits(raw, _MEME)

    return {
        # 长、有论证词、给理由
        "观点输出派": 1.8 * argument + (1.5 if length >= 60 else 0.0) + math.log1p(length) * 0.25,
        # 强情绪、感叹号
        "情绪激进派": 2.2 * emotion + 1.0 * shout + (0.6 if marks >= 2 else 0.0),
        # 指向某个群体、升级对立
        "矛盾激化派": 2.2 * conflict + (0.6 if conflict and emotion else 0.0),
        # 玩梗、反问、围观
        "吃瓜派": 2.0 * meme + (0.5 if marks >= 2 and length < 30 else 0.0),
    }


def classify(text: str) -> str:
    """判定派系；没有明显特征时归入表态判断派。"""
    scores = faction_scores(text)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], FACTIONS.index(item[0])))
    best_name, best_score = ranked[0]
    return best_name if best_score >= RESIDUAL_THRESHOLD else RESIDUAL


# --------------------------------------------------------------------------
# 配额均衡采样
# --------------------------------------------------------------------------


def effective_min(min_each: int, target: int) -> int:
    """目标条数不足 5×派系数时，按比例下调每派下限，避免保底把名额耗尽。"""
    return max(1, min(min_each, target // len(FACTIONS)))


def allocate_quota(
    available: dict[str, int],
    target: int,
    min_each: int = 5,
    max_share: float = 0.4,
) -> dict[str, int]:
    """每派保底 + 单派上限 + 余量按可得数量分配。

    上限是为了跨批次对照：某一表达方式即使天然更多，也不该垄断样本。
    """
    quota = {name: 0 for name in FACTIONS}
    remaining = target
    floor = effective_min(min_each, target)

    for name in FACTIONS:
        take = min(floor, available.get(name, 0), remaining)
        quota[name] = take
        remaining -= take
    if remaining <= 0:
        return quota

    cap = max(floor, int(math.ceil(target * max_share)))
    for _ in range(remaining):
        candidates = [
            name for name in FACTIONS
            if quota[name] < available.get(name, 0) and quota[name] < cap
        ]
        if not candidates:
            break
        # 每次给「当前占配额比例最低」的派系加一个名额，天然收敛到均衡
        name = min(candidates, key=lambda n: (quota[n] / max(1, available[n]), FACTIONS.index(n)))
        quota[name] += 1
    return quota


def _pick_within(bucket: list[dict], count: int, rng: random.Random) -> list[dict]:
    """单个派系内部仍按 热评 / 最新 / 随机 三通道取，保持样本多样性。"""
    if count <= 0 or not bucket:
        return []
    hot = sorted(bucket, key=lambda c: -int(c.get("likes", 0)))
    latest = sorted(bucket, key=lambda c: c.get("created_at", 0), reverse=True)
    shuffled = bucket[:]
    rng.shuffle(shuffled)
    plan = [
        ("top", hot, math.ceil(count * 0.4)),
        ("latest", latest, math.ceil(count * 0.3)),
        ("random", shuffled, count),
    ]
    picked: dict[str, dict] = {}
    for channel, pool, limit in plan:
        taken = 0
        for item in pool:
            if len(picked) >= count or taken >= limit:
                break
            cid = item["comment_id"]
            if cid in picked:
                continue
            picked[cid] = {**item, "sampling_channel": channel}
            taken += 1
    return list(picked.values())


def balance_sample(
    comments: list[dict],
    target: int,
    min_each: int = 5,
    max_share: float = 0.4,
    seed: int = 17,
) -> tuple[list[dict], dict]:
    """按派系配额采样。返回 (采样结果, 统计)。"""
    rng = random.Random(seed)
    for item in comments:
        if not item.get("faction"):
            item["faction"] = classify(item.get("text", ""))

    buckets: dict[str, list[dict]] = {name: [] for name in FACTIONS}
    for item in comments:
        buckets[item["faction"]].append(item)

    available = {name: len(items) for name, items in buckets.items()}
    quota = allocate_quota(available, target, min_each, max_share)

    picked: list[dict] = []
    for name in FACTIONS:
        picked.extend(_pick_within(buckets[name], quota[name], rng))

    # 配额因某派系不足而落空时，用其余派系补足
    if len(picked) < min(target, len(comments)):
        chosen = {item["comment_id"] for item in picked}
        rest = [item for item in comments if item["comment_id"] not in chosen]
        rest.sort(key=lambda c: -int(c.get("likes", 0)))
        need = min(target, len(comments)) - len(picked)
        picked.extend({**item, "sampling_channel": "fill"} for item in rest[:need])

    counts: dict[str, int] = {}
    for item in picked:
        counts[item["faction"]] = counts.get(item["faction"], 0) + 1

    # 严格口径：complete 仅当每派都达到 min_each；候选池不足时如实记为 short
    floor = effective_min(min_each, target)
    short = {name: counts.get(name, 0) for name in FACTIONS if counts.get(name, 0) < floor}
    complete = not short
    return picked, {
        "target": target,
        "sampled": len(picked),
        "min_per_faction": min_each,
        "min_effective": effective_min(min_each, target),
        "max_share": max_share,
        "available": available,
        "quota": quota,
        "counts": counts,
        "short": short,
        "complete": complete,
    }
