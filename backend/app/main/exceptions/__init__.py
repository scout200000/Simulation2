"""HTTP 错误映射。

业务层不直接依赖 HTTP：路由与用例抛出 ``ValueError``、``FileNotFoundError``
等标准异常，由本模块统一映射为 API 响应状态码。
"""

from __future__ import annotations

import json
from http import HTTPStatus


def resolve_http_error(error: BaseException) -> tuple[int, str]:
    """把业务异常转换为 ``(状态码, 错误信息)``。"""

    if isinstance(error, FileNotFoundError):
        return HTTPStatus.NOT_FOUND, str(error)
    if isinstance(
        error,
        (ValueError, KeyError, TypeError, json.JSONDecodeError),
    ):
        return HTTPStatus.BAD_REQUEST, str(error)
    return HTTPStatus.INTERNAL_SERVER_ERROR, str(error)


__all__ = ["resolve_http_error"]
