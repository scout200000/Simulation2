# -*- coding: utf-8 -*-
"""派系判定与配额均衡采样的离线测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.comments.faction_balance import (
    FACTIONS,
    allocate_quota,
    balance_sample,
    classify,
    effective_min,
)

# 每个派系准备 10 条同质样本，便于构造可控的候选池
SAMPLES = {
    "观点输出派": [
        f"这件事说明管理存在漏洞，因为监管缺位，所以应该从源头解决，第{i}点"
        for i in range(10)
    ],
    "表态判断派": [f"是这样的{i}" for i in range(10)],
    "情绪激进派": [f"太恶心了！这帮人真该被拘留！！{i}" for i in range(10)],
    "矛盾激化派": [f"笑死，又是这个地方，果然活该{i}" for i in range(10)],
    "吃瓜派": [f"看看不说话[doge]{i}" for i in range(10)],
}


def build_pool(per_faction: dict[str, int]) -> list[dict]:
    pool: list[dict] = []
    for faction, count in per_faction.items():
        for text in SAMPLES[faction][:count]:
            pool.append(
                {
                    "comment_id": f"{faction}-{len(pool)}",
                    "text": text,
                    "likes": len(pool),
                    "created_at": len(pool),
                }
            )
    return pool


class ClassifierTests(unittest.TestCase):
    def test_emotion_marker_is_aggressive(self) -> None:
        self.assertEqual(classify("太恶心了！这帮人真该被拘留！！"), "情绪激进派")

    def test_argument_is_opinion_output(self) -> None:
        self.assertEqual(
            classify("这件事说明城市管理还有很大提升空间，因为监管缺位，所以应该从源头解决"),
            "观点输出派",
        )

    def test_group_attack_is_conflict(self) -> None:
        self.assertEqual(classify("笑死，又是武汉，果然活该"), "矛盾激化派")

    def test_meme_is_bystander(self) -> None:
        self.assertEqual(classify("司机一脚油门就真过节了[吃瓜]"), "吃瓜派")

    def test_plain_short_is_residual(self) -> None:
        self.assertEqual(classify("是这样的"), "表态判断派")
        self.assertEqual(classify("我就看看不说话"), "表态判断派")

    def test_empty_text_is_residual(self) -> None:
        self.assertEqual(classify(""), "表态判断派")


class QuotaTests(unittest.TestCase):
    def test_floor_and_cap(self) -> None:
        available = {name: 100 for name in FACTIONS}
        quota = allocate_quota(available, target=40, min_each=5, max_share=0.4)
        self.assertEqual(sum(quota.values()), 40)
        for name in FACTIONS:
            self.assertGreaterEqual(quota[name], 5)
            self.assertLessEqual(quota[name], 16)

    def test_floor_scales_down_for_small_target(self) -> None:
        self.assertEqual(effective_min(5, 20), 4)
        self.assertEqual(effective_min(5, 10), 2)
        available = {name: 100 for name in FACTIONS}
        quota = allocate_quota(available, target=20, min_each=5)
        self.assertEqual(sum(quota.values()), 20)
        self.assertTrue(all(value >= 4 for value in quota.values()))

    def test_scarce_faction_is_not_padded(self) -> None:
        available = {name: 100 for name in FACTIONS}
        available["情绪激进派"] = 2
        quota = allocate_quota(available, target=40, min_each=5)
        self.assertEqual(quota["情绪激进派"], 2)


class BalanceSampleTests(unittest.TestCase):
    def test_meets_floor_at_full_size(self) -> None:
        pool = build_pool({name: 10 for name in FACTIONS})
        picked, stats = balance_sample(pool, target=40)
        self.assertEqual(len(picked), 40)
        for name in FACTIONS:
            self.assertGreaterEqual(stats["counts"].get(name, 0), 5)
        self.assertTrue(stats["complete"])
        self.assertEqual(stats["short"], {})

    def test_reports_short_instead_of_faking(self) -> None:
        pool = build_pool({**{name: 10 for name in FACTIONS}, "情绪激进派": 2})
        picked, stats = balance_sample(pool, target=40)
        self.assertEqual(stats["counts"]["情绪激进派"], 2)
        self.assertIn("情绪激进派", stats["short"])
        self.assertFalse(stats["complete"])
        self.assertEqual(len(picked), 40)

    def test_keeps_channel_marks(self) -> None:
        pool = build_pool({name: 10 for name in FACTIONS})
        picked, _ = balance_sample(pool, target=30)
        channels = {item["sampling_channel"] for item in picked}
        self.assertTrue(channels & {"top", "latest", "random"})

    def test_no_duplicate_comment(self) -> None:
        pool = build_pool({name: 10 for name in FACTIONS})
        picked, _ = balance_sample(pool, target=40)
        ids = [item["comment_id"] for item in picked]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
