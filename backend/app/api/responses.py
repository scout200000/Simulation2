"""API 响应类型。

JSON 之外的二进制响应（当前只有 PDF）通过本模块描述，HTTP 细节仍由
``app.main.api_server`` 统一处理。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FileResponse:
    """一段需要原样返回的文件内容。"""

    content: bytes
    media_type: str
    filename: str


__all__ = ["FileResponse"]
