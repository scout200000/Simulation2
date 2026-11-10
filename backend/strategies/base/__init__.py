"""策略稳定契约。"""

from __future__ import annotations

from typing import TypedDict


class ContentStrategy(TypedDict):
    """一个官方内容回应方案的稳定结构。"""

    strategy_id: str
    strategy_name: str
    official_statement: str
    official_statement_status: str
    evidence_dimensions: dict[str, bool]


class OfficialResponseOptions(TypedDict):
    """一次实验使用的官方回应方案集合。"""

    event_id: str
    entry_strategy: str
    stagnation_rounds: int
    negative_rate_improvement_tolerance: float
    content_strategies: list[ContentStrategy]


__all__ = ["ContentStrategy", "OfficialResponseOptions"]
