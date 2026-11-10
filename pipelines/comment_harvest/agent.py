# -*- coding: utf-8 -*-
"""事件评论采集 Agent（B 站版，真实抓取）。

流程：事件 → 多路检索 → 候选合并与热度打分 → 定帖 → 评论抓取（热评+最新+楼中楼）
→ 清洗 → 分层采样 → 情感与议题分析 → 报告 → 账单。

用法：
    py pipelines/comment_harvest/agent.py --event "武汉万圣节网约车"
    py pipelines/comment_harvest/agent.py --event "..." --comments 100 --videos 4 --qps 1.2
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipelines.comment_harvest import prompts, score
from pipelines.comment_harvest.bili import BiliClient, BiliError, MODE_HOT, MODE_NEW
from pipelines.comment_harvest.llm import CostTracker, estimate_tokens

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "var" / "comment_harvest"

# 事件专用词表（规则模式用；接入大模型后由模型自行归纳，不再依赖此表）
EXTRA_NEG = (
    "暴民", "土匪", "流氓", "畜生", "人渣", "该抓", "拘留", "判刑", "违法", "寻衅滋事",
    "故意毁坏", "过分", "嚣张", "恶劣", "没素质", "素质差", "缺德", "可耻", "耻辱",
    "心疼", "可怜", "委屈", "无辜", "崩溃", "欺负", "欺负人", "欺负老实人",
)
EXTRA_POS = ("理性", "冷静", "克制", "依法", "支持警方", "处理得当", "点赞")

# 立场判定：这批语料的真实结构不是「褒/贬」，而是「替武汉辩护 / 批评武汉 / 玩梗」，
# 因此主维度用立场，情感只作辅助。规则按优先级从强到弱排列，先命中者胜。
STANCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("谴责围堵行为", ("暴民", "围堵", "砸", "扔垃圾", "放气", "涂鸦", "过分", "违法",
                  "该抓", "拘留", "寻衅滋事", "故意毁坏", "无法无天")),
    ("同情司机", ("司机", "大叔", "师傅", "心疼", "可怜", "不容易", "绷住", "崩溃",
              "老实人", "放过")),
    ("反驳地域黑", ("以偏概全", "一概而论", "刻板印象", "哪里都有", "别地域黑", "就事论事",
                "网暴", "霸凌", "不能代表", "一竿子", "理性", "地域黑", "以点概面",
                "没有网上传的", "幸存者偏差", "哪个城市没有", "见不得")),
    ("玩梗嘲讽", ("典", "绷", "笑死", "笑", "doge", "梗", "节目效果", "抽象", "难绷",
              "离谱", "赢", "好活", "乐子", "神人")),
    ("批评城市形象", ("确实是", "是这样的", "印象差", "拒载", "不打表", "闯红灯", "交通",
                 "素质", "不敢去", "不去", "现身说法", "风评", "口碑", "老鼠屎",
                 "见怪不怪", "受不了", "失望", "乱", "管理")),
    ("其他/未归类", ()),
)


# --------------------------------------------------------------------------
# 打分
# --------------------------------------------------------------------------


def hotness(video: dict, tau_hours: float = 72.0) -> dict:
    age_h = max(0.0, (time.time() - (video.get("pubdate") or 0)) / 3600)
    fresh = math.exp(-age_h / tau_hours) if age_h else 0.5
    views = int(video.get("view") or video.get("play") or 0)
    replies = int(video.get("reply_total") or video.get("reply") or 0)
    likes = int(video.get("like") or 0)
    play = min(1.0, math.log10(1 + views) / 7)
    reply = min(1.0, math.log10(1 + replies) / 5)
    like = min(1.0, math.log10(1 + likes) / 6)
    total = 0.35 * play + 0.30 * reply + 0.20 * fresh + 0.15 * like
    return {
        "hotness": round(total, 4),
        "play_n": round(play, 3),
        "reply_n": round(reply, 3),
        "like_n": round(like, 3),
        "fresh_n": round(fresh, 3),
        "age_hours": round(age_h, 1),
    }


# --------------------------------------------------------------------------
# 清洗
# --------------------------------------------------------------------------

_AT_RE = re.compile(r"回复\s*@[^:：]*[:：]?")
_EMOJI_RE = re.compile(r"\[[^\[\]]{1,6}\]")
_SPACE_RE = re.compile(r"\s+")


def clean_text(text: str) -> str:
    text = _AT_RE.sub("", text or "")
    text = _EMOJI_RE.sub(" ", text)
    text = text.replace("//@", " ")
    return _SPACE_RE.sub(" ", text).strip()


def sentiment_of(text: str) -> str:
    pos = sum(1 for w in score.POS_WORDS + EXTRA_POS if w in text)
    neg = sum(1 for w in score.NEG_WORDS + EXTRA_NEG if w in text)
    if pos > neg and pos >= 1:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def cluster_of(text: str) -> str:
    for label, words in STANCES:
        if any(w in text for w in words):
            return label
    return STANCES[-1][0]


_TERM_STOP = {
    "一个", "什么", "自己", "这个", "那个", "出来", "没有", "知道", "就是", "不是",
    "可以", "觉得", "现在", "还是", "真的", "已经", "应该", "因为", "所以", "但是",
    "如果", "这样", "那样", "我们", "你们", "他们", "这地", "地方", "事情", "问题",
    "时候", "东西", "感觉", "确实", "其实", "而且", "然后", "看到", "说的", "来说",
}


def top_terms(texts: list[str], k: int = 15) -> list[tuple[str, int]]:
    """数据驱动的词频：统计 2~4 字子串，取高频且互不包含的。"""
    counter: Counter[str] = Counter()
    for text in texts:
        runs = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        for run in runs:
            for size in (2, 3, 4):
                for i in range(len(run) - size + 1):
                    term = run[i:i + size]
                    if term in _TERM_STOP or any(ch in term for ch in "的了是在和与"):
                        continue
                    counter[term] += 1
    picked: list[tuple[str, int]] = []
    for term, n in counter.most_common(600):
        if n < 4 or term in _TERM_STOP:
            break
        if any(term in kept or kept in term for kept, _ in picked):
            continue
        picked.append((term, n))
        if len(picked) >= k:
            break
    return picked


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


class Agent:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.client = BiliClient(qps=args.qps)
        self.tracker = CostTracker(model="deepseek-chat", peak=False)
        self.started = time.time()
        self.notes: list[str] = []
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", args.event)[:24]
        self.out = Path(args.out) / f"{slug}_{stamp}"
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "llm_prompts").mkdir(exist_ok=True)

    # -- 工具 ---------------------------------------------------------------

    def save(self, name: str, payload) -> None:
        (self.out / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def stage_tokens(self, stage: str, system: str, user: str, skeleton: str) -> None:
        """记录该阶段在真实输入下的 token 预估（无 Key 时无法实测，只能按文本折算）。"""
        prompt = f"{system}\n\n{user}"
        self.tracker.record(stage, prompt, skeleton, usage=None, source="estimated")
        (self.out / "llm_prompts" / f"{stage.split()[0].lower()}_{stage.split()[-1]}.txt").write_text(
            prompt, encoding="utf-8"
        )

    # -- [1] 检索 -----------------------------------------------------------

    def discover(self) -> list[dict]:
        queries = self.args.queries or [
            self.args.event,
            f"{self.args.event} 司机",
            f"{self.args.event} 处理结果",
            f"{self.args.event} 官方通报",
        ]
        seen: dict[str, dict] = {}
        for q in queries:
            try:
                rows = self.client.search_videos(q, pages=self.args.search_pages)
            except BiliError as exc:
                self.notes.append(f"检索失败（{q}）：{exc}")
                continue
            for row in rows:
                bvid = row.get("bvid")
                if not bvid:
                    continue
                if bvid in seen:
                    seen[bvid]["matched"].append(q)
                    continue
                row["matched"] = [q]
                seen[bvid] = row
            print(f"      「{q}」→ {len(rows)} 条")
        return list(seen.values())

    # -- [2] 定帖 -----------------------------------------------------------

    def select_videos(self, candidates: list[dict]) -> list[dict]:
        relevant = [
            c for c in candidates
            if score.keyword_hits(c["title"] + c["description"], ["网约车", "万圣", "武汉", "司机"]) >= 1
        ]
        for c in relevant:
            c.update(hotness(c))
        relevant.sort(key=lambda c: -c["hotness"])
        return relevant[: self.args.videos]

    # -- [3] 抓评论 ---------------------------------------------------------

    def harvest(self, videos: list[dict]) -> list[dict]:
        pool: list[dict] = []
        for video in videos:
            try:
                info = self.client.video_info(video["bvid"])
            except BiliError as exc:
                self.notes.append(f"视频信息失败 {video['bvid']}：{exc}")
                continue
            video.update({"aid": info["aid"], "view": info["view"], "reply_total": info["reply"],
                          "owner": info["owner"], "url": info["url"]})
            try:
                hot = self.client.replies(info["aid"], video["bvid"], mode=MODE_HOT, max_pages=self.args.hot_pages)
                latest = self.client.replies(info["aid"], video["bvid"], mode=MODE_NEW, max_pages=self.args.new_pages)
            except BiliError as exc:
                self.notes.append(f"评论失败 {video['bvid']}：{exc}")
                continue
            merged = {c["comment_id"]: c for c in hot + latest}
            # 楼中楼：只对热评里回复较多的补采，成本可控
            for comment in hot:
                if comment["rcount"] >= 5:
                    try:
                        subs = self.client.sub_replies(info["aid"], video["bvid"], comment["comment_id"].split(":")[-1], limit=8)
                    except BiliError:
                        continue
                    for sub in subs:
                        merged.setdefault(sub["comment_id"], sub)
            video["harvested"] = len(merged)
            pool.extend(merged.values())
            print(f"      {video['bvid']}（{info['reply']} 条评论）→ 采集 {len(merged)}")
        return pool

    # -- [4] 清洗采样 -------------------------------------------------------

    def prepare(self, raw: list[dict]) -> tuple[list[dict], dict]:
        for item in raw:
            item["text_raw"] = item["text"]
            item["text"] = clean_text(item["text"])
        cleaned, stats = score.clean_comments(raw, min_chars=6)
        sampled, sample_stats = score.stratified_sample(cleaned, self.args.comments, per_post_min=20)
        return sampled, {"clean": stats, "sample": sample_stats, "raw": len(raw)}

    # -- [5] 分析 -----------------------------------------------------------

    def analyze(self, sampled: list[dict], event_summary: str) -> dict:
        for item in sampled:
            item["sentiment"] = sentiment_of(item["text"])
            item["cluster"] = cluster_of(item["text"])

        by_label: dict[str, list[dict]] = {}
        for item in sampled:
            by_label.setdefault(item["cluster"], []).append(item)

        themes = []
        total_likes = sum(i["likes"] for i in sampled) or 1
        for label, rows in sorted(by_label.items(), key=lambda kv: -len(kv[1])):
            mix = Counter(r["sentiment"] for r in rows)
            total = len(rows)
            quotes = sorted(rows, key=lambda r: -r["likes"])[:3]
            themes.append(
                {
                    "label": label,
                    "n": total,
                    "share": round(total / len(sampled), 3),
                    "likes_share": round(sum(r["likes"] for r in rows) / total_likes, 3),
                    "sentiment_mix": {k: round(mix.get(k, 0) / total, 3) for k in ("positive", "neutral", "negative")},
                    "mean_likes": round(statistics.mean(r["likes"] for r in rows), 1),
                    "quotes": [{"comment_id": q["comment_id"], "text": q["text"][:100],
                                "likes": q["likes"]} for q in quotes],
                }
            )
        # 未归类是残差，排到最后，避免它占据头条位置
        residual = STANCES[-1][0]
        themes.sort(key=lambda t: (t["label"] == residual, -t["n"]))

        shares = {
            k: round(sum(1 for i in sampled if i["sentiment"] == k) / max(1, len(sampled)), 3)
            for k in ("negative", "neutral", "positive")
        }
        stance_shares = {
            label: round(sum(1 for i in sampled if i["cluster"] == label) / max(1, len(sampled)), 3)
            for label, _ in STANCES
        }
        return {
            "themes": themes,
            "shares": shares,
            "stance_shares": stance_shares,
            "top_terms": top_terms([i["text"] for i in sampled]),
            "event_summary": event_summary,
        }

    # -- [6] 产出 -----------------------------------------------------------

    def build_cost(self, analysis: dict, sampled: list[dict], videos: list[dict]) -> dict:
        summary = self.tracker.summary()
        # 检索走平台公开接口，无检索费；只保留模型费
        summary["retrieval_usd"] = 0.0
        summary["notes"] = [
            "检索与评论抓取全部走 B 站公开接口，按请求计费为 0。",
            "无 API Key，未实际调用模型；输入 token 按真实提示词折算（0.6 token/汉字）。",
        ]
        return summary

    def run(self) -> int:
        t0 = time.time()
        if self.args.reuse:
            base = Path(self.args.reuse)
            raw = json.loads((base / "comments_raw.json").read_text(encoding="utf-8"))
            videos = json.loads((base / "posts.json").read_text(encoding="utf-8"))
            candidates = json.loads((base / "candidates.json").read_text(encoding="utf-8"))
            print(f"[1-3/6] 复用 {base.name}：{len(raw)} 条评论 / {len(videos)} 个帖子")
        else:
            print(f"[1/6] 检索候选：{self.args.event}")
            candidates = self.discover()
            print(f"      去重后 {len(candidates)} 个视频")

            print("[2/6] 热度打分与定帖")
            videos = self.select_videos(candidates)
            for v in videos:
                print(f"      {v['hotness']:.3f}  {v['bvid']}  play={v['play']:>7} reply={v['reply']:>5}  {v['title'][:32]}")
            if not videos:
                print("没有相关视频，终止。", file=sys.stderr)
                return 2

            print("[3/6] 抓取评论")
            raw = self.harvest(videos)
        if not raw:
            print("没有抓到评论，终止。", file=sys.stderr)
            return 2

        print("[4/6] 清洗与分层采样")
        sampled, stats = self.prepare(raw)
        print(f"      原始 {len(raw)} → 清洗 {stats['clean']['kept']} → 采样 {len(sampled)}")

        print("[5/6] 情感与议题分析")
        analysis = self.analyze(sampled, self.args.event)

        print("[6/6] 产出")
        # 账单：用真实输入构造各阶段提示词并折算 token
        card_sys, card_user = prompts.build_event_card(self.args.event, ["bilibili"], str(datetime.now().date()))[1:]
        self.stage_tokens("S1 事件结构化", card_sys, card_user,
                          json.dumps({"summary": "…", "keywords_zh": ["…"] * 6, "queries": ["…"] * 5}, ensure_ascii=False))

        rank_candidates = [
            {"title": v["title"], "site": "bilibili.com", "snippet": v["description"], "source": "search",
             "engagement": {"likes": v.get("like", 0), "comments": v.get("reply", 0)}}
            for v in videos
        ]
        rank_sys, rank_user = prompts.build_rank(self.args.event, rank_candidates, min(4, len(videos)))[1:]
        self.stage_tokens("S2 候选精排", rank_sys, rank_user,
                          json.dumps({"picked": [{"id": 0, "reason": "…", "expected_comment_volume": "high"}] * 4}, ensure_ascii=False))

        batches = [sampled[i:i + self.args.batch] for i in range(0, len(sampled), self.args.batch)]
        for idx, batch in enumerate(batches, start=1):
            tag_sys, tag_user = prompts.build_tag(self.args.event, batch, [])[1:]
            skeleton = json.dumps({"comments": [{"id": "…", "cluster": "…", "sentiment": "negative",
                                                 "stance": "oppose", "intensity": 0.8,
                                                 "is_noise": False}] * len(batch)}, ensure_ascii=False)
            self.stage_tokens(f"S6 评论理解#{idx}", tag_sys, tag_user, skeleton)

        quote_pool = [{"comment_id": i["comment_id"], "text": i["text"][:80], "likes": i["likes"]}
                      for i in sorted(sampled, key=lambda x: -x["likes"])[:40]]
        merge_sys, merge_user = prompts.build_merge(self.args.event, sampled, quote_pool)[1:]
        self.stage_tokens("S7 全局归并", merge_sys, merge_user,
                          json.dumps({"themes": [{"label": "…", "n": 0, "sentiment_mix": {}, "argument": "…",
                                                  "quotes": ["…"]}] * 6}, ensure_ascii=False))

        rep_sys, rep_user = prompts.build_report(self.args.event, videos, analysis["themes"],
                                                 analysis["shares"], stats, quote_pool)[1:]
        self.stage_tokens("S8 报告", rep_sys, rep_user,
                          json.dumps({"summary": "…" * 60, "sections": [{"heading": "…", "body": "…" * 200}] * 4,
                                      "claims": [{"claim": "…", "evidence": ["…"], "confidence": 0.6}] * 5,
                                      "caveats": ["…"] * 2}, ensure_ascii=False))

        ver_sys, ver_user = prompts.build_verify({"claims": []}, quote_pool)[1:]
        self.stage_tokens("S9 引用自检", ver_sys, ver_user,
                          json.dumps({"checks": [{"claim": "…", "supported": True, "why": "…"}] * 5,
                                      "unsupported_count": 0}, ensure_ascii=False))

        cost = self.build_cost(analysis, sampled, videos)
        cost["elapsed_sec"] = round(time.time() - t0, 1)
        cost["http_calls"] = self.client.calls

        self.save("candidates.json", candidates)
        self.save("posts.json", videos)
        self.save("comments_raw.json", raw)
        self.save("comments.json", sampled)
        self.save("analysis.json", analysis)
        self.save("cost.json", cost)
        self.write_report(videos, sampled, analysis, stats, cost)

        print(f"\n产物：{self.out}")
        print(f"HTTP 请求 {self.client.calls} 次，耗时 {cost['elapsed_sec']}s")
        print(f"token 预估 {cost['total_tokens']:,}（输入 {cost['prompt_tokens']:,} / 输出 {cost['completion_tokens']:,}）")
        print(f"模型费 ${cost['cost_usd']:.4f} ≈ ¥{cost['cost_cny']:.2f}")
        for note in self.notes[:5]:
            print(f"  ! {note}")
        return 0

    def write_report(self, videos, sampled, analysis, stats, cost) -> None:
        lines = [f"# 事件评论采集报告：{self.args.event}", ""]
        lines.append(f"采集时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　·　"
                     f"样本 {len(sampled)} 条 / 清洗后 {stats['clean']['kept']} 条 / 原始 {stats['raw']} 条")
        lines.append("")
        lines.append("## 一、样本与口径")
        lines.append("")
        lines.append(f"- 检索式：{'、'.join(self.args.queries or [self.args.event])}")
        lines.append(f"- 候选视频 {len(videos)} 个，共 {sum(v.get('reply_total', 0) for v in videos):,} 条评论（平台计数）")
        lines.append(f"- 实际抓取 {stats['raw']} 条，清洗丢弃 {stats['raw'] - stats['clean']['kept']} 条"
                     f"（重复/广告/过短），保留 {stats['clean']['kept']} 条")
        lines.append(f"- 分层采样 {len(sampled)} 条：{json.dumps(stats['sample']['channels'], ensure_ascii=False)}")
        lines.append("")
        lines.append("## 二、立场分布（样本内）")
        lines.append("")
        lines.append("| 立场 | 条数 | 条数占比 | 赞数占比 | 平均赞 |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for theme in analysis["themes"]:
            lines.append(f"| {theme['label']} | {theme['n']} | {theme['share']:.1%} | "
                         f"{theme['likes_share']:.1%} | {theme['mean_likes']} |")
        lines.append("")
        lines.append("## 三、情感（辅助维度）")
        lines.append("")
        lines.append("| 情感 | 条数 | 占比 |")
        lines.append("| --- | ---: | ---: |")
        for key in ("negative", "neutral", "positive"):
            n = sum(1 for i in sampled if i["sentiment"] == key)
            lines.append(f"| {key} | {n} | {analysis['shares'][key]:.1%} |")
        lines.append("")
        lines.append("> 情感列为词表判定的辅助结果：该语料大量使用反讽、玩梗与地域辩论，"
                     "显式情绪词比例低，中性占比偏高属于已知偏差；线上应开启大模型打标（见第六节）。")
        lines.append("")
        lines.append("## 四、代表性评论")
        lines.append("")
        for theme in analysis["themes"][:5]:
            lines.append(f"### {theme['label']}（{theme['n']} 条）")
            lines.append("")
            for q in theme["quotes"]:
                lines.append(f"> {q['text']}　— 赞 {q['likes']}〔{q['comment_id']}〕")
                lines.append("")
        lines.append("## 五、高频词（数据驱动）")
        lines.append("")
        lines.append("　·　".join(f"{term}({n})" for term, n in analysis["top_terms"]))
        lines.append("")
        lines.append("## 六、帖子清单")
        lines.append("")
        for v in videos:
            lines.append(f"- [{v['title'][:40]}]({v.get('url', '')})　播放 {v.get('view', v.get('play', 0)):,}　"
                         f"评论 {v.get('reply_total', v.get('reply', 0)):,}　热度 {v['hotness']:.3f}")
        lines.append("")
        lines.append("## 七、本次消耗")
        lines.append("")
        lines.append(f"- HTTP 请求 {cost['http_calls']} 次，耗时 {cost['elapsed_sec']} 秒")
        lines.append(f"- token 预估 {cost['total_tokens']:,}（输入 {cost['prompt_tokens']:,} / 输出 {cost['completion_tokens']:,}）")
        lines.append(f"- 模型费 ${cost['cost_usd']:.4f} ≈ ¥{cost['cost_cny']:.2f}")
        lines.append("")
        lines.append(f"> {cost['notes'][1]}")
        (self.out / "report.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="事件评论采集 Agent（B 站）")
    p.add_argument("--event", required=True, help="事件描述或关键词")
    p.add_argument("--queries", nargs="*", help="自定义检索式，默认由事件派生 4 条")
    p.add_argument("--comments", type=int, default=100, help="目标样本条数")
    p.add_argument("--videos", type=int, default=4, help="定帖数量")
    p.add_argument("--hot-pages", type=int, default=3, help="按热度抓几页（20 条/页）")
    p.add_argument("--new-pages", type=int, default=2, help="按时间抓几页")
    p.add_argument("--search-pages", type=int, default=1)
    p.add_argument("--batch", type=int, default=50, help="打标批大小（影响 token 预估）")
    p.add_argument("--qps", type=float, default=1.2, help="请求间隔秒")
    p.add_argument("--reuse", help="复用某次运行的 comments_raw.json，跳过检索与抓取")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return Agent(parse_args(argv)).run()


if __name__ == "__main__":
    raise SystemExit(main())
