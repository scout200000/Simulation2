"""API 请求体结构。

仅用于类型说明和文档，运行时仍按字典校验，保持对旧前端调用的兼容。
"""

from __future__ import annotations

from typing import Any, TypedDict


class SessionCreateRequest(TypedDict, total=False):
    """创建推演会话的请求体。"""

    web_event_input: dict[str, Any]
    official_content_input: dict[str, Any]
    entry_timing_input: dict[str, Any]
    announcement_timeline_input: dict[str, Any]
    announcement_drafts_input: list[dict[str, Any]]
    selected_strategy_id: str


class InputPreviewRequest(TypedDict, total=False):
    """预览合并后输入（事件、公告、进场时机）的请求体。"""

    web_event_input: dict[str, Any]
    official_content_input: dict[str, Any]
    entry_timing_input: dict[str, Any]
    announcement_timeline_input: dict[str, Any]


class SessionActionRequest(TypedDict, total=False):
    """会话动作的请求体，不同动作只读取自己需要的字段。"""

    steps: int
    round: int
    official_statement: str
    official_statement_status: str


__all__ = [
    "InputPreviewRequest",
    "SessionActionRequest",
    "SessionCreateRequest",
]
