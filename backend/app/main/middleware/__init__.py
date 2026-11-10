"""请求日志等轻量中间件。

stdio HTTP 服务没有框架级中间件机制，这里提供可复用的辅助函数，
由 ``app.main.api_server`` 在统一出口调用。
"""

from __future__ import annotations

from http import HTTPStatus


def log_request(method: str, path: str, status: int) -> None:
    """按统一格式输出一条访问日志。"""

    try:
        status_name = HTTPStatus(status).phrase
    except ValueError:
        status_name = ""
    print(f"[api server] {method} {path} -> {status} {status_name}".rstrip())


__all__ = ["log_request"]
