"""事件输入合并测试：改正文时生成新 event_id。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.application import input_compat
from app.infrastructure.storage.json_storage import load_json


class CustomEventIdTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.default_file = Path(self.temp.name) / "event.json"
        self.default_file.write_text(
            json.dumps(
                {
                    "event_id": "event_base_001",
                    "event_content": "默认事件正文：某地发生一起交通事故。",
                    "event_labels": {
                        "topic": "社会事件",
                        "event_valence": "negative",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.patcher = patch.object(
            input_compat,
            "load_event_input",
            side_effect=lambda path: load_json(path),
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _resolve(self, event_input):
        return input_compat.resolve_event_input(self.default_file, event_input)

    def test_changed_content_gets_stable_custom_id(self):
        first = self._resolve(
            {"event_content": "新事件正文：另一地发生一起治安案件，正在调查。"}
        )
        second = self._resolve(
            {"event_content": "新事件正文：另一地发生一起治安案件，正在调查。"}
        )

        self.assertTrue(first["event_id"].startswith("event_custom_"))
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertNotEqual(first["event_id"], "event_base_001")

    def test_same_content_keeps_default_id(self):
        result = self._resolve(
            {"event_content": "默认事件正文：某地发生一起交通事故。"}
        )
        self.assertEqual(result["event_id"], "event_base_001")

    def test_explicit_event_id_is_respected(self):
        result = self._resolve(
            {
                "event_id": "event_explicit_001",
                "event_content": "新事件正文：某地发生一起治安案件。",
            }
        )
        self.assertEqual(result["event_id"], "event_explicit_001")


if __name__ == "__main__":
    unittest.main()
