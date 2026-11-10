#!/usr/bin/env python3
"""One-click launcher for the Future frontend and its local backend.

后端固定为本仓库的 ``backend``（``app.main.api_server``），不再读取旧的
Simulation2 环境变量。端口可通过 ``SIMULATION2_BACKEND_PORT`` 和
``SIMULATION2_FRONTEND_PORT`` 调整。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parent
BACKEND_DIR = (FRONTEND_DIR.parent / "backend").resolve()
BACKEND_PORT = int(os.environ.get("SIMULATION2_BACKEND_PORT", "8770"))
FRONTEND_PORT_START = int(os.environ.get("SIMULATION2_FRONTEND_PORT", "5173"))
BACKEND_HEALTH_URL = f"http://127.0.0.1:{BACKEND_PORT}/api/health"


def find_node() -> Path | None:
    """按 PATH、常见安装目录和本机运行时目录查找 Node.js。"""

    candidates = [
        os.environ.get("NODE_EXE"),
        shutil.which("node"),
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
        str(
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Programs"
            / "nodejs"
            / "node.exe"
        ),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)

    runtime_roots = (
        (Path.home() / ".dsh" / "dsh-runtimes", "*/dependencies/node/bin/node.exe"),
        (Path.home() / ".cache" / "codex-runtimes", "*/dependencies/node/bin/node.exe"),
    )
    for root, pattern in runtime_roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob(pattern), reverse=True):
            if path.is_file():
                return path
    return None


def find_package_manager() -> Path | None:
    candidates = [shutil.which("pnpm"), shutil.which("npm")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)

    for path in sorted(
        (Path.home() / ".dsh" / "dsh-runtimes").glob(
            "*/dependencies/pnpm/bin/pnpm.mjs"
        ),
        reverse=True,
    ):
        if path.is_file():
            return path
    return None


def python_has_requests(executable: Path) -> bool:
    try:
        result = subprocess.run(
            [str(executable), "-c", "import requests"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def find_backend_python() -> Path | None:
    candidates = [
        BACKEND_DIR / ".venv" / "Scripts" / "python.exe",
        Path(sys.executable),
        shutil.which("python"),
    ]
    for candidate in candidates:
        if (
            candidate
            and Path(candidate).is_file()
            and python_has_requests(Path(candidate))
        ):
            return Path(candidate)
    return None


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def backend_ready(timeout: float = 1.5) -> bool:
    """8770 上是否是本仓库的 Future 后端。"""

    try:
        with urllib.request.urlopen(BACKEND_HEALTH_URL, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (
        OSError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ):
        return False
    return isinstance(payload, dict) and payload.get("service") == "future-backend"


def http_ok(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 500
    except (OSError, urllib.error.URLError):
        return False


def wait_http(url: str, process: subprocess.Popen | None, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if http_ok(url):
            return
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"进程提前退出，退出码：{process.returncode}")
        time.sleep(0.35)
    raise TimeoutError(f"等待服务超时：{url}")


def free_port(start: int, limit: int = 20) -> int:
    for port in range(start, start + limit):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"未找到可用端口：{start}-{start + limit - 1}")


def ensure_frontend_dependencies(node: Path) -> Path:
    vite_js = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if vite_js.is_file():
        return vite_js

    package_manager = find_package_manager()
    if package_manager is None:
        raise RuntimeError("未找到 pnpm/npm，且 node_modules 中也没有 Vite。")
    print("首次运行，正在安装前端依赖……")
    if package_manager.suffix == ".mjs":
        command = [str(node), str(package_manager), "install"]
    else:
        command = [str(package_manager), "install"]
    subprocess.run(command, cwd=FRONTEND_DIR, check=True)
    if not vite_js.is_file():
        raise RuntimeError("依赖安装完成，但仍未找到 Vite。")
    return vite_js


def terminate_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def backend_command(python: Path) -> list[str]:
    return [
        str(python),
        "-m",
        "app.main.api_server",
        "--host",
        "127.0.0.1",
        "--port",
        str(BACKEND_PORT),
    ]


def main() -> int:
    if not (BACKEND_DIR / "app" / "main" / "api_server.py").is_file():
        print(f"后端目录不完整：{BACKEND_DIR}")
        print("请确认存在 backend/app/main/api_server.py。")
        return 1

    backend_process = None
    frontend_process = None
    try:
        if backend_ready():
            print(f"复用已运行的 Future 后端：{BACKEND_HEALTH_URL}")
        elif port_in_use(BACKEND_PORT):
            raise RuntimeError(
                f"端口 {BACKEND_PORT} 已被其他服务占用，请先停止它再运行 start.py。"
            )
        else:
            backend_python = find_backend_python()
            if backend_python is None:
                raise RuntimeError("未找到可导入 requests 的 Python 解释器。")

            print(f"启动 Future 后端：{backend_python}（{BACKEND_DIR}）")
            backend_process = subprocess.Popen(
                backend_command(backend_python),
                cwd=BACKEND_DIR,
            )
            wait_http(BACKEND_HEALTH_URL, backend_process, timeout=25)
            if not backend_ready():
                raise RuntimeError("后端已启动，但健康检查未返回 Future 服务标识。")

        node = find_node()
        if node is None:
            raise RuntimeError(
                "未找到 Node.js，请安装 Node.js 20+，或设置 NODE_EXE 指向 node.exe。"
            )

        vite_js = ensure_frontend_dependencies(node)
        frontend_port = free_port(FRONTEND_PORT_START)
        frontend_url = f"http://127.0.0.1:{frontend_port}"

        print(f"启动前端：{frontend_url}")
        frontend_process = subprocess.Popen(
            [
                str(node),
                str(vite_js),
                "--host",
                "127.0.0.1",
                "--port",
                str(frontend_port),
                "--strictPort",
            ],
            cwd=FRONTEND_DIR,
        )
        wait_http(frontend_url + "/", frontend_process, timeout=30)

        print()
        print("=" * 58)
        print(f"项目入口：{frontend_url}")
        print(f"控制台：{frontend_url}/#/console")
        print(f"后端接口：http://127.0.0.1:{BACKEND_PORT}/api")
        print(f"后端目录：{BACKEND_DIR}")
        print("按 Ctrl+C 停止本次启动的前后端进程。")
        print("=" * 58)
        print()
        webbrowser.open(frontend_url)

        while True:
            if backend_process is not None and backend_process.poll() is not None:
                raise RuntimeError("后端进程已退出。")
            if frontend_process.poll() is not None:
                raise RuntimeError("前端进程已退出。")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在停止服务……")
        return 0
    except (OSError, RuntimeError, TimeoutError, subprocess.SubprocessError) as error:
        print(f"启动失败：{error}")
        return 1
    finally:
        terminate_process(frontend_process)
        terminate_process(backend_process)


if __name__ == "__main__":
    raise SystemExit(main())
