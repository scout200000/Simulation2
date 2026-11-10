"""集中管理历史复现模式使用的路径。

路径统一来自 ``app.main.config.settings``：事件资料位于
``data/historical_replay/events/``，当前事件指针位于
``configs/events/active_event.json``，实验批次与其他实验共用
``var/experiments/``。
"""

from app.main.config.settings import (
    EXPERIMENT_DIR,
    HISTORICAL_ACTIVE_EVENT_FILE,
    HISTORICAL_EVENTS_DIR,
    HISTORICAL_REPLAY_DIR,
)


EVENTS_DIR = HISTORICAL_EVENTS_DIR
ACTIVE_EVENT_FILE = HISTORICAL_ACTIVE_EVENT_FILE

__all__ = [
    "ACTIVE_EVENT_FILE",
    "EVENTS_DIR",
    "EXPERIMENT_DIR",
    "HISTORICAL_REPLAY_DIR",
]
