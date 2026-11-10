"""PDF 报告排版的离线回归测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.evaluation.report_pdf import build_report_pdf  # noqa: E402


def _page_count(pdf: bytes) -> int:
    return pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")


class ReportPdfTests(unittest.TestCase):
    def test_builds_multi_page_pdf_with_all_sections(self):
        report = {
            "report_id": "report_test_001",
            "title": "测试舆情推演报告",
            "subtitle": "规则评分与规则摘要",
            "generated_at": "2026-11-03 20:00",
            "simulation": {
                "batch_id": "event_test_001",
                "rounds": 3,
                "agent_count": 30,
                "model": "deepseek-v4-flash（规则模式）",
            },
            "event": {
                "event_id": "event_test_001",
                "title": "测试事件",
                "time": "2026-11-01",
                "location": "测试地点",
                "labels": ["主题：社会事件", "情绪：负面"],
                "content": "这是一段用于测试 PDF 排版的事件正文。" * 4,
            },
            "summary": {
                "risk_level": "中",
                "peak_negative_rate": 0.5,
                "final_negative_rate": 0.4,
                "best_announcement_id": "plan_1",
                "best_score": 66.5,
                "overall": "最佳方案「方案一」总分 66.5；负面率峰值 50%，期末 40%。",
            },
            "sentiment_trend": [
                {"round": index, "negative": 0.5 - index * 0.02, "neutral": 0.4, "positive": index * 0.02}
                for index in range(1, 4)
            ],
            "announcements": [
                {
                    "id": "plan_1",
                    "name": "方案一",
                    "published_at": "第 2 轮",
                    "official_statement": "这是测试公告正文。" * 8,
                    "score": {
                        "total": 66.5,
                        "level": "一般",
                        "response_step": 2,
                        "dimensions": [
                            {"name": "事实清晰", "score": 14},
                            {"name": "行动完整", "score": 12},
                            {"name": "责任明确", "score": 10},
                            {"name": "共情表达", "score": 15},
                            {"name": "过程说明", "score": 15.5},
                        ],
                        "rounds": [],
                    },
                    "analysis": {
                        "summary": "规则评分与摘要。",
                        "strengths": ["回应及时", "信息完整"],
                        "risks": ["情绪安抚不足"],
                    },
                },
                {
                    "id": "plan_2",
                    "name": "方案二",
                    "published_at": "第 2 轮",
                    "official_statement": "第二个测试公告。" * 6,
                    "score": {
                        "total": 42.0,
                        "level": "较差",
                        "response_step": 2,
                        "rounds": [
                            {"step": 2, "comment_score": 30, "attitude_score": 50, "combined_score": 42},
                            {"step": 3, "comment_score": 20, "attitude_score": 40, "combined_score": 32},
                        ],
                    },
                    "analysis": {"summary": "第二个方案摘要。", "strengths": [], "risks": ["信息不足"]},
                },
            ],
            "word_cloud": [
                {"text": "处置进展", "weight": 90, "tone": "negative"},
                {"text": "受害者", "weight": 70, "tone": "neutral"},
                {"text": "官方通报", "weight": 50, "tone": "positive"},
            ],
            "key_comments": [
                {
                    "id": "c1",
                    "round": 2,
                    "emotion": "negative",
                    "faction": "观点输出派",
                    "text": "测试评论内容。" * 6,
                    "insight": "被曝光 20 次。",
                },
                {
                    "id": "c2",
                    "round": 3,
                    "emotion": "neutral",
                    "faction": "吃瓜派",
                    "text": "另一条测试评论。" * 4,
                    "insight": "被曝光 10 次。",
                },
            ],
            "conclusion": {
                "recommendations": ["补齐事实细节", "明确处理时限", "保持口径一致"],
                "limitations": "测试报告，仅供回归验证。",
            },
        }

        pdf = build_report_pdf(report)

        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 10_000)
        self.assertGreaterEqual(_page_count(pdf), 2)

    def test_builds_pdf_for_minimal_report(self):
        pdf = build_report_pdf({"title": "最简报告"})

        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreaterEqual(_page_count(pdf), 1)


if __name__ == "__main__":
    unittest.main()
