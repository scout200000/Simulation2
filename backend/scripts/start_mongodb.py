"""启动本地 MongoDB（项目内数据目录）。

开发机通常没有常驻 MongoDB 服务；本脚本以 ``.data/mongodb`` 为数据目录
启动 ``mongod``，并把日志写入 ``.data/mongodb-log``。生产环境仍建议使用
Windows 服务或容器，并通过 ``MONGO_URI`` 指向对应实例。

用法::

    py -3 backend/scripts/start_mongodb.py
    py -3 backend/scripts/start_mongodb.py --status
    py -3 backend/scripts/start_mongodb.py --stop
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
DEFAULT_DATA_DIR = PROJECT_DIR / ".data" / "mongodb"
DEFAULT_LOG_DIR = PROJECT_DIR / ".data" / "mongodb-log"


def find_mongod() -> Path:
    """按环境变量、PATH 和常见安装目录查找 mongod。"""

    configured = os.environ.get("MONGOD_BINARY", "").strip()
    if configured and Path(configured).is_file():
        return Path(configured)

    found = shutil.which("mongod")
    if found:
        return Path(found)

    candidates = [
        Path(r"D:\MongoDB\Server\8.3\bin\mongod.exe"),
        Path(r"C:\Program Files\MongoDB\Server\8.0\bin\mongod.exe"),
        Path(r"C:\Program Files\MongoDB\Server\7.0\bin\mongod.exe"),
    ]
    candidates.extend(
        sorted(
            Path(r"C:\Program Files\MongoDB\Server").glob(
                r"*\bin\mongod.exe"
            ),
            reverse=True,
        )
        if Path(r"C:\Program Files\MongoDB\Server").is_dir()
        else []
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "找不到 mongod。请安装 MongoDB，或设置 MONGOD_BINARY 指向 mongod.exe。"
    )


def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """检查端口是否可连接。"""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def ping(uri: str, timeout_ms: int = 1000) -> dict | None:
    """通过 pymongo 执行 ping，失败返回 None。"""

    try:
        from pymongo import MongoClient
    except ImportError:
        return None
    client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)
    try:
        return client.admin.command("ping")
    except Exception:  # noqa: BLE001 - 启动探测需要吞掉连接异常
        return None
    finally:
        client.close()


def status(host: str, port: int, uri: str) -> int:
    """打印 MongoDB 状态；未运行返回 1。"""

    result = ping(uri)
    payload = {
        "host": host,
        "port": port,
        "uri": uri,
        "running": result is not None,
        "ping": result,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result is not None else 1


def start(args) -> int:
    """启动 mongod 并等待可连接。"""

    data_dir = Path(args.data_dir).resolve()
    log_dir = Path(args.log_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    uri = f"mongodb://{args.host}:{args.port}"
    if port_open(args.host, args.port) and ping(uri) is not None:
        print(f"MongoDB 已在运行：{uri}（数据目录未变更）")
        return status(args.host, args.port, uri)

    mongod = find_mongod()
    log_path = log_dir / "mongod.log"
    command = [
        str(mongod),
        "--dbpath",
        str(data_dir),
        "--port",
        str(args.port),
        "--bind_ip",
        args.host,
        "--wiredTigerCacheSizeGB",
        str(args.cache_gb),
        "--logpath",
        str(log_path),
        "--logappend",
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    # 某些宿主（IDE、任务运行器）会用 Job Object 回收子进程；允许时请求
    # 脱离 Job，使 mongod 在启动命令结束后继续运行。不允许时退回普通启动。
    breakaway_flags = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    candidate_flags = (
        [creationflags | breakaway_flags, creationflags]
        if breakaway_flags
        else [creationflags]
    )
    process = None
    last_error = None
    with open(log_dir / "mongod.stdout.log", "ab") as stdout, open(
        log_dir / "mongod.stderr.log", "ab"
    ) as stderr:
        for flags in candidate_flags:
            try:
                process = subprocess.Popen(
                    command,
                    stdout=stdout,
                    stderr=stderr,
                    stdin=subprocess.DEVNULL,
                    creationflags=flags,
                    close_fds=True,
                )
                break
            except OSError as error:
                last_error = error
    if process is None:
        print(f"mongod 启动失败：{last_error}")
        return 1

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if process.poll() is not None:
            print(
                f"mongod 启动失败（退出码 {process.returncode}）。"
                f"请查看日志：{log_path}"
            )
            return 1
        if ping(uri) is not None:
            print(f"MongoDB 已启动：{uri}")
            print(f"数据目录：{data_dir}")
            print(f"日志文件：{log_path}")
            print(f"进程编号：{process.pid}")
            return 0
        time.sleep(0.5)

    print(f"等待 MongoDB 启动超时（{args.timeout} 秒），请查看日志：{log_path}")
    return 1


def stop(args) -> int:
    """通过 admin 命令关闭本地 mongod。"""

    uri = f"mongodb://{args.host}:{args.port}"
    try:
        from pymongo import MongoClient

        client = MongoClient(uri, serverSelectionTimeoutMS=2000)
        client.admin.command("shutdown")
    except Exception as error:  # noqa: BLE001 - 关闭时连接中断属正常
        print(f"MongoDB 关闭请求已发送：{error}")
    finally:
        time.sleep(1)
    running = port_open(args.host, args.port)
    print("MongoDB 仍在运行。" if running else "MongoDB 已停止。")
    return 0 if not running else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="启动/查看/停止本地 MongoDB")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=27017)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--cache-gb", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--status", action="store_true", help="只查看状态")
    parser.add_argument("--stop", action="store_true", help="停止本地 MongoDB")
    args = parser.parse_args()

    uri = f"mongodb://{args.host}:{args.port}"
    if args.status:
        return status(args.host, args.port, uri)
    if args.stop:
        return stop(args)
    return start(args)


if __name__ == "__main__":
    sys.exit(main())
