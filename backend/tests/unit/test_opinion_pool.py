# -*- coding: utf-8 -*-
"""初始舆论池来源调度的离线测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.comments.opinion_pool import (
    build_initial_comment_pool,
    comment_count_for,
    normalize_opinion_pool_config,
)

EVENT = {"event_id": "event_test", "event_content": "某地发生一起事件，引发讨论。"}


class OpinionPoolConfigTests(unittest.TestCase):
    def test_defaults_to_generate_with_sixty(self) -> None:
        config = normalize_opinion_pool_config(None)
        self.assertEqual(config["source"], "generate")
        self.assertEqual(comment_count_for(config), 60)

    def test_harvest_switch_changes_count(self) -> None:
        config = normalize_opinion_pool_config({"source": "harvest"})
        self.assertEqual(config["source"], "harvest")
        self.assertEqual(comment_count_for(config), 40)

    def test_unknown_source_falls_back_to_generate(self) -> None:
        config = normalize_opinion_pool_config({"source": "crawl"})
        self.assertEqual(config["source"], "generate")

    def test_counts_are_clamped(self) -> None:
        config = normalize_opinion_pool_config(
            {"source": "harvest", "harvest": {"comment_count": 5}}
        )
        self.assertEqual(comment_count_for(config), 10)
        config = normalize_opinion_pool_config(
            {"source": "harvest", "harvest": {"comment_count": 9999}}
        )
        self.assertEqual(comment_count_for(config), 200)


class OpinionPoolDispatchTests(unittest.TestCase):
    def test_generate_branch_calls_generator(self) -> None:
        with patch("app.comments.opinion_pool.generate_comment_pool") as generator:
            generator.return_value = {"comments": [], "event_id": "event_test"}
            result = build_initial_comment_pool(EVENT, {"source": "generate"})
        generator.assert_called_once()
        self.assertEqual(result["opinion_pool_config"]["source"], "generate")

    def test_harvest_branch_calls_harvester(self) -> None:
        with patch("app.comments.opinion_pool.harvest_comment_pool") as harvester:
            harvester.return_value = {"comments": [1], "event_id": "event_test"}
            result = build_initial_comment_pool(
                EVENT, {"source": "harvest", "harvest": {"comment_count": 30}}
            )
        harvester.assert_called_once()
        args = harvester.call_args[0]
        self.assertEqual(args[1], 30)
        self.assertEqual(result["opinion_pool_config"]["source"], "harvest")

    def test_harvest_rejects_calibration(self) -> None:
        with self.assertRaises(ValueError):
            build_initial_comment_pool(
                EVENT,
                {"source": "harvest"},
                initial_opinion={
                    "event_id": "event_test",
                    "comment_count": 40,
                    "emotion_targets": {"negative": 1, "neutral": 1, "positive": 1},
                    "mode": "historical_calibration",
                    "evaluation_role": "initial_condition",
                },
            )


if __name__ == "__main__":
    unittest.main()
