"""事件图谱服务与策略运行入库测试（Neo4j 使用内存假实现）。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.application import knowledge_graph_service, knowledge_graph_sync


class FakeRepository:
    """内存版 Neo4j 仓库，只实现服务用到的接口。"""

    def __init__(self, available=True, existing=False, nodes=None, edges=None):
        self.is_available = available
        self.existing = existing
        self.nodes = list(nodes or [])
        self.edges = list(edges or [])
        self.merged = []

    def available(self):
        return self.is_available

    def event_exists(self, event_id):
        return self.existing

    def count_events(self):
        return len([node for node in self.nodes if node["label"] == "Event"])

    def merge_graph(self, payload):
        self.merged.append(payload)
        nodes = {node["id"]: node for node in self.nodes}
        for node in payload.get("nodes") or []:
            nodes[node["id"]] = node
        self.nodes = list(nodes.values())
        edges = {
            (edge["source"], edge["type"], edge["target"]): edge
            for edge in self.edges
        }
        for edge in payload.get("edges") or []:
            edges[(edge["source"], edge["type"], edge["target"])] = edge
        self.edges = list(edges.values())
        return len(payload.get("nodes") or []) + len(payload.get("edges") or [])

    def event_ids(self):
        return sorted(
            {
                str((node.get("props") or {}).get("event_id"))
                for node in self.nodes
                if node.get("label") == "Event"
                and (node.get("props") or {}).get("event_id")
            }
        )

    def read_graph(self):
        return {"meta": {}, "nodes": list(self.nodes), "edges": list(self.edges)}


RAW_GRAPH = {
    "meta": {"events": 1, "nodes": 2, "edges": 1},
    "nodes": [
        {
            "id": "event:e1",
            "label": "Event",
            "name": "事件一",
            "props": {
                "event_id": "e1",
                "summary": "事件摘要",
                "region": "河北省保定市",
            },
        },
        {
            "id": "topic:事故原因",
            "label": "Topic",
            "name": "事故原因",
            "props": {"focus": "关注事故原因"},
        },
    ],
    "edges": [
        {"source": "event:e1", "target": "topic:事故原因", "type": "HAS_TOPIC"}
    ],
}


def _write_graph(path: Path) -> None:
    path.write_text(json.dumps(RAW_GRAPH, ensure_ascii=False), encoding="utf-8")


class KnowledgeGraphServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.graph_file = Path(self.temp.name) / "graph.json"
        _write_graph(self.graph_file)
        self.patches = [
            patch.object(knowledge_graph_service, "KG_GRAPH_FILE", self.graph_file),
            patch.object(knowledge_graph_service, "KG_NEO4J_ENABLED", True),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        knowledge_graph_service._JSON_CACHE.update(
            {"signature": None, "payload": None}
        )

    def test_prefers_neo4j_when_available(self):
        repository = FakeRepository(nodes=RAW_GRAPH["nodes"], edges=RAW_GRAPH["edges"])
        with patch.object(knowledge_graph_service, "get_repository", return_value=repository):
            payload = knowledge_graph_service.get_knowledge_graph()

        self.assertEqual(payload["meta"]["storage"], "neo4j")
        self.assertEqual(len(payload["events"]), 1)
        self.assertEqual(payload["events"][0]["eventId"], "e1")

    def test_seeds_empty_neo4j_from_json_once(self):
        repository = FakeRepository()
        with patch.object(knowledge_graph_service, "get_repository", return_value=repository):
            payload = knowledge_graph_service.get_knowledge_graph()

        self.assertEqual(payload["meta"]["storage"], "neo4j")
        self.assertEqual(len(repository.merged), 1)
        self.assertEqual(len(payload["events"]), 1)

        with patch.object(knowledge_graph_service, "get_repository", return_value=repository):
            knowledge_graph_service.get_knowledge_graph()
        self.assertEqual(len(repository.merged), 1)  # 不再重复导入

    def test_imports_pending_local_event_when_neo4j_nonempty(self):
        pending = json.loads(json.dumps(RAW_GRAPH))
        pending["nodes"].append(
            {
                "id": "event:e2",
                "label": "Event",
                "name": "事件二",
                "props": {"event_id": "e2", "summary": "待补录事件"},
            }
        )
        self.graph_file.write_text(
            json.dumps(pending, ensure_ascii=False), encoding="utf-8"
        )
        repository = FakeRepository(
            nodes=[RAW_GRAPH["nodes"][0]], edges=[]
        )

        with patch.object(knowledge_graph_service, "get_repository", return_value=repository):
            payload = knowledge_graph_service.get_knowledge_graph()

        self.assertEqual(len(repository.merged), 1)
        self.assertEqual(len(payload["events"]), 2)
        self.assertEqual(
            {event["eventId"] for event in payload["events"]}, {"e1", "e2"}
        )

    def test_falls_back_to_json_when_neo4j_unavailable(self):
        repository = FakeRepository(available=False)
        with patch.object(knowledge_graph_service, "get_repository", return_value=repository):
            payload = knowledge_graph_service.get_knowledge_graph()

        self.assertEqual(payload["meta"]["storage"], "json")
        self.assertEqual(len(payload["events"]), 1)


class KnowledgeGraphSyncTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.experiment_dir = Path(self.temp.name) / "experiment"
        self.experiment_dir.mkdir()

        event_input = {
            "event_id": "event_test_001",
            "event_content": (
                "8月29日中午，河北省保定市高阳县一商场门口发生两名女子冲突，"
                "一名女子对另一名女子实施殴打，相关视频在网络传播。"
                "公安机关到场处置并控制涉事人员，案件正在调查。"
            ),
            "event_labels": {"topic": "社会事件", "event_valence": "negative"},
        }
        comment_pool = {
            "event_id": "event_test_001",
            "angle_plan": {
                "angles": [
                    {
                        "angle_id": "responsibility",
                        "angle_name": "责任认定",
                        "focus": "关注责任认定与后续处置",
                    }
                ]
            },
            "comments": [
                {"comment_id": "c1", "text": "要求公开调查进展", "emotion": "negative"},
                {"comment_id": "c2", "text": "等待权威通报", "emotion": "neutral"},
                {"comment_id": "c3", "text": "处置及时", "emotion": "positive"},
            ],
        }
        self.event_file = self.experiment_dir / "event_input.json"
        self.pool_file = self.experiment_dir / "comment_pool.json"
        self.event_file.write_text(
            json.dumps(event_input, ensure_ascii=False), encoding="utf-8"
        )
        self.pool_file.write_text(
            json.dumps(comment_pool, ensure_ascii=False), encoding="utf-8"
        )
        self.graph_file = Path(self.temp.name) / "graph.json"
        _write_graph(self.graph_file)
        self.graph_patch = patch.object(
            knowledge_graph_sync, "KG_GRAPH_FILE", self.graph_file
        )
        self.graph_patch.start()
        self.addCleanup(self.graph_patch.stop)
        self.control = {
            "event_id": "event_test_001",
            "event_file": str(self.event_file),
            "comment_pool_file": str(self.pool_file),
            "response_step": 2,
            "current_step": 5,
            "strategy": {
                "official_statement": "警方通报：已介入调查，将及时公布进展。",
                "official_statement_status": "clear",
            },
        }

    def test_new_event_is_extracted_and_written(self):
        repository = FakeRepository(existing=False)
        with patch.object(knowledge_graph_sync, "KG_NEO4J_ENABLED", True), patch(
            "app.application.knowledge_graph_service.get_repository",
            return_value=repository,
        ):
            result = knowledge_graph_sync.sync_event_after_run(
                self.experiment_dir, self.control
            )

        self.assertEqual(result["status"], "added")
        self.assertEqual(result["event_id"], "event_test_001")
        self.assertEqual(len(repository.merged), 1)
        self.assertEqual(result["snapshot"]["events"], 2)
        local = json.loads(self.graph_file.read_text(encoding="utf-8"))
        local_ids = {
            node["props"]["event_id"]
            for node in local["nodes"]
            if node["label"] == "Event"
        }
        self.assertEqual(local_ids, {"e1", "event_test_001"})

        payload = repository.merged[0]
        events = [node for node in payload["nodes"] if node["label"] == "Event"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["props"]["event_id"], "event_test_001")
        self.assertEqual(events[0]["props"]["origin"], "strategy_run")
        self.assertGreater(events[0]["props"]["init_negative_rate"], 0)
        self.assertTrue(
            any(node["label"] == "Topic" for node in payload["nodes"])
        )
        self.assertTrue(
            any(node["label"] == "Claim" for node in payload["nodes"])
        )

    def test_existing_event_is_skipped(self):
        repository = FakeRepository(existing=True)
        with patch.object(knowledge_graph_sync, "KG_NEO4J_ENABLED", True), patch(
            "app.application.knowledge_graph_service.get_repository",
            return_value=repository,
        ):
            result = knowledge_graph_sync.sync_event_after_run(
                self.experiment_dir, self.control
            )

        self.assertEqual(result["status"], "exists")
        self.assertEqual(repository.merged, [])
        self.assertEqual(result["snapshot"]["events"], 2)

    def test_unavailable_neo4j_is_reported(self):
        repository = FakeRepository(available=False)
        with patch.object(knowledge_graph_sync, "KG_NEO4J_ENABLED", True), patch(
            "app.application.knowledge_graph_service.get_repository",
            return_value=repository,
        ):
            result = knowledge_graph_sync.sync_event_after_run(
                self.experiment_dir, self.control
            )

        self.assertEqual(result["status"], "stored_locally")
        self.assertEqual(result["reason"], "neo4j_unavailable")
        self.assertEqual(repository.merged, [])
        self.assertEqual(result["snapshot"]["events"], 2)
        local = json.loads(self.graph_file.read_text(encoding="utf-8"))
        self.assertTrue(
            any(
                node["label"] == "Event"
                and node["props"].get("event_id") == "event_test_001"
                for node in local["nodes"]
            )
        )

    def test_extraction_falls_back_to_mongo_when_file_missing(self):
        event_input = json.loads(self.event_file.read_text(encoding="utf-8"))
        self.event_file.unlink()
        with patch(
            "app.infrastructure.database.repositories.load_event_input",
            return_value=event_input,
        ):
            extraction = knowledge_graph_sync.build_session_extraction(
                self.experiment_dir, self.control
            )
        self.assertEqual(extraction["event"]["id"], "event_test_001")

    def test_extraction_uses_comment_angles_and_official_statement(self):
        extraction = knowledge_graph_sync.build_session_extraction(
            self.experiment_dir, self.control
        )

        self.assertEqual(extraction["event"]["id"], "event_test_001")
        self.assertEqual(extraction["event"]["time_text"], "8月29日中午")
        self.assertIn(
            "责任认定", {topic["name"] for topic in extraction["topics"]}
        )
        self.assertEqual(len(extraction["claims"]), 1)
        self.assertEqual(extraction["provenance"]["origin"], "strategy_run")


if __name__ == "__main__":
    unittest.main()
