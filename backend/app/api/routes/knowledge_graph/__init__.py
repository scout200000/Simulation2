"""历史事件知识图谱路由：读取前端渲染所需的事件与关联视图。"""

from __future__ import annotations

from http import HTTPStatus

from app.application import knowledge_graph_service


def get_knowledge_graph():
    """返回事件图谱视图。"""

    return knowledge_graph_service.get_knowledge_graph(), HTTPStatus.OK


__all__ = ["get_knowledge_graph"]
