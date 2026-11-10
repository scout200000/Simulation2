from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.application.announcement_drafts import (
    build_announcement_draft_snapshot,
    build_draft_content_strategies,
    normalize_announcement_drafts,
)


def options():
    return {
        "content_strategies": [
            {
                "strategy_id": "response_plan_1",
                "strategy_name": "事实通报",
                "official_statement": "默认公告",
                "official_statement_status": "clear",
                "evidence_dimensions": {
                    "verified_fact": True,
                    "empathy": False,
                },
            },
            {
                "strategy_id": "custom",
                "strategy_name": "自定义",
                "official_statement": "",
                "official_statement_status": "none",
                "evidence_dimensions": {
                    "verified_fact": False,
                    "empathy": True,
                },
            },
        ]
    }


class AnnouncementDraftTests(unittest.TestCase):
    def test_normalizes_statement_and_inherits_strategy_fields(self) -> None:
        drafts = normalize_announcement_drafts(
            [
                {
                    "draft_id": "draft-a",
                    "strategy_id": "custom",
                    "official_statement": "  第一条公告  ",
                    "official_statement_status": "clear",
                }
            ],
            options(),
        )

        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["official_statement"], "第一条公告")
        self.assertEqual(drafts[0]["strategy_name"], "自定义")
        self.assertEqual(
            drafts[0]["evidence_dimensions"],
            {"verified_fact": False, "empathy": True},
        )

    def test_rejects_unknown_strategy(self) -> None:
        with self.assertRaises(ValueError):
            normalize_announcement_drafts(
                [
                    {
                        "strategy_id": "missing",
                        "official_statement": "公告",
                        "official_statement_status": "clear",
                    }
                ],
                options(),
            )

    def test_rejects_empty_statement_and_none_status(self) -> None:
        for statement, status in (("   ", "clear"), ("公告", "none")):
            with self.subTest(statement=statement, status=status):
                with self.assertRaises(ValueError):
                    normalize_announcement_drafts(
                        [
                            {
                                "strategy_id": "custom",
                                "official_statement": statement,
                                "official_statement_status": status,
                            }
                        ],
                        options(),
                    )

    def test_builds_stable_scenario_ids(self) -> None:
        drafts = normalize_announcement_drafts(
            [
                {
                    "draft_id": "a",
                    "strategy_id": "custom",
                    "official_statement": "A",
                    "official_statement_status": "clear",
                },
                {
                    "draft_id": "b",
                    "strategy_id": "response_plan_1",
                    "official_statement": "B",
                    "official_statement_status": "incomplete",
                },
            ],
            options(),
        )

        scenarios = build_draft_content_strategies(drafts)
        self.assertEqual(
            [item["strategy_id"] for item in scenarios],
            ["draft_1", "draft_2"],
        )
        self.assertEqual(scenarios[0]["strategy_name"], "自定义 · 草稿1")
        self.assertEqual(scenarios[1]["strategy_name"], "事实通报 · 草稿2")
        self.assertEqual(
            scenarios[1]["evidence_dimensions"],
            {"verified_fact": True, "empathy": False},
        )

    def test_snapshot_keeps_only_auditable_fields(self) -> None:
        drafts = normalize_announcement_drafts(
            [
                {
                    "strategy_id": "custom",
                    "official_statement": "公告",
                    "official_statement_status": "clear",
                }
            ],
            options(),
        )
        snapshot = build_announcement_draft_snapshot(drafts)
        self.assertEqual(snapshot["draft_count"], 1)
        self.assertEqual(snapshot["drafts"][0]["official_statement"], "公告")
        self.assertNotIn("scenario_id", snapshot["drafts"][0])



class DraftSessionTests(unittest.TestCase):
    """验证草稿批次从创建到 run 分派的会话层行为。"""

    def setUp(self) -> None:
        from unittest.mock import patch

        from app.application import session_service
        from app.infrastructure.storage.json_storage import load_json, save_json

        import shutil
        self.root = Path(BACKEND_DIR).parent / "var" / "test_announcement_drafts"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.event = {
            "event_id": "event_test_draft_001",
            "event_content": "测试事件正文。",
            "event_labels": {
                "topic": "社会事件",
                "event_valence": "negative",
            },
        }
        self.official = {
            "event_id": "event_test_draft_001",
            "entry_strategy": "combined_policy",
            "stagnation_rounds": 2,
            "negative_rate_improvement_tolerance": 0.05,
            "content_strategies": [
                {
                    "strategy_id": "response_plan_1",
                    "strategy_name": "事实通报",
                    "official_statement": "方案一公告",
                    "official_statement_status": "clear",
                    "evidence_dimensions": {"verified_fact": True},
                },
                {
                    "strategy_id": "response_plan_2",
                    "strategy_name": "共情安抚",
                    "official_statement": "方案二公告",
                    "official_statement_status": "incomplete",
                    "evidence_dimensions": {"empathy": True},
                },
                {
                    "strategy_id": "response_plan_3",
                    "strategy_name": "辟谣澄清",
                    "official_statement": "方案三公告",
                    "official_statement_status": "clear",
                    "evidence_dimensions": {"rumor_control": True},
                },
                {
                    "strategy_id": "custom",
                    "strategy_name": "自定义",
                    "official_statement": "",
                    "official_statement_status": "none",
                    "evidence_dimensions": {"accountability": True},
                },
            ],
        }
        self.event_file = self.root / "event.json"
        self.official_file = self.root / "official.json"
        save_json(self.event_file, self.event)
        save_json(self.official_file, self.official)

        self.load_json = load_json
        self.save_json = save_json
        self.session_service = session_service

        def fake_batch(event_input, experiment_id=None, official_response_options=None):
            experiment_dir = self.root / "event_test_draft_001_exp"
            experiment_dir.mkdir(parents=True, exist_ok=True)
            event_path = experiment_dir / "event_input.json"
            official_path = experiment_dir / "official_response_options.json"
            save_json(event_path, event_input)
            save_json(official_path, official_response_options)
            return {
                "experiment_id": experiment_dir.name,
                "experiment_dir": experiment_dir,
                "event_file": event_path,
                "comment_pool_file": experiment_dir / "comment_pool.json",
                "official_response_file": official_path,
            }

        self.patches = [
            patch.object(session_service, "EVENT_FILE", self.event_file),
            patch.object(session_service, "OFFICIAL_RESPONSE_FILE", self.official_file),
            patch.object(session_service, "prepare_simulation_batch", new=fake_batch),
            patch.object(session_service, "load_event_input", new=lambda path: self.event),
            patch("app.application.input_compat.load_event_input", new=lambda path: self.event),
            patch("app.main.config.settings.EXPERIMENT_DIR", self.root),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_create_and_run_dispatches_all_drafts(self) -> None:
        from unittest.mock import patch

        session = self.session_service.create_web_experiment(
            announcement_drafts_input=[
                {
                    "draft_id": "draft-a",
                    "strategy_id": "custom",
                    "official_statement": "自定义草稿公告",
                    "official_statement_status": "clear",
                },
                {
                    "draft_id": "draft-b",
                    "strategy_id": "response_plan_1",
                    "official_statement": "事实通报草稿公告",
                    "official_statement_status": "incomplete",
                },
            ]
        )

        self.assertEqual(session["mode"], "drafts")
        self.assertEqual(session["draft_count"], 2)
        self.assertEqual(session["selected_strategy_id"], "__drafts__")
        control = self.load_json(
            self.root / "event_test_draft_001_exp" / "web_control.json"
        )
        self.assertEqual(control["drafts"][0]["strategy_id"], "custom")
        self.assertEqual(control["drafts"][1]["strategy_id"], "response_plan_1")

        captured = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return {
                "status": "completed",
                "strategy_results": [
                    {"strategy": "no_response"},
                    {"strategy": "draft_1"},
                    {"strategy": "draft_2"},
                ],
            }

        with patch.object(
            self.session_service, "run_experiment", side_effect=fake_run
        ), patch.object(
            self.session_service, "_ensure_initial_comment_pool"
        ), patch.object(
            self.session_service, "_sync_event_graph_quietly"
        ):
            result = self.session_service.run_all_web_experiment(
                session["experiment_id"]
            )

        scenarios = captured["content_strategies"]
        self.assertEqual(
            [item["strategy_id"] for item in scenarios],
            ["draft_1", "draft_2"],
        )
        self.assertEqual(scenarios[0]["official_statement"], "自定义草稿公告")
        self.assertEqual(scenarios[1]["strategy_name"], "事实通报 · 草稿2")
        self.assertEqual(result["strategy_count"], 3)

    def test_all_strategy_mode_rejects_drafts(self) -> None:
        with self.assertRaises(ValueError):
            self.session_service.create_web_experiment(
                selected_strategy_id="__all__",
                announcement_drafts_input=[
                    {
                        "strategy_id": "custom",
                        "official_statement": "公告",
                        "official_statement_status": "clear",
                    }
                ],
            )

if __name__ == "__main__":
    unittest.main()
