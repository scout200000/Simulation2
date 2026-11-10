"""后端 JSON API 服务。

以标准库 ``http.server`` 提供前端控制台需要的 HTTP 接口。本模块只负责
HTTP 报文读写、请求分发和错误映射，业务逻辑全部在 ``app.application``。

运行方式（在 ``backend`` 目录下）::

    python -m app.main.api_server --host 127.0.0.1 --port 8770

或使用 ``python backend/scripts/run_api_server.py``。
"""

from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


# 支持直接运行 ``python backend/app/main/api_server.py``。
BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.responses import FileResponse  # noqa: E402
from app.api.router import dispatch  # noqa: E402
from app.main.config.settings import ensure_runtime_directories  # noqa: E402
from app.main.exceptions import resolve_http_error  # noqa: E402
from app.main.middleware import log_request  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    """把请求交给 ``app.api.router``，并统一输出 JSON 响应。"""

    protocol_version = "HTTP/1.1"

    def _send_json(self, payload, status=HTTPStatus.OK):
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_file(self, payload: FileResponse, status=HTTPStatus.OK):
        content = payload.content
        self.send_response(status)
        self.send_header("Content-Type", payload.media_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{payload.filename}"',
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def _handle(self, method: str) -> None:
        path = urlparse(self.path).path
        status = HTTPStatus.INTERNAL_SERVER_ERROR
        try:
            body = self._read_json() if method == "POST" else None
            result = dispatch(method, path, body)
            if result is None:
                status = HTTPStatus.NOT_FOUND
                self._send_json({"error": "not found"}, status)
                return
            payload, status = result
            if isinstance(payload, FileResponse):
                self._send_file(payload, status)
            else:
                self._send_json(payload, status)
        except Exception as error:  # noqa: BLE001 - 统一转换为 API 错误响应
            status, message = resolve_http_error(error)
            self._send_json({"error": message}, status)
        finally:
            log_request(method, path, int(status))

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 约定命名
        self._handle("GET")

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler 约定命名
        self._handle("POST")

    def do_DELETE(self):  # noqa: N802 - BaseHTTPRequestHandler 约定命名
        self._handle("DELETE")

    def log_message(self, format_string, *args):  # noqa: A003
        """访问日志由 ``log_request`` 统一输出，避免重复。"""


def main():
    parser = argparse.ArgumentParser(description="Future 后端 JSON API 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()

    ensure_runtime_directories()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Future backend API: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBackend API server stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
