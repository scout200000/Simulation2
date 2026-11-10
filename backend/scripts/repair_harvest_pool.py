# -*- coding: utf-8 -*-
"""修复采集式评论池的角度计划（字段口径与生成式对齐）。

早期版本的采集式池子只写了 ``angle_focus`` 而没写 ``focus``，增量生成阶段用
``validate_event_angle_plan`` 读它会直接报「字段不完整」。本脚本用评论里已经
存在的角度名重建计划，不需要重新抓取，也不消耗模型额度。

用法：
    py backend/scripts/repair_harvest_pool.py --pool var/experiments/<批次>/comment_pool.json
    py backend/scripts/repair_harvest_pool.py --pool ... --in-place
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.comments.angle_planner import validate_event_angle_plan
from app.comments.repository import load_comment_pool
from app.comments.web_harvest import build_angle_plan


def repair(pool: dict, event_input: dict) -> tuple[dict, list[str]]:
    """用评论里现成的角度名重建 angle_plan，并回填评论的 angle_id。"""
    comments = pool.get("comments") or []
    if not comments:
        raise ValueError("评论池没有 comments，无法重建角度")

    names: list[str] = []
    for comment in comments:
        name = str(comment.get("angle_name") or comment.get("topic") or "").strip()
        if name and name not in names:
            names.append(name)
    if not names:
        raise ValueError("评论里没有可用的角度名（angle_name / topic 均为空）")

    # 旧 angle_id 与新角度按名字配对，保持同一议题的评论归到同一角度
    plan, labels = build_angle_plan(names, event_input)
    old_id_by_name = {}
    for comment in comments:
        name = str(comment.get("angle_name") or comment.get("topic") or "").strip()
        old_id_by_name.setdefault(name, comment.get("angle_id"))
    new_id_by_name = {angle["angle_name"]: angle["angle_id"] for angle in plan["angles"]}
    id_map = {old_id_by_name[name]: new_id_by_name[name] for name in labels if old_id_by_name.get(name)}

    changed = []
    for comment in comments:
        name = str(comment.get("angle_name") or comment.get("topic") or "").strip()
        label = name if name in new_id_by_name else labels[0]
        new_id = new_id_by_name[label]
        if comment.get("angle_id") != new_id:
            changed.append(f"{comment.get('comment_id')}: {comment.get('angle_id')} -> {new_id}")
        comment["angle_id"] = new_id
        comment["angle_name"] = label
        comment["angle_focus"] = f"{label}（采集自bilibili真实评论）"

    pool["angle_plan"] = plan
    return pool, changed


def main() -> int:
    parser = argparse.ArgumentParser(description="修复采集式评论池的角度计划")
    parser.add_argument("--pool", type=Path, required=True, help="comment_pool.json 路径")
    parser.add_argument("--event", type=Path, default=None,
                        help="event_input.json；默认读同目录下的 event_input.json")
    parser.add_argument("--in-place", action="store_true", help="直接覆盖原文件")
    parser.add_argument("--out", type=Path, default=None, help="输出路径，默认 <pool>.repaired.json")
    args = parser.parse_args()

    pool_path = args.pool
    event_path = args.event or (pool_path.parent / "event_input.json")
    if not pool_path.is_file():
        print(f"评论池不存在：{pool_path}", file=sys.stderr)
        return 1
    if not event_path.is_file():
        print(f"事件文件不存在：{event_path}（用 --event 指定）", file=sys.stderr)
        return 1

    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    event_input = json.loads(event_path.read_text(encoding="utf-8"))

    if pool.get("generation_method") != "web_harvest_labeled":
        print("这不是采集式评论池，无需修复。")
        return 0

    repaired, changed = repair(pool, event_input)
    validate_event_angle_plan(repaired["angle_plan"], event_input)

    target = pool_path if args.in_place else (args.out or pool_path.with_suffix(".repaired.json"))
    target.write_text(json.dumps(repaired, ensure_ascii=False, indent=1), encoding="utf-8")
    load_comment_pool(target)

    angles = repaired["angle_plan"]["angles"]
    print(f"角度计划已重建：{len(angles)} 个 -> {[a['angle_id'] for a in angles]}")
    print(f"调整的评论：{len(changed)} 条" + (f"（例：{changed[0]}）" if changed else ""))
    print(f"输出：{target}")
    print("校验：validate_event_angle_plan + load_comment_pool 均通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
