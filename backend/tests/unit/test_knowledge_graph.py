"""历史事件知识图谱视图的规则测试（离线、无外部依赖）。"""

import unittest

from app.domain.knowledge_graph import build_event_graph, normalize_place


def _sample_graph():
    return {
        "meta": {"events": 2, "nodes": 7, "edges": 8},
        "nodes": [
            {
                "id": "event:e1",
                "label": "Event",
                "name": "事件一",
                "props": {"event_id": "e1", "region": "河北省保定市"},
            },
            {
                "id": "event:e2",
                "label": "Event",
                "name": "事件二",
                "props": {"event_id": "e2", "region": "河北保定"},
            },
            {
                "id": "topic:事故原因",
                "label": "Topic",
                "name": "事故原因",
                "props": {"focus": "关注事故原因"},
            },
            {
                "id": "actor:公安机关",
                "label": "Actor",
                "name": "公安机关",
                "props": {"actor_type": "organization", "role": "处置方"},
            },
            {"id": "location:河北保定", "label": "Location", "name": "河北保定", "props": {}},
            {"id": "subevent:e1:1", "label": "SubEvent", "name": "进展一", "props": {}},
            {"id": "subevent:e2:1", "label": "SubEvent", "name": "进展二", "props": {}},
        ],
        "edges": [
            {"source": "event:e1", "target": "topic:事故原因", "type": "HAS_TOPIC"},
            {"source": "event:e2", "target": "topic:事故原因", "type": "HAS_TOPIC"},
            {"source": "event:e1", "target": "location:河北保定", "type": "HAS_LOCATION"},
            {"source": "event:e2", "target": "location:河北保定", "type": "HAS_LOCATION"},
            {"source": "event:e1", "target": "subevent:e1:1", "type": "HAS_SUBEVENT"},
            {"source": "event:e2", "target": "subevent:e2:1", "type": "HAS_SUBEVENT"},
            {"source": "subevent:e1:1", "target": "actor:公安机关", "type": "INVOLVES"},
            {"source": "subevent:e2:1", "target": "actor:公安机关", "type": "INVOLVES"},
        ],
    }


class KnowledgeGraphTest(unittest.TestCase):
    def test_normalize_place_merges_suffixes(self):
        self.assertEqual(normalize_place("河北省保定市"), "河北保定")
        self.assertEqual(normalize_place("河北保定"), "河北保定")

    def test_event_links_are_derived_from_shared_entities(self):
        payload = build_event_graph(_sample_graph())

        self.assertEqual(payload["meta"]["eventCount"], 2)
        self.assertEqual(len(payload["eventLinks"]), 1)

        link = payload["eventLinks"][0]
        self.assertEqual(link["weight"], 3)
        self.assertEqual(
            {item["name"] for item in link["shared"]},
            {"事故原因", "公安机关", "河北保定"},
        )
        self.assertIn("共同议题 1", link["label"])
        self.assertIn("共同主体 1", link["label"])
        self.assertIn("同一地域 1", link["label"])

        shared = [item for item in payload["entities"] if item["shared"]]
        self.assertEqual(len(shared), 3)
        self.assertEqual(len(payload["entities"]), 3)

    def test_events_without_shared_entities_have_no_link(self):
        graph = _sample_graph()
        graph["nodes"].append(
            {
                "id": "topic:独立议题",
                "label": "Topic",
                "name": "独立议题",
                "props": {"focus": "只属于事件一"},
            }
        )
        graph["edges"].append(
            {"source": "event:e1", "target": "topic:独立议题", "type": "HAS_TOPIC"}
        )

        payload = build_event_graph(graph)
        self.assertEqual(len(payload["eventLinks"]), 1)
        self.assertIn(
            "独立议题",
            {topic["name"] for topic in payload["events"][0]["topics"]},
        )

    def test_missing_event_nodes_raise(self):
        with self.assertRaises(ValueError):
            build_event_graph({"nodes": [], "edges": []})


if __name__ == "__main__":
    unittest.main()
