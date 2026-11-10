# -*- coding: utf-8 -*-
"""试跑采集式初始舆论池：检索 → 抓取 → 标注 → 组装 → 校验。

用法：
    py backend/scripts/try_harvest_pool.py --count 40
    py backend/scripts/try_harvest_pool.py --count 40 --videos 2 --out var/state/harvest_pool.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.comments.opinion_pool import build_initial_comment_pool, normalize_opinion_pool_config
from app.comments.repository import load_comment_pool
from app.infrastructure.llm.llm_service import get_llm_performance_stats

DEFAULT_EVENT = {
    "event_id": "event_wuhan_halloween_rideshare_20261101",
    "event_content": (
        "2026年11月1日，武汉江汉路万圣节活动中，一位网约车司机接单后误入人流密集路段，"
        "车辆被困车道难以挪动。司机被狂欢人群围堵数小时，期间遭扔垃圾、车胎放气、车身涂鸦，"
        "司机在驾驶室内情绪崩溃。事后警方通报，1人被行政处罚，其余人员被训诫。"
        "事件发酵后，讨论迅速转向武汉城市形象与地域评价。"
    ),
    "event_labels": {"topic": "社会事件", "event_valence": "negative"},
}


def token_delta(before, after):
    keys = ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens",
            "logical_request_count")
    return {key: after.get(key, 0) - before.get(key, 0) for key in keys}


def main() -> int:
    parser = argparse.ArgumentParser(description="试跑采集式初始舆论池")
    parser.add_argument("--count", type=int, default=40, help="目标评论条数")
    parser.add_argument("--videos", type=int, default=3, help="定帖数量")
    parser.add_argument("--hot-pages", type=int, default=2)
    parser.add_argument("--new-pages", type=int, default=1)
    parser.add_argument("--event-file", type=Path, default=None, help="读取现成的 event_input.json")
    parser.add_argument("--out", type=Path, default=PROJECT_DIR / "var" / "state" / "harvest_pool.json")
    args = parser.parse_args()

    event = (
        json.loads(args.event_file.read_text(encoding="utf-8"))
        if args.event_file
        else DEFAULT_EVENT
    )
    config = normalize_opinion_pool_config(
        {
            "source": "harvest",
            "harvest": {
                "comment_count": args.count,
                "videos": args.videos,
                "hot_pages": args.hot_pages,
                "new_pages": args.new_pages,
            },
        }
    )

    print(f"事件：{event['event_id']}")
    print(f"目标：采集 {args.count} 条，最多 {args.videos} 个帖子\n")

    before = get_llm_performance_stats()
    started = time.time()
    pool = build_initial_comment_pool(event, config)
    elapsed = time.time() - started
    delta = token_delta(before, get_llm_performance_stats())

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")

    load_comment_pool(args.out)  # 用生产校验器验证结构

    harvest = pool.get("harvest", {})
    print(f"产出：{args.out}")
    print(f"评论 {pool['requested_comment_count']} 条 / 角度 {len(pool['angle_plan']['angles'])} 个")
    print(f"抓取：原始 {harvest.get('raw_comments')} 条 → 清洗 {harvest.get('clean', {}).get('kept')} 条")
    coverage = pool.get("faction_coverage", {})
    print(f"派系配额：{json.dumps(coverage.get('quota'), ensure_ascii=False)}")
    print(f"派系实得：{json.dumps(coverage.get('counts'), ensure_ascii=False)}；"
          f"候选池：{json.dumps(coverage.get('available'), ensure_ascii=False)}")
    if coverage.get("short"):
        print(f"未达下限：{json.dumps(coverage['short'], ensure_ascii=False)}（真实语料不足，未编造）")
    print(f"标注方式：{harvest.get('labeling')}")
    print(f"HTTP 请求：{harvest.get('http_calls')} 次")
    print(f"耗时：{elapsed:.1f} 秒")
    print(f"token：输入 {delta['prompt_tokens']:,} / 输出 {delta['completion_tokens']:,} / "
          f"合计 {delta['total_tokens']:,}（缓存 {delta['cached_tokens']:,}，"
          f"{delta['logical_request_count']} 次调用）")

    miss = delta["prompt_tokens"] - delta["cached_tokens"]
    usd = (miss * 0.15 + delta["cached_tokens"] * 0.003 + delta["completion_tokens"] * 0.60) / 1e6
    print(f"模型费：${usd:.4f} ≈ ¥{usd * 7.1:.4f}")

    factions = {}
    for comment in pool["comments"]:
        factions[comment["faction"]] = factions.get(comment["faction"], 0) + 1
    print(f"派系分布：{json.dumps(factions, ensure_ascii=False)}")
    print("结构校验：通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
