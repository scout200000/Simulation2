# -*- coding: utf-8 -*-
"""采集式初始舆论池：从 B 站公开评论区抓取真实评论，边采集边标注。

与 ``pool_generator`` 的区别只在数据来源：本模块产出与 ``comment_pool.json``
完全相同的结构（含 angle_plan），因此下游的 Agent 决策、公共黑板、报告
都不需要改动。

四个成本 / 质量控制点：
1. **减量**：默认只取 40 条（生成式 60 条），抓取按 1.5 倍冗余并提前停止；
2. **压缩标注**：一次请求标注整批评论，输出为位置对齐的整数元组；
3. **相关性过滤**：多标一位 `relevant`，跑题段子不进池；
4. **派系均衡**：派系由文本特征判定（不是模型印象），配额靠采样满足，
   保证不会出现「40 条里 34 条同一派」。
"""

from __future__ import annotations

import math
import re
import sys
import time
from collections import Counter

from app.comments.angle_planner import validate_event_angle_plan
from app.comments.faction_balance import FACTIONS, balance_sample, classify
from app.infrastructure.llm.llm_service import call_deepseek_json
from app.main.config.settings import PROJECT_DIR

PLATFORM = "bilibili"

EMOTIONS = ("positive", "neutral", "negative")
STANCES = ("support", "questioning", "neutral", "criticism")
ORIENTATIONS = ("fact", "opinion", "questioning")

# 派系配额：每派至少 min 条，单派不超过 target 的 max_share
MIN_PER_FACTION = 5
MAX_FACTION_SHARE = 0.4

LABEL_SYSTEM = "你只返回合法 JSON 对象，不要 Markdown，不要解释。"

LABEL_PROMPT = """你是舆情标注器。给定事件和一批真实评论，逐条标注。

【事件】
{event}

【评论】（编号|正文）
{rows}

【标注口径】
- 议题：把评论归到 3~6 个议题，用不超过 8 个字的中文短语；相同议题只出现一次。
- sentiment：0=正面 1=中性 2=负面（对该事件/涉事方的情绪，反讽按真实态度判）
- stance：0=支持 1=质疑 2=中立 3=批评
- orientation：0=事实陈述 1=观点表达 2=提问
- relevant：1=在讨论本事件；0=跑题、纯段子、与本事件无关

【输出】
{{"clusters": ["议题A", "议题B"], "tags": [[0, 2, 3, 1, 1], [1, 1, 2, 0, 1]]}}

要求：
- 议题编号 **从 0 开始**，必须落在 clusters 的下标范围内；
- tags 的顺序必须与评论一一对应，长度必须等于 {count}；
- 每行恰好 5 个整数（派系由程序另行判定，不需要你判断），
  不要输出评论编号，不要输出任何额外字段。"""


class HarvestError(RuntimeError):
    """采集失败（无可用评论或平台不可达）。"""


# --------------------------------------------------------------------------
# 依赖桥接：复用 pipelines 里的 B 站客户端与清洗逻辑
# --------------------------------------------------------------------------


def _shared():
    """延迟导入 pipelines 侧的纯逻辑模块，避免 import 期副作用。"""
    root = str(PROJECT_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)
    from pipelines.comment_harvest import score  # noqa: PLC0415
    from pipelines.comment_harvest.bili import BiliClient, BiliError, MODE_HOT, MODE_NEW  # noqa: PLC0415

    return score, BiliClient, BiliError, MODE_HOT, MODE_NEW


# --------------------------------------------------------------------------
# 检索式
# --------------------------------------------------------------------------

_STOP_CHARS = set("的了是在和与及或就都很也太又还这个那个一个没有我们他们你们")


def derive_keywords(text: str, limit: int = 4, min_count: int = 2) -> list[str]:
    """从事件正文里取高频 2~4 字片段作为检索词（无需分词器）。

    ``min_count`` 用来滤掉只在词边界偶然出现的片段（例如「武汉江汉路」里的「汉江」）。
    """
    counter: Counter[str] = Counter()
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", text or ""):
        for size in (2, 3, 4):
            for i in range(len(run) - size + 1):
                term = run[i:i + size]
                if any(ch in _STOP_CHARS for ch in term):
                    continue
                counter[term] += 1
    picked: list[str] = []
    for term, count in counter.most_common(200):
        if count < min_count:
            break
        if any(term in kept or kept in term for kept in picked):
            continue
        picked.append(term)
        if len(picked) >= limit:
            break
    return picked


_CLAUSE_SPLIT = re.compile(r"[，。；！？、,.;!?\s]+")
_LEADING_DATE = re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日|^\d{1,2}月\d{1,2}日")
_DATE_ONLY = re.compile(r"[\d年月日\-/:.]+")

# 时间词会把首个子句吃空，必须显式剔除
_TIME_WORDS = (
    "凌晨", "清晨", "早上", "上午", "中午", "下午", "傍晚", "晚上", "深夜",
    "当日", "当天", "近日", "日前", "目前", "随后", "事后", "现在", "当天下午",
    "今天", "昨天", "前天", "今年以来", "以来",
)
# 出现在标题里但完全不区分事件的泛词
_GENERIC = ("事件", "处理", "情况", "现场", "视频", "网友", "通报", "后续")
_PLACE_SUFFIX = "省市县区镇路街村乡"

PLAN_SYSTEM = "你只返回合法 JSON 对象，不要 Markdown，不要解释。"
PLAN_PROMPT_RETRY = """上一次用这些检索式没找到对应视频：{previous}

事件：{event}

请换一个角度，给出**更宽泛**但仍指向同一件事的检索式。

输出 JSON：
{{"queries": ["4 条短查询，3-12 字"],
  "keywords": ["4-6 个关键词，2-6 字"]}}

要求：
- 把县级地名换成市级地名（如「高阳县」→「保定」），保留事件的核心动作；
- 用人们转述这件事时最可能写的说法，不要用公文式表述；
- keywords 必须原样出现在事件正文里，且至少包含一个地名。"""
PLAN_PROMPT = """把下面的社会事件转成检索计划。

事件：{event}

输出 JSON：
{{"queries": ["4 条用于站内搜索的短查询，3-12 字"],
  "keywords": ["4-6 个判断视频是否在讲这件事的关键词，2-6 字"]}}

要求：
- queries 必须是事件里的具体实体或争议点，不要用「中午」「近日」这类时间词；
- keywords 只取事件里出现过的地名、机构、人物、行为，必须原样出现在事件正文里；
- 不要用「司机」「事件」「处理」「现场」这类放到任何事件都成立的泛词；
- 中英文事件分别给中文/英文词。"""


def _strip_temporal(text: str) -> str:
    """去掉开头的日期与全文里的时间词，留下有检索价值的部分。"""
    text = _LEADING_DATE.sub("", text or "")
    for word in _TIME_WORDS:
        text = text.replace(word, "")
    return text.strip("，。；、:： ")


def _starts_after_digit(term: str, text: str) -> bool:
    """判断片段是不是从数字后面开始的跨词碎片（「8月29日中午」里的「日中」）。"""
    index = (text or "").find(term)
    return index > 0 and (text[index - 1].isdigit() or text[index - 1] in "月日年")


def _usable_keywords(text: str, limit: int = 4) -> list[str]:
    """兜底关键词：去掉时间词与跨词碎片，优先长词。"""
    raw = derive_keywords(text, max(limit, 6), min_count=1)
    cleaned = [
        word for word in raw
        if word not in _TIME_WORDS and word not in _GENERIC and not _starts_after_digit(word, text)
    ]
    cleaned.sort(key=lambda word: -len(word))
    return cleaned[:limit]


def _pick_head(clause: str) -> str:
    """取一个以行政/道路单位结尾的前缀，避免把地名截断。"""
    cleaned = _strip_temporal(clause)
    window = cleaned[:12]
    for index in range(len(window) - 1, 1, -1):
        if window[index] in _PLACE_SUFFIX:
            return window[: index + 1]
    return cleaned[:8]


def heuristic_queries(event_content: str, config: dict) -> list[str]:
    """无模型时的检索式：首个子句去掉时间词后取地名前缀 + 两个追问。"""
    text = (event_content or "").strip()
    clauses = [c for c in _CLAUSE_SPLIT.split(text) if len(c) >= 4]
    head = ""
    for clause in clauses:
        if _DATE_ONLY.fullmatch(clause):
            continue
        candidate = _pick_head(clause)
        if len(re.findall(r"[\u4e00-\u9fff]", candidate)) >= 3:
            head = candidate
            break
    if not head:
        keywords = _usable_keywords(text, 2)
        head = keywords[0] if keywords else ""
    if not head:
        return []

    base = head[:6] or head
    queries = [head, f"{base} 事件", f"{base} 官方", f"{base} 视频"]
    return list(dict.fromkeys([q.strip() for q in queries if q.strip()]))[:4]


def plan_retrieval(
    event_content: str,
    config: dict,
    attempt: int = 1,
    previous: list[str] | None = None,
) -> tuple[list[str], list[str], str]:
    """生成检索式与相关性关键词。优先让模型规划，失败退回启发式。"""
    explicit = [str(q).strip() for q in (config.get("queries") or []) if str(q).strip()]
    if explicit:
        return explicit[:4], derive_keywords(event_content, 5, min_count=1), "config"

    try:
        template = PLAN_PROMPT if attempt == 1 else PLAN_PROMPT_RETRY
        result = call_deepseek_json(
            prompt=template.format(
                event=(event_content or "")[:400],
                previous="、".join(previous or []) or "（无）",
            ),
            system_prompt=PLAN_SYSTEM,
            temperature=0.2,
            max_tokens=400,
            request_type=f"opinion_pool_query_plan_{attempt}",
        )
        queries = [str(q).strip() for q in (result.get("queries") or []) if str(q).strip()][:4]
        # 关键词必须真的出现在事件正文里，否则拒收——防止模型给出泛词
        keywords = [
            str(k).strip() for k in (result.get("keywords") or [])
            if str(k).strip() and str(k).strip() in (event_content or "")
        ][:6]
        if queries and keywords:
            return queries, keywords, "llm"
    except Exception:  # noqa: BLE001 - 规划失败不影响主流程
        pass

    queries = heuristic_queries(event_content, config)
    keywords = _usable_keywords(event_content, 6)
    return queries, keywords, "heuristic"


FILTER_SYSTEM = "你只返回合法 JSON 对象，不要 Markdown，不要解释。"
FILTER_PROMPT = """下面是「一个事件」和一批候选视频标题。只保留确实在讲**同一件事**的视频。

【事件】
{event}

【候选视频】（编号|标题）
{rows}

输出 JSON：{{"keep": [1, 3]}}

判断口径：
- 只是同一地区、同一类事件（别的打人、别的冲突）不算，必须能对上事件里的具体情节；
- 标题看不出是否同一件事时，不要保留；
- 一个都不像就返回空数组。"""


def _anchor_keywords(keywords: list[str], event_content: str) -> dict[str, list[str]]:
    """把关键词分成「实体锚点」和「泛化动作词」，兜底判定时用法不同。"""
    # 锚点只认「地名/机构」或足够长的具体短语；「商场门口」这种四字泛词不算
    anchors = []
    for word in keywords:
        if any(ch in word for ch in _PLACE_SUFFIX) or len(word) >= 5:
            anchors.append(word)
        elif any(f"{word}{suffix}" in (event_content or "") for suffix in _PLACE_SUFFIX):
            # 两字地名（保定）在正文里以「保定市」出现，也算锚点
            anchors.append(word)
    supports = [word for word in keywords if word not in anchors]
    return {"anchors": anchors, "supports": supports}


def anchor_match(text: str, anchors: list[str]) -> bool:
    """地名锚点匹配：允许「高阳县」对上标题里的「高阳」，也允许反过来。"""
    blob = text or ""
    for word in anchors:
        if word in blob:
            return True
        trimmed = word.rstrip(_PLACE_SUFFIX)
        if len(trimmed) >= 2 and trimmed in blob:
            return True
    return False


def select_relevant(event_content: str, rows: list[dict], keywords: list[str]) -> tuple[list[dict], str]:
    """从候选里挑出确实在讲本事件的视频。模型优先，失败退回锚点规则。"""
    if not rows:
        return [], "empty"

    listing = "\n".join(
        f"{index}|{(row.get('title') or '')[:50]}" for index, row in enumerate(rows, start=1)
    )
    try:
        result = call_deepseek_json(
            prompt=FILTER_PROMPT.format(event=(event_content or "")[:400], rows=listing),
            system_prompt=FILTER_SYSTEM,
            temperature=0.1,
            max_tokens=400,
            request_type="opinion_pool_relevance",
        )
        keep = []
        for value in result.get("keep") or []:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= index <= len(rows):
                keep.append(index)
        picked = [rows[index - 1] for index in dict.fromkeys(keep)]
        anchors = _anchor_keywords(keywords, event_content)["anchors"]
        if anchors:
            picked = [
                row for row in picked
                if anchor_match(
                    row.get("title", "") + " " + row.get("description", ""), anchors
                )
            ]
        return picked, "llm+anchor"
    except Exception:  # noqa: BLE001 - 模型不可用时退回规则
        pass

    groups = _anchor_keywords(keywords, event_content)
    kept = []
    for row in rows:
        blob = f"{row.get('title', '')} {row.get('description', '')}"
        anchor_hit = anchor_match(blob, groups["anchors"])
        support_hits = sum(1 for word in groups["supports"] if word in blob)
        if anchor_hit or support_hits >= 2:
            kept.append(row)
    return kept, "heuristic"


def relevance_hits(title: str, description: str, keywords: list[str]) -> int:
    """候选与事件的相关性：命中的关键词个数。"""
    blob = f"{title or ''} {description or ''}"
    return sum(1 for word in keywords if word and word in blob)


def _score_video(row: dict, now: float) -> float:
    age_h = max(0.0, (now - (row.get("pubdate") or 0)) / 3600)
    fresh = math.exp(-age_h / 72) if age_h else 0.5
    play = min(1.0, math.log10(1 + row.get("play", 0)) / 7)
    reply = min(1.0, math.log10(1 + row.get("reply", 0)) / 5)
    like = min(1.0, math.log10(1 + row.get("like", 0)) / 6)
    return 0.35 * play + 0.30 * reply + 0.20 * fresh + 0.15 * like


def collect(event_input: dict, sample_size: int, config: dict) -> tuple[list[dict], dict]:
    """检索 → 定帖 → 抓评论 → 清洗 → 按派系配额采样。返回 (采样评论, 采集元信息)。"""
    score, BiliClient, BiliError, MODE_HOT, MODE_NEW = _shared()

    client = BiliClient(qps=float(config.get("qps", 1.2)))
    event_content = event_input.get("event_content", "")
    queries, keywords, plan_source = plan_retrieval(event_content, config)
    if not queries:
        raise HarvestError("无法从事件正文生成检索式，请用 opinion_pool.harvest.queries 指定")

    def search_round(search_queries: list[str]) -> dict[str, dict]:
        seen: dict[str, dict] = {}
        for query in search_queries:
            try:
                for row in client.search_videos(query, pages=1):
                    if row.get("bvid") and row["bvid"] not in seen:
                        seen[row["bvid"]] = row
            except BiliError:
                continue
        return seen

    attempts: list[dict] = []
    videos: list[dict] = []
    seen: dict[str, dict] = {}
    filter_source = "none"
    # 第一轮用精确检索式；没找到就自动放宽一次（县级地名 → 市级地名，保留核心动作）
    for attempt in (1, 2):
        if attempt == 2:
            queries, keywords, plan_source = plan_retrieval(
                event_content, config, attempt=2, previous=queries
            )
        seen = search_round(queries)
        scored = []
        for row in seen.values():
            hits = relevance_hits(row.get("title", ""), row.get("description", ""), keywords)
            if hits:
                scored.append((hits, row))
        candidates = [row for _, row in sorted(scored, key=lambda item: -_score_video(item[1], time.time()))]
        picked, filter_source = select_relevant(event_content, candidates[:24], keywords)
        attempts.append(
            {
                "attempt": attempt,
                "queries": queries,
                "keywords": keywords,
                "hits": len(scored),
                "kept": len(picked),
                "query_plan": plan_source,
                "relevance_filter": filter_source,
            }
        )
        if picked:
            videos = picked
            break

    now = time.time()
    if not videos:
        raise HarvestError(
            f"两轮检索都没有找到在讲这个事件的视频（最后一组检索式：{'、'.join(queries)}）。"
            "采集式不适合站内没有对应讨论的事件，请改用生成式，"
            "或用 opinion_pool.harvest.queries 手工指定检索式。"
        )
    videos.sort(key=lambda row: -_score_video(row, now))
    videos = videos[: int(config.get("videos", 3))]
    for row in videos:
        row["relevance_hits"] = relevance_hits(row.get("title", ""), row.get("description", ""), keywords)

    target_raw = int(sample_size * float(config.get("expand_ratio", 1.5)))
    pool: dict[str, dict] = {}
    crawled: list[dict] = []
    for video in videos:
        if len(pool) >= target_raw:
            break
        bvid = video["bvid"]
        try:
            info = client.video_info(bvid)
            video.update({"aid": info["aid"], "view": info["view"], "reply_total": info["reply"]})
            rows = client.replies(info["aid"], bvid, mode=MODE_HOT,
                                  max_pages=int(config.get("hot_pages", 2)))
            rows += client.replies(info["aid"], bvid, mode=MODE_NEW,
                                   max_pages=int(config.get("new_pages", 1)))
        except BiliError as exc:
            crawled.append({"bvid": bvid, "error": str(exc)})
            continue
        for row in rows:
            row["url"] = f"https://www.bilibili.com/video/{bvid}"
            pool.setdefault(row["comment_id"], row)
        crawled.append({"bvid": bvid, "title": video.get("title", "")[:60], "raw": len(rows)})

    cleaned, clean_stats = score.clean_comments(pool.values(), min_chars=8)
    sampled, faction_stats = balance_sample(
        cleaned, target_raw, min_each=MIN_PER_FACTION, max_share=MAX_FACTION_SHARE
    )
    if not sampled:
        raise HarvestError("抓到的评论全部未通过清洗")

    meta = {
        "queries": queries,
        "keywords": keywords,
        "retrieval_attempts": attempts,
        "relevance_filter": filter_source,
        "videos": [
            {
                "bvid": v["bvid"],
                "title": v.get("title", "")[:60],
                "play": v.get("play"),
                "reply": v.get("reply_total") or v.get("reply"),
                "hotness": round(_score_video(v, now), 3),
                "relevance_hits": v.get("relevance_hits"),
            }
            for v in videos
        ],
        "crawled": crawled,
        "raw_comments": len(pool),
        "clean": clean_stats,
        "faction_available": faction_stats["available"],
        "http_calls": client.calls,
        "platform": PLATFORM,
    }
    return sampled, meta


# --------------------------------------------------------------------------
# 标注
# --------------------------------------------------------------------------


def _parse_tags(raw_tags, comments_len: int, clusters_len: int) -> list[list[int]]:
    """把模型返回的元组规整成 5 元组；自动纠正 1 基编号。"""
    if len(raw_tags) != comments_len:
        raise ValueError(f"标注结果长度不匹配：{len(raw_tags)} != {comments_len}")

    rows: list[list[int]] = []
    for tag in raw_tags:
        if not isinstance(tag, (list, tuple)) or len(tag) < 4:
            raise ValueError("标注元组格式不正确")
        rows.append([int(x) for x in tag[:5]] + [1] * max(0, 5 - len(tag)))

    # 议题编号若整体落在 1..N，说明模型用了 1 基编号，整体左移一位
    cluster_ids = [row[0] for row in rows]
    if clusters_len and min(cluster_ids) >= 1 and max(cluster_ids) == clusters_len:
        for row in rows:
            row[0] -= 1

    out: list[list[int]] = []
    for cluster, sentiment, stance, orientation, relevance in rows:
        out.append([
            min(max(cluster, 0), max(0, clusters_len - 1)),
            min(max(sentiment, 0), 2),
            min(max(stance, 0), 3),
            min(max(orientation, 0), 2),
            1 if relevance else 0,
        ])
    return out


def label(comments: list[dict], event_content: str, config: dict) -> tuple[list[list[int]], list[str], str]:
    """一次请求完成全部标注。返回 (5 元组列表, 议题名列表, 标注方式)。"""
    if not comments:
        return [], [], "empty"

    rows = "\n".join(f"{i}|{c['text'][:70]}" for i, c in enumerate(comments, start=1))
    prompt = config.get("prompt") or LABEL_PROMPT.format(
        event=event_content[:400], rows=rows, count=len(comments)
    )
    try:
        result = call_deepseek_json(
            prompt=prompt,
            system_prompt=LABEL_SYSTEM,
            temperature=0.2,
            max_tokens=3000,
            request_type="opinion_pool_labeling",
        )
        clusters = [str(x).strip() for x in (result.get("clusters") or []) if str(x).strip()]
        if not clusters:
            raise ValueError("标注结果缺少 clusters")
        tags = _parse_tags(result.get("tags") or [], len(comments), len(clusters))
        return tags, clusters, "llm"
    except Exception:  # noqa: BLE001 - 模型失败时降级为规则标注，不阻塞实验
        return _label_by_rules(comments)


_NEG = ("失望", "愤怒", "气愤", "离谱", "恶心", "垃圾", "骗", "坑", "暴民", "该抓", "过分",
        "没素质", "素质", "追责", "问责", "敷衍", "不作为", "瞒", "甩锅", "心疼", "可怜",
        "不敢", "拒载", "风评", "口碑", "乱")
_POS = ("支持", "感谢", "点赞", "理性", "冷静", "依法", "及时", "负责", "辛苦了", "不错")


def _label_by_rules(comments: list[dict]) -> tuple[list[list[int]], list[str], str]:
    clusters = ["谴责围堵", "地域争论", "同情司机", "城市治理", "玩梗其他"]
    tags: list[list[int]] = []
    for item in comments:
        text = item.get("text", "")
        if any(w in text for w in ("司机", "大叔", "师傅", "可怜", "心疼")):
            cluster = 2
        elif any(w in text for w in ("地域", "武汉人", "湖北", "以偏概全", "刻板印象", "哪里都有")):
            cluster = 1
        elif any(w in text for w in ("管理", "交通", "政府", "罚", "整治", "交警")):
            cluster = 3
        elif any(w in text for w in ("暴民", "围堵", "砸", "扔", "放气", "过分", "违法")):
            cluster = 0
        else:
            cluster = 4
        neg = sum(1 for w in _NEG if w in text)
        pos = sum(1 for w in _POS if w in text)
        sentiment = 0 if pos > neg else (2 if neg > pos else 1)
        stance = 3 if sentiment == 2 else (0 if sentiment == 0 else 2)
        tags.append([cluster, sentiment, stance, 1 if sentiment != 1 else 0, 1])
    return tags, clusters, "rule"


# --------------------------------------------------------------------------
# 组装评论池
# --------------------------------------------------------------------------


def _slug(index: int) -> str:
    return f"harvest_{index + 1}"


def build_angle_plan(clusters: list[str], event_input: dict) -> tuple[dict, list[str]]:
    """把议题名转成角度计划，并用生成式校验器规范化。

    采集式的角度来自真实语料归纳，但下游（增量生成）是用生成式的
    ``validate_event_angle_plan`` 读它的，字段口径必须完全一致：
    ``angle_id / angle_name / focus / evidence_text``，且 evidence_text
    必须是事件正文原文片段。这里直接调同一个校验器，避免再次手写字段漂移。
    """
    content = str(event_input.get("event_content") or "").strip()
    if not content:
        raise HarvestError("事件正文为空，无法生成讨论角度")
    evidence = content[:40]

    labels: list[str] = []
    seen: set[str] = set()
    for index, name in enumerate(clusters):
        label = (name or "其他").strip()[:16] or "其他"
        if label in seen:
            label = f"{label}-{index + 1}"[:16]
        seen.add(label)
        labels.append(label)

    raw = {
        "angles": [
            {
                "angle_id": _slug(i),
                "angle_name": label,
                "focus": f"{label}（采集自{PLATFORM}真实评论）",
                "evidence_text": evidence,
            }
            for i, label in enumerate(labels)
        ]
    }
    try:
        plan = validate_event_angle_plan(raw, event_input)
    except ValueError as exc:
        raise HarvestError(f"采集的角度计划未通过校验：{exc}") from exc
    plan["generation_method"] = "web_harvest_angle_plan"
    return plan, labels


def assemble(
    event_input: dict,
    comments: list[dict],
    tags: list[list[int]],
    clusters: list[str],
    meta: dict,
    method: str,
    comment_count: int,
) -> dict:
    """剔除非相关评论 → 二次按派系配额取样 → 拼成与生成式同构的评论池。"""
    joined = list(zip(comments, tags))
    relevant_pairs = [pair for pair in joined if pair[1][4] == 1]
    pool_pairs = relevant_pairs or joined

    # 相关性过滤会打乱派系配比，这里做第二次配额采样，保证最终池的派系结构
    candidates = []
    for comment, tag in pool_pairs:
        comment = dict(comment)
        comment.setdefault("faction", classify(comment.get("text", "")))
        candidates.append((comment, tag))
    picked, faction_stats = balance_sample(
        [comment for comment, _ in candidates], comment_count,
        min_each=MIN_PER_FACTION, max_share=MAX_FACTION_SHARE,
    )
    tag_by_id = {comment["comment_id"]: tag for comment, tag in candidates}
    kept = [
        (item, tag_by_id[item["comment_id"]])
        for item in picked
        if item["comment_id"] in tag_by_id
    ][:comment_count]
    dropped = len(joined) - len(relevant_pairs)

    angle_plan, labels = build_angle_plan(clusters, event_input)

    result = []
    for index, (comment, tag) in enumerate(kept, start=1):
        cluster_id, sentiment_id, stance_id, orientation_id, _ = tag
        cluster_name = labels[cluster_id] if 0 <= cluster_id < len(labels) else "其他"
        task_id = f"harvest_{index:03d}"
        result.append(
            {
                "comment_id": f"comment_{index:03d}",
                "task_id": task_id,
                "angle_id": _slug(cluster_id),
                "angle_name": cluster_name,
                "angle_focus": f"{cluster_name}（采集自{PLATFORM}真实评论）",
                "text": comment["text"],
                "profile_id": None,
                "profile_label": "真实网民",
                "topic": cluster_name,
                "emotion": EMOTIONS[sentiment_id],
                "faction": comment.get("faction") or FACTIONS[4],
                "orientation": ORIENTATIONS[orientation_id],
                "stance": STANCES[stance_id],
                "introduced_step": 1,
                "generation_trigger": "initial_event",
                "source_type": "web_harvest",
                "provenance_type": f"{PLATFORM}_public_comment",
                "information_source_type": "public",
                "information_origin": "exogenous",
                "reaction_target": "event_harm",
                "evidence_role": "opinion",
                "claim_id": None,
                "root_id": task_id,
                # 采集特有字段：保留溯源信息，便于审计与复现
                "source_platform": PLATFORM,
                "source_url": comment.get("url", ""),
                "source_comment_id": comment.get("comment_id"),
                "source_likes": comment.get("likes", 0),
                "sampling_channel": comment.get("sampling_channel"),
            }
        )

    counts = Counter(item["faction"] for item in result)
    return {
        "event_id": event_input["event_id"],
        "generation_method": "web_harvest_labeled",
        "profile_source": "public_commenters",
        "requested_comment_count": len(result),
        "angle_plan": angle_plan,
        "faction_coverage": {
            "minimum_per_faction": MIN_PER_FACTION,
            "max_share": MAX_FACTION_SHARE,
            "counts": dict(counts),
            "available": faction_stats["available"],
            "quota": faction_stats["quota"],
            "short": faction_stats["short"],
            "complete": faction_stats["complete"],
            "note": "派系由文本特征判定，配额靠采样满足；与生成式的人物类型配额不是同一口径",
        },
        "harvest": {
            **meta,
            "labeling": method,
            "labeled": len(tags),
            "irrelevant_dropped": dropped,
            "labeled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": "评论来自平台公开接口，已去除用户标识，仅保留点赞数与来源链接",
        },
        "comments": result,
    }


def harvest_comment_pool(event_input: dict, comment_count: int, config: dict) -> dict:
    """对外入口：采集 + 标注 + 组装。"""
    comments, meta = collect(event_input, comment_count, config)
    tags, clusters, method = label(comments, event_input.get("event_content", ""), config)
    if len(tags) != len(comments):
        tags, clusters, method = _label_by_rules(comments)
    return assemble(event_input, comments, tags, clusters, meta, method, comment_count)
