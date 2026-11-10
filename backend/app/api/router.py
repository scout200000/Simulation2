"""路由表与请求分发。

路由以 ``(HTTP 方法, 正则表达式, 处理函数)`` 声明；处理函数只接收路径参数
（以及可选的 ``body`` 关键字），返回 ``(payload, status)``。HTTP 报文读写
统一由 ``app.main.api_server`` 负责，便于后续替换为 FastAPI 等框架。
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any, Callable

from app.api.routes import health, inputs, knowledge_graph, reports, sessions


SESSION_ID_PATTERN = r"(?P<experiment_id>[0-9A-Za-z_\-]+)"
SESSION_ACTION_PATTERN = (
    r"(?P<action>start|step|continue|pause|resume|rollback|restart|run|"
    r"announcement)"
)


@dataclass(frozen=True)
class Route:
    """一条 HTTP 路由声明。"""

    method: str
    pattern: str
    handler: Callable[..., tuple[Any, int]]

    @property
    def regex(self) -> re.Pattern[str]:
        return re.compile(self.pattern)


ROUTES: tuple[Route, ...] = (
    Route("GET", r"^/api/health$", health.health),
    Route("GET", r"^/api/input/defaults$", inputs.get_defaults),
    Route("POST", r"^/api/input/preview$", inputs.preview_inputs),
    Route("GET", r"^/api/knowledge-graph$", knowledge_graph.get_knowledge_graph),
    Route("GET", r"^/api/sessions$", sessions.list_sessions),
    Route("POST", r"^/api/sessions$", sessions.create_session),
    Route(
        "GET",
        rf"^/api/sessions/{SESSION_ID_PATTERN}/report$",
        reports.get_session_report,
    ),
    Route(
        "GET",
        rf"^/api/sessions/{SESSION_ID_PATTERN}/report\.pdf$",
        reports.download_session_report_pdf,
    ),
    Route(
        "POST",
        rf"^/api/sessions/{SESSION_ID_PATTERN}/report$",
        reports.generate_session_report,
    ),
    Route(
        "GET",
        rf"^/api/sessions/{SESSION_ID_PATTERN}$",
        sessions.get_session,
    ),
    Route(
        "DELETE",
        rf"^/api/sessions/{SESSION_ID_PATTERN}$",
        sessions.delete_session,
    ),
    Route(
        "POST",
        rf"^/api/sessions/{SESSION_ID_PATTERN}/{SESSION_ACTION_PATTERN}$",
        sessions.run_session_action,
    ),
)


def _accepts_body(handler: Callable[..., Any]) -> bool:
    return "body" in inspect.signature(handler).parameters


def dispatch(method: str, path: str, body: dict | None = None):
    """匹配路由并执行处理函数；未匹配时返回 ``None``。"""

    for route in ROUTES:
        if route.method != method:
            continue
        match = route.regex.match(path)
        if match is None:
            continue
        arguments = match.groupdict()
        if _accepts_body(route.handler):
            arguments["body"] = body or {}
        return route.handler(**arguments)
    return None


__all__ = ["ROUTES", "Route", "dispatch"]
