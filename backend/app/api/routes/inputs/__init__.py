"""输入准备路由：默认事件、公告方案与合并预览。"""

from __future__ import annotations

from http import HTTPStatus

from app.api.schemas import InputPreviewRequest
from app.application.session_facade import (
    get_event_web_default,
    get_official_content_web_default,
    prepare_web_inputs,
)


def get_defaults():
    """返回前端初始化控制台所需的默认输入。"""

    payload = prepare_web_inputs()
    payload["event_default"] = get_event_web_default()
    payload["official_default"] = get_official_content_web_default()
    return payload, HTTPStatus.OK


def preview_inputs(body: InputPreviewRequest | None = None):
    """合并并校验一次实验的 web 输入，不创建会话。"""

    body = body or {}
    payload = prepare_web_inputs(
        web_event_input=body.get("web_event_input"),
        official_content_input=body.get("official_content_input"),
        entry_timing_input=body.get("entry_timing_input"),
        announcement_timeline_input=body.get("announcement_timeline_input"),
    )
    return payload, HTTPStatus.OK


__all__ = ["get_defaults", "preview_inputs"]
