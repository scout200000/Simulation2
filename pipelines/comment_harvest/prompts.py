# -*- coding: utf-8 -*-
"""各阶段的提示词构造。

约定：每个函数返回 `(stage, system, user)`；系统提示统一要求只输出 JSON，
避免模型在正文里夹带解释导致解析失败。
"""

from __future__ import annotations

import json
from typing import Any

COMMON_SYSTEM = (
    "你是舆情分析流水线中的一个环节，只做被明确要求的那一步，不要发挥。"
    "严格输出 JSON 对象，不要 Markdown 代码块，不要解释性文字。"
    "不确定的字段填 null，不要编造。"
)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


# --------------------------------------------------------------------------
# S1 事件结构化
# --------------------------------------------------------------------------


def build_event_card(event_text: str, platforms: list[str], now: str) -> tuple[str, str, str]:
    system = COMMON_SYSTEM
    user = f"""把下面这条事件描述转成检索计划。

事件：
{event_text}

当前日期：{now}
可用平台：{", ".join(platforms)}

输出 JSON：
{{
  "summary": "一句话概括（不超过 40 字）",
  "keywords_zh": ["3-6 个能在中文社媒命中的关键词，含事件主体与争议点"],
  "keywords_en": ["1-3 个英文关键词，无则空数组"],
  "entities": ["涉事机构/地点/人物等实体"],
  "time_window": {{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}},
  "platforms": [{{"name": "平台名", "weight": 0.0-1.0}}],
  "queries": ["4-6 条检索式，可使用 site: / lang: / after: 操作符"]
}}

要求：
- queries 要覆盖「事件本体」「官方回应」「争议焦点」三个角度，不要同义重复；
- 至少一条带 site: 定向到社媒平台，至少一条用于找官方通报；
- 不要输出事件里没有的细节。"""
    return "S1 事件结构化", system, user


# --------------------------------------------------------------------------
# S2 候选精排
# --------------------------------------------------------------------------


def build_rank(event_summary: str, candidates: list[dict], limit: int) -> tuple[str, str, str]:
    rows = [
        {
            "id": i,
            "title": c.get("title", "")[:80],
            "site": c.get("site", ""),
            "snippet": (c.get("snippet") or "")[:120],
            "source": c.get("source", ""),
            "engagement": c.get("engagement", {}),
        }
        for i, c in enumerate(candidates)
    ]
    system = COMMON_SYSTEM
    user = f"""事件：{event_summary}

下面是待排序的候选页面。请挑出最可能是「该事件下讨论最集中、评论最多」的 {limit} 个页面。

{_dump(rows)}

输出 JSON：
{{
  "picked": [
    {{"id": 候选编号, "reason": "为什么选它（20 字内）", "expected_comment_volume": "high|medium|low"}}
  ]
}}

要求：
- 优先选有真实评论区的页面（视频站、论坛、问答、社交平台），新闻通稿与聚合页一律不选；
- 同一站点最多选 2 个，保证平台多样性；
- 只输出确实与事件相关的，宁缺毋滥。"""
    return "S2 候选精排", system, user


# --------------------------------------------------------------------------
# S3 版面判断
# --------------------------------------------------------------------------


def build_triage(event_summary: str, pages: list[dict]) -> tuple[str, str, str]:
    rows = [
        {
            "id": i,
            "url": p.get("url", ""),
            "title": p.get("title", "")[:80],
            "content": (p.get("content") or "")[:1500],
        }
        for i, p in enumerate(pages)
    ]
    system = COMMON_SYSTEM
    user = f"""事件：{event_summary}

下面是已抓取的页面正文（截断到前 1500 字）。判断每个页面是否值得深读并抓取评论。

{_dump(rows)}

输出 JSON：
{{
  "pages": [
    {{
      "id": 页面编号,
      "has_comment_section": true/false,
      "content_quality": "high|medium|low",
      "hotness_signal": "页面里体现热度的证据，如点赞/评论数/热度标识；没有则 null",
      "keep": true/false,
      "reason": "20 字内"
    }}
  ]
}}

要求：
- 正文里能看到评论区、楼层、点赞数、"条评论"等痕迹才判 has_comment_section=true；
- 正文是登录墙、验证码、空壳页面时 content_quality=low 且 keep=false。"""
    return "S3 版面判断", system, user


# --------------------------------------------------------------------------
# S4 帖子深读
# --------------------------------------------------------------------------


def build_deep_read(event_summary: str, page: dict) -> tuple[str, str, str]:
    system = COMMON_SYSTEM
    user = f"""事件：{event_summary}

帖子标题：{page.get("title", "")}
正文（截断）：
{(page.get("content") or "")[:2400]}

输出 JSON：
{{
  "core_claims": ["帖子主张的 2-4 个要点"],
  "controversies": ["评论区的争议点，没有则空数组"],
  "comment_entry": "评论入口在页面里的位置或接口标识，如 BV 号 / item id / permalink；判断不出填 null",
  "read_quality": "high|medium|low"
}}"""
    return "S4 帖子深读", system, user


# --------------------------------------------------------------------------
# S6 评论理解（分批）
# --------------------------------------------------------------------------


def build_tag(event_summary: str, comments: list[dict], existing_labels: list[str]) -> tuple[str, str, str]:
    rows = [{"id": c["comment_id"], "text": c["text"][:120]} for c in comments]
    labels = "、".join(existing_labels) if existing_labels else "（无，需自行归纳）"
    system = COMMON_SYSTEM
    user = f"""事件：{event_summary}

给下面的评论逐条打标签。已有议题标签：{labels}

{_dump(rows)}

输出 JSON：
{{
  "comments": [
    {{
      "id": "评论 id 原样返回",
      "cluster": "议题标签；优先复用已有标签，确实无法归类时新建一个不超过 8 字的标签",
      "sentiment": "positive|neutral|negative",
      "stance": "support|oppose|neutral|question",
      "intensity": 0.0-1.0,
      "is_noise": true/false
    }}
  ]
}}

要求：
- 一条都不能漏，顺序与输入一致；
- 广告、纯表情、无意义刷屏判 is_noise=true，但仍要输出该条；
- sentiment 判断的是对「事件/涉事方」的态度，不是语气；反讽按真实态度判。"""
    return "S6 评论理解", system, user


# --------------------------------------------------------------------------
# S7 全局归并
# --------------------------------------------------------------------------


def build_merge(event_summary: str, tags: list[dict], quotes: list[dict]) -> tuple[str, str, str]:
    counts: dict[str, int] = {}
    for tag in tags:
        counts[tag.get("cluster") or "其他"] = counts.get(tag.get("cluster") or "其他", 0) + 1
    system = COMMON_SYSTEM
    user = f"""事件：{event_summary}

各议题的原始计数：{_dump(counts)}

代表评论候选（含点赞数）：
{_dump(quotes[:40])}

输出 JSON：
{{
  "themes": [
    {{
      "label": "议题名（不超过 10 字）",
      "n": 该议题条数,
      "sentiment_mix": {{"positive": 0.0, "neutral": 0.0, "negative": 0.0}},
      "argument": "这个议题下人们的核心论点，40 字内",
      "quotes": ["从候选里挑 1-2 条 id"]
    }}
  ]
}}

要求：
- 合并语义重复的议题，总数控制在 4-8 个；
- n 必须来自上面的计数，不要新造；
- 按 n 从大到小排序。"""
    return "S7 全局归并", system, user


# --------------------------------------------------------------------------
# S8 报告
# --------------------------------------------------------------------------


def build_report(
    event_summary: str,
    posts: list[dict],
    themes: list[dict],
    shares: dict[str, float],
    stats: dict[str, Any],
    quotes: list[dict],
    length: int = 1300,
) -> tuple[str, str, str]:
    system = COMMON_SYSTEM
    user = f"""事件：{event_summary}

取样口径：{_dump(stats)}
情感分布：{_dump(shares)}
帖子：{_dump([{"title": p.get("title"), "platform": p.get("platform"), "url": p.get("url")} for p in posts])}
议题：{_dump(themes)}
可用引文：{_dump([{"id": q["comment_id"], "text": q["text"][:80], "likes": q.get("likes")} for q in quotes[:20]])}

写一份约 {length} 字的分析报告。输出 JSON：
{{
  "summary": "三句话以内的结论",
  "sections": [{{"heading": "小标题", "body": "正文段落"}}],
  "claims": [
    {{"claim": "一条可核验的判断", "evidence": ["引文 id", "引文 id"], "confidence": 0.0-1.0}}
  ],
  "caveats": ["取样与推断的局限，至少一条"]
}}

要求：
- 每个百分比都要说明分母是「清洗后的 N 条样本」，不能把样本比例写成全网比例；
- claims 里每条至少挂一个引文 id，挂不上的话不要写这条判断；
- 不要写"网友普遍认为"这类无证据的笼统表述。"""
    return "S8 报告", system, user


# --------------------------------------------------------------------------
# S9 引用自检
# --------------------------------------------------------------------------


def build_verify(report: dict, quotes: list[dict]) -> tuple[str, str, str]:
    allowed = {q["comment_id"] for q in quotes}
    system = COMMON_SYSTEM
    user = f"""核对报告里的每条判断是否真有引文支撑。

报告：{_dump(report)}

可用引文 id：{_dump(sorted(allowed))}

输出 JSON：
{{
  "checks": [{{"claim": "原判断", "supported": true/false, "why": "20 字内"}}],
  "unsupported_count": 不成立的条数
}}

要求：引文 id 不在可用列表里、或引文内容与该判断无关，都算 supported=false。"""
    return "S9 引用自检", system, user
