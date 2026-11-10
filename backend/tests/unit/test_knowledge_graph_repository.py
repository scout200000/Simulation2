"""Neo4j 仓库与 Cypher 生成测试（不依赖真实 Neo4j）。"""

import json
import unittest
from unittest.mock import Mock

from app.infrastructure.graph.neo4j_repository import (
    Neo4jError,
    Neo4jRepository,
    build_merge_statements,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)[:500]

    def json(self):
        return self._payload


def _result(*rows):
    return {"data": [{"row": list(row)} for row in rows]}


class MergeStatementTest(unittest.TestCase):
    def test_nodes_merge_by_id_and_edges_merge_with_labels(self):
        payload = {
            "nodes": [
                {
                    "id": "event:e1",
                    "label": "Event",
                    "name": "事件一",
                    "props": {"event_id": "e1", "summary": "摘要"},
                },
                {
                    "id": "topic:事故原因",
                    "label": "Topic",
                    "name": "事故原因",
                    "props": {"focus": "关注原因"},
                },
            ],
            "edges": [
                {
                    "source": "event:e1",
                    "target": "topic:事故原因",
                    "type": "HAS_TOPIC",
                    "props": {},
                }
            ],
        }

        statements = build_merge_statements(payload)

        self.assertEqual(len(statements), 3)
        self.assertIn("MERGE (n:`Event` {id: $id})", statements[0]["statement"])
        self.assertEqual(statements[0]["parameters"]["props"]["name"], "事件一")
        self.assertNotIn("id", statements[0]["parameters"]["props"])
        self.assertIn("MATCH (a:`Event` {id: $source})", statements[2]["statement"])
        self.assertIn("MERGE (a)-[r:`HAS_TOPIC`]->(b)", statements[2]["statement"])

    def test_unknown_label_or_relation_is_rejected(self):
        with self.assertRaises(Neo4jError):
            build_merge_statements(
                {"nodes": [{"id": "x", "label": "Unknown", "name": "x"}], "edges": []}
            )
        with self.assertRaises(Neo4jError):
            build_merge_statements(
                {
                    "nodes": [
                        {"id": "event:e1", "label": "Event", "name": "e1"},
                        {"id": "topic:t", "label": "Topic", "name": "t"},
                    ],
                    "edges": [{"source": "event:e1", "target": "topic:t", "type": "BAD"}],
                }
            )


class RepositoryTest(unittest.TestCase):
    def _repository(self):
        return Neo4jRepository(
            "http://127.0.0.1:7474", "neo4j", "eventkg123", timeout=1
        )

    def test_available_and_event_exists(self):
        repository = self._repository()
        responses = [
            FakeResponse({"errors": [], "results": [_result((1,))]}),
            FakeResponse({"errors": [], "results": [_result((1,))]}),
            FakeResponse({"errors": [], "results": [_result((0,))]}),
        ]
        repository._session.post = Mock(side_effect=responses)

        self.assertTrue(repository.available())
        self.assertTrue(repository.event_exists("event_e1"))
        self.assertFalse(repository.event_exists("event_missing"))
        self.assertEqual(repository._session.post.call_count, 3)

    def test_auth_failure_raises(self):
        repository = self._repository()
        repository._session.post = Mock(
            return_value=FakeResponse({"errors": []}, status_code=401)
        )
        with self.assertRaises(Neo4jError):
            repository.event_exists("event_e1")

    def test_cypher_error_raises(self):
        repository = self._repository()
        repository._session.post = Mock(
            return_value=FakeResponse(
                {"results": [], "errors": [{"message": "boom"}]}
            )
        )
        with self.assertRaises(Neo4jError):
            repository.event_exists("event_e1")

    def test_read_graph_parses_nodes_and_edges(self):
        repository = self._repository()
        node_rows = _result(
            (["Event"], {"id": "event:e1", "name": "事件一", "event_id": "e1"}),
            (["Topic"], {"id": "topic:t", "name": "议题", "focus": "关注"}),
        )["data"]
        edge_rows = _result(("event:e1", "HAS_TOPIC", "topic:t", {}))["data"]
        repository._session.post = Mock(
            return_value=FakeResponse(
                {
                    "errors": [],
                    "results": [
                        {"data": node_rows, "columns": []},
                        {"data": edge_rows, "columns": []},
                    ],
                }
            )
        )

        payload = repository.read_graph()

        self.assertEqual(len(payload["nodes"]), 2)
        self.assertEqual(payload["nodes"][0]["id"], "event:e1")
        self.assertEqual(payload["nodes"][0]["props"]["event_id"], "e1")
        self.assertNotIn("id", payload["nodes"][0]["props"])
        self.assertEqual(len(payload["edges"]), 1)
        self.assertEqual(payload["edges"][0]["type"], "HAS_TOPIC")
        self.assertEqual(payload["meta"]["events"], 1)

    def test_event_ids(self):
        repository = self._repository()
        repository._session.post = Mock(
            return_value=FakeResponse(
                {
                    "errors": [],
                    "results": [
                        {
                            "data": [
                                {"row": ["e1"]},
                                {"row": ["e2"]},
                                {"row": [None]},
                            ],
                            "columns": [],
                        }
                    ],
                }
            )
        )

        self.assertEqual(repository.event_ids(), ["e1", "e2"])

    def test_query_api_available_uses_query_endpoint(self):
        repository = Neo4jRepository(
            "https://example.databases.neo4j.io",
            "user",
            "pass",
            database="db1",
            timeout=1,
            query_api=True,
        )
        repository._session.post = Mock(
            return_value=FakeResponse(
                {"data": {"fields": ["ok"], "values": [[1]]}, "errors": []},
                status_code=202,
            )
        )

        self.assertTrue(repository.available())
        body = repository._session.post.call_args.kwargs["json"]
        self.assertEqual(body["statement"], "RETURN 1 AS ok")
        self.assertTrue(repository.endpoint.endswith("/db/db1/query/v2"))

    def test_query_api_merge_batches_by_label_and_type(self):
        repository = Neo4jRepository(
            "https://example.databases.neo4j.io",
            "user",
            "pass",
            database="db1",
            timeout=1,
            query_api=True,
        )
        calls = []

        def fake_post(url, json, timeout):
            calls.append(json)
            return FakeResponse({"data": None, "errors": []}, status_code=202)

        repository._session.post = Mock(side_effect=fake_post)
        payload = {
            "nodes": [
                {"id": "event:e1", "label": "Event", "name": "e1"},
                {"id": "topic:t", "label": "Topic", "name": "t"},
            ],
            "edges": [
                {"source": "event:e1", "target": "topic:t", "type": "HAS_TOPIC"}
            ],
        }

        count = repository.merge_graph(payload)

        self.assertEqual(count, 3)
        statements = [call["statement"] for call in calls]
        self.assertEqual(len([s for s in statements if "UNWIND $nodes" in s]), 2)
        self.assertEqual(len([s for s in statements if "UNWIND $edges" in s]), 1)
        self.assertTrue(any("MATCH (a:`Event`)" in s for s in statements))

    def test_merge_graph_batches_statements(self):
        repository = self._repository()
        repository._session.post = Mock(
            return_value=FakeResponse({"errors": [], "results": []})
        )
        payload = {
            "nodes": [
                {"id": "event:e1", "label": "Event", "name": "e1"},
                {"id": "topic:t", "label": "Topic", "name": "t"},
            ],
            "edges": [{"source": "event:e1", "target": "topic:t", "type": "HAS_TOPIC"}],
        }

        count = repository.merge_graph(payload)

        self.assertEqual(count, 3)
        self.assertEqual(repository._session.post.call_count, 1)
        body = repository._session.post.call_args.kwargs["json"]
        self.assertEqual(len(body["statements"]), 3)


if __name__ == "__main__":
    unittest.main()
