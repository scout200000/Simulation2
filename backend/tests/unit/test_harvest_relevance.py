# -*- coding: utf-8 -*-
"""取数相关性测试：检索式、锚点、相关性判定。

这些用例直接对应一次真实事故：事件开头是「8月29日中午」，
检索式被剥成了「中午」，最终抓到的是三鹿奶粉视频。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.comments import web_harvest as w

GAOYANG = (
    "8月29日中午，河北省保定市高阳县一商场门口发生两名女子冲突。"
    "一名女子对另一名女子实施殴打，并强行脱去其外裤，相关现场视频随后在网络传播。"
)


class TemporalStripTests(unittest.TestCase):
    def test_date_and_time_words_are_removed(self) -> None:
        self.assertEqual(w._strip_temporal("8月29日中午"), "")
        self.assertEqual(w._strip_temporal("2026年11月1日下午"), "")

    def test_place_is_kept(self) -> None:
        self.assertEqual(w._strip_temporal("武汉江汉路万圣节活动中"), "武汉江汉路万圣节活动中")


class QueryBuildingTests(unittest.TestCase):
    def test_head_is_not_a_time_word(self) -> None:
        queries = w.heuristic_queries(GAOYANG, {})
        self.assertTrue(queries)
        self.assertNotIn("中午", queries[0])
        self.assertIn("高阳", queries[0])
        for query in queries:
            self.assertNotEqual(query.strip(), "中午")

    def test_head_ends_on_place_boundary(self) -> None:
        # 「河北省保定市高阳县一商场门口」不应截断成「河北省保定市高」
        self.assertEqual(w._pick_head("河北省保定市高阳县一商场门口发生冲突"), "河北省保定市高阳县")

    def test_falls_back_to_keywords_when_all_clauses_are_temporal(self) -> None:
        queries = w.heuristic_queries("8月29日中午，下午。", {})
        self.assertEqual(queries, [])


class AnchorTests(unittest.TestCase):
    def test_county_name_matches_city_title(self) -> None:
        # 标题只写「保定」，事件写「高阳县」——必须能对上
        anchors = w._anchor_keywords(["高阳县", "保定", "殴打"], GAOYANG)["anchors"]
        self.assertIn("保定", anchors)
        self.assertTrue(w.anchor_match("保定一女子被当众殴打 扒裤子", anchors))

    def test_generic_word_is_not_anchor(self) -> None:
        anchors = w._anchor_keywords(["商场门口", "殴打"], GAOYANG)["anchors"]
        self.assertEqual(anchors, [])

    def test_unrelated_title_does_not_match(self) -> None:
        anchors = w._anchor_keywords(["高阳县", "保定"], GAOYANG)["anchors"]
        self.assertFalse(w.anchor_match("四川宜宾一小区保安被反复殴打", anchors))


class SelectRelevantTests(unittest.TestCase):
    def _rows(self) -> list[dict]:
        return [
            {"title": "保定一女子被当众殴打 扒裤子", "description": ""},
            {"title": "四川宜宾一小区保安被反复殴打", "description": ""},
        ]

    def test_llm_keep_is_rechecked_by_anchor(self) -> None:
        with patch.object(w, "call_deepseek_json", return_value={"keep": [1, 2]}):
            picked, source = w.select_relevant(
                GAOYANG, self._rows(), ["高阳县", "保定", "殴打"]
            )
        self.assertEqual(source, "llm+anchor")
        self.assertEqual([row["title"] for row in picked], ["保定一女子被当众殴打 扒裤子"])

    def test_llm_failure_falls_back_to_rules(self) -> None:
        with patch.object(w, "call_deepseek_json", side_effect=RuntimeError("boom")):
            picked, source = w.select_relevant(
                GAOYANG, self._rows(), ["高阳县", "保定", "殴打"]
            )
        self.assertEqual(source, "heuristic")
        self.assertEqual([row["title"] for row in picked], ["保定一女子被当众殴打 扒裤子"])

    def test_empty_keep_raises_nothing(self) -> None:
        with patch.object(w, "call_deepseek_json", return_value={"keep": []}):
            picked, _ = w.select_relevant(GAOYANG, self._rows(), ["高阳县"])
        self.assertEqual(picked, [])


class PlanRetrievalTests(unittest.TestCase):
    def test_keywords_must_appear_in_event(self) -> None:
        payload = {"queries": ["保定 女子 被打"], "keywords": ["保定", "完全不在正文里的词"]}
        with patch.object(w, "call_deepseek_json", return_value=payload):
            queries, keywords, source = w.plan_retrieval(GAOYANG, {})
        self.assertEqual(source, "llm")
        self.assertEqual(queries, ["保定 女子 被打"])
        self.assertIn("保定", keywords)
        self.assertNotIn("完全不在正文里的词", keywords)

    def test_falls_back_when_llm_fails(self) -> None:
        with patch.object(w, "call_deepseek_json", side_effect=RuntimeError("boom")):
            queries, keywords, source = w.plan_retrieval(GAOYANG, {})
        self.assertEqual(source, "heuristic")
        self.assertIn("高阳", queries[0])
        self.assertNotEqual(queries[0], "中午")


if __name__ == "__main__":
    unittest.main()
