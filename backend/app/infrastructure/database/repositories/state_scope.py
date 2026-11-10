"""实验状态目录复制/删除时的 MongoDB 作用域同步。

文件系统本身由 ``shutil`` 维护；本模块保证同一次复制、回滚或删除也同步
``event_states`` 与 ``social_networks`` 集合，避免 MongoDB 中残留旧场景
数据或缺少新场景数据。
"""

from __future__ import annotations

from pathlib import Path

from app.infrastructure.database.repositories.events import (
    copy_event_state_history,
    delete_event_input,
    delete_event_state_history,
    delete_event_states_under,
    event_state_history_exists,
)
from app.infrastructure.database.repositories.social_networks import (
    copy_social_network,
    delete_social_network,
    delete_social_networks_under,
    social_network_exists,
)

STATE_EVENT_STATE_FILE = "event_state_history.json"
STATE_NETWORK_FILE = "social_network_snapshot.json"
EVENT_INPUT_FILES = ("event_input.json", "event.json")


def copy_state_documents(source_dir, target_dir) -> None:
    """复制状态目录中的事件状态和网络快照文档。"""

    source_path = Path(source_dir)
    target_path = Path(target_dir)
    source_state = source_path / STATE_EVENT_STATE_FILE
    target_state = target_path / STATE_EVENT_STATE_FILE
    if event_state_history_exists(source_state):
        copy_event_state_history(source_state, target_state)

    source_network = source_path / STATE_NETWORK_FILE
    target_network = target_path / STATE_NETWORK_FILE
    if social_network_exists(source_network):
        copy_social_network(source_network, target_network)


def delete_state_documents(state_dir) -> None:
    """删除状态目录对应的事件状态和网络文档。"""

    state_path = Path(state_dir)
    delete_event_state_history(state_path / STATE_EVENT_STATE_FILE)
    delete_social_network(state_path / STATE_NETWORK_FILE)


def delete_directory_documents(directory) -> None:
    """删除目录下全部场景的事件状态与网络文档。"""

    directory_path = Path(directory)
    delete_event_states_under(directory_path)
    delete_social_networks_under(directory_path)


def delete_file_document(path) -> None:
    """删除受管文件（事件输入、事件状态、网络快照）对应的文档。"""

    file_path = Path(path)
    if file_path.name in EVENT_INPUT_FILES:
        delete_event_input(file_path)
    elif file_path.name == STATE_EVENT_STATE_FILE:
        delete_event_state_history(file_path)
    elif file_path.name == STATE_NETWORK_FILE:
        delete_social_network(file_path)


__all__ = [
    "copy_state_documents",
    "delete_directory_documents",
    "delete_file_document",
    "delete_state_documents",
]
