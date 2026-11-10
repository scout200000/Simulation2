"""原创表达中证据编号泄漏的离线回归测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.strategy_expression import (  # noqa: E402
    strip_evidence_ids_from_text,
    validate_strategy_expression,
)


CATALOG = [
    {
        "evidence_id": "official_statement_step_10",
        "kind": "official_statement",
        "content": "第十轮通报确认接报调查。",
    },
    {"evidence_id": "comment_132", "kind": "comment", "content": "提醒别传未确认信息"},
    {"evidence_id": "comment_125", "kind": "comment", "content": "强制措施采没采"},
]


def _expression(text, evidence_ids=None):
    return {
        "text": text,
        "emotion": "negative",
        "stance": "questioning",
        "evidence_ids": evidence_ids or ["official_statement_step_10"],
        "reaction_target": "investigation_process",
        "evidence_role": "question",
    }


class EvidenceIdSanitizerTests(unittest.TestCase):
    def test_removes_bracketed_ids_and_keeps_sentence(self):
        text = (
            "第十轮通报确认接报调查、询问涉事人员、调监控固定证据"
            "（official_statement_step_10）。"
        )
        cleaned = strip_evidence_ids_from_text(text)
        self.assertNotIn("official_statement_step_10", cleaned)
        self.assertTrue(cleaned.endswith("。"))

    def test_removes_multiple_ids_in_one_group(self):
        text = "通报里还是空白（comment_125、comment_129）。"
        cleaned = strip_evidence_ids_from_text(text)
        self.assertNotIn("comment_125", cleaned)
        self.assertNotIn("comment_129", cleaned)
        self.assertEqual(cleaned, "通报里还是空白。")

    def test_removes_bare_ids_and_dangling_separator(self):
        text = "可信度终究要靠动作撑（comment_132），别让调查变空档。"
        cleaned = strip_evidence_ids_from_text(text)
        self.assertEqual(cleaned, "可信度终究要靠动作撑，别让调查变空档。")

    def test_drops_empty_brackets_left_behind(self):
        cleaned = strip_evidence_ids_from_text("公告已读（comment_1）。")
        self.assertEqual(cleaned, "公告已读。")

    def test_validate_expression_strips_ids(self):
        normalized = validate_strategy_expression(
            _expression(
                "通报内容认可（official_statement_step_10），"
                "但评论区反复问的问题没回应（comment_132）。"
            ),
            CATALOG,
        )
        self.assertNotIn("official_statement_step_10", normalized["text"])
        self.assertNotIn("comment_132", normalized["text"])
        self.assertEqual(normalized["evidence_ids"], ["official_statement_step_10"])

    def test_validate_rejects_text_that_is_only_ids(self):
        with self.assertRaisesRegex(ValueError, "非空"):
            validate_strategy_expression(_expression("（comment_132）"), CATALOG)

    def test_keeps_normal_text_unchanged(self):
        text = "通报承认接报调查，但强制措施和伤情鉴定进度仍没交代。"
        self.assertEqual(strip_evidence_ids_from_text(text), text)


if __name__ == "__main__":
    unittest.main()

