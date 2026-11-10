# -*- coding: utf-8 -*-
"""采集式评论池结构测试：重点覆盖角度计划必须能通过生成式校验器。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.comments.angle_planner import validate_event_angle_plan
from app.comments.repository import load_comment_pool
from app.comments.web_harvest import HarvestError, assemble, build_angle_plan

EVENT = {
    "event_id": "event_wuhan_halloween_rideshare_20261101",
    "event_content": (
        "2026年11月1日，武汉江汉路万圣节活动中，一位网约车司机接单后误入人流密集路段，"
        "车辆被困车道难以挪动，遭人群围堵数小时并扔垃圾、放车胎气。"
    ),
}

CLUSTERS = ["城市形象质疑", "处罚力度争议"]


def make_comments(count: int = 12) -> list[dict]:
    texts = [
        "是这样的，没什么好说的",
        "这件事说明管理有漏洞，因为监管缺位，所以应该从源头解决，不该只怪一线",
        "太恶心了！这帮人真该被拘留！！",
        "笑死，又是这个地方，果然活该",
        "看看不说话[doge]",
        "处罚太轻了，训诫算什么",
        "司机太可怜了，希望他没事",
        "我觉得还是要看官方通报，别急着下结论",
    ]
    out = []
    for index in range(count):
        out.append(
            {
                "comment_id": f"raw_{index}",
                "text": texts[index % len(texts)] + f"（{index}）",
                "likes": count - index,
                "created_at": 1000 + index,
                "url": "https://www.bilibili.com/video/BV1TEST",
            }
        )
    return out


def make_tags(count: int) -> list[list[int]]:
    return [[index % len(CLUSTERS), 2, 3, 1, 1] for index in range(count)]


class AnglePlanTests(unittest.TestCase):
    def test_plan_passes_generation_validator(self) -> None:
        plan, labels = build_angle_plan(CLUSTERS, EVENT)
        validate_event_angle_plan(plan, EVENT)  # 与增量生成读取的是同一个校验器
        self.assertEqual([a["angle_id"] for a in plan["angles"]], ["harvest_1", "harvest_2"])
        self.assertEqual(labels, CLUSTERS)
        for angle in plan["angles"]:
            self.assertTrue(angle["focus"])
            self.assertIn(angle["evidence_text"], EVENT["event_content"])

    def test_duplicate_names_are_made_unique(self) -> None:
        plan, labels = build_angle_plan(["城市形象质疑", "城市形象质疑"], EVENT)
        validate_event_angle_plan(plan, EVENT)
        self.assertEqual(len(set(labels)), 2)

    def test_empty_event_content_is_rejected(self) -> None:
        with self.assertRaises(HarvestError):
            build_angle_plan(CLUSTERS, {"event_id": "e", "event_content": "  "})


class AssembleTests(unittest.TestCase):
    def test_pool_passes_repository_and_angle_validation(self) -> None:
        comments = make_comments()
        pool = assemble(EVENT, comments, make_tags(len(comments)), CLUSTERS, {}, "llm", 8)

        self.assertEqual(pool["requested_comment_count"], len(pool["comments"]))
        self.assertEqual(pool["generation_method"], "web_harvest_labeled")
        validate_event_angle_plan(pool["angle_plan"], EVENT)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "comment_pool.json"
            path.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
            loaded = load_comment_pool(path)
        self.assertEqual(len(loaded["comments"]), len(pool["comments"]))

    def test_comment_angles_exist_in_plan(self) -> None:
        comments = make_comments()
        pool = assemble(EVENT, comments, make_tags(len(comments)), CLUSTERS, {}, "llm", 8)
        planned = {angle["angle_id"] for angle in pool["angle_plan"]["angles"]}
        for comment in pool["comments"]:
            self.assertIn(comment["angle_id"], planned)

    def test_faction_coverage_is_reported(self) -> None:
        comments = make_comments()
        pool = assemble(EVENT, comments, make_tags(len(comments)), CLUSTERS, {}, "llm", 8)
        coverage = pool["faction_coverage"]
        self.assertIn("counts", coverage)
        self.assertIn("short", coverage)
        self.assertIsInstance(coverage["complete"], bool)


if __name__ == "__main__":
    unittest.main()
